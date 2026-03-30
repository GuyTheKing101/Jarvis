import os
from pathlib import Path

def load_env():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

load_env()

JARVIS_TEXT_MODEL = os.getenv("JARVIS_TEXT_MODEL", "llama3")
JARVIS_VISION_MODEL = os.getenv("JARVIS_VISION_MODEL", "llava")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-now")
CREATOR_NAME = os.getenv("CREATOR_NAME", "Guy")
APP_TITLE = os.getenv("APP_TITLE", "Jarvix AI")
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN", "jarvix.world")
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "https://api.jarvix.world")
