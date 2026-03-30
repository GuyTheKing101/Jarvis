from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from server.db.db import get_db
from server.db.models import User
from server.core.security import verify_password, create_token, get_user_id_from_token

router = APIRouter()

@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"token": create_token(user.id), "username": user.username}

@router.get("/me")
def me(authorization: str = ""):
    token = authorization.removeprefix("Bearer ").strip()
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"user_id": user_id}
