import base64
import json
import requests
from sqlalchemy.orm import Session
from server.core.config import JARVIS_TEXT_MODEL, JARVIS_VISION_MODEL, OLLAMA_URL, CREATOR_NAME
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
            "options": {
                "temperature": 0.7,
                "num_predict": 260
            }
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
                if not line:
                    continue

                data = json.loads(line.decode("utf-8"))
                chunk = data.get("response", "")
                if chunk:
                    full.append(chunk)
                    yield chunk

            final = "".join(full).strip()
            db.add(ChatMessage(user_id=user_id, role="user", content=text))
            db.add(ChatMessage(user_id=user_id, role="assistant", content=final))
            db.commit()

    def analyze_images(self, prompt: str, image_bytes_list: list[bytes], db: Session, user_id: int) -> str:
        encoded_images = [base64.b64encode(b).decode("utf-8") for b in image_bytes_list]

        full_prompt = (
            f"{SYSTEM_PROMPT.strip()}\\n"
            f"User request about the image(s): {prompt or 'Analyze this image in detail.'}\\n"
            "Describe what is visible, then answer the user's request clearly in English."
        )

        payload = {
            "model": self.vision_model,
            "prompt": full_prompt,
            "images": encoded_images,
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": 380
            }
        }

        r = requests.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            timeout=900
        )
        r.raise_for_status()

        data = r.json()
        final = (data.get("response") or "").strip()

        db.add(ChatMessage(user_id=user_id, role="user", content=f"[Image] {prompt or 'Analyze this image'}"))
        db.add(ChatMessage(user_id=user_id, role="assistant", content=final))
        db.commit()

        return final