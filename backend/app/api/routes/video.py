import os, shutil
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.models.models import VideoFeed, DetectionEvent, Zone
from app.schemas.schemas import VideoFeedResponse
from app.services.detection.yolo_detector import YOLODetector
from app.services.detection.tracker import CentroidTracker
from app.services.detection.zone_intelligence import ZoneIntelligence
from app.services.detection.event_intelligence_engine import EventIntelligenceEngine
from app.services.detection.loitering_intelligence import LoiteringIntelligence
from app.services.detection.track_stabilizer import TrackStabilizationLayer
from app.services.detection.behavior_scorer import BehaviorScorer
from app.services.detection.explainability_layer import ExplainabilityLayer
from app.services.detection.zone_policy import ZonePolicyRegistry
from app.services.detection.movement_intelligence import MovementIntelligence
from app.services.recording.adaptive_recorder import AdaptiveRecorder
from app.services.recording.annotated_writer import AnnotatedVideoWriter

router = APIRouter()
detector = YOLODetector()


@router.post("/upload", response_model=VideoFeedResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    feed = VideoFeed(name=file.filename, source_type="upload", file_path=file_path, status="queued")
    db.add(feed); db.commit(); db.refresh(feed)
    background_tasks.add_task(process_video_file, feed.id, file_path)
    return feed


@router.get("/", response_model=list[VideoFeedResponse])
def list_feeds(db: Session = Depends(get_db)):
    return db.query(VideoFeed).all()


@router.get("/{feed_id}", response_model=VideoFeedResponse)
def get_feed(feed_id: int, db: Session = Depends(get_db)):
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


@router.get("/{feed_id}/download")
def download_annotated(feed_id: int, db: Session = Depends(get_db)):
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    if feed.status != "completed":
        raise HTTPException(status_code=409, detail=f"Video not ready — status: {feed.status}")
    path = _annotated_path(feed_id, feed.name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Annotated file not found.")
    return FileResponse(path, media_type="video/mp4", filename=f"annotated_{feed.name}")


@router.post("/{feed_id}/reprocess")
def reprocess_feed(feed_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Re-run detection on an existing feed (clears old events first)."""
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    if not feed.file_path or not os.path.exists(feed.file_path):
        raise HTTPException(status_code=404, detail="Source file no longer exists")
    # Clear old events for this feed
    db.query(DetectionEvent).filter(DetectionEvent.feed_id == feed_id).delete()
    feed.status = "queued"
    db.commit()
    # Delete old annotated file so it regenerates
    old_path = _annotated_path(feed_id, os.path.basename(feed.file_path))
    if os.path.exists(old_path):
        os.remove(old_path)
    background_tasks.add_task(process_video_file, feed.id, feed.file_path)
    return {"ok": True, "feed_id": feed_id, "message": "Reprocessing started"}



@router.get("/{feed_id}/annotated-status")
def annotated_status(feed_id: int, db: Session = Depends(get_db)):
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    path = _annotated_path(feed_id, feed.name)
    return {"feed_id": feed_id, "feed_status": feed.status, "annotated_ready": os.path.exists(path)}

@router.get("/{feed_id}/frame")
def get_frame(feed_id: int, db: Session = Depends(get_db)):
    """Return the first frame of the video as a JPEG for zone drawing preview."""
    import cv2
    from fastapi.responses import Response
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    if not feed or not feed.file_path:
        raise HTTPException(status_code=404, detail="Feed not found")
    cap = cv2.VideoCapture(feed.file_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise HTTPException(status_code=404, detail="Could not read frame")
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/{feed_id}/risk-profiles")
def get_risk_profiles(feed_id: int, db: Session = Depends(get_db)):
    """
    Returns serialized risk profiles + explanations stored in recent events.
    Used by frontend Risk Intelligence Panel.
    """
    from app.models.models import DetectionEvent
    rows = db.query(DetectionEvent).filter(
        DetectionEvent.feed_id == feed_id,
        DetectionEvent.event_type == "suspicious_behavior",
    ).order_by(DetectionEvent.video_timestamp_seconds.desc()).limit(100).all()

    # Deduplicate by track_id keeping highest score
    seen: Dict[int, Dict] = {}
    for row in rows:
        ed = row.extra_data or {}
        tid = ed.get("track_id")
        if tid is None:
            continue
        if tid not in seen or ed.get("risk_score", 0) > seen[tid].get("risk_score", 0):
            seen[tid] = {
                "track_id":          tid,
                "risk_score":        ed.get("risk_score", 0),
                "risk_level":        ed.get("risk_level", "normal"),
                "trend":             ed.get("trend", "stable"),
                "dominant_signals":  ed.get("dominant_signals", []),
                "contributors":      ed.get("contributors", {}),
                "top_contributors":  ed.get("top_contributors", []),
                "escalation_history":ed.get("escalation_history", []),
                "timeline":          ed.get("timeline", []),
                "trigger":           ed.get("trigger", ""),
                "summary":           ed.get("message", ""),
                "zone_dwell_secs":   ed.get("zone_dwell_secs", 0),
                "reentry_count":     ed.get("reentry_count", 0),
                "incident_count":    ed.get("incident_count", 0),
                "video_ts":          row.video_timestamp_seconds,
            }

    return sorted(seen.values(), key=lambda x: x["risk_score"], reverse=True)




def _annotated_path(feed_id: int, original_name: str) -> str:
    base = os.path.splitext(original_name)[0]
    return os.path.join(settings.RECORDINGS_DIR, f"annotated_{feed_id}_{base}.mp4")


def _load_zones(feed_id: int, db: Session):
    rows = db.query(Zone).filter(
        Zone.is_active == True,
        (Zone.feed_id == feed_id) | (Zone.feed_id == None)
    ).all()
    return [{"id": z.id, "zone_name": z.zone_name, "zone_type": z.zone_type,
             "points": z.points, "color": z.color} for z in rows]


def process_video_file(feed_id: int, file_path: str):
    import cv2
    from app.core.database import SessionLocal

    db   = SessionLocal()
    feed = db.query(VideoFeed).filter(VideoFeed.id == feed_id).first()
    feed.status = "processing"; db.commit()

    # Load zones configured for this feed
    zone_dicts = _load_zones(feed_id, db)
    tracker           = CentroidTracker()
    stabilizer        = TrackStabilizationLayer()
    scorer            = BehaviorScorer()
    explainer         = ExplainabilityLayer()
    zi                = ZoneIntelligence(zone_dicts)
    loitering_intel   = LoiteringIntelligence()
    engine            = EventIntelligenceEngine(zones=zone_dicts)
    recorder = AdaptiveRecorder()

    cap    = cv2.VideoCapture(file_path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_path = _annotated_path(feed_id, os.path.basename(file_path))
    os.makedirs(settings.RECORDINGS_DIR, exist_ok=True)
    writer = AnnotatedVideoWriter(out_path, fps, width, height)

    frame_number   = 0
    activity_score = 0.0
    last_tracks    = []
    last_zone_results = []
    recent_events  = []
    total_new = total_ended = 0
    risk_profiles  = {}
    explanations   = {}

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = frame_number / fps

            if recorder.should_process_frame(frame_number, activity_score):
                detections        = detector.detect(frame)
                raw_tracks        = tracker.update(detections, timestamp)

                # Stabilization layer: grace-period lifecycle, recovery, state machine
                all_tracks, internal_events = stabilizer.update(raw_tracks, timestamp, frame_number)
                last_tracks = stabilizer.get_stable_tracks(all_tracks)

                # Scene summary (every 30s)
                summary = stabilizer.scene_summary(all_tracks, timestamp)

                last_zone_results = zi.test(last_tracks)
                activity_score    = engine.compute_activity_score(last_tracks)

                loitering_signals = loitering_intel.analyze(
                    last_tracks, last_zone_results, frame_number, timestamp
                )

                # Behavior scoring → Explainability
                risk_profiles, escalations = scorer.score(
                    last_tracks, last_zone_results, loitering_signals,
                    frame_number, timestamp
                )

                new_events, ended_events = engine.process(
                    last_tracks, frame_number, timestamp,
                    zone_results=last_zone_results,
                    loitering_signals=loitering_signals,
                )

                # Append behavior escalations to DB-bound events
                # Explainability layer — produces structured reasoning
                explanations = explainer.explain(risk_profiles)
                all_new = new_events + escalations

                # Persist only VISIBLE security incidents to DB
                # Internal tracking events are excluded (visible=False)
                all_new = new_events + ended_events
                visible_events = [
                    ev for ev in (new_events + escalations)
                    if ev.get("extra_data", {}).get("visible", True)
                ]
                total_new   += len(new_events)
                total_ended += len(ended_events)

                for ev in visible_events:
                    db.add(DetectionEvent(
                        feed_id=feed_id,
                        event_type=ev["event_type"],
                        frame_number=ev["frame_number"],
                        video_timestamp_seconds=ev["video_timestamp_seconds"],
                        confidence=ev.get("confidence", 1.0),
                        bounding_box=ev.get("bounding_box", {}),
                        extra_data=ev.get("extra_data", {}),
                    ))

                recent_events = (recent_events + visible_events)[-5:]

            # Draw: zones first, then tracks, then zone hits
            track_dets = [{
                "class": t.cls, "confidence": t.confidence, "bbox": t.bbox,
                "track_id": t.track_id, "dwell_seconds": t.dwell_seconds,
                "is_stationary": t.is_stationary,
            } for t in last_tracks]

            writer.write(
                frame, track_dets, recent_events, frame_number,
                activity_score, recorder.current_mode,
                zone_intelligence=zi, zone_results=last_zone_results,
                risk_profiles=risk_profiles,
                explanations=explanations,
            )
            frame_number += 1

        db.commit()
        feed.status = "completed"
        print(f"[Pipeline] Done — {frame_number} frames | {total_new} events | zones: {len(zone_dicts)}")

    except Exception as e:
        feed.status = "error"
        print(f"[process_video] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        cap.release()
        writer.release()
        db.commit()
        db.close()
