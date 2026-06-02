import os, shutil
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.models.models import SuspectProfile
from app.schemas.schemas import SuspectProfileResponse
from app.services.face_recognition.face_service import FaceRecognitionService

router = APIRouter()
face_service = FaceRecognitionService()

@router.post("/suspects", response_model=SuspectProfileResponse)
async def add_suspect(name: str, notes: str = "", image: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs(settings.FACES_DB_DIR, exist_ok=True)
    image_path = os.path.join(settings.FACES_DB_DIR, f"{name.replace(' ', '_')}_{image.filename}")
    with open(image_path, "wb") as f:
        shutil.copyfileobj(image.file, f)
    profile = SuspectProfile(name=name, notes=notes, image_path=image_path)
    db.add(profile); db.commit(); db.refresh(profile)
    if not face_service.add_suspect(profile.id, name, image_path):
        raise HTTPException(status_code=400, detail="No face detected in image.")
    return profile

@router.get("/suspects", response_model=list[SuspectProfileResponse])
def list_suspects(db: Session = Depends(get_db)):
    return db.query(SuspectProfile).filter(SuspectProfile.is_active == True).all()
