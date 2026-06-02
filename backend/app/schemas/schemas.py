from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class VideoFeedCreate(BaseModel):
    name: str
    source_type: str
    source_url: Optional[str] = None

class VideoFeedResponse(BaseModel):
    id: int
    name: str
    source_type: str
    status: str
    annotated_path: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True

class DetectionEventResponse(BaseModel):
    id: int
    feed_id: int
    event_type: str
    timestamp: datetime
    frame_number: Optional[int]
    video_timestamp_seconds: Optional[float]
    confidence: Optional[float]
    bounding_box: Optional[Dict]
    extra_data: Optional[Dict]
    snapshot_path: Optional[str]
    class Config:
        from_attributes = True

class AlertResponse(BaseModel):
    id: int
    feed_id: int
    alert_type: str
    severity: str
    message: str
    is_read: bool
    created_at: datetime
    class Config:
        from_attributes = True

class SuspectProfileCreate(BaseModel):
    name: str
    notes: Optional[str] = None

class SuspectProfileResponse(BaseModel):
    id: int
    name: str
    notes: Optional[str]
    image_path: Optional[str]
    added_at: datetime
    is_active: bool
    class Config:
        from_attributes = True

class ZoneCreate(BaseModel):
    feed_id:   Optional[int] = None
    zone_name: str
    zone_type: str = "restricted"
    points:    List[List[float]]
    color:     Optional[str] = "#ef4444"

class ZoneResponse(BaseModel):
    id:        int
    feed_id:   Optional[int]
    zone_name: str
    zone_type: str
    points:    List[List[float]]
    color:     str
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True
