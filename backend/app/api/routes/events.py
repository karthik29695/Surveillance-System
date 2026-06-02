from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.models.models import DetectionEvent
from app.schemas.schemas import DetectionEventResponse

router = APIRouter()

# Security incident types shown in dashboard/alerts/timeline
SECURITY_INCIDENT_TYPES = {
    "zone_breach", "loitering_detected", "crowd_detected",
    "object_left_behind", "suspect_identified", "re_entry",
    "suspicious_behavior", "zone_breach:ended", "loitering_detected:ended",
}

@router.get("/", response_model=List[DetectionEventResponse])
def list_events(
    feed_id:       Optional[int]  = Query(None),
    event_type:    Optional[str]  = Query(None),
    incidents_only: bool          = Query(False),  # only security incidents
    limit:         int            = Query(50, le=500),
    db: Session = Depends(get_db)
):
    q = db.query(DetectionEvent)
    if feed_id:
        q = q.filter(DetectionEvent.feed_id == feed_id)
    if event_type:
        q = q.filter(DetectionEvent.event_type == event_type)
    if incidents_only:
        q = q.filter(DetectionEvent.event_type.in_(SECURITY_INCIDENT_TYPES))
    return q.order_by(DetectionEvent.timestamp.desc()).limit(limit).all()

@router.get("/incidents", response_model=List[DetectionEventResponse])
def list_incidents(
    feed_id: Optional[int] = Query(None),
    limit:   int           = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """Returns only visible security incidents for dashboard/alerts."""
    q = db.query(DetectionEvent).filter(
        DetectionEvent.event_type.in_(SECURITY_INCIDENT_TYPES)
    )
    if feed_id:
        q = q.filter(DetectionEvent.feed_id == feed_id)
    return q.order_by(DetectionEvent.timestamp.desc()).limit(limit).all()
