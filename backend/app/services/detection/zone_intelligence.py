"""
Zone Intelligence Layer
=======================
Sits between the Tracker and the Event Intelligence Engine.
Responsibility: spatial relationship only — which tracks are inside which zones.
No event lifecycle logic here (that lives in EIE).

Usage:
    zi = ZoneIntelligence(zones)   # zones from DB as list of dicts
    results = zi.test(tracks)      # returns ZoneTestResult per track
"""
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


ZONE_TYPE_COLOR = {
    "restricted":  (0,   0,   220),   # red   (BGR)
    "entry":       (0,   200, 0  ),   # green
    "exit":        (0,   165, 255),   # orange
    "monitoring":  (0,   200, 200),   # yellow
}


@dataclass
class ZoneTestResult:
    track_id:    int
    cls:         str
    bbox:        Dict
    centroid:    Tuple[float, float]
    inside_zones: List[Dict] = field(default_factory=list)  # [{id, zone_name, zone_type, color}]

    @property
    def in_restricted(self) -> bool:
        return any(z["zone_type"] == "restricted" for z in self.inside_zones)

    @property
    def zone_names(self) -> List[str]:
        return [z["zone_name"] for z in self.inside_zones]


class ZoneIntelligence:
    def __init__(self, zones: List[Dict]):
        """
        zones: list of dicts from DB:
            {id, zone_name, zone_type, points: [[x,y],...], color}
        """
        self._zones = []
        for z in zones:
            pts = np.array(z["points"], dtype=np.float32)
            self._zones.append({
                "id":        z["id"],
                "zone_name": z["zone_name"],
                "zone_type": z["zone_type"],
                "color":     z.get("color", "#ef4444"),
                "contour":   pts.reshape((-1, 1, 2)),
            })

    def test(self, tracks: List[Any]) -> List[ZoneTestResult]:
        """Test every track against every zone. Returns one result per track."""
        results = []
        for t in tracks:
            cx, cy = t.centroid
            inside = []
            for z in self._zones:
                dist = cv2.pointPolygonTest(z["contour"], (float(cx), float(cy)), False)
                if dist >= 0:   # inside or on boundary
                    inside.append({
                        "id":        z["id"],
                        "zone_name": z["zone_name"],
                        "zone_type": z["zone_type"],
                        "color":     z["color"],
                    })
            results.append(ZoneTestResult(
                track_id=t.track_id,
                cls=t.cls,
                bbox=t.bbox,
                centroid=(cx, cy),
                inside_zones=inside,
            ))
        return results

    def draw_zones(self, frame: np.ndarray) -> np.ndarray:
        """Overlay all configured zones onto a frame (call before drawing tracks)."""
        for z in self._zones:
            pts = z["contour"].astype(np.int32)

            # Parse hex color → BGR
            color = _hex_to_bgr(z["color"])

            # Semi-transparent fill
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)

            # Border
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)

            # Label at centroid of polygon
            M = cv2.moments(pts)
            if M["m00"] != 0:
                lx = int(M["m10"] / M["m00"])
                ly = int(M["m01"] / M["m00"])
            else:
                lx, ly = int(pts[0][0][0]), int(pts[0][0][1])

            label = f"{z['zone_name']} [{z['zone_type']}]"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
            cv2.rectangle(frame, (lx - 4, ly - th - 6), (lx + tw + 4, ly + 2), color, -1)
            cv2.putText(frame, label, (lx, ly - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        return frame

    def draw_zone_hits(self, frame: np.ndarray, results: List[ZoneTestResult]) -> np.ndarray:
        """Draw a pulsing highlight border around tracks inside restricted zones."""
        for r in results:
            if not r.inside_zones:
                continue
            b = r.bbox
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            for z in r.inside_zones:
                color = _hex_to_bgr(z["color"])
                # Double-border alert effect
                cv2.rectangle(frame, (x - 3, y - 3), (x + w + 3, y + h + 3), color, 3)
                cv2.rectangle(frame, (x - 6, y - 6), (x + w + 6, y + h + 6), color, 1)
                # Zone tag below box
                tag = z["zone_name"]
                cv2.putText(frame, tag, (x, y + h + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        return frame

    def reload(self, zones: List[Dict]):
        self.__init__(zones)


def _hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0, 0, 200)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)   # OpenCV uses BGR
