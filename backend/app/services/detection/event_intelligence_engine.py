"""
Event Intelligence Engine
=========================
Sits between the tracking layer and the persistence/alert layer.

Responsibilities:
  - Persistence validation  : detection must be stable for MIN_PERSIST_SECONDS before firing
  - Lifecycle management    : every event has STARTED → ACTIVE → ENDED states
  - Cooldown registry       : same event type cannot fire again within COOLDOWN_SECONDS
  - Event aggregation       : repeated detections merged into one structured EventRecord
  - Severity classification : LOW / MEDIUM / HIGH / CRITICAL

The YOLO + Tracker layers only provide:
  track_id, class, bbox, confidence, dwell_seconds, is_stationary, centroid

All decision-making lives here.
"""

from __future__ import annotations
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any
from collections import defaultdict


# ── enums ────────────────────────────────────────────────────────────────────

class EventState(str, Enum):
    STARTED = "STARTED"
    ACTIVE  = "ACTIVE"
    ENDED   = "ENDED"


class Severity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ── config ───────────────────────────────────────────────────────────────────

class EIEConfig:
    # Persistence: how long a condition must be true before an event fires
    PERSIST_SECONDS: Dict[str, float] = {
        "person_appeared":    0.5,
        "person_left":        1.0,
        "vehicle_entered":    0.5,
        "vehicle_left":       1.0,
        "crowd_detected":     2.0,
        "loitering_detected": 15.0,
        "object_left_behind": 25.0,
        "zone_breach":        0.2,   # low — fire quickly on zone entry
        "re_entry":           0.5,
    }

    # Cooldown: minimum seconds before the same event type fires again
    COOLDOWN_SECONDS: Dict[str, float] = {
        "person_appeared":    3.0,
        "person_left":        3.0,
        "vehicle_entered":    3.0,
        "vehicle_left":       3.0,
        "crowd_detected":     10.0,
        "loitering_detected": 30.0,
        "object_left_behind": 60.0,
        "zone_breach":        10.0,
        "re_entry":           5.0,
    }

    # How long after condition disappears before event is ENDED
    END_GRACE_SECONDS: Dict[str, float] = {
        "crowd_detected":     3.0,
        "loitering_detected": 2.0,
        "object_left_behind": 5.0,
        "zone_breach":        2.0,
    }

    # Severity rules
    SEVERITY_MAP: Dict[str, Severity] = {
        "person_appeared":    Severity.LOW,
        "person_left":        Severity.LOW,
        "vehicle_entered":    Severity.LOW,
        "vehicle_left":       Severity.LOW,
        "crowd_detected":     Severity.HIGH,
        "loitering_detected": Severity.HIGH,
        "object_left_behind": Severity.CRITICAL,
        "zone_breach":        Severity.CRITICAL,
        "re_entry":           Severity.MEDIUM,
    }

    # Crowd threshold
    CROWD_MIN_PEOPLE: int = 3

    # Loitering
    LOITERING_SECONDS: float = 20.0

    # Object left behind
    OBJECT_LEFT_SECONDS: float = 30.0


# ── EventRecord ───────────────────────────────────────────────────────────────

@dataclass
class EventRecord:
    event_id:       str                    # unique key
    event_type:     str
    state:          EventState = EventState.STARTED
    severity:       Severity   = Severity.LOW

    started_at:     float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    ended_at:       Optional[float] = None

    # Frame / video positions
    start_frame:    int = 0
    start_ts:       float = 0.0
    last_frame:     int = 0
    last_ts:        float = 0.0

    # Aggregated data
    track_ids:      Set[int]   = field(default_factory=set)
    peak_count:     int        = 0
    bbox:           Dict       = field(default_factory=dict)
    zone:           Optional[str] = None
    extra:          Dict       = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or time.time()
        return round(end - self.started_at, 2)

    def to_dict(self) -> Dict:
        return {
            "event_id":         self.event_id,
            "event_type":       self.event_type,
            "state":            self.state.value,
            "severity":         self.severity.value,
            "started_at":       self.started_at,
            "ended_at":         self.ended_at,
            "duration_seconds": self.duration_seconds,
            "start_frame":      self.start_frame,
            "start_ts":         self.start_ts,
            "last_frame":       self.last_frame,
            "last_ts":          self.last_ts,
            "track_ids":        list(self.track_ids),
            "peak_count":       self.peak_count,
            "bbox":             self.bbox,
            "zone":             self.zone,
            **self.extra,
        }

    def to_db_dict(self) -> Dict:
        """Shape expected by DetectionEvent model."""
        return {
            "event_type":              self.event_type,
            "frame_number":            self.start_frame,
            "video_timestamp_seconds": self.start_ts,
            "confidence":              self.extra.get("confidence", 1.0),
            "bounding_box":            self.bbox,
            "extra_data": {
                "event_id":         self.event_id,
                "state":            self.state.value,
                "severity":         self.severity.value,
                "duration_seconds": self.duration_seconds,
                "track_ids":        list(self.track_ids),
                "peak_count":       self.peak_count,
                "zone":             self.zone,
                **self.extra,
            },
        }


# ── sub-systems ───────────────────────────────────────────────────────────────

class CooldownRegistry:
    """Prevents the same event_type (+ optional zone) from firing too soon."""
    def __init__(self):
        self._last_fired: Dict[str, float] = {}

    def can_fire(self, event_type: str, key: str = "") -> bool:
        cooldown = EIEConfig.COOLDOWN_SECONDS.get(event_type, 5.0)
        full_key = f"{event_type}:{key}"
        return time.time() - self._last_fired.get(full_key, 0) >= cooldown

    def mark_fired(self, event_type: str, key: str = ""):
        self._last_fired[f"{event_type}:{key}"] = time.time()

    def reset(self):
        self._last_fired.clear()


class PersistenceValidator:
    """
    A condition must be continuously true for PERSIST_SECONDS before it fires.
    Call observe(key, True/False) each frame; returns True when threshold met.
    """
    def __init__(self):
        self._first_seen: Dict[str, float] = {}
        self._fired:      Set[str]         = set()

    def observe(self, key: str, condition: bool, event_type: str) -> bool:
        if not condition:
            self._first_seen.pop(key, None)
            self._fired.discard(key)
            return False
        threshold = EIEConfig.PERSIST_SECONDS.get(event_type, 1.0)
        now = time.time()
        self._first_seen.setdefault(key, now)
        elapsed = now - self._first_seen[key]
        if elapsed >= threshold and key not in self._fired:
            self._fired.add(key)
            return True
        return False

    def reset(self, key: str):
        self._first_seen.pop(key, None)
        self._fired.discard(key)

    def reset_all(self):
        self._first_seen.clear()
        self._fired.clear()


# ── main engine ───────────────────────────────────────────────────────────────

class EventIntelligenceEngine:
    """
    Transform raw Track objects into stable, lifecycle-managed EventRecords.

    Usage (per frame):
        new_events, ended_events = engine.process(tracks, frame_number, timestamp)

    `new_events`   — EventRecords that just transitioned to STARTED or need DB insert
    `ended_events` — EventRecords that just transitioned to ENDED
    Both are plain dicts via .to_db_dict() for easy DB persistence.
    """

    def __init__(self, zones: Optional[List[Dict]] = None):
        self.zones  = zones or []          # [{"name": str, "polygon": [(x,y),...]}]
        self.config = EIEConfig()

        self._cooldown   = CooldownRegistry()
        self._persist    = PersistenceValidator()
        self._active: Dict[str, EventRecord] = {}   # event_id → EventRecord
        self._counter    = 0

    # ── public API ────────────────────────────────────────────────────────────

    def process(
        self,
        tracks: List[Any],           # Track objects from CentroidTracker
        frame_number: int,
        timestamp: float,
        zone_results: Optional[List[Any]] = None,   # ZoneTestResult list from ZoneIntelligence
        loitering_signals: Optional[List[Any]] = None,  # LoiteringSignal list from LoiteringIntelligence
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Returns (new_or_updated_events, ended_events) as lists of db dicts.
        Only STARTED events and ENDED events are returned for DB write.
        ACTIVE updates are silent (avoid DB spam).
        """
        now          = time.time()
        new_events:  List[Dict] = []
        ended_events: List[Dict] = []

        people   = [t for t in tracks if t.cls == "person"]
        vehicles = [t for t in tracks if t.cls in {"car","truck","bus","motorcycle","bicycle"}]
        bags     = [t for t in tracks if t.cls in {"backpack","handbag","suitcase"}]
        all_ids  = {t.track_id for t in tracks}

        # ── 1. appeared / left ───────────────────────────────────────────────
        for t in tracks:
            etype = ("person_appeared" if t.cls == "person"
                     else "vehicle_entered" if t.cls in {"car","truck","bus","motorcycle","bicycle"}
                     else None)
            if not etype:
                continue
            key = f"{etype}:{t.track_id}"
            if self._persist.observe(key, True, etype) and self._cooldown.can_fire(etype, str(t.track_id)):
                rec = self._start_event(etype, t, frame_number, timestamp)
                self._cooldown.mark_fired(etype, str(t.track_id))
                new_events.append(rec.to_db_dict())

        # Track IDs that disappeared → fire left events
        gone_ids = set(self._track_last_seen.keys()) - all_ids if hasattr(self, "_track_last_seen") else set()
        for tid in gone_ids:
            info = self._track_last_seen.pop(tid, {})
            cls  = info.get("cls", "person")
            etype = "person_left" if cls == "person" else "vehicle_left" if cls in {"car","truck","bus","motorcycle","bicycle"} else None
            if etype and self._cooldown.can_fire(etype, str(tid)):
                fake_bbox = info.get("bbox", {})
                ev_id = self._make_id(etype)
                rec = EventRecord(
                    event_id=ev_id, event_type=etype,
                    state=EventState.ENDED,
                    severity=EIEConfig.SEVERITY_MAP.get(etype, Severity.LOW),
                    start_frame=frame_number, start_ts=timestamp,
                    last_frame=frame_number, last_ts=timestamp,
                    bbox=fake_bbox,
                )
                rec.track_ids.add(tid)
                rec.ended_at = now
                self._cooldown.mark_fired(etype, str(tid))
                new_events.append(rec.to_db_dict())

        # Update last-seen registry
        if not hasattr(self, "_track_last_seen"):
            self._track_last_seen: Dict[int, Dict] = {}
        for t in tracks:
            self._track_last_seen[t.track_id] = {"cls": t.cls, "bbox": t.bbox}

        # ── 2. crowd ─────────────────────────────────────────────────────────
        crowd_key  = "crowd_detected:scene"
        is_crowd   = len(people) >= self.config.CROWD_MIN_PEOPLE
        if self._persist.observe(crowd_key, is_crowd, "crowd_detected"):
            if self._cooldown.can_fire("crowd_detected") and crowd_key not in self._active:
                rec = self._make_record("crowd_detected", frame_number, timestamp,
                    bbox={}, track_ids={t.track_id for t in people},
                    extra={"count": len(people), "message": f"{len(people)} people detected"})
                self._active[crowd_key] = rec
                self._cooldown.mark_fired("crowd_detected")
                new_events.append(rec.to_db_dict())

        if crowd_key in self._active:
            rec = self._active[crowd_key]
            if is_crowd:
                rec.state          = EventState.ACTIVE
                rec.last_frame     = frame_number
                rec.last_ts        = timestamp
                rec.last_active_at = now
                rec.peak_count     = max(rec.peak_count, len(people))
                rec.track_ids.update(t.track_id for t in people)
            else:
                grace = EIEConfig.END_GRACE_SECONDS.get("crowd_detected", 3.0)
                if now - rec.last_active_at >= grace:
                    rec.state    = EventState.ENDED
                    rec.ended_at = now
                    self._persist.reset(crowd_key)
                    ended_events.append(rec.to_db_dict())
                    del self._active[crowd_key]

        # loitering handled by LoiteringIntelligence layer (see 5a above)

        # ── 4. object left behind ─────────────────────────────────────────────
        person_centroids = [t.centroid for t in people]
        for t in bags:
            okey = f"object_left_behind:{t.track_id}"
            no_owner = not any(
                abs(px - t.centroid[0]) < 80 and abs(py - t.centroid[1]) < 80
                for px, py in person_centroids
            )
            is_abandoned = t.dwell_seconds >= self.config.OBJECT_LEFT_SECONDS and t.is_stationary and no_owner
            if self._persist.observe(okey, is_abandoned, "object_left_behind"):
                if self._cooldown.can_fire("object_left_behind", str(t.track_id)) and okey not in self._active:
                    rec = self._make_record("object_left_behind", frame_number, timestamp,
                        bbox=t.bbox, track_ids={t.track_id},
                        extra={"object_class": t.cls, "dwell_seconds": round(t.dwell_seconds, 1),
                               "confidence": t.confidence,
                               "message": f"Unattended {t.cls} for {t.dwell_seconds:.0f}s"})
                    rec.severity = Severity.CRITICAL
                    self._active[okey] = rec
                    self._cooldown.mark_fired("object_left_behind", str(t.track_id))
                    new_events.append(rec.to_db_dict())

            if okey in self._active:
                rec = self._active[okey]
                if is_abandoned:
                    rec.state          = EventState.ACTIVE
                    rec.last_active_at = now
                    rec.last_frame     = frame_number
                    rec.last_ts        = timestamp
                else:
                    grace = EIEConfig.END_GRACE_SECONDS.get("object_left_behind", 5.0)
                    if now - rec.last_active_at >= grace:
                        rec.state = EventState.ENDED; rec.ended_at = now
                        ended_events.append(rec.to_db_dict())
                        del self._active[okey]

        # ── 5a. loitering (from LoiteringIntelligence signals) ──────────────
        for sig in (loitering_signals or []):
            lkey = f"loitering_detected:{sig.zone_name}:{sig.track_id}"

            if sig.state == "STARTED":
                if self._cooldown.can_fire("loitering_detected", f"{sig.zone_name}:{sig.track_id}") and lkey not in self._active:
                    rec = self._make_record(
                        "loitering_detected", sig.frame_number, sig.timestamp,
                        bbox=sig.bbox, track_ids={sig.track_id}, zone=sig.zone_name,
                        extra=sig.to_eie_event()["extra_data"],
                    )
                    rec.severity = Severity.CRITICAL if sig.zone_type == "restricted" else Severity.HIGH
                    rec.extra["visible"] = True
                    self._active[lkey] = rec
                    self._cooldown.mark_fired("loitering_detected", f"{sig.zone_name}:{sig.track_id}")
                    new_events.append(rec.to_db_dict())

            elif sig.state == "ACTIVE" and lkey in self._active:
                rec = self._active[lkey]
                rec.state          = EventState.ACTIVE
                rec.last_active_at = now
                rec.last_frame     = sig.frame_number
                rec.last_ts        = sig.timestamp
                rec.extra["dwell_seconds"]  = sig.dwell_seconds
                rec.extra["movement_score"] = sig.movement_score

            elif sig.state == "ENDED" and lkey in self._active:
                rec = self._active.pop(lkey)
                rec.state    = EventState.ENDED
                rec.ended_at = now
                rec.extra["dwell_seconds"]  = sig.dwell_seconds
                rec.extra["movement_score"] = sig.movement_score
                ended_events.append(rec.to_db_dict())

        # ── 5. zone breach (driven by ZoneIntelligence results) ─────────────
        # zone_results is a List[ZoneTestResult] — one per track, pre-computed by ZoneIntelligence
        active_zone_keys: set = set()
        for zr in (zone_results or []):
            for z in zr.inside_zones:
                zname = z["zone_name"]
                ztype = z["zone_type"]
                zkey  = f"zone_breach:{zname}:{zr.track_id}"
                active_zone_keys.add(zkey)

                # Persistence: must be inside zone for PERSIST_SECONDS before firing
                if self._persist.observe(zkey, True, "zone_breach"):
                    if self._cooldown.can_fire("zone_breach", f"{zname}:{zr.track_id}") and zkey not in self._active:
                        severity = Severity.CRITICAL if ztype == "restricted" else Severity.MEDIUM
                        rec = self._make_record(
                            "zone_breach", frame_number, timestamp,
                            bbox=zr.bbox, track_ids={zr.track_id}, zone=zname,
                            extra={
                                "zone":      zname,
                                "zone_type": ztype,
                                "track_id":  zr.track_id,
                                "confidence": 1.0,
                                "message":   f"{zr.cls.title()} #{zr.track_id} entered {ztype} zone '{zname}'",
                            }
                        )
                        rec.severity = severity
                        rec.extra["visible"] = True
                        self._active[zkey] = rec
                        self._cooldown.mark_fired("zone_breach", f"{zname}:{zr.track_id}")
                        new_events.append(rec.to_db_dict())

                if zkey in self._active:
                    rec = self._active[zkey]
                    rec.state = EventState.ACTIVE
                    rec.last_active_at = now
                    rec.last_frame = frame_number
                    rec.last_ts = timestamp

        # End zone events for tracks that left the zone
        for zkey in list(self._active.keys()):
            if not zkey.startswith("zone_breach:"):
                continue
            if zkey not in active_zone_keys:
                rec = self._active[zkey]
                grace = EIEConfig.END_GRACE_SECONDS.get("zone_breach", 2.0)
                if now - rec.last_active_at >= grace:
                    rec.state = EventState.ENDED
                    rec.ended_at = now
                    ended_events.append(rec.to_db_dict())
                    del self._active[zkey]

        # ── 6. re-entry ──────────────────────────────────────────────────────
        if not hasattr(self, "_seen_ids"):
            self._seen_ids:  Set[int] = set()
            self._left_ids:  Set[int] = set()
        for t in tracks:
            if t.track_id not in self._seen_ids:
                self._seen_ids.add(t.track_id)
            elif t.track_id in self._left_ids:
                rekey = f"re_entry:{t.track_id}"
                if self._cooldown.can_fire("re_entry", str(t.track_id)):
                    rec = self._make_record("re_entry", frame_number, timestamp,
                        bbox=t.bbox, track_ids={t.track_id},
                        extra={"confidence": t.confidence,
                               "message": f"Track #{t.track_id} re-entered the scene"})
                    self._left_ids.discard(t.track_id)
                    self._cooldown.mark_fired("re_entry", str(t.track_id))
                    new_events.append(rec.to_db_dict())
        for tid in gone_ids:
            self._left_ids.add(tid)

        return new_events, ended_events

    def compute_activity_score(self, tracks: List[Any]) -> float:
        people   = sum(1 for t in tracks if t.cls == "person")
        vehicles = sum(1 for t in tracks if t.cls in {"car","truck","bus"})
        return min(1.0, people * 0.25 + vehicles * 0.2 + len(tracks) * 0.05)

    def reset(self):
        self._cooldown.reset()
        self._persist.reset_all()
        self._active.clear()
        if hasattr(self, "_track_last_seen"): self._track_last_seen.clear()
        if hasattr(self, "_seen_ids"):        self._seen_ids.clear()
        if hasattr(self, "_left_ids"):        self._left_ids.clear()

    # ── private ───────────────────────────────────────────────────────────────

    def _make_id(self, event_type: str) -> str:
        self._counter += 1
        return f"{event_type}_{self._counter}"

    def _start_event(self, event_type: str, track: Any,
                     frame_number: int, timestamp: float) -> EventRecord:
        rec = EventRecord(
            event_id=self._make_id(event_type),
            event_type=event_type,
            state=EventState.STARTED,
            severity=EIEConfig.SEVERITY_MAP.get(event_type, Severity.LOW),
            start_frame=frame_number, start_ts=timestamp,
            last_frame=frame_number, last_ts=timestamp,
            bbox=track.bbox,
            extra={"confidence": track.confidence,
                   "track_id":   track.track_id,
                   "message":    f"{track.cls.title()} #{track.track_id} detected"},
        )
        rec.track_ids.add(track.track_id)
        rec.peak_count = 1
        return rec

    def _make_record(self, event_type: str, frame_number: int, timestamp: float,
                     bbox: Dict, track_ids: Set[int], zone: str = None,
                     extra: Dict = None) -> EventRecord:
        rec = EventRecord(
            event_id=self._make_id(event_type),
            event_type=event_type,
            state=EventState.STARTED,
            severity=EIEConfig.SEVERITY_MAP.get(event_type, Severity.LOW),
            start_frame=frame_number, start_ts=timestamp,
            last_frame=frame_number, last_ts=timestamp,
            bbox=bbox, zone=zone, extra=extra or {},
        )
        rec.track_ids = track_ids
        rec.peak_count = len(track_ids)
        return rec


# ── geometry ──────────────────────────────────────────────────────────────────

def _point_in_polygon(px: float, py: float, polygon: List[Tuple]) -> bool:
    n = len(polygon); inside = False; j = n - 1
    for i in range(n):
        xi, yi = polygon[i]; xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside
