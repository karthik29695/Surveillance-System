"""
Centroid-based multi-object tracker.
Assigns consistent track IDs across frames using IoU matching.
No extra dependencies — pure numpy + Python.
"""
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import time


def _iou(boxA: Dict, boxB: Dict) -> float:
    """Compute IoU between two bbox dicts {x, y, w, h}."""
    ax1, ay1 = boxA["x"], boxA["y"]
    ax2, ay2 = ax1 + boxA["w"], ay1 + boxA["h"]
    bx1, by1 = boxB["x"], boxB["y"]
    bx2, by2 = bx1 + boxB["w"], by1 + boxB["h"]

    inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0, min(ay2, by2) - max(ay1, by1))
    inter   = inter_w * inter_h
    union   = boxA["w"] * boxA["h"] + boxB["w"] * boxB["h"] - inter
    return inter / union if union > 0 else 0.0


def _centroid(bbox: Dict) -> Tuple[float, float]:
    return bbox["x"] + bbox["w"] / 2, bbox["y"] + bbox["h"] / 2


class Track:
    def __init__(self, track_id: int, detection: Dict, timestamp: float):
        self.track_id    = track_id
        self.cls         = detection["class"]
        self.bbox        = detection["bbox"]
        self.confidence  = detection["confidence"]
        self.first_seen  = timestamp
        self.last_seen   = timestamp
        self.missed      = 0          # consecutive frames without match
        self.history: List[Tuple[float, float]] = [_centroid(detection["bbox"])]

    def update(self, detection: Dict, timestamp: float):
        self.bbox       = detection["bbox"]
        self.confidence = detection["confidence"]
        self.last_seen  = timestamp
        self.missed     = 0
        self.history.append(_centroid(detection["bbox"]))
        if len(self.history) > 60:          # keep last 60 positions
            self.history = self.history[-60:]

    @property
    def dwell_seconds(self) -> float:
        return self.last_seen - self.first_seen
    @property
    def centroid(self) -> tuple:
        return (self.bbox["x"] + self.bbox["w"] / 2,
                self.bbox["y"] + self.bbox["h"] / 2)


    @property
    def is_stationary(self) -> bool:
        """True if centroid hasn't moved much over last N positions."""
        if len(self.history) < 10:
            return False
        recent = self.history[-10:]
        xs = [p[0] for p in recent]
        ys = [p[1] for p in recent]
        return (max(xs) - min(xs)) < 25 and (max(ys) - min(ys)) < 25

    def to_dict(self) -> Dict:
        return {
            "track_id":      self.track_id,
            "class":         self.cls,
            "bbox":          self.bbox,
            "confidence":    self.confidence,
            "dwell_seconds": round(self.dwell_seconds, 2),
            "is_stationary": self.is_stationary,
            "centroid":      _centroid(self.bbox),
        }


class CentroidTracker:
    """
    IoU-based multi-object tracker.
    Call update() each frame with the list of detections.
    Returns active Track objects with stable IDs.
    """
    def __init__(self, iou_threshold: float = 0.25, max_missed: int = 8):
        self.iou_threshold = iou_threshold
        self.max_missed    = max_missed
        self._next_id      = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, detections: List[Dict], timestamp: float) -> List[Track]:
        if not detections:
            # Age out all tracks
            for t in list(self.tracks.values()):
                t.missed += 1
            self._prune()
            return list(self.tracks.values())

        # Match detections to existing tracks via IoU
        track_ids   = list(self.tracks.keys())
        matched_det = set()
        matched_trk = set()

        if track_ids:
            iou_matrix = np.zeros((len(track_ids), len(detections)))
            for ti, tid in enumerate(track_ids):
                for di, det in enumerate(detections):
                    if self.tracks[tid].cls == det["class"]:
                        iou_matrix[ti, di] = _iou(self.tracks[tid].bbox, det["bbox"])

            # Greedy match: highest IoU first
            flat = np.argsort(-iou_matrix, axis=None)
            for idx in flat:
                ti, di = divmod(int(idx), len(detections))
                if iou_matrix[ti, di] < self.iou_threshold:
                    break
                if ti in matched_trk or di in matched_det:
                    continue
                self.tracks[track_ids[ti]].update(detections[di], timestamp)
                matched_trk.add(ti)
                matched_det.add(di)

        # Age unmatched tracks
        for ti, tid in enumerate(track_ids):
            if ti not in matched_trk:
                self.tracks[tid].missed += 1

        # Register new tracks for unmatched detections
        for di, det in enumerate(detections):
            if di not in matched_det:
                self.tracks[self._next_id] = Track(self._next_id, det, timestamp)
                self._next_id += 1

        self._prune()
        return list(self.tracks.values())

    def _prune(self):
        self.tracks = {tid: t for tid, t in self.tracks.items() if t.missed <= self.max_missed}

    def reset(self):
        self.tracks = {}
        self._next_id = 1
