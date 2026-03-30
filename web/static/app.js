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

let busy = false;
let selectedFiles = [];

function setBusy(state) {
  busy = state;
  sendBtn.disabled = state;
  promptEl.disabled = state;
  imageFileInput.disabled = state;
  logoutBtn.disabled = state;
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
  fileLabel.textContent = selectedFiles.length ? `${selectedFiles.length} image(s) selected` : "Choose images";
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
  for (const file of Array.from(fileList)) {
    if (file.type.startsWith("image/")) selectedFiles.push(file);
  }
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
  await loadHistory();
});

logoutBtn?.addEventListener("click", () => {
  if (busy) return;
  localStorage.removeItem(tokenKey);
  localStorage.removeItem(userKey);
  showLogin();
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

  const userText = hasImages ? `[Image${selectedFiles.length > 1 ? "s" : ""}] ${text || "Analyze these images."}` : text;
  addMessage("user", userText);
  const assistantBubble = addMessage("assistant", "");
  setBusy(true);

  try {
    if (hasImages) {
      const formData = new FormData();
      selectedFiles.forEach((file) => formData.append("images", file));
      formData.append("prompt", text || "Analyze these images.");
      const res = await fetch("/vision/analyze", {
        method: "POST",
        headers: { "Authorization": `Bearer ${getToken()}` },
        body: formData
      });
      const data = await res.json();
      assistantBubble.textContent = res.ok ? (data.response || "No response.") : (data.detail || "Image analysis failed.");
    } else {
      const res = await fetch("/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${getToken()}`
        },
        body: JSON.stringify({ text })
      });

      if (!res.ok || !res.body) {
        let message = "Something went wrong while contacting Jarvis.";
        try {
          const data = await res.json();
          if (data.detail) message = data.detail;
        } catch {}
        assistantBubble.textContent = message;
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
      }
    }
  } catch (err) {
    assistantBubble.textContent = "Request failed. Check that Jarvis and the local models are running.";
  } finally {
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
  await loadHistory();
});