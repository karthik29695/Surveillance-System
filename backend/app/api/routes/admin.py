from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import VideoFeed, DetectionEvent, Alert, SuspectProfile, Zone

router = APIRouter()

@router.delete("/clear-db")
def clear_db(db: Session = Depends(get_db)):
    """Delete all feeds, events, alerts. Keep zones and suspects."""
    db.query(DetectionEvent).delete()
    db.query(Alert).delete()
    db.query(VideoFeed).delete()
    db.commit()
    return {"ok": True, "message": "All feeds and events cleared."}

@router.delete("/clear-all")
def clear_all(db: Session = Depends(get_db)):
    """Delete everything including zones."""
    db.query(DetectionEvent).delete()
    db.query(Alert).delete()
    db.query(Zone).delete()
    db.query(VideoFeed).delete()
    db.commit()
    return {"ok": True, "message": "Everything cleared."}
