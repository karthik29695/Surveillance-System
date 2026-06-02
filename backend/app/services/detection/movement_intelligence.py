"""
Movement Intelligence Layer — Phase 4
======================================
Analyzes trajectory history to detect behavioral movement patterns.
Outputs probabilistic movement signals consumed by BehaviorScorer.

Patterns detected:
  pacing           — repeated back-and-forth short paths
  circling         — closed-loop repeated trajectory
  boundary_probing — repeated approach to zone edge
  erratic          — high angular instability
  running          — sudden velocity spike
  hovering         — slow oscillation near fixed point
  stationary       — minimal movement over time

All signals carry a confidence (0-1) and contribute to scoring
rather than creating incidents directly.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Any, Optional


@dataclass
class MovementSignal:
    pattern:    str      # pacing | circling | boundary_probing | erratic | running | hovering
    confidence: float    # 0.0 – 1.0
    score_contribution: float  # direct points to add to risk score

    def to_dict(self) -> Dict:
        return {"pattern": self.pattern, "confidence": round(self.confidence, 2),
                "score_contribution": round(self.score_contribution, 2)}


class MovementIntelligence:
    """
    Per-track movement analysis.
    Call analyze(track) each processed frame.
    Returns list of MovementSignals.
    """

    # Config
    MIN_HISTORY        = 12    # frames needed before analysis
    VELOCITY_WINDOW    = 8     # frames for velocity average
    PACING_WINDOW      = 20
    PACING_REVERSAL_THRESH = 130.0   # degrees for direction reversal
    PACING_MIN_REVERSALS   = 3
    RUNNING_VELOCITY_THRESH = 30.0   # px/frame spike
    ERRATIC_ANGLE_THRESH    = 110.0
    ERRATIC_MIN_SPIKES      = 3
    HOVERING_MAX_RADIUS     = 20.0   # px
    CIRCLING_MIN_FRAMES     = 16

    def analyze(self, track: Any) -> List[MovementSignal]:
        history = getattr(track, "history", [])
        if len(history) < self.MIN_HISTORY:
            return []

        signals: List[MovementSignal] = []

        vectors   = self._vectors(history)
        speeds    = [math.hypot(v[0], v[1]) for v in vectors]
        angles    = self._angles(vectors)
        avg_speed = sum(speeds[-self.VELOCITY_WINDOW:]) / max(1, len(speeds[-self.VELOCITY_WINDOW:]))

        # ── Running ───────────────────────────────────────────────────────
        recent_max = max(speeds[-8:]) if len(speeds) >= 8 else 0
        if recent_max > self.RUNNING_VELOCITY_THRESH and avg_speed < recent_max * 0.4:
            conf = min(1.0, recent_max / (self.RUNNING_VELOCITY_THRESH * 2))
            signals.append(MovementSignal("running", conf, conf * 4.0))

        # ── Erratic movement ──────────────────────────────────────────────
        if len(angles) >= 6:
            spikes = sum(1 for a in angles[-10:] if a > self.ERRATIC_ANGLE_THRESH)
            if spikes >= self.ERRATIC_MIN_SPIKES:
                conf = min(1.0, spikes / 6.0)
                signals.append(MovementSignal("erratic", conf, conf * 5.0))

        # ── Pacing ────────────────────────────────────────────────────────
        recent_h = history[-self.PACING_WINDOW:]
        if len(recent_h) >= self.PACING_WINDOW:
            rev_vecs = self._vectors(recent_h)
            rev_angles = self._angles(rev_vecs)
            reversals = sum(1 for a in rev_angles if a > self.PACING_REVERSAL_THRESH)
            if reversals >= self.PACING_MIN_REVERSALS:
                conf = min(1.0, reversals / 6.0)
                signals.append(MovementSignal("pacing", conf, conf * 6.0))

        # ── Hovering (oscillating near fixed point) ───────────────────────
        if len(history) >= 16:
            recent_16 = history[-16:]
            xs = [p[0] for p in recent_16]; ys = [p[1] for p in recent_16]
            spread = math.hypot(max(xs)-min(xs), max(ys)-min(ys))
            if spread < self.HOVERING_MAX_RADIUS and avg_speed > 1.0:
                conf = min(1.0, (self.HOVERING_MAX_RADIUS - spread) / self.HOVERING_MAX_RADIUS)
                signals.append(MovementSignal("hovering", conf, conf * 3.0))

        # ── Circling ──────────────────────────────────────────────────────
        if len(history) >= self.CIRCLING_MIN_FRAMES:
            cx = sum(p[0] for p in history[-self.CIRCLING_MIN_FRAMES:]) / self.CIRCLING_MIN_FRAMES
            cy = sum(p[1] for p in history[-self.CIRCLING_MIN_FRAMES:]) / self.CIRCLING_MIN_FRAMES
            radii = [math.dist(p, (cx,cy)) for p in history[-self.CIRCLING_MIN_FRAMES:]]
            mean_r = sum(radii) / len(radii)
            variance = sum((r-mean_r)**2 for r in radii) / len(radii)
            if 15 < mean_r < 120 and variance < mean_r * 0.4 and avg_speed > 1.5:
                conf = min(1.0, 1.0 - variance / (mean_r * 0.4))
                signals.append(MovementSignal("circling", conf, conf * 5.0))

        return signals

    def _vectors(self, history: List[Tuple]) -> List[Tuple[float,float]]:
        return [(history[i][0]-history[i-1][0], history[i][1]-history[i-1][1])
                for i in range(1, len(history))]

    def _angles(self, vectors: List[Tuple]) -> List[float]:
        angles = []
        for i in range(1, len(vectors)):
            v1, v2 = vectors[i-1], vectors[i]
            m1, m2 = math.hypot(*v1), math.hypot(*v2)
            if m1 < 0.5 or m2 < 0.5: continue
            cos_a = max(-1.0, min(1.0, (v1[0]*v2[0]+v1[1]*v2[1])/(m1*m2)))
            angles.append(math.degrees(math.acos(cos_a)))
        return angles
