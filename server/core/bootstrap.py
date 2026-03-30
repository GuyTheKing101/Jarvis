from sqlalchemy.orm import Session
from server.core.config import ADMIN_USERNAME, ADMIN_PASSWORD
from server.core.security import hash_password
from server.db.models import User

def ensure_admin_user(db: Session):
    existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
    if existing:
        return
    db.add(User(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD)))
    db.commit()
