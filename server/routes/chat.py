from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from server.brain.agent import JarvisAgent
from server.core.security import get_user_id_from_token
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
    return StreamingResponse(agent.stream_reply(text, db, user_id), media_type="text/plain")
