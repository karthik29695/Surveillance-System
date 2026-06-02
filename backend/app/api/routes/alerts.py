from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.models import Alert
from app.schemas.schemas import AlertResponse

router = APIRouter()

@router.get("/", response_model=List[AlertResponse])
def list_alerts(unread_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Alert)
    if unread_only: q = q.filter(Alert.is_read == False)
    return q.order_by(Alert.created_at.desc()).limit(100).all()

@router.patch("/{alert_id}/read")
def mark_read(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert: alert.is_read = True; db.commit()
    return {"ok": True}
