"""
Live Stream — Refined Pipeline v6
===================================
Fixes:
  1. Frame pacing — token bucket regulator, not just interval check
  2. Frame age tracking — capture_ts → process_ts → send_ts → age_ms
  3. WebSocket instrumentation — send time, backlog detection
  4. Dropped frame policy — always process newest, discard stale
  5. Tracker responsiveness — predict position forward by frame_age
"""
import asyncio, cv2, base64, time, math, collections
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.profiler import PipelineProfiler
from app.services.detection.yolo_detector import YOLODetector
from app.services.detection.tracker import CentroidTracker
from app.services.detection.track_stabilizer import TrackStabilizationLayer
from app.services.detection.zone_intelligence import ZoneIntelligence
from app.services.detection.zone_policy import ZonePolicyRegistry
from app.services.detection.loitering_intelligence import LoiteringIntelligence
from app.services.detection.movement_intelligence import MovementIntelligence
from app.services.detection.behavior_scorer import BehaviorScorer
from app.services.detection.explainability_layer import ExplainabilityLayer
from app.services.detection.event_intelligence_engine import EventIntelligenceEngine
from app.services.recording.annotated_writer import (
    draw_detections, draw_event_banners, draw_hud
)

router    = APIRouter()
detector  = YOLODetector()
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="stream")


class StreamConfig:
    INFER_WIDTH:       int   = 640
    INFER_HEIGHT:      int   = 360
    DISPLAY_WIDTH:     int   = 960
    DISPLAY_HEIGHT:    int   = 540
    JPEG_QUALITY:      int   = 60
    TARGET_FPS:        float = 20.0
    STATS_REFRESH_HZ:  float = 1.0
    # Frame age threshold — drop frames older than this before sending
    MAX_FRAME_AGE_MS:  float = 150.0
    # Bounding box prediction — compensate for detection lag
    BBOX_PREDICT_MS:   float = 80.0    # predict tracks forward by this amount


# ── Frame Pacer ───────────────────────────────────────────────────────────
class FramePacer:
    """
    Token bucket rate limiter for smooth frame delivery.
    Prevents bursts of frames followed by gaps (micro-stutter cause #1).
    """
    def __init__(self, target_fps: float):
        self._interval   = 1.0 / target_fps
        self._next_send  = time.perf_counter()
        self._jitter_buf = collections.deque(maxlen=30)   # inter-frame interval log

    def ready(self) -> bool:
        now = time.perf_counter()
        if now >= self._next_send:
            gap = now - self._next_send
            self._jitter_buf.append(gap * 1000)   # ms overshoot
            # Schedule next slot from ideal time, not now (prevents drift)
            self._next_send += self._interval
            # If we're more than 2 frames behind, reset (burst recovery)
            if now > self._next_send + self._interval:
                self._next_send = now + self._interval
            return True
        return False

    @property
    def jitter_ms(self) -> float:
        if not self._jitter_buf: return 0.0
        return round(sum(self._jitter_buf) / len(self._jitter_buf), 2)

    @property
    def max_jitter_ms(self) -> float:
        if not self._jitter_buf: return 0.0
        return round(max(self._jitter_buf), 2)


# ── Frame Age Tracker ─────────────────────────────────────────────────────
class FrameAgeTracker:
    """Tracks latency at each pipeline stage."""
    def __init__(self):
        self._ages: collections.deque = collections.deque(maxlen=60)
        self._capture_ts: float = 0.0

    def mark_capture(self): self._capture_ts = time.perf_counter()

    def mark_send(self) -> float:
        age_ms = (time.perf_counter() - self._capture_ts) * 1000
        self._ages.append(age_ms)
        return age_ms

    @property
    def avg_age_ms(self) -> float:
        if not self._ages: return 0.0
        return round(sum(self._ages) / len(self._ages), 1)

    @property
    def max_age_ms(self) -> float:
        if not self._ages: return 0.0
        return round(max(self._ages), 1)

    @property
    def is_stale(self) -> bool:
        age = (time.perf_counter() - self._capture_ts) * 1000
        return age > StreamConfig.MAX_FRAME_AGE_MS


# ── Drop Counter ──────────────────────────────────────────────────────────
class DropCounter:
    def __init__(self):
        self.total_frames   = 0
        self.dropped_frames = 0
        self._window: collections.deque = collections.deque(maxlen=100)

    def frame(self, dropped: bool):
        self.total_frames += 1
        if dropped:
            self.dropped_frames += 1
        self._window.append(1 if dropped else 0)

    @property
    def drop_rate_pct(self) -> float:
        if not self._window: return 0.0
        return round(sum(self._window) / len(self._window) * 100, 1)


# ── WS Instrumentation ────────────────────────────────────────────────────
class WSInstrumentation:
    def __init__(self):
        self._send_times: collections.deque = collections.deque(maxlen=30)
        self.backlog_warnings = 0

    def record_send(self, ms: float):
        self._send_times.append(ms)
        if ms > 50:
            self.backlog_warnings += 1

    @property
    def avg_send_ms(self) -> float:
        if not self._send_times: return 0.0
        return round(sum(self._send_times) / len(self._send_times), 1)

    @property
    def max_send_ms(self) -> float:
        if not self._send_times: return 0.0
        return round(max(self._send_times), 1)


# ── Bbox Predictor ────────────────────────────────────────────────────────
class BboxPredictor:
    """
    Compensates for detection lag by predicting where objects will be
    at display time based on their recent velocity.
    """
    def __init__(self):
        self._velocities: dict = {}   # track_id → (vx, vy) px/ms

    def update(self, tracks: list):
        for t in tracks:
            hist = getattr(t, "history", [])
            if len(hist) < 2: continue
            # Average velocity over last 3 positions
            n = min(3, len(hist) - 1)
            vx = (hist[-1][0] - hist[-n-1][0]) / max(n, 1)
            vy = (hist[-1][1] - hist[-n-1][1]) / max(n, 1)
            self._velocities[t.track_id] = (vx, vy)

    def predict_dets(self, track_dets: list, predict_ms: float) -> list:
        """Shift bboxes forward by velocity * predict_ms."""
        if predict_ms <= 0:
            return track_dets
        result = []
        for det in track_dets:
            tid = det.get("track_id")
            if tid and tid in self._velocities:
                vx, vy = self._velocities[tid]
                # Clamp prediction to avoid wild jumps
                dx = max(-30, min(30, int(vx * predict_ms / 40)))
                dy = max(-30, min(30, int(vy * predict_ms / 40)))
                b = det["bbox"]
                det = {**det, "bbox": {
                    "x": b["x"] + dx, "y": b["y"] + dy,
                    "w": b["w"],       "h": b["h"],
                }}
            result.append(det)
        return result


def _load_zones(feed_id: int):
    try:
        from app.core.database import SessionLocal
        from app.models.models import Zone
        db = SessionLocal()
        rows = db.query(Zone).filter(
            Zone.is_active == True,
            (Zone.feed_id == feed_id) | (Zone.feed_id == None)
        ).all()
        db.close()
        return [{"id": z.id, "zone_name": z.zone_name, "zone_type": z.zone_type,
                 "points": z.points, "color": z.color} for z in rows]
    except Exception as e:
        print(f"[stream] Zone load: {e}"); return []


def _scale_dets(dets, sx, sy):
    return [{**d, "bbox": {
        "x": int(d["bbox"]["x"]*sx), "y": int(d["bbox"]["y"]*sy),
        "w": int(d["bbox"]["w"]*sx), "h": int(d["bbox"]["h"]*sy),
    }} for d in dets]


def _run_yolo(frame_small):
    return detector.detect(frame_small)


def _encode_jpeg(frame, quality):
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


@router.websocket("/ws/{feed_id}")
async def stream_ws(websocket: WebSocket, feed_id: int):
    await websocket.accept()

    zone_dicts = _load_zones(feed_id)
    print(f"[stream] Feed {feed_id} — {len(zone_dicts)} zones")

    tracker         = CentroidTracker()
    stabilizer      = TrackStabilizationLayer()
    zi              = ZoneIntelligence(zone_dicts)
    policy          = ZonePolicyRegistry(zone_dicts)
    loitering_intel = LoiteringIntelligence(policy_registry=policy)
    movement_intel  = MovementIntelligence()
    scorer          = BehaviorScorer(policy_registry=policy)
    explainer       = ExplainabilityLayer()
    engine          = EventIntelligenceEngine(zones=zone_dicts)
    profiler        = PipelineProfiler(report_every=100)

    pacer       = FramePacer(StreamConfig.TARGET_FPS)
    age_tracker = FrameAgeTracker()
    drops       = DropCounter()
    ws_stats    = WSInstrumentation()
    predictor   = BboxPredictor()

    yolo_future   = None
    encode_future = None
    cap = None

    try:
        config = await websocket.receive_json()
        source = config.get("source", 0)
        if str(source).isdigit(): source = int(source)

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            await websocket.send_json({"error": f"Cannot open: {source}"}); return

        orig_w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 1280
        orig_h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        disp_w  = min(orig_w, StreamConfig.DISPLAY_WIDTH)
        disp_h  = min(orig_h, StreamConfig.DISPLAY_HEIGHT)
        isx = disp_w / StreamConfig.INFER_WIDTH
        isy = disp_h / StreamConfig.INFER_HEIGHT
        needs_disp = (disp_w != orig_w or disp_h != orig_h)

        print(f"[stream] {orig_w}x{orig_h} → disp {disp_w}x{disp_h}")

        frame_number      = 0
        last_detections   = []
        last_tracks       = []
        last_zone_results = []
        risk_profiles     = {}
        explanations      = {}
        recent_incidents  = []
        cached_zone_layer = None
        last_encoded_bytes= None

        stats_payload   = {}
        last_stats_time = 0.0
        total_incidents = 0
        peak_occupancy  = 0
        stream_start    = time.time()
        loop            = asyncio.get_event_loop()

        while cap.isOpened():
            # ── Capture ───────────────────────────────────────────────────
            profiler.start("cap_read")
            age_tracker.mark_capture()
            ret, frame = cap.read()
            profiler.end("cap_read")
            if not ret: break

            timestamp = frame_number / cap_fps

            # ── Resize ────────────────────────────────────────────────────
            profiler.start("resize")
            frame_disp  = cv2.resize(frame, (disp_w, disp_h),
                                     interpolation=cv2.INTER_LINEAR)                           if needs_disp else frame.copy()
            frame_small = cv2.resize(frame,
                (StreamConfig.INFER_WIDTH, StreamConfig.INFER_HEIGHT),
                interpolation=cv2.INTER_LINEAR)
            profiler.end("resize")

            # ── Async YOLO: collect + submit ──────────────────────────────
            if yolo_future is not None and yolo_future.done():
                profiler.start("yolo_collect")
                try:
                    raw_dets = yolo_future.result()
                    last_detections = _scale_dets(raw_dets, isx, isy)
                except Exception: pass
                yolo_future = None
                profiler.end("yolo_collect")

                profiler.start("intel")
                if last_tracks:
                    last_zone_results  = zi.test(last_tracks)
                    loitering_signals  = loitering_intel.analyze(
                        last_tracks, last_zone_results, frame_number, timestamp)
                    movement_signals   = {
                        t.track_id: movement_intel.analyze(t) for t in last_tracks}
                    risk_profiles, esc = scorer.score(
                        last_tracks, last_zone_results, loitering_signals,
                        frame_number, timestamp, movement_signals=movement_signals)
                    explanations       = explainer.explain(risk_profiles)
                    new_ev, ended_ev   = engine.process(
                        last_tracks, frame_number, timestamp,
                        zone_results=last_zone_results,
                        loitering_signals=loitering_signals)
                    visible = [ev for ev in (new_ev+esc)
                               if ev.get("extra_data",{}).get("visible",True)]
                    recent_incidents = (recent_incidents+visible)[-6:]
                    total_incidents += len(visible)
                    peak_occupancy   = max(peak_occupancy, len(last_tracks))
                profiler.end("intel")

            if yolo_future is None:
                yolo_future = loop.run_in_executor(
                    _executor, _run_yolo, frame_small.copy())

            # ── Tracking ──────────────────────────────────────────────────
            profiler.start("tracker")
            raw_tracks = tracker.update(last_detections, timestamp)
            profiler.end("tracker")

            profiler.start("stabilizer")
            all_t, _ = stabilizer.update(raw_tracks, timestamp, frame_number)
            last_tracks = stabilizer.get_stable_tracks(all_t)
            predictor.update(last_tracks)
            profiler.end("stabilizer")

            # ── Annotate ──────────────────────────────────────────────────
            profiler.start("annotate")
            frame_out = frame_disp.copy()

            if cached_zone_layer is None and zone_dicts:
                blank = np.zeros((disp_h, disp_w, 3), dtype=np.uint8)
                cached_zone_layer = zi.draw_zones(blank)
            if cached_zone_layer is not None:
                cv2.addWeighted(cached_zone_layer, 0.45, frame_out, 0.55, 0, frame_out)

            # Predict bbox positions forward to compensate for detection lag
            frame_age_ms = (time.perf_counter() - age_tracker._capture_ts) * 1000
            track_dets = [{
                "class": t.cls, "confidence": t.confidence, "bbox": t.bbox,
                "track_id": t.track_id, "dwell_seconds": t.dwell_seconds,
                "is_stationary": t.is_stationary,
            } for t in last_tracks]
            track_dets = predictor.predict_dets(track_dets, frame_age_ms)

            frame_out = draw_detections(frame_out, track_dets,
                                        risk_profiles=risk_profiles,
                                        explanations=explanations)
            frame_out = zi.draw_zone_hits(frame_out, last_zone_results)
            frame_out = draw_hud(frame_out, frame_number, cap_fps,
                                 min(1.0, len(last_tracks)*0.12),
                                 "active" if last_tracks else "idle")
            frame_out = draw_event_banners(frame_out, recent_incidents,
                                           frame_out.shape[0])
            profiler.end("annotate")

            # ── Paced push ────────────────────────────────────────────────
            if pacer.ready():
                # Drop policy: if frame is too old, skip sending it
                frame_age_ms = age_tracker.mark_send() if not age_tracker.is_stale else 999
                is_stale = frame_age_ms > StreamConfig.MAX_FRAME_AGE_MS
                drops.frame(dropped=is_stale)

                if not is_stale:
                    # Collect finished encode
                    if encode_future is not None and encode_future.done():
                        try: last_encoded_bytes = encode_future.result()
                        except Exception: pass
                        encode_future = None

                    if encode_future is None:
                        encode_future = loop.run_in_executor(
                            _executor, _encode_jpeg,
                            frame_out.copy(), StreamConfig.JPEG_QUALITY)

                    if last_encoded_bytes is not None:
                        frame_b64 = base64.b64encode(last_encoded_bytes).decode()

                        now = time.time()
                        if now - last_stats_time >= 1.0 / StreamConfig.STATS_REFRESH_HZ:
                            last_stats_time = now
                            risk_summary = [
                                {"track_id": p.track_id, "score": round(p.score,1),
                                 "risk_level": p.risk_level, "trend": p.trend,
                                 "color": p.to_dict()["color"],
                                 "signals": p.dominant_signal_labels(),
                                 "zone": p.current_zone}
                                for p in risk_profiles.values() if p.score >= 25.0
                            ]
                            stats_payload = {
                                "track_count":     len(last_tracks),
                                "peak_occupancy":  peak_occupancy,
                                "total_incidents": total_incidents,
                                "uptime_seconds":  round(now - stream_start, 1),
                                "risk_profiles":   risk_summary,
                                "incidents":       [e.get("extra_data",{})
                                                    for e in recent_incidents[-3:]],
                                "profile_report":  profiler.report(),
                                # ── New latency metrics ───────────────────
                                "latency": {
                                    "avg_frame_age_ms":  age_tracker.avg_age_ms,
                                    "max_frame_age_ms":  age_tracker.max_age_ms,
                                    "drop_rate_pct":     drops.drop_rate_pct,
                                    "total_dropped":     drops.dropped_frames,
                                    "avg_ws_send_ms":    ws_stats.avg_send_ms,
                                    "max_ws_send_ms":    ws_stats.max_send_ms,
                                    "ws_backlog_warns":  ws_stats.backlog_warnings,
                                    "pacer_jitter_ms":   pacer.jitter_ms,
                                    "pacer_max_jitter":  pacer.max_jitter_ms,
                                },
                            }

                        t_send = time.perf_counter()
                        profiler.start("ws_send")
                        await websocket.send_json({
                            "frame":        frame_b64,
                            "frame_number": frame_number,
                            **stats_payload,
                        })
                        profiler.end("ws_send")
                        ws_ms = (time.perf_counter() - t_send) * 1000
                        ws_stats.record_send(ws_ms)

            profiler.frame()
            frame_number += 1
            await asyncio.sleep(0)

    except WebSocketDisconnect:
        print(f"[stream] Disconnected at frame {frame_number} | "
              f"drops={drops.dropped_frames} | avg_age={age_tracker.avg_age_ms}ms")
    except Exception as e:
        print(f"[stream] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if cap: cap.release()
        for f in [yolo_future, encode_future]:
            if f and not f.done():
                try: f.cancel()
                except: pass
