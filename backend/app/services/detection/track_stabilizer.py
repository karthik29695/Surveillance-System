"""
Track Stabilization Layer
==========================
Sits between CentroidTracker and all intelligence layers.

Responsibilities:
  - Maintains a proper track state machine: NEW → ACTIVE → LOST → RECOVERED → TERMINATED
  - Prevents duplicate entry/exit events caused by occlusion or brief disappearance
  - Recovers lost tracks that reappear nearby within LOST_TIMEOUT seconds
  - Emits StabilizedTrack objects (not raw Track objects) to downstream layers
  - Separates low-level tracking activity from meaningful surveillance incidents

The Tracker still does what it always did (IoU matching, IDs).
This layer wraps its output and adds lifecycle semantics.
"""

from __future__ import annotations
import time
import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# ── Config ────────────────────────────────────────────────────────────────────

class StabConfig:
    LOST_TIMEOUT_SECONDS:     float = 3.0    # Grace period before TERMINATED
    RECOVERY_MAX_DISTANCE_PX: float = 120.0  # Max centroid distance for recovery match
    RECOVERY_SAME_CLASS:      bool  = True   # Must match class to recover
    NEW_TO_ACTIVE_FRAMES:     int   = 3      # Frames before NEW → ACTIVE
    SCENE_SUMMARY_INTERVAL:   float = 30.0   # Seconds between scene summaries


# ── State machine ─────────────────────────────────────────────────────────────

class TrackState(str, Enum):
    NEW        = "NEW"
    ACTIVE     = "ACTIVE"
    LOST       = "LOST"
    RECOVERED  = "RECOVERED"
    TERMINATED = "TERMINATED"


# ── Incident severity hierarchy ───────────────────────────────────────────────

class IncidentSeverity(str, Enum):
    INFO     = "info"      # person_appeared, person_left — internal metadata
    LOW      = "low"       # zone entry/exit
    MEDIUM   = "medium"    # crowd detected
    HIGH     = "high"      # loitering, sustained zone presence
    CRITICAL = "critical"  # suspect identified, restricted intrusion

SEVERITY_VISIBLE = {
    # Only MEDIUM and above appear in dashboard/alerts/timeline
    IncidentSeverity.INFO:     False,
    IncidentSeverity.LOW:      False,
    IncidentSeverity.MEDIUM:   True,
    IncidentSeverity.HIGH:     True,
    IncidentSeverity.CRITICAL: True,
}

EVENT_SEVERITY_MAP = {
    # Internal tracking events — INFO only
    "track_new":        IncidentSeverity.INFO,
    "track_active":     IncidentSeverity.INFO,
    "track_lost":       IncidentSeverity.INFO,
    "track_recovered":  IncidentSeverity.INFO,
    "track_terminated": IncidentSeverity.INFO,
    "person_appeared":  IncidentSeverity.INFO,
    "person_left":      IncidentSeverity.INFO,
    "vehicle_entered":  IncidentSeverity.LOW,
    "vehicle_left":     IncidentSeverity.LOW,
    "object_detected":  IncidentSeverity.LOW,
    "re_entry":         IncidentSeverity.LOW,
    # Security incidents — visible
    "zone_breach":          IncidentSeverity.MEDIUM,
    "crowd_detected":       IncidentSeverity.MEDIUM,
    "object_left_behind":   IncidentSeverity.HIGH,
    "loitering_detected":   IncidentSeverity.HIGH,
    "zone_breach:restricted": IncidentSeverity.CRITICAL,
    "suspect_identified":   IncidentSeverity.CRITICAL,
}

def get_severity(event_type: str, zone_type: str = "") -> IncidentSeverity:
    if event_type == "zone_breach" and zone_type == "restricted":
        return IncidentSeverity.CRITICAL
    return EVENT_SEVERITY_MAP.get(event_type, IncidentSeverity.LOW)

def is_visible_incident(event_type: str, zone_type: str = "") -> bool:
    return SEVERITY_VISIBLE.get(get_severity(event_type, zone_type), False)


# ── Stabilized track ──────────────────────────────────────────────────────────

@dataclass
class StabilizedTrack:
    """
    Wraps a raw Track with lifecycle state.
    This is what gets passed to ZoneIntel / LoiteringIntel / EIE.
    """
    track_id:    int
    cls:         str
    bbox:        Dict
    confidence:  float
    centroid:    Tuple[float, float]
    state:       TrackState
    frame_count: int = 0          # frames seen in current state
    first_seen:  float = field(default_factory=time.time)
    last_seen:   float = field(default_factory=time.time)
    lost_since:  Optional[float] = None
    dwell_seconds: float = 0.0
    is_stationary: bool = False
    history:     List[Tuple[float,float]] = field(default_factory=list)

    @property
    def is_stable(self) -> bool:
        """Only ACTIVE and RECOVERED tracks feed into intelligence layers."""
        return self.state in (TrackState.ACTIVE, TrackState.RECOVERED)


# ── Internal state entry ──────────────────────────────────────────────────────

@dataclass
class _TrackEntry:
    stabilized:  StabilizedTrack
    raw_track_id: int   # may differ from stabilized.track_id after recovery


# ── Main stabilizer ───────────────────────────────────────────────────────────

class TrackStabilizationLayer:
    """
    Wraps CentroidTracker output with lifecycle state management.

    Usage (once per processed frame):
        stable_tracks, internal_events = stabilizer.update(raw_tracks, timestamp)

    stable_tracks   — List[StabilizedTrack] with state NEW/ACTIVE/RECOVERED/LOST
    internal_events — List[Dict] tracking lifecycle signals (INFO severity only)

    Pass stable_tracks (filter by is_stable) to ZoneIntel and LoiteringIntel.
    Pass internal_events to EIE only if you want full audit logging.
    """

    def __init__(self):
        self._entries:      Dict[int, _TrackEntry]  = {}   # stabilized_id → entry
        self._lost:         Dict[int, _TrackEntry]  = {}   # stabilized_id → lost entry
        self._next_id:      int   = 1
        self._raw_to_stab:  Dict[int, int] = {}            # raw tracker ID → stabilized ID
        self._last_summary: float = 0.0
        self._peak_count:   int   = 0

    # ── public API ────────────────────────────────────────────────────────────

    def update(
        self,
        raw_tracks: List[Any],     # Track objects from CentroidTracker
        timestamp: float,
        frame_number: int = 0,
    ) -> Tuple[List[StabilizedTrack], List[Dict]]:
        """
        Returns (stable_tracks, internal_events).
        stable_tracks includes NEW, ACTIVE, RECOVERED, LOST tracks.
        Filter by .is_stable for intelligence layers.
        """
        now = time.time()
        internal_events: List[Dict] = []
        current_raw_ids = {t.track_id for t in raw_tracks}

        # ── 1. Update existing stable tracks ─────────────────────────────────
        matched_stab_ids: set = set()

        for raw in raw_tracks:
            stab_id = self._raw_to_stab.get(raw.track_id)

            if stab_id and stab_id in self._entries:
                # Known track — update
                entry = self._entries[stab_id]
                st    = entry.stabilized
                st.bbox       = raw.bbox
                st.confidence = raw.confidence
                st.centroid   = raw.centroid
                st.last_seen  = now
                st.dwell_seconds  = raw.dwell_seconds
                st.is_stationary  = raw.is_stationary
                st.history.append(raw.centroid)
                if len(st.history) > 60: st.history = st.history[-60:]
                st.frame_count += 1
                st.lost_since  = None

                prev_state = st.state
                if st.state == TrackState.NEW and st.frame_count >= StabConfig.NEW_TO_ACTIVE_FRAMES:
                    st.state = TrackState.ACTIVE
                    internal_events.append(self._make_internal("track_active", st, frame_number, timestamp))
                elif st.state == TrackState.LOST:
                    st.state = TrackState.RECOVERED
                    internal_events.append(self._make_internal("track_recovered", st, frame_number, timestamp))
                else:
                    st.state = TrackState.ACTIVE
                matched_stab_ids.add(stab_id)

            elif raw.track_id in self._raw_to_stab:
                pass  # already mapped, handled above
            else:
                # Check if this could recover a LOST track
                recovered = self._try_recover(raw, now)
                if recovered:
                    stab_id = recovered.stabilized.track_id
                    st = recovered.stabilized
                    st.bbox = raw.bbox; st.confidence = raw.confidence
                    st.centroid = raw.centroid; st.last_seen = now
                    st.dwell_seconds = raw.dwell_seconds
                    st.is_stationary = raw.is_stationary
                    st.lost_since = None; st.state = TrackState.RECOVERED
                    st.frame_count += 1
                    self._entries[stab_id] = recovered
                    self._raw_to_stab[raw.track_id] = stab_id
                    del self._lost[stab_id]
                    internal_events.append(self._make_internal("track_recovered", st, frame_number, timestamp))
                    matched_stab_ids.add(stab_id)
                else:
                    # Genuinely new track
                    stab_id = self._next_id; self._next_id += 1
                    st = StabilizedTrack(
                        track_id=stab_id, cls=raw.cls,
                        bbox=raw.bbox, confidence=raw.confidence,
                        centroid=raw.centroid, state=TrackState.NEW,
                        first_seen=now, last_seen=now,
                        dwell_seconds=raw.dwell_seconds,
                        is_stationary=raw.is_stationary,
                    )
                    entry = _TrackEntry(stabilized=st, raw_track_id=raw.track_id)
                    self._entries[stab_id] = entry
                    self._raw_to_stab[raw.track_id] = stab_id
                    internal_events.append(self._make_internal("track_new", st, frame_number, timestamp))
                    matched_stab_ids.add(stab_id)

        # ── 2. Handle tracks not seen this frame → LOST ───────────────────────
        for stab_id, entry in list(self._entries.items()):
            if stab_id not in matched_stab_ids:
                st = entry.stabilized
                if st.state not in (TrackState.LOST,):
                    st.state = TrackState.LOST
                    st.lost_since = now
                    self._lost[stab_id] = entry
                    internal_events.append(self._make_internal("track_lost", st, frame_number, timestamp))
                del self._entries[stab_id]

        # ── 3. Terminate tracks that exceeded grace period ────────────────────
        for stab_id, entry in list(self._lost.items()):
            st = entry.stabilized
            if st.lost_since and (now - st.lost_since) > StabConfig.LOST_TIMEOUT_SECONDS:
                st.state = TrackState.TERMINATED
                internal_events.append(self._make_internal("track_terminated", st, frame_number, timestamp))
                del self._lost[stab_id]
                # Clean up raw mapping
                self._raw_to_stab = {k: v for k, v in self._raw_to_stab.items() if v != stab_id}

        # ── 4. Collect all output tracks ──────────────────────────────────────
        all_tracks = (
            [e.stabilized for e in self._entries.values()] +
            [e.stabilized for e in self._lost.values()]
        )
        self._peak_count = max(self._peak_count,
                               sum(1 for t in all_tracks if t.is_stable))

        return all_tracks, internal_events

    def get_stable_tracks(self, all_tracks: List[StabilizedTrack]) -> List[StabilizedTrack]:
        """Filter to only tracks ready for intelligence layers."""
        return [t for t in all_tracks if t.is_stable]

    def scene_summary(self, all_tracks: List[StabilizedTrack], timestamp: float) -> Optional[Dict]:
        """Emit a scene activity summary every SCENE_SUMMARY_INTERVAL seconds."""
        now = time.time()
        if now - self._last_summary < StabConfig.SCENE_SUMMARY_INTERVAL:
            return None
        self._last_summary = now
        stable = self.get_stable_tracks(all_tracks)
        people   = [t for t in stable if t.cls == "person"]
        vehicles = [t for t in stable if t.cls in {"car","truck","bus","motorcycle","bicycle"}]
        if not stable:
            return None
        return {
            "event_type": "scene_summary",
            "video_timestamp_seconds": timestamp,
            "extra_data": {
                "severity":        "info",
                "visible":         False,
                "active_people":   len(people),
                "active_vehicles": len(vehicles),
                "peak_count":      self._peak_count,
                "message": (
                    f"Scene: {len(people)} people, {len(vehicles)} vehicles active. "
                    f"Peak occupancy: {self._peak_count}."
                ),
            }
        }

    def reset(self):
        self._entries.clear()
        self._lost.clear()
        self._raw_to_stab.clear()
        self._peak_count = 0

    # ── private ───────────────────────────────────────────────────────────────

    def _try_recover(self, raw_track: Any, now: float) -> Optional[_TrackEntry]:
        """Find best LOST track candidate for recovery."""
        best_entry = None
        best_dist  = float("inf")
        cx, cy = raw_track.centroid

        for stab_id, entry in self._lost.items():
            st = entry.stabilized
            if StabConfig.RECOVERY_SAME_CLASS and st.cls != raw_track.cls:
                continue
            if st.lost_since and (now - st.lost_since) > StabConfig.LOST_TIMEOUT_SECONDS:
                continue
            lx, ly = st.centroid
            dist = math.dist((cx, cy), (lx, ly))
            if dist < StabConfig.RECOVERY_MAX_DISTANCE_PX and dist < best_dist:
                best_dist  = dist
                best_entry = entry
        return best_entry

    def _make_internal(self, event_type: str, st: StabilizedTrack,
                       frame_number: int, timestamp: float) -> Dict:
        return {
            "event_type":              event_type,
            "frame_number":            frame_number,
            "video_timestamp_seconds": timestamp,
            "confidence":              st.confidence,
            "bounding_box":            st.bbox,
            "extra_data": {
                "severity":   IncidentSeverity.INFO.value,
                "visible":    False,   # never shown in dashboard/alerts
                "track_id":   st.track_id,
                "state":      st.state.value,
                "cls":        st.cls,
                "message":    f"Track #{st.track_id} ({st.cls}) → {st.state.value}",
            },
        }
