"""
Intelligent Event Engine.
Consumes tracker output and fires high-level surveillance events:
  - person_appeared / person_left
  - vehicle_entered / vehicle_left
  - loitering_detected        (person stationary > threshold)
  - crowd_detected            (>= N people in frame)
  - object_left_behind        (bag/luggage stationary > threshold, no nearby person)
  - zone_breach               (track centroid enters a defined polygon zone)
  - re_entry                  (track ID seen again after leaving)
"""
import time
from typing import List, Dict, Set, Optional, Tuple
from app.services.detection.tracker import Track


def _point_in_polygon(px: float, py: float, polygon: List[Tuple]) -> bool:
    """Ray-casting algorithm."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


class IntelligentEventEngine:
    def __init__(
        self,
        loitering_threshold_seconds: float = 20.0,
        object_left_threshold_seconds: float = 30.0,
        crowd_threshold: int = 3,
        zones: Optional[List[Dict]] = None,   # [{"name": "entrance", "polygon": [(x,y),...]}]
    ):
        self.loitering_threshold   = loitering_threshold_seconds
        self.object_left_threshold = object_left_threshold_seconds
        self.crowd_threshold       = crowd_threshold
        self.zones                 = zones or []

        # State
        self._active_ids: Set[int]        = set()   # IDs currently in scene
        self._left_ids:   Set[int]        = set()   # IDs that left (for re-entry)
        self._loitering_fired: Set[int]   = set()   # track IDs that already triggered loitering
        self._zone_breached: Set[Tuple]   = set()   # (track_id, zone_name) already fired
        self._obj_left_fired: Set[int]    = set()   # track IDs that already triggered obj_left

    # ── public ──────────────────────────────────────────────────────────────

    def analyze(self, tracks: List[Track], frame_number: int, timestamp: float) -> List[Dict]:
        events = []
        current_ids = {t.track_id for t in tracks}

        people  = [t for t in tracks if t.cls == "person"]
        vehicles = [t for t in tracks if t.cls in {"car", "truck", "bus", "motorcycle", "bicycle"}]
        bags    = [t for t in tracks if t.cls in {"backpack", "handbag", "suitcase"}]

        # ── appeared / left ─────────────────────────────────────────────────
        for t in tracks:
            if t.track_id not in self._active_ids:
                self._active_ids.add(t.track_id)
                label = "person_appeared" if t.cls == "person" else "vehicle_entered" if t.cls in {"car","truck","bus","motorcycle","bicycle"} else "object_detected"
                events.append(self._make(label, t, frame_number, timestamp))

        for tid in list(self._active_ids):
            if tid not in current_ids:
                self._active_ids.discard(tid)
                self._left_ids.add(tid)
                self._loitering_fired.discard(tid)
                self._obj_left_fired.discard(tid)

        # ── re-entry ────────────────────────────────────────────────────────
        for t in tracks:
            if t.track_id in self._left_ids:
                self._left_ids.discard(t.track_id)
                events.append(self._make("re_entry", t, frame_number, timestamp,
                    extra={"message": f"Track #{t.track_id} re-entered the scene"}))

        # ── loitering ───────────────────────────────────────────────────────
        for t in people:
            if (t.track_id not in self._loitering_fired
                    and t.dwell_seconds >= self.loitering_threshold
                    and t.is_stationary):
                self._loitering_fired.add(t.track_id)
                events.append(self._make("loitering_detected", t, frame_number, timestamp,
                    extra={"dwell_seconds": round(t.dwell_seconds, 1),
                           "message": f"Person #{t.track_id} stationary for {t.dwell_seconds:.0f}s"}))

        # ── crowd ────────────────────────────────────────────────────────────
        if len(people) >= self.crowd_threshold:
            events.append(self._make("crowd_detected", people[0], frame_number, timestamp,
                extra={"count": len(people)}))

        # ── object left behind ───────────────────────────────────────────────
        person_centroids = [t.centroid for t in people]
        for t in bags:
            if t.track_id in self._obj_left_fired:
                continue
            if t.dwell_seconds >= self.object_left_threshold and t.is_stationary:
                # Check no person is nearby
                cx, cy = t.centroid
                nearby = any(abs(px - cx) < 80 and abs(py - cy) < 80 for px, py in person_centroids)
                if not nearby:
                    self._obj_left_fired.add(t.track_id)
                    events.append(self._make("object_left_behind", t, frame_number, timestamp,
                        extra={"dwell_seconds": round(t.dwell_seconds, 1),
                               "message": f"Unattended {t.cls} for {t.dwell_seconds:.0f}s"}))

        # ── zone breach ──────────────────────────────────────────────────────
        for zone in self.zones:
            poly = zone["polygon"]
            name = zone["name"]
            for t in tracks:
                key = (t.track_id, name)
                cx, cy = t.centroid
                if key not in self._zone_breached and _point_in_polygon(cx, cy, poly):
                    self._zone_breached.add(key)
                    events.append(self._make("zone_breach", t, frame_number, timestamp,
                        extra={"zone": name, "message": f"{t.cls.title()} #{t.track_id} entered zone '{name}'"}))

        return events

    def compute_activity_score(self, tracks: List[Track]) -> float:
        people   = sum(1 for t in tracks if t.cls == "person")
        vehicles = sum(1 for t in tracks if t.cls in {"car","truck","bus"})
        return min(1.0, people * 0.25 + vehicles * 0.2 + len(tracks) * 0.05)

    def reset(self):
        self._active_ids.clear()
        self._left_ids.clear()
        self._loitering_fired.clear()
        self._zone_breached.clear()
        self._obj_left_fired.clear()

    # ── private ─────────────────────────────────────────────────────────────

    def _make(self, event_type: str, track: Track, frame_number: int,
              timestamp: float, extra: Optional[Dict] = None) -> Dict:
        return {
            "event_type":             event_type,
            "track_id":               track.track_id,
            "entity":                 track.cls,
            "frame_number":           frame_number,
            "video_timestamp_seconds": timestamp,
            "confidence":             track.confidence,
            "bounding_box":           track.bbox,
            "dwell_seconds":          round(track.dwell_seconds, 2),
            "metadata": {
                **(extra or {}),
                "is_stationary": track.is_stationary,
                "track_id":      track.track_id,
            },
        }
