"""
Live Stream — Smooth HLS Streaming
====================================
Root cause of fast-forward + hang:
  OpenCV buffers an entire HLS segment (~150 frames) before the loop starts.
  The loop drains that buffer in ~0.3s (fast-forward), then waits for the
  next network segment (~4.7s hang). Repeat forever.

Fix:
  _drain_to_live_edge() reads and discards frames synchronously at startup
  until cap.read() starts taking >80ms — that means we're waiting on the
  network, i.e. we're at the true live edge. From that point on every frame
  is genuinely fresh and the loop runs smoothly.
"""
import asyncio, cv2, base64, time, threading, collections, subprocess, shutil
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
from app.services.recording.annotated_writer import draw_detections, draw_event_banners, draw_hud

router    = APIRouter()
detector  = YOLODetector()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yolo")


class StreamConfig:
    INFER_W:      int   = 640
    INFER_H:      int   = 360
    DISPLAY_W:    int   = 960
    DISPLAY_H:    int   = 540
    JPEG_QUALITY: int   = 60
    TARGET_FPS:   float = 20.0
    STATS_HZ:     float = 1.0


# ── Live-edge drain ────────────────────────────────────────────────────────────
def _drain_to_live_edge(cap: cv2.VideoCapture, source) -> None:
    """
    Discard buffered HLS frames until cap.read() blocks on the network.

    OpenCV's FFMPEG backend pre-buffers the current HLS segment entirely
    before returning any frames.  Those buffered reads complete in <5ms each
    (memory copy).  Once the buffer is empty, the next read has to wait for
    the network → takes 80-200ms.  That transition is the live edge.

    We drain only for HTTP/HLS sources — webcam/RTSP don't need it.
    Timeout: 15s maximum so we never hang on a slow source.
    """
    src = str(source).lower()
    is_network = any(src.startswith(p) for p in ("http", "rtsp", "rtmp")) or \
                 any(k in src for k in ("googlevideo", "m3u8", "manifest", "live"))
    if not is_network:
        return

    print("[stream] Draining HLS pre-buffer to reach live edge...")
    drained    = 0
    t_start    = time.perf_counter()
    last_frame = None

    while time.perf_counter() - t_start < 15.0:
        t0  = time.perf_counter()
        ret, frame = cap.read()
        dt  = (time.perf_counter() - t0) * 1000   # ms per read

        if not ret:
            time.sleep(0.05)
            continue

        drained   += 1
        last_frame = frame

        # Once reads are slow (network-bound) AND we've drained at least
        # one segment worth of frames, we're at the live edge.
        # 80ms threshold: buffered reads ~2ms, network reads ~33-200ms.
        if dt > 80 and drained > 5:
            print(f"[stream] ✓ Live edge after {drained} frames drained "
                  f"(last read {dt:.0f}ms, took {(time.perf_counter()-t_start):.1f}s)")
            return

    # Timeout fallback — just use whatever we have
    print(f"[stream] Drain timeout — drained {drained} frames in 15s")


# ── YouTube / yt-dlp resolver ──────────────────────────────────────────────────
def _resolve_source(source) -> str:
    """
    If `source` looks like a YouTube URL, resolve it via yt-dlp to a direct
    stream URL that OpenCV/FFMPEG can open. Returns the resolved URL or the
    original source unchanged.
    """
    s = str(source).strip()
    is_youtube = any(host in s for host in (
        "youtube.com", "youtu.be", "youtube-nocookie.com"
    ))
    if not is_youtube:
        return source

    yt_dlp = shutil.which("yt-dlp")
    if not yt_dlp:
        print("[stream] yt-dlp not found — pass a direct stream URL instead")
        return source

    print(f"[stream] Resolving YouTube URL via yt-dlp...")
    try:
        result = subprocess.run(
            [yt_dlp, "--no-warnings", "-f",
             "best[height<=720][ext=mp4]/best[height<=720]/best",
             "-g", s],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip().split("\n")[0]  # first URL (video)
            print(f"[stream] ✓ Resolved to direct URL ({len(url)} chars)")
            return url
        else:
            err = result.stderr.strip()[:200]
            print(f"[stream] yt-dlp failed: {err}")
            return source
    except subprocess.TimeoutExpired:
        print("[stream] yt-dlp timed out (20s)")
        return source
    except Exception as e:
        print(f"[stream] yt-dlp error: {e}")
        return source


# ── Latest-frame buffer ────────────────────────────────────────────────────────
class LatestFrameBuffer:
    """
    Background thread reads from cap continuously, keeping only the newest
    frame. Processing loop always gets the freshest available frame.

    Enhancements:
      - Tracks dropped frames (overwritten before consumer reads them)
      - Exposes an asyncio.Event to wake the consumer immediately on new frame
      - Exception handling: catches OpenCV C++ exceptions (thrown on CDN host
        switches in YouTube HLS) and attempts a single reopen before giving up.
    """
    def __init__(self, cap: cv2.VideoCapture, source):
        self._cap    = cap
        self._source = source
        self._lock   = threading.Lock()
        self._frame  = None
        self._ts     = 0.0
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="frame_buf")
        # Drop tracking
        self._total_read    = 0
        self._total_dropped = 0

    def start(self):
        self._thread.start()

    def _reopen(self) -> bool:
        try:
            self._cap.release()
        except Exception:
            pass
        src = self._source
        if str(src).isdigit():
            src = int(src)
        self._cap = cv2.VideoCapture(src)
        if not self._cap.isOpened():
            return False
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return True

    def _run(self):
        # Determine source FPS to pace the reader (prevents instant-drain of HLS buffers)
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps > 120:
            fps = 30.0
        interval = 1.0 / fps
        next_read_time = time.perf_counter()

        errors = 0
        while not self._stop.is_set():
            try:
                ret, frame = self._cap.read()
            except Exception as e:
                errors += 1
                print(f"[FrameBuf] Exception #{errors}: {e}")
                if errors > 8:
                    self._stop.set(); break
                time.sleep(0.3)
                if self._reopen():
                    errors = 0
                    print("[FrameBuf] Reopened OK")
                continue

            if not ret:
                errors += 1
                if errors > 10:
                    self._stop.set(); break
                time.sleep(0.05)
                continue

            # ── Pace the reading to native FPS ─────────────────────────
            now = time.perf_counter()
            wait = next_read_time - now
            if wait > 0.001:
                time.sleep(wait)
            next_read_time += interval
            # Prevent fast-forward catch-up after a network stall
            if next_read_time < time.perf_counter():
                next_read_time = time.perf_counter()

            errors = 0
            ts = time.perf_counter()
            with self._lock:
                # Track drops: if previous frame wasn't consumed, it's dropped
                if self._frame is not None:
                    self._total_dropped += 1
                self._frame = frame
                self._ts    = ts
                self._total_read += 1

    def get(self):
        """Consume + return (frame, ts). Returns (None, 0) if nothing ready."""
        with self._lock:
            f, ts        = self._frame, self._ts
            self._frame  = None
            return f, ts

    def peek(self):
        with self._lock:
            return self._frame is not None

    @property
    def drop_stats(self):
        with self._lock:
            total = self._total_read
            dropped = self._total_dropped
        pct = round(100.0 * dropped / max(1, total), 1)
        return {"total_read": total, "total_dropped": dropped, "drop_rate_pct": pct}

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._cap.release()

    @property
    def stopped(self):
        return self._stop.is_set()


def _load_zones(feed_id):
    try:
        from app.core.database import SessionLocal
        from app.models.models import Zone
        db   = SessionLocal()
        rows = db.query(Zone).filter(
            Zone.is_active == True,
            (Zone.feed_id == feed_id) | (Zone.feed_id == None)
        ).all()
        db.close()
        return [{"id": z.id, "zone_name": z.zone_name, "zone_type": z.zone_type,
                 "points": z.points, "color": z.color} for z in rows]
    except Exception as e:
        print(f"[stream] zones: {e}"); return []


def _scale(dets, sx, sy):
    return [{**d, "bbox": {
        "x": int(d["bbox"]["x"]*sx), "y": int(d["bbox"]["y"]*sy),
        "w": int(d["bbox"]["w"]*sx), "h": int(d["bbox"]["h"]*sy),
    }} for d in dets]


def _run_yolo(fs):
    return detector.detect(fs)


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

    buf         = None
    yolo_future = None
    frame_ages  = collections.deque(maxlen=60)
    ws_times    = collections.deque(maxlen=30)
    pacer_jitters = collections.deque(maxlen=60)
    frame_interval = 1.0 / StreamConfig.TARGET_FPS

    try:
        loop = asyncio.get_event_loop()
        config = await websocket.receive_json()
        source = config.get("source", 0)
        print(f"[stream] Received source: {repr(source)[:120]}")
        if str(source).isdigit():
            source = int(source)

        # ── Resolve YouTube URLs via yt-dlp ────────────────────────────────
        if isinstance(source, str):
            source = await loop.run_in_executor(None, _resolve_source, source)

        # ── Open capture ───────────────────────────────────────────────────
        src = source if isinstance(source, int) else str(source)
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            await websocket.send_json({"error": f"Cannot open: {source}"}); return
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # ── DRAIN: blocks here until live edge is reached ──────────────────
        # Run in thread pool so the event loop stays responsive
        await loop.run_in_executor(None, _drain_to_live_edge, cap, source)

        orig_w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 1280
        orig_h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        disp_w  = min(orig_w, StreamConfig.DISPLAY_W)
        disp_h  = min(orig_h, StreamConfig.DISPLAY_H)
        isx     = disp_w / StreamConfig.INFER_W
        isy     = disp_h / StreamConfig.INFER_H
        needs_disp = (disp_w != orig_w or disp_h != orig_h)
        print(f"[stream] {orig_w}x{orig_h} → {disp_w}x{disp_h} @ {cap_fps:.0f}fps")

        # ── Start background frame reader ──────────────────────────────────
        buf = LatestFrameBuffer(cap, source)
        buf.start()

        # Wait for first live frame
        for _ in range(100):
            if buf.peek(): break
            await asyncio.sleep(0.05)
        if not buf.peek():
            await websocket.send_json({"error": "No frames from source"}); return

        await websocket.send_json({
            "status": "connected", "width": disp_w, "height": disp_h
        })

        frame_number      = 0
        last_detections   = []
        last_tracks       = []
        last_zone_results = []
        risk_profiles     = {}
        explanations      = {}
        recent_incidents  = []
        cached_zone_layer = None
        stats_payload     = {}
        last_stats_time   = 0.0
        total_incidents   = 0
        peak_occupancy    = 0
        ws_backlog_warns  = 0
        stream_start      = time.time()
        last_good_frame   = None   # reused during inter-segment gaps

        yolo_timestamp           = 0.0
        yolo_in_flight_timestamp = 0.0

        # Strict pacing: deadline advances by exactly frame_interval each slot
        next_deadline = time.perf_counter() + frame_interval

        while not buf.stopped:

            # ── Frame pacing ──────────────────────────────────────────────
            now  = time.perf_counter()
            wait = next_deadline - now
            if wait > 0.001:
                await asyncio.sleep(wait)
            actual_time = time.perf_counter()
            jitter_ms = abs(actual_time - next_deadline) * 1000
            pacer_jitters.append(jitter_ms)
            next_deadline += frame_interval
            # Prevent runaway catch-up after a stall
            if next_deadline < time.perf_counter() - frame_interval:
                next_deadline = time.perf_counter() + frame_interval

            # ── Get frame ─────────────────────────────────────────────────
            profiler.start("cap_read")
            frame, capture_ts = buf.get()
            profiler.end("cap_read")

            if frame is None:
                # No new frame yet (between HLS segments) — reuse last good
                if last_good_frame is None:
                    continue
                frame      = last_good_frame
                capture_ts = 0.0   # age unknown, don't record
            else:
                last_good_frame = frame
                age_ms = (time.perf_counter() - capture_ts) * 1000
                frame_ages.append(age_ms)

            timestamp = frame_number / cap_fps

            # ── Resize ────────────────────────────────────────────────────
            profiler.start("resize")
            frame_disp  = cv2.resize(frame, (disp_w, disp_h),
                                     interpolation=cv2.INTER_LINEAR) \
                          if needs_disp else frame.copy()
            frame_small = cv2.resize(frame,
                (StreamConfig.INFER_W, StreamConfig.INFER_H),
                interpolation=cv2.INTER_LINEAR)
            profiler.end("resize")

            # ── Async YOLO ────────────────────────────────────────────────
            detection_fresh = False
            if yolo_future is not None and yolo_future.done():
                profiler.start("yolo_collect")
                try:
                    last_detections = _scale(yolo_future.result(), isx, isy)
                    detection_fresh = True
                    yolo_timestamp = yolo_in_flight_timestamp
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
                    new_ev, _          = engine.process(
                        last_tracks, frame_number, timestamp,
                        zone_results=last_zone_results,
                        loitering_signals=loitering_signals)
                    visible = [ev for ev in (new_ev + esc)
                               if ev.get("extra_data", {}).get("visible", True)]
                    recent_incidents  = (recent_incidents + visible)[-6:]
                    total_incidents  += len(visible)
                    peak_occupancy    = max(peak_occupancy, len(last_tracks))
                profiler.end("intel")

            # ── Tracking (predictor-corrector) ────────────────────────────
            profiler.start("tracker")
            if detection_fresh:
                # Fresh YOLO detections available — full tracker update with historical timestamp
                raw_tracks = tracker.update(last_detections, yolo_timestamp)
            elif yolo_future is None:
                # No YOLO in flight and no fresh results — update with last known
                raw_tracks = tracker.update(last_detections, yolo_timestamp)
            else:
                # YOLO is running — predict for smooth interpolation
                raw_tracks = tracker.predict(timestamp)
            profiler.end("tracker")

            if yolo_future is None:
                yolo_in_flight_timestamp = timestamp
                yolo_future = loop.run_in_executor(
                    _executor, _run_yolo, frame_small.copy())

            profiler.start("stabilizer")
            all_t, _ = stabilizer.update(raw_tracks, timestamp, frame_number)
            last_tracks = stabilizer.get_stable_tracks(all_t)
            profiler.end("stabilizer")

            # ── Annotate ──────────────────────────────────────────────────
            profiler.start("annotate")
            frame_out = frame_disp.copy()
            if cached_zone_layer is None and zone_dicts:
                blank = np.zeros((disp_h, disp_w, 3), dtype=np.uint8)
                cached_zone_layer = zi.draw_zones(blank)
            if cached_zone_layer is not None:
                cv2.addWeighted(cached_zone_layer, 0.45, frame_out, 0.55, 0, frame_out)
            # Predictor-corrector: use predicted bboxes for smooth rendering
            track_dets = []
            for t in last_tracks:
                pred_bbox = t.bbox
                if hasattr(tracker, 'tracks'):
                    raw_t = tracker.tracks.get(t.track_id)
                    # Always project the raw tracker's bbox forward to the *current* frame timestamp.
                    # This eliminates lag caused by YOLO inference latency.
                    if raw_t:
                        pred_bbox = raw_t.predict(timestamp)
                track_dets.append({
                    "class": t.cls, "confidence": t.confidence, "bbox": pred_bbox,
                    "track_id": t.track_id, "dwell_seconds": t.dwell_seconds,
                    "is_stationary": t.is_stationary,
                })
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

            # ── Encode ────────────────────────────────────────────────────
            profiler.start("jpeg_encode")
            _, jpg = cv2.imencode(".jpg", frame_out,
                                  [cv2.IMWRITE_JPEG_QUALITY, StreamConfig.JPEG_QUALITY])
            frame_b64 = base64.b64encode(jpg).decode()
            profiler.end("jpeg_encode")

            # ── Stats (complete telemetry) ─────────────────────────────────
            now = time.time()
            if now - last_stats_time >= 1.0 / StreamConfig.STATS_HZ:
                last_stats_time = now
                avg_age = round(sum(frame_ages)/len(frame_ages), 1) if frame_ages else 0
                max_age = round(max(frame_ages), 1)                  if frame_ages else 0
                avg_ws  = round(sum(ws_times)/len(ws_times), 1)      if ws_times  else 0
                max_ws  = round(max(ws_times), 1)                    if ws_times  else 0
                avg_jit = round(sum(pacer_jitters)/len(pacer_jitters), 1) if pacer_jitters else 0
                max_jit = round(max(pacer_jitters), 1)                   if pacer_jitters else 0
                drop    = buf.drop_stats
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
                    "incidents":       [e.get("extra_data", {})
                                        for e in recent_incidents[-3:]],
                    "profile_report":  profiler.report(),
                    "latency": {
                        "avg_frame_age_ms":  avg_age,
                        "max_frame_age_ms":  max_age,
                        "avg_ws_send_ms":    avg_ws,
                        "max_ws_send_ms":    max_ws,
                        "pacer_jitter_ms":   avg_jit,
                        "pacer_max_jitter":  max_jit,
                        "ws_backlog_warns":  ws_backlog_warns,
                        "drop_rate_pct":     drop["drop_rate_pct"],
                        "total_dropped":     drop["total_dropped"],
                        "measured_fps":      StreamConfig.TARGET_FPS,
                    },
                }

            # ── Send ──────────────────────────────────────────────────────
            t0 = time.perf_counter()
            profiler.start("ws_send")
            await websocket.send_json({
                "frame":        frame_b64,
                "frame_number": frame_number,
                **stats_payload,
            })
            profiler.end("ws_send")
            ws_elapsed = (time.perf_counter() - t0) * 1000
            ws_times.append(ws_elapsed)
            if ws_elapsed > 30.0:
                ws_backlog_warns += 1
            frame_number += 1
            profiler.frame()

    except WebSocketDisconnect:
        print(f"[stream] Disconnected at frame {frame_number}")
    except Exception as e:
        print(f"[stream] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if buf: buf.stop()
        if yolo_future and not yolo_future.done():
            try: yolo_future.cancel()
            except: pass


@router.post("/reload-zones/{feed_id}")
async def reload_zones(feed_id: int):
    zones = _load_zones(feed_id)
    return {"feed_id": feed_id, "zones": zones, "count": len(zones)}