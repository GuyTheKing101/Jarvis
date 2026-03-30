from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from server.db.db import init_db, SessionLocal
from server.core.bootstrap import ensure_admin_user
from server.routes import auth, chat, history, vision
import os

app = FastAPI(title="Jarvix AI", version="4.0.0")

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

@app.get("/")
def landing():
    return FileResponse(os.path.join("web", "static", "landing.html"))

@app.get("/app")
def app_shell():
    return FileResponse(os.path.join("web", "static", "app.html"))

app.mount("/", StaticFiles(directory="web/static"), name="static")
