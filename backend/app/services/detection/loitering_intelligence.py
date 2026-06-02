"""
Loitering Intelligence Layer
=============================
Sits between ZoneIntelligence and the Event Intelligence Engine.

Single responsibility: temporal-behavioral analysis.
  - Tracks per-track zone entry time and movement history
  - Computes movement score (average centroid displacement per frame)
  - Decides when a person qualifies as "loitering"
  - Emits structured LoiteringSignal objects to the EIE

YOLO provides detections.
Tracker provides stable IDs + centroids.
ZoneIntelligence provides which tracks are in which zones.
THIS layer decides if the behavior is suspicious.
EIE decides whether to fire/suppress/end the event.
"""

from __future__ import annotations
import time
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# ── Config ────────────────────────────────────────────────────────────────────

class LoiteringConfig:
    # Seconds a person must be inside a zone before loitering fires
    LOITER_THRESHOLD_SECONDS: float = 15.0

    # Max average pixels/frame movement to be considered "stationary"
    MOVEMENT_THRESHOLD_PX: float = 12.0

    # Minimum frames of zone presence before movement score is trusted
    MIN_FRAMES_FOR_SCORE: int = 8

    # Zone types that trigger loitering (others are ignored)
    SENSITIVE_ZONE_TYPES: set = frozenset({"restricted", "monitoring"})

    # How often (seconds) to re-emit ACTIVE signal while loitering continues
    ACTIVE_SIGNAL_INTERVAL: float = 10.0


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ZonePresence:
    """State for a single (track_id, zone_name) pair."""
    track_id:     int
    zone_name:    str
    zone_type:    str
    entered_at:   float                            # wall-clock time
    centroids:    List[Tuple[float, float]] = field(default_factory=list)
    last_signal_at: float = 0.0                   # last ACTIVE signal sent
    loitering_started: bool = False

    @property
    def dwell_seconds(self) -> float:
        return round(time.time() - self.entered_at, 2)

    @property
    def movement_score(self) -> float:
        """Average pixel displacement per frame. Low = stationary."""
        if len(self.centroids) < 2:
            return 0.0
        total = sum(
            math.dist(self.centroids[i], self.centroids[i - 1])
            for i in range(1, len(self.centroids))
        )
        return round(total / (len(self.centroids) - 1), 2)

    @property
    def is_stationary(self) -> bool:
        if len(self.centroids) < LoiteringConfig.MIN_FRAMES_FOR_SCORE:
            return False
        return self.movement_score < LoiteringConfig.MOVEMENT_THRESHOLD_PX

    def update_centroid(self, cx: float, cy: float):
        self.centroids.append((cx, cy))
        if len(self.centroids) > 120:        # keep last 120 positions (~5s at 25fps adaptive)
            self.centroids = self.centroids[-120:]


@dataclass
class LoiteringSignal:
    """Emitted by LoiteringIntelligence → consumed by EIE."""
    track_id:       int
    cls:            str
    zone_name:      str
    zone_type:      str
    dwell_seconds:  float
    movement_score: float
    bbox:           Dict
    centroid:       Tuple[float, float]
    state:          str    # "STARTED" | "ACTIVE" | "ENDED"
    frame_number:   int
    timestamp:      float  # video timestamp in seconds

    def to_eie_event(self) -> Dict:
        severity = "critical" if self.zone_type == "restricted" else "high"
        return {
            "event_type":              "loitering_detected",
            "frame_number":            self.frame_number,
            "video_timestamp_seconds": self.timestamp,
            "confidence":              1.0,
            "bounding_box":            self.bbox,
            "extra_data": {
                "track_id":       self.track_id,
                "zone":           self.zone_name,
                "zone_type":      self.zone_type,
                "dwell_seconds":  self.dwell_seconds,
                "movement_score": self.movement_score,
                "state":          self.state,
                "severity":       severity,
                "message":        (
                    f"Person #{self.track_id} loitering in '{self.zone_name}' "
                    f"for {self.dwell_seconds:.0f}s "
                    f"(movement: {self.movement_score:.1f}px/frame)"
                ),
            },
        }


# ── Main class ────────────────────────────────────────────────────────────────

class LoiteringIntelligence:
    """
    Analyzes temporal behavior of tracked objects inside zones.

    Usage (once per processed frame):
        signals = loitering_intel.analyze(tracks, zone_results, frame_number, timestamp)
        # signals is List[LoiteringSignal] — pass to EIE

    The EIE remains responsible for cooldown, persistence, and DB writes.
    This class only produces behavioral signals.
    """

    def __init__(self, policy_registry=None):
        # Key: (track_id, zone_name)
        self._presences: Dict[Tuple[int, str], ZonePresence] = {}
        self._policy = policy_registry

    def analyze(
        self,
        tracks: List[Any],           # Track objects from CentroidTracker
        zone_results: List[Any],     # ZoneTestResult list from ZoneIntelligence
        frame_number: int,
        timestamp: float,
    ) -> List[LoiteringSignal]:

        signals: List[LoiteringSignal] = []
        now = time.time()

        # Build lookup: track_id → (ZoneTestResult, Track)
        track_map = {t.track_id: t for t in tracks}
        zone_map: Dict[int, List[Dict]] = {}
        for zr in zone_results:
            zone_map[zr.track_id] = [
                z for z in zr.inside_zones
                if z["zone_type"] in LoiteringConfig.SENSITIVE_ZONE_TYPES
            ]

        active_keys: set = set()

        # ── Update presences for tracks currently in sensitive zones ──────────
        for track_id, sensitive_zones in zone_map.items():
            if not sensitive_zones:
                continue
            track = track_map.get(track_id)
            if not track or track.cls != "person":
                continue   # loitering only applies to people

            for z in sensitive_zones:
                key = (track_id, z["zone_name"])
                active_keys.add(key)

                if key not in self._presences:
                    # New presence — person just entered this zone
                    self._presences[key] = ZonePresence(
                        track_id=track_id,
                        zone_name=z["zone_name"],
                        zone_type=z["zone_type"],
                        entered_at=now,
                    )

                presence = self._presences[key]
                cx, cy = track.centroid
                presence.update_centroid(cx, cy)

                # ── Check loitering conditions ────────────────────────────────
                # Zone-policy aware threshold (Phase 1)
                threshold = LoiteringConfig.LOITER_THRESHOLD_SECONDS
                if self._policy:
                    policy = self._policy.get(z["zone_name"])
                    if policy:
                        if not policy.loitering_enabled:
                            continue   # loitering disabled for this zone
                        threshold = policy.loiter_threshold_seconds
                threshold_exceeded = presence.dwell_seconds >= threshold
                stationary         = presence.is_stationary

                if threshold_exceeded and stationary:
                    if not presence.loitering_started:
                        # First time threshold crossed → STARTED
                        presence.loitering_started = True
                        presence.last_signal_at    = now
                        signals.append(LoiteringSignal(
                            track_id=track_id, cls=track.cls,
                            zone_name=z["zone_name"], zone_type=z["zone_type"],
                            dwell_seconds=presence.dwell_seconds,
                            movement_score=presence.movement_score,
                            bbox=track.bbox, centroid=(cx, cy),
                            state="STARTED",
                            frame_number=frame_number, timestamp=timestamp,
                        ))
                    elif now - presence.last_signal_at >= LoiteringConfig.ACTIVE_SIGNAL_INTERVAL:
                        # Periodic ACTIVE heartbeat
                        presence.last_signal_at = now
                        signals.append(LoiteringSignal(
                            track_id=track_id, cls=track.cls,
                            zone_name=z["zone_name"], zone_type=z["zone_type"],
                            dwell_seconds=presence.dwell_seconds,
                            movement_score=presence.movement_score,
                            bbox=track.bbox, centroid=(cx, cy),
                            state="ACTIVE",
                            frame_number=frame_number, timestamp=timestamp,
                        ))

        # ── Fire ENDED for presences no longer active ─────────────────────────
        for key in list(self._presences.keys()):
            if key not in active_keys:
                presence = self._presences.pop(key)
                if presence.loitering_started:
                    track = track_map.get(presence.track_id)
                    signals.append(LoiteringSignal(
                        track_id=presence.track_id,
                        cls="person",
                        zone_name=presence.zone_name,
                        zone_type=presence.zone_type,
                        dwell_seconds=presence.dwell_seconds,
                        movement_score=presence.movement_score,
                        bbox=track.bbox if track else {},
                        centroid=track.centroid if track else (0, 0),
                        state="ENDED",
                        frame_number=frame_number, timestamp=timestamp,
                    ))

        return signals

    def reset(self):
        self._presences.clear()

    def get_active_loiterers(self) -> List[Dict]:
        """Returns current loitering presences — useful for live stream overlay."""
        return [
            {
                "track_id":       p.track_id,
                "zone_name":      p.zone_name,
                "dwell_seconds":  p.dwell_seconds,
                "movement_score": p.movement_score,
                "is_loitering":   p.loitering_started,
            }
            for p in self._presences.values()
            if p.loitering_started
        ]
