from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from server.core.security import get_user_id_from_token
from server.db.db import get_db
from server.db.models import ChatMessage

router = APIRouter()

@router.get("/")
def history(db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.id.asc())
        .limit(200)
        .all()
    )
    return [{"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()} for r in rows]
