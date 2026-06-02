import cv2
import numpy as np
from typing import List, Dict

CLASS_COLORS = {
    "person":     (0, 255, 0),
    "car":        (255, 165, 0),
    "truck":      (255, 100, 0),
    "bus":        (255, 50,  0),
    "motorcycle": (0, 200, 255),
    "bicycle":    (0, 150, 255),
    "backpack":   (255, 0, 255),
    "handbag":    (200, 0, 255),
    "suitcase":   (150, 0, 255),
    "bottle":     (0, 255, 200),
}
DEFAULT_COLOR = (200, 200, 200)

EVENT_COLORS = {
    "person_appeared":    (0, 200, 50),
    "person_left":        (100, 100, 100),
    "vehicle_entered":    (0, 165, 255),
    "vehicle_left":       (100, 100, 100),
    "crowd_detected":     (0, 0, 220),
    "object_left_behind": (0, 100, 255),
    "loitering_detected": (0, 0, 255),
    "zone_breach":        (0, 0, 200),
    "re_entry":           (180, 0, 255),
}


def draw_detections(frame: np.ndarray, detections: List[Dict], risk_profiles=None, explanations=None) -> np.ndarray:
    RISK_COLORS = {
        "normal":     None,
        "elevated":   (0, 200, 200),
        "suspicious": (0, 140, 255),
        "critical":   (0, 0, 220),
    }
    for det in detections:
        cls   = det["class"]
        conf  = det.get("confidence", 0)
        bbox  = det["bbox"]
        tid   = det.get("track_id")
        dwell = det.get("dwell_seconds", 0)
        stationary = det.get("is_stationary", False)
        x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]

        # Risk profile overrides color and thickness
        profile = (risk_profiles or {}).get(tid)
        risk_level = profile.risk_level if profile else "normal"
        risk_score = profile.score if profile else 0.0

        if risk_level == "critical":
            color = (0, 0, 220)       # red
            thickness = 4
        elif risk_level == "suspicious":
            color = (0, 120, 255)     # orange
            thickness = 3
        elif risk_level == "elevated":
            color = (0, 200, 220)     # yellow
            thickness = 2
        elif stationary:
            color = (0, 80, 255)
            thickness = 3
        else:
            color = CLASS_COLORS.get(cls, DEFAULT_COLOR)
            thickness = 1 if risk_level == "normal" else 2

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness)

        # Extra glow border for critical tracks
        if risk_level == "critical":
            cv2.rectangle(frame, (x-3, y-3), (x+w+3, y+h+3), color, 1)

        # Label: class #ID  R:score  dominant_signal
        exp = (explanations or {}).get(tid)
        parts = [cls]
        if tid is not None:
            parts.append(f"#{tid}")
        if risk_score >= 25:
            parts.append(f"R:{risk_score:.0f}")
        if exp and exp.dominant_signals:
            parts.append(exp.dominant_signals[0][:12])
        elif dwell > 1:
            parts.append(f"{dwell:.0f}s")
        label = "  ".join(parts)

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
        cv2.rectangle(frame, (x, y - th - 8), (x + tw + 6, y), color, -1)
        cv2.putText(frame, label, (x + 3, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 1, cv2.LINE_AA)

        # Loitering visual — pulsing red overlay + warning text
        if stationary and dwell > 10:
            # Animated-style double border
            cv2.rectangle(frame, (x-4, y-4), (x+w+4, y+h+4), (0, 0, 255), 2)
            # Warning badge
            badge = f" LOITERING {dwell:.0f}s "
            (bw, bh), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x, y+h+2), (x+bw+4, y+h+bh+10), (0, 0, 200), -1)
            cv2.putText(frame, badge, (x+2, y+h+bh+6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def draw_event_banners(frame: np.ndarray, events: List[Dict], frame_h: int) -> np.ndarray:
    for i, event in enumerate(events[-4:]):
        etype = event.get("event_type", "")
        color = EVENT_COLORS.get(etype, (180, 180, 180))
        label = etype.replace("_", " ").upper()
        ts    = event.get("video_timestamp_seconds", 0)
        tid   = event.get("track_id")
        text  = f"  {label}  #{ tid }  @{ts:.1f}s" if tid else f"  {label}  @{ts:.1f}s"

        y_base = frame_h - 30 - i * 34
        overlay = frame.copy()
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.58, 2)
        cv2.rectangle(overlay, (10, y_base - 22), (tw + 20, y_base + 6), color, -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        cv2.putText(frame, text, (10, y_base),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def draw_hud(frame: np.ndarray, frame_number: int, fps: float,
             activity_score: float, mode: str) -> np.ndarray:
    h, w = frame.shape[:2]
    timestamp_sec = frame_number / fps
    mins, secs = divmod(int(timestamp_sec), 60)
    time_str = f"{mins:02d}:{secs:02d}"

    cv2.putText(frame, f"T {time_str}  F {frame_number}", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, f"T {time_str}  F {frame_number}", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)

    mode_color = (0, 200, 80) if mode == "active" else (0, 180, 220)
    badge = f" {mode.upper()} "
    (bw, bh), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(frame, (w - bw - 14, 6), (w - 6, 30), mode_color, -1)
    cv2.putText(frame, badge, (w - bw - 10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)

    bar_w = 120; bar_h = 10
    bx, by = w - bar_w - 14, h - 20
    cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h), (60, 60, 60), -1)
    fill = int(bar_w * min(activity_score, 1.0))
    bar_color = (0, 200, 80) if activity_score < 0.5 else (0, 100, 255)
    cv2.rectangle(frame, (bx, by), (bx + fill, by + bar_h), bar_color, -1)
    cv2.putText(frame, "ACT", (bx - 34, by + 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    return frame


class AnnotatedVideoWriter:
    def __init__(self, output_path: str, fps: float, width: int, height: int):
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        self._writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if not self._writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            print("[AnnotatedWriter] Fell back to mp4v")
        self._fps = fps
        self.output_path = output_path

    def write(self, frame: np.ndarray, detections: List[Dict], events: List[Dict],
              frame_number: int, activity_score: float = 0.0, mode: str = "idle",
              zone_intelligence=None, zone_results=None, risk_profiles=None, explanations=None):
        out = frame.copy()
        if zone_intelligence is not None:
            out = zone_intelligence.draw_zones(out)
        out = draw_detections(out, detections, risk_profiles=risk_profiles, explanations=explanations)
        if zone_intelligence is not None and zone_results is not None:
            out = zone_intelligence.draw_zone_hits(out, zone_results)
        out = draw_hud(out, frame_number, self._fps, activity_score, mode)
        out = draw_event_banners(out, events, out.shape[0])
        self._writer.write(out)

    def release(self):
        self._writer.release()


import os  # needed for makedirs at top of class
