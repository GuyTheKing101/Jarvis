from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session
from server.brain.agent import JarvisAgent
from server.core.security import get_user_id_from_token
from server.db.db import get_db

router = APIRouter()
agent = JarvisAgent()

MAX_IMAGES = 1
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


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

    if len(images) > MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail="Please upload only one image at a time for now."
        )

    image_bytes_list = []

    for image in images:
        content = await image.read()

        if not content:
            continue

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"{image.filename} is too large. Max size is 5MB."
            )

        image_bytes_list.append(content)

    if not image_bytes_list:
        raise HTTPException(status_code=400, detail="No valid images were uploaded.")

    try:
        result = agent.analyze_images(prompt, image_bytes_list, db, user_id)
        return {"response": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image analysis failed: {e}")