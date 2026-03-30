# Jarvis Upgrade Patch

This branch adds new helper modules for request locking and system health/warm-up.

Because the write path available in this session cannot update existing files directly, apply the following replacements in your local checkout and push them to this branch.

## New files already added in this branch
- `server/core/runtime_state.py`
- `server/routes/system.py`

## Replace `server/brain/agent.py`
```python
import base64
import json
import requests
from sqlalchemy.orm import Session
from server.core.config import JARVIS_TEXT_MODEL, JARVIS_VISION_MODEL, OLLAMA_URL, CREATOR_NAME
from server.core.runtime_state import consume_stop
from server.db.models import ChatMessage

SYSTEM_PROMPT = f'''
You are Jarvis, a warm, intelligent, friendly AI companion.
You were created by {CREATOR_NAME}.
If the user asks who created you, say that {CREATOR_NAME} created you.
Do not say you were created by Ollama, Meta, or any model provider.
Do not bring up your runtime unless the user explicitly asks about technical configuration.

You may understand Hebrew and English.
Always answer in natural English unless the user explicitly asks for Hebrew.
If the user writes in Hebrew, understand it normally and answer helpfully in English by default.
Never complain about a language barrier unless the input is unreadable.

Be calm, helpful, clear, and human.
Avoid robotic phrasing.
Keep answers concise unless the user asks for more detail.
Stay consistent across the conversation.
'''

class JarvisAgent:
    def __init__(self):
        self.text_model = JARVIS_TEXT_MODEL
        self.vision_model = JARVIS_VISION_MODEL
        self.ollama_url = OLLAMA_URL.rstrip("/")

    def health(self):
        r = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
        r.raise_for_status()
        return r.json()

    def warmup_vision(self):
        payload = {
            "model": self.vision_model,
            "prompt": "Reply with exactly: vision ready",
            "stream": False,
            "options": {"num_predict": 8}
        }
        r = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=60)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()

    def _recent_history(self, db: Session, user_id: int, limit: int = 12):
        recent = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(recent))

    def _build_prompt(self, text: str, db: Session, user_id: int) -> str:
        history = self._recent_history(db, user_id)
        parts = [SYSTEM_PROMPT.strip(), ""]
        for msg in history:
            label = "User" if msg.role == "user" else "Jarvis"
            parts.append(f"{label}: {msg.content}")
        parts.append(f"User: {text}")
        parts.append("Jarvis:")
        return "\\n".join(parts)

    def stream_reply(self, text: str, db: Session, user_id: int):
        yield " "

        prompt = self._build_prompt(text, db, user_id)
        payload = {
            "model": self.text_model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.7, "num_predict": 260}
        }

        with requests.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            stream=True,
            timeout=300
        ) as r:
            r.raise_for_status()
            full = []

            for line in r.iter_lines():
                if consume_stop(user_id):
                    break
                if not line:
                    continue

                data = json.loads(line.decode("utf-8"))
                chunk = data.get("response", "")
                if chunk:
                    full.append(chunk)
                    yield chunk

            final = "".join(full).strip()
            if final:
                db.add(ChatMessage(user_id=user_id, role="user", content=text))
                db.add(ChatMessage(user_id=user_id, role="assistant", content=final))
                db.commit()

    def clear_history(self, db: Session, user_id: int):
        db.query(ChatMessage).filter(ChatMessage.user_id == user_id).delete()
        db.commit()

    def analyze_images(self, prompt: str, image_bytes_list: list[bytes], db: Session, user_id: int) -> str:
        encoded_images = [base64.b64encode(b).decode("utf-8") for b in image_bytes_list]

        full_prompt = (
            f"{SYSTEM_PROMPT.strip()}\\n"
            f"User request about the image(s): {prompt or 'Analyze this image in detail.'}\\n"
            "Be specific. Describe what is visible, count obvious objects when possible, mention colors, structure, and readable details. Then answer the user's exact question clearly in English."
        )

        payload = {
            "model": self.vision_model,
            "prompt": full_prompt,
            "images": encoded_images,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 420}
        }

        r = requests.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            timeout=180
        )
        r.raise_for_status()

        data = r.json()
        final = (data.get("response") or "").strip()

        db.add(ChatMessage(user_id=user_id, role="user", content=f"[Image] {prompt or 'Analyze this image'}"))
        db.add(ChatMessage(user_id=user_id, role="assistant", content=final))
        db.commit()

        return final
```

## Replace `server/routes/chat.py`
```python
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from server.brain.agent import JarvisAgent
from server.core.security import get_user_id_from_token
from server.core.runtime_state import acquire_user_lock, release_user_lock, request_stop
from server.db.db import get_db

router = APIRouter()
agent = JarvisAgent()

@router.post("/stream")
def chat_stream(data: dict, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required.")

    if not acquire_user_lock(user_id):
        raise HTTPException(status_code=429, detail="Jarvis is already processing another request.")

    def wrapped():
        try:
            for chunk in agent.stream_reply(text, db, user_id):
                yield chunk
        finally:
            release_user_lock(user_id)

    return StreamingResponse(wrapped(), media_type="text/plain")

@router.post("/stop")
def stop_chat(authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    request_stop(user_id)
    return {"status": "stopping"}

@router.post("/clear")
def clear_chat(db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    agent.clear_history(db, user_id)
    return {"status": "cleared"}
```

## Replace `server/routes/vision.py`
```python
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session
from server.brain.agent import JarvisAgent
from server.core.security import get_user_id_from_token
from server.core.runtime_state import acquire_user_lock, release_user_lock
from server.db.db import get_db

router = APIRouter()
agent = JarvisAgent()

MAX_IMAGES = 1
MAX_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}

@router.post("/analyze")
async def analyze_images(
    images: list[UploadFile] = File(...),
    prompt: str = Form("Analyze this image."),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not acquire_user_lock(user_id):
        raise HTTPException(status_code=429, detail="Jarvis is already processing another request.")

    try:
        if len(images) > MAX_IMAGES:
            raise HTTPException(status_code=400, detail="Please upload only one image at a time for now.")

        image_bytes_list = []
        for image in images:
            if image.content_type not in ALLOWED_TYPES:
                raise HTTPException(status_code=400, detail="Only JPG, PNG, and WEBP images are supported.")

            content = await image.read()
            if not content:
                continue

            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail=f"{image.filename} is too large. Max size is 5MB.")

            image_bytes_list.append(content)

        if not image_bytes_list:
            raise HTTPException(status_code=400, detail="No valid images were uploaded.")

        result = agent.analyze_images(prompt, image_bytes_list, db, user_id)
        return {"response": result}

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Image analysis failed: {e}")
    finally:
        release_user_lock(user_id)
```

## Replace `server/main.py`
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from server.db.db import init_db, SessionLocal
from server.core.bootstrap import ensure_admin_user
from server.routes import auth, chat, history, vision, system
import os

app = FastAPI(title="Jarvix AI", version="5.0.0")

init_db()
db = SessionLocal()
try:
    ensure_admin_user(db)
finally:
    db.close()

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(vision.router, prefix="/vision", tags=["vision"])
app.include_router(system.router, prefix="/system", tags=["system"])

@app.get("/")
def landing():
    return FileResponse(os.path.join("web", "static", "landing.html"))

@app.get("/app")
def app_shell():
    return FileResponse(os.path.join("web", "static", "app.html"))

app.mount("/", StaticFiles(directory="web/static"), name="static")
```

## Replace `web/static/app.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Jarvix AI App</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div id="app">
    <div id="loginView" class="center-wrap">
      <div class="glass card auth-card">
        <div class="brand">
          <div class="brand-badge">J</div>
          <div>
            <h1>Jarvix AI</h1>
            <p>Sign in to your Jarvis dashboard</p>
          </div>
        </div>
        <form id="loginForm" class="auth-form">
          <label>Username</label>
          <input id="username" autocomplete="username" placeholder="Enter your username">
          <label>Password</label>
          <input id="password" type="password" autocomplete="current-password" placeholder="Enter your password">
          <button type="submit" class="primary-btn">Sign in</button>
          <div id="loginError" class="error-text"></div>
        </form>
      </div>
    </div>

    <div id="chatView" class="hidden">
      <aside class="sidebar glass">
        <div class="brand brand-small">
          <div class="brand-badge">J</div>
          <div>
            <h2>Jarvix AI</h2>
            <p>Full local companion stack</p>
          </div>
        </div>
        <div class="user-box">
          <div class="user-label">Signed in as</div>
          <div id="whoami">admin</div>
        </div>
        <div class="status-box">
          <div><span class="dot"></span> Chat and image analysis</div>
          <div class="small-note" id="statusText">Ready.</div>
        </div>
        <button id="newChatBtn" class="secondary-btn">New chat</button>
        <button id="warmupBtn" class="secondary-btn">Warm up vision</button>
        <button id="stopBtn" class="secondary-btn">Stop</button>
        <button id="logoutBtn" class="secondary-btn">Log out</button>
      </aside>

      <main class="main-panel">
        <div class="topbar glass">
          <div>
            <h1>Jarvis</h1>
            <p>Friendly chat, memory, image analysis, Cloudflare-ready</p>
          </div>
        </div>

        <div id="messages" class="messages glass"></div>

        <form id="composerForm" class="composer glass">
          <div class="dropzone" id="dropzone">
            <div class="drop-main">Drop one image here or choose it below</div>
            <div class="drop-sub">Single image mode is enabled for stability.</div>
          </div>

          <div class="composer-top">
            <textarea id="prompt" placeholder="Talk to Jarvis or ask about an image..." rows="3"></textarea>
          </div>

          <div class="composer-bottom">
            <label class="file-pill" id="filePill">
              <input id="imageFile" type="file" accept="image/jpeg,image/png,image/webp">
              <span id="fileLabel">Choose image</span>
            </label>
            <div id="typing" class="typing hidden">Jarvis is thinking…</div>
            <button id="sendBtn" type="submit" class="primary-btn">Send</button>
          </div>

          <div id="previewWrap" class="preview-wrap hidden"></div>
        </form>
      </main>
    </div>
  </div>
  <script src="/app.js"></script>
</body>
</html>
```

## Replace `web/static/app.js`
```javascript
const tokenKey = "jarvix_token";
const userKey = "jarvix_user";

const loginView = document.getElementById("loginView");
const chatView = document.getElementById("chatView");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const composerForm = document.getElementById("composerForm");
const imageFileInput = document.getElementById("imageFile");
const fileLabel = document.getElementById("fileLabel");
const filePill = document.getElementById("filePill");
const previewWrap = document.getElementById("previewWrap");
const messagesEl = document.getElementById("messages");
const typingEl = document.getElementById("typing");
const whoamiEl = document.getElementById("whoami");
const logoutBtn = document.getElementById("logoutBtn");
const sendBtn = document.getElementById("sendBtn");
const promptEl = document.getElementById("prompt");
const dropzone = document.getElementById("dropzone");
const stopBtn = document.getElementById("stopBtn");
const newChatBtn = document.getElementById("newChatBtn");
const warmupBtn = document.getElementById("warmupBtn");
const statusText = document.getElementById("statusText");

let busy = false;
let selectedFiles = [];
let currentController = null;

function setStatus(text) {
  statusText.textContent = text;
}
function setBusy(state) {
  busy = state;
  sendBtn.disabled = state;
  promptEl.disabled = state;
  imageFileInput.disabled = state;
  logoutBtn.disabled = state;
  newChatBtn.disabled = state;
  warmupBtn.disabled = state;
  filePill.classList.toggle("disabled", state);
  typingEl.classList.toggle("hidden", !state);
}
function showChat() {
  loginView.classList.add("hidden");
  chatView.classList.remove("hidden");
}
function showLogin() {
  chatView.classList.add("hidden");
  loginView.classList.remove("hidden");
}
function getToken() {
  return localStorage.getItem(tokenKey) || "";
}
function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.textContent = content;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}
function updateFileLabel() {
  fileLabel.textContent = selectedFiles.length ? `${selectedFiles.length} image selected` : "Choose image";
}
function renderPreviews() {
  previewWrap.innerHTML = "";
  if (!selectedFiles.length) {
    previewWrap.classList.add("hidden");
    return;
  }
  previewWrap.classList.remove("hidden");
  selectedFiles.forEach((file, index) => {
    const card = document.createElement("div");
    card.className = "preview-card";
    const img = document.createElement("img");
    const name = document.createElement("div");
    name.className = "preview-name";
    name.textContent = file.name;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-image-btn";
    removeBtn.textContent = "Remove";
    removeBtn.disabled = busy;
    removeBtn.addEventListener("click", () => {
      if (busy) return;
      selectedFiles.splice(index, 1);
      renderPreviews();
      updateFileLabel();
    });
    const reader = new FileReader();
    reader.onload = () => { img.src = reader.result; };
    reader.readAsDataURL(file);
    card.appendChild(img);
    card.appendChild(name);
    card.appendChild(removeBtn);
    previewWrap.appendChild(card);
  });
}
function addFiles(fileList) {
  const arr = Array.from(fileList).filter(f => f.type.startsWith("image/"));
  selectedFiles = arr.slice(0, 1);
  updateFileLabel();
  renderPreviews();
}
function clearFiles() {
  selectedFiles = [];
  imageFileInput.value = "";
  updateFileLabel();
  renderPreviews();
}
async function loadHistory() {
  messagesEl.innerHTML = "";
  const res = await fetch("/history/", {
    headers: { Authorization: `Bearer ${getToken()}` }
  });
  if (!res.ok) return;
  const rows = await res.json();
  if (!rows.length) {
    addMessage("assistant", "Hi. I'm Jarvis. What would you like to do today?");
    return;
  }
  for (const row of rows) {
    addMessage(row.role === "assistant" ? "assistant" : "user", row.content);
  }
}

loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.textContent = "";
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  const data = await res.json();
  if (!res.ok) {
    loginError.textContent = data.detail || "Login failed.";
    return;
  }
  localStorage.setItem(tokenKey, data.token);
  localStorage.setItem(userKey, data.username);
  whoamiEl.textContent = data.username;
  showChat();
  setStatus("Ready.");
  await loadHistory();
});

logoutBtn?.addEventListener("click", () => {
  if (busy) return;
  localStorage.removeItem(tokenKey);
  localStorage.removeItem(userKey);
  showLogin();
});

newChatBtn?.addEventListener("click", async () => {
  if (busy) return;
  await fetch("/chat/clear", {
    method: "POST",
    headers: { "Authorization": `Bearer ${getToken()}` }
  });
  messagesEl.innerHTML = "";
  addMessage("assistant", "New chat started. What would you like to do?");
});

warmupBtn?.addEventListener("click", async () => {
  if (busy) return;
  setStatus("Warming up the vision model...");
  try {
    const res = await fetch("/system/warmup-vision", { method: "POST" });
    const data = await res.json();
    setStatus(res.ok ? "Vision model is ready." : (data.detail || "Vision warm-up failed."));
  } catch {
    setStatus("Vision warm-up failed.");
  }
});

stopBtn?.addEventListener("click", async () => {
  if (currentController) currentController.abort();
  try {
    await fetch("/chat/stop", {
      method: "POST",
      headers: { "Authorization": `Bearer ${getToken()}` }
    });
  } catch {}
  setBusy(false);
  setStatus("Stopped.");
});

imageFileInput?.addEventListener("change", () => addFiles(imageFileInput.files || []));

dropzone?.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (!busy) dropzone.classList.add("active");
});
dropzone?.addEventListener("dragleave", () => dropzone.classList.remove("active"));
dropzone?.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("active");
  if (busy) return;
  addFiles(e.dataTransfer.files || []);
});

composerForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy) return;

  const text = promptEl.value.trim();
  const hasImages = selectedFiles.length > 0;
  if (!text && !hasImages) return;

  const userText = hasImages ? `[Image] ${text || "Analyze this image."}` : text;
  addMessage("user", userText);
  const assistantBubble = addMessage("assistant", "");
  setBusy(true);

  try {
    if (hasImages) {
      setStatus("Analyzing image. This can take up to 2-3 minutes.");
      currentController = new AbortController();
      const timeout = setTimeout(() => currentController.abort(), 180000);

      try {
        const formData = new FormData();
        selectedFiles.forEach((file) => formData.append("images", file));
        formData.append("prompt", text || "Analyze this image.");

        const res = await fetch("/vision/analyze", {
          method: "POST",
          headers: { "Authorization": `Bearer ${getToken()}` },
          body: formData,
          signal: currentController.signal
        });
        const data = await res.json();
        assistantBubble.textContent = res.ok ? (data.response || "No response.") : (data.detail || "Image analysis failed.");
        setStatus(res.ok ? "Ready." : "Vision request failed.");
      } catch (err) {
        assistantBubble.textContent = err.name === "AbortError"
          ? "Image analysis timed out. Try a smaller image or warm up the vision model first."
          : "Request failed. Check that Jarvis and the local models are running.";
        setStatus("Vision request stopped or failed.");
      } finally {
        clearTimeout(timeout);
      }
    } else {
      setStatus("Generating reply...");
      currentController = new AbortController();
      const res = await fetch("/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${getToken()}`
        },
        body: JSON.stringify({ text }),
        signal: currentController.signal
      });

      if (!res.ok || !res.body) {
        let message = "Something went wrong while contacting Jarvis.";
        try {
          const data = await res.json();
          if (data.detail) message = data.detail;
        } catch {}
        assistantBubble.textContent = message;
        setStatus("Request failed.");
      } else {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let finalText = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          finalText += chunk;
          assistantBubble.textContent = finalText;
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
        setStatus("Ready.");
      }
    }
  } catch (err) {
    assistantBubble.textContent = "Request failed. Check that Jarvis and the local models are running.";
    setStatus("Request failed.");
  } finally {
    currentController = null;
    promptEl.value = "";
    clearFiles();
    setBusy(false);
  }
});

window.addEventListener("load", async () => {
  const token = localStorage.getItem(tokenKey) || "";
  const username = localStorage.getItem(userKey) || "user";
  updateFileLabel();
  if (!token) {
    showLogin();
    return;
  }
  whoamiEl.textContent = username;
  showChat();
  setStatus("Ready.");
  await loadHistory();
});
```

## Add `.gitignore`
```gitignore
venv/
__pycache__/
*.pyc
.env
data/*.db
server/__pycache__/
server/*/__pycache__/
web/static/*.map
```

## Local commands after replacing files
```bash
git checkout feature-jarvis-upgrade
git add .
git commit -m "Upgrade Jarvis stability and UX"
git push
```
