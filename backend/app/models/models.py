from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class VideoFeed(Base):
    __tablename__ = "video_feeds"
    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String, nullable=False)
    source_type    = Column(String, nullable=False)
    source_url     = Column(String)
    file_path      = Column(String)
    annotated_path = Column(String, nullable=True)
    status         = Column(String, default="idle")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    events         = relationship("DetectionEvent", back_populates="feed")
    zones          = relationship("FeedZone", back_populates="feed")

class DetectionEvent(Base):
    __tablename__ = "detection_events"
    id                       = Column(Integer, primary_key=True, index=True)
    feed_id                  = Column(Integer, ForeignKey("video_feeds.id"))
    event_type               = Column(String, nullable=False)
    timestamp                = Column(DateTime(timezone=True), server_default=func.now())
    frame_number             = Column(Integer)
    video_timestamp_seconds  = Column(Float)
    confidence               = Column(Float)
    bounding_box             = Column(JSON)
    extra_data               = Column(JSON)
    snapshot_path            = Column(String)
    feed                     = relationship("VideoFeed", back_populates="events")

class Alert(Base):
    __tablename__ = "alerts"
    id         = Column(Integer, primary_key=True, index=True)
    feed_id    = Column(Integer, ForeignKey("video_feeds.id"))
    alert_type = Column(String, nullable=False)
    severity   = Column(String, default="medium")
    message    = Column(Text)
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    event_id   = Column(Integer, ForeignKey("detection_events.id"), nullable=True)

class SuspectProfile(Base):
    __tablename__ = "suspect_profiles"
    id                 = Column(Integer, primary_key=True, index=True)
    name               = Column(String, nullable=False)
    notes              = Column(Text)
    face_encoding_path = Column(String)
    image_path         = Column(String)
    added_at           = Column(DateTime(timezone=True), server_default=func.now())
    is_active          = Column(Boolean, default=True)

class FeedZone(Base):
    __tablename__ = "feed_zones"
    id        = Column(Integer, primary_key=True, index=True)
    feed_id   = Column(Integer, ForeignKey("video_feeds.id"), nullable=False)
    name      = Column(String, nullable=False)
    zone_type = Column(String, nullable=False, default="restricted")
    points    = Column(JSON, nullable=False)       # [[x,y], ...]
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    feed      = relationship("VideoFeed", back_populates="zones")

class Zone(Base):
    __tablename__ = "zones"
    id          = Column(Integer, primary_key=True, index=True)
    feed_id     = Column(Integer, ForeignKey("video_feeds.id"), nullable=True)
    zone_name   = Column(String, nullable=False)
    zone_type   = Column(String, nullable=False)
    points      = Column(JSON, nullable=False)
    color       = Column(String, default="#ef4444")
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())