from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models.models import Zone
from app.schemas.schemas import ZoneCreate, ZoneResponse

router = APIRouter()

@router.post("/", response_model=ZoneResponse)
def create_zone(zone: ZoneCreate, db: Session = Depends(get_db)):
    db_zone = Zone(**zone.model_dump())
    db.add(db_zone); db.commit(); db.refresh(db_zone)
    return db_zone

@router.get("/", response_model=List[ZoneResponse])
def list_zones(feed_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Zone).filter(Zone.is_active == True)
    if feed_id is not None:
        q = q.filter((Zone.feed_id == feed_id) | (Zone.feed_id == None))
    return q.all()

@router.delete("/{zone_id}")
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone.is_active = False
    db.commit()
    return {"ok": True}

@router.put("/{zone_id}", response_model=ZoneResponse)
def update_zone(zone_id: int, zone: ZoneCreate, db: Session = Depends(get_db)):
    db_zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not db_zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    for k, v in zone.model_dump().items():
        setattr(db_zone, k, v)
    db.commit(); db.refresh(db_zone)
    return db_zone
