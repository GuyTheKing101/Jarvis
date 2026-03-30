from fastapi import APIRouter, HTTPException
from server.brain.agent import JarvisAgent

router = APIRouter()
agent = JarvisAgent()


@router.get("/health")
def health():
    try:
        return {"status": "ok", "ollama": agent.health()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")


@router.post("/warmup-vision")
def warmup_vision():
    try:
        return {"status": "ok", "message": agent.warmup_vision()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision warm-up failed: {e}")
