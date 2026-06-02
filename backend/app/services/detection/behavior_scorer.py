"""
Refined Behavior Scorer — Production Tuning
=============================================
Changes from previous version:
  1. Rebalanced zone scoring — restricted zone alone → ELEVATED only
  2. Independent zone dwell tracking — resets on zone change
  3. Stricter re-entry suppression — requires existing evidence
  4. Exponential score smoothing — gradual rise, no spikes
  5. Weighted evidence accumulation — replaces signal count
  6. Risk memory — peak-based floor slows decay on high-risk tracks
"""
from __future__ import annotations
import time, math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


class ScorerConfig:
    # ── Base scores (per second) ──────────────────────────────────────────
    # Rebalanced: zone alone should not reach CRITICAL
    BASE_ZONE_RESTRICTED:   float = 1.1    # was 2.5 — reduced significantly
    BASE_ZONE_MONITORING:   float = 0.7    # was 1.2
    BASE_LOITERING:         float = 3.0    # kept strong — this is the key signal
    BASE_REENTRY:           float = 5.0    # was 8.0 — further reduced
    BASE_MOVEMENT:          float = 1.0    # per unit confidence

    # ── Contributor caps ──────────────────────────────────────────────────
    CAP_ZONE:               float = 22.0   # was 50 — zone alone max ELEVATED
    CAP_LOITERING:          float = 45.0   # loitering can drive to SUSPICIOUS
    CAP_REENTRY:            float = 10.0   # was 12 — hard ceiling
    CAP_MOVEMENT:           float = 25.0

    # ── Severity-based decay ──────────────────────────────────────────────
    DECAY_NORMAL:           float = 5.0
    DECAY_ELEVATED:         float = 2.5
    DECAY_SUSPICIOUS:       float = 1.2
    DECAY_CRITICAL:         float = 0.6

    # ── Risk memory floor ─────────────────────────────────────────────────
    # Tracks that reached high risk decay toward a floor, not zero
    MEMORY_FACTOR:          float = 0.15   # floor = peak_score * MEMORY_FACTOR
    MEMORY_DECAY_RATE:      float = 0.05   # floor itself decays slowly

    # ── Score smoothing ───────────────────────────────────────────────────
    # Exponential weighted moving average — alpha controls rise speed
    # Lower alpha = smoother but slower; higher = faster but spikier
    SMOOTH_ALPHA_RISE:      float = 0.25   # blending factor for score increases
    SMOOTH_ALPHA_FALL:      float = 0.40   # slightly faster fall than rise

    # ── Risk thresholds ───────────────────────────────────────────────────
    ELEVATED_THRESHOLD:     float = 25.0
    SUSPICIOUS_THRESHOLD:   float = 50.0
    CRITICAL_THRESHOLD:     float = 75.0
    MAX_SCORE:              float = 100.0

    # ── Weighted evidence accumulation ───────────────────────────────────
    # Replaces simple signal count — each signal type has behavioral weight
    EVIDENCE_WEIGHTS: Dict[str, float] = {
        "restricted_zone": 0.3,   # weak — presence alone is low evidence
        "monitoring_zone": 0.2,
        "loitering":       0.7,   # moderate-strong
        "re_entry":        0.2,   # weak supporting signal
        "movement_pacing":     0.6,
        "movement_circling":   0.5,
        "movement_erratic":    0.5,
        "movement_hovering":   0.4,
        "movement_running":    0.3,
    }
    EVIDENCE_ESCALATION_THRESHOLD: float = 0.8   # weighted sum needed to allow escalation

    # ── Phase 5: false positive suppression ──────────────────────────────
    MIN_CONFIDENCE:             float = 0.4
    MIN_ZONE_DWELL_SECONDS:     float = 1.5
    MIN_TRACK_AGE_FRAMES:       int   = 5
    MIN_PERSISTENCE_SECONDS:    float = 3.0
    # Re-entry suppression thresholds
    REENTRY_MIN_SCORE:          float = 20.0  # must already have risk
    REENTRY_MIN_ZONE_DWELL:     float = 3.0   # must be meaningfully in zone

    # ── Compound multiplier ───────────────────────────────────────────────
    COMPOUND_THRESHOLD:         float = 40.0
    COMPOUND_MULTIPLIER:        float = 1.25  # gentler than before

    TIMELINE_SAMPLE_INTERVAL:   float = 0.5


class RiskLevel:
    NORMAL     = "normal"
    ELEVATED   = "elevated"
    SUSPICIOUS = "suspicious"
    CRITICAL   = "critical"

    @staticmethod
    def from_score(s: float) -> str:
        if s >= ScorerConfig.CRITICAL_THRESHOLD:   return RiskLevel.CRITICAL
        if s >= ScorerConfig.SUSPICIOUS_THRESHOLD: return RiskLevel.SUSPICIOUS
        if s >= ScorerConfig.ELEVATED_THRESHOLD:   return RiskLevel.ELEVATED
        return RiskLevel.NORMAL

    @staticmethod
    def decay_rate(level: str) -> float:
        return {
            RiskLevel.NORMAL:     ScorerConfig.DECAY_NORMAL,
            RiskLevel.ELEVATED:   ScorerConfig.DECAY_ELEVATED,
            RiskLevel.SUSPICIOUS: ScorerConfig.DECAY_SUSPICIOUS,
            RiskLevel.CRITICAL:   ScorerConfig.DECAY_CRITICAL,
        }.get(level, ScorerConfig.DECAY_ELEVATED)

RISK_COLOR    = {RiskLevel.NORMAL:"#4b5563", RiskLevel.ELEVATED:"#eab308",
                 RiskLevel.SUSPICIOUS:"#f97316", RiskLevel.CRITICAL:"#ef4444"}
RISK_SEVERITY = {RiskLevel.NORMAL:"info", RiskLevel.ELEVATED:"low",
                 RiskLevel.SUSPICIOUS:"high", RiskLevel.CRITICAL:"critical"}


@dataclass
class EscalationEvent:
    timestamp: float; video_ts: float
    from_level: str;  to_level: str
    score: float;     trigger: str
    contributors: Dict[str, float]
    direction: str = "up"


@dataclass
class TimelinePoint:
    video_ts: float; score: float
    risk_level: str; dominant: str
    event_marker: Optional[str] = None


@dataclass
class RiskProfile:
    track_id: int
    cls:      str
    # Smoothed score (what's displayed)
    score:        float = 0.0
    # Raw target score (before smoothing)
    _raw_score:   float = 0.0
    # Risk memory floor
    _memory_floor:float = 0.0

    risk_level:   str   = RiskLevel.NORMAL
    last_updated: float = field(default_factory=time.time)

    contributors: Dict[str,float] = field(default_factory=lambda:{
        "restricted_zone":0.0, "monitoring_zone":0.0, "loitering":0.0,
        "re_entry":0.0, "movement":0.0, "decay":0.0,
    })
    frame_contributors: Dict[str,float] = field(default_factory=dict)
    escalation_history: List[EscalationEvent] = field(default_factory=list)
    timeline: List[TimelinePoint] = field(default_factory=list)

    peak_score:    float = 0.0
    peak_risk:     str   = RiskLevel.NORMAL
    reentry_count: int   = 0
    incident_count:int   = 0
    active_signals:List[str] = field(default_factory=list)

    # Zone dwell — independent per zone (resets on zone change)
    current_zone:       Optional[str] = None
    _prev_zone:         Optional[str] = None
    zone_dwell_secs:    float = 0.0

    # Weighted evidence accumulation
    _evidence_score:    float = 0.0

    # Signal persistence
    _signal_first_seen: Dict[str,float] = field(default_factory=dict)

    trend:        str   = "stable"
    _prev_score:  float = 0.0
    _last_tl_ts:  float = 0.0

    critical_fired:   bool = False
    suspicious_fired: bool = False

    def apply_smoothing(self, target: float, dt: float) -> float:
        """Exponential weighted moving average — smooth rise and fall."""
        if target > self.score:
            alpha = ScorerConfig.SMOOTH_ALPHA_RISE
        else:
            alpha = ScorerConfig.SMOOTH_ALPHA_FALL
        # Clamp alpha to frame-rate-independent range
        effective_alpha = min(0.9, alpha * (dt / 0.04))
        return self.score + effective_alpha * (target - self.score)

    def update_score(self, frame_deltas: Dict[str,float], dt: float, video_ts: float) -> str:
        prev_level = self.risk_level
        total_positive = sum(v for v in frame_deltas.values() if v > 0)

        if total_positive <= 0:
            # Severity-based decay toward memory floor
            decay = RiskLevel.decay_rate(self.risk_level) * dt
            floor = self._memory_floor
            self._raw_score = max(floor, self._raw_score - decay)
            self.contributors["decay"] = self.contributors.get("decay", 0.0) - decay * 0.5
            self.frame_contributors = {"decay": -decay}
            # Slowly decay the memory floor itself
            self._memory_floor = max(0.0, self._memory_floor - ScorerConfig.MEMORY_DECAY_RATE * dt)
        else:
            effective = total_positive
            if self._raw_score >= ScorerConfig.COMPOUND_THRESHOLD:
                effective *= ScorerConfig.COMPOUND_MULTIPLIER
            self._raw_score = min(ScorerConfig.MAX_SCORE, self._raw_score + effective * dt)
            for k, v in frame_deltas.items():
                if v > 0:
                    self.contributors[k] = min(
                        self._cap(k),
                        self.contributors.get(k, 0.0) + v * dt
                    )
            self.frame_contributors = frame_deltas

        # Apply smoothing
        self.score = self.apply_smoothing(self._raw_score, dt)
        self.score = max(0.0, min(ScorerConfig.MAX_SCORE, self.score))

        # Update peak and memory floor
        if self.score > self.peak_score:
            self.peak_score    = self.score
            # Set memory floor — high peaks leave a lasting impression
            self._memory_floor = max(
                self._memory_floor,
                self.peak_score * ScorerConfig.MEMORY_FACTOR
            )

        self.risk_level  = RiskLevel.from_score(self.score)
        self.peak_risk   = RiskLevel.from_score(self.peak_score)
        self.last_updated = time.time()

        delta = self.score - self._prev_score
        self.trend = "escalating" if delta > 0.8 else "cooling" if delta < -0.8 else "stable"
        self._prev_score = self.score

        # Sample timeline
        if video_ts - self._last_tl_ts >= ScorerConfig.TIMELINE_SAMPLE_INTERVAL:
            self.timeline.append(TimelinePoint(
                video_ts=round(video_ts, 2), score=round(self.score, 1),
                risk_level=self.risk_level, dominant=self._dominant(),
            ))
            if len(self.timeline) > 200: self.timeline = self.timeline[-200:]
            self._last_tl_ts = video_ts

        return prev_level

    def update_zone_dwell(self, zone_name: Optional[str], dt: float):
        """Independent zone dwell — resets when zone changes."""
        if zone_name != self._prev_zone:
            self.zone_dwell_secs = 0.0   # reset on zone change
            self._prev_zone = zone_name
        if zone_name:
            self.zone_dwell_secs += dt

    def compute_evidence(self, signals: List[str]) -> float:
        """Weighted evidence score from current signals."""
        total = 0.0
        for sig in signals:
            base_key = sig.split(":")[0]
            # Movement pattern keys like movement_pacing
            if sig.startswith("movement:"):
                pattern = sig.split(":")[1]
                key = f"movement_{pattern}"
            else:
                key = base_key
            total += ScorerConfig.EVIDENCE_WEIGHTS.get(key, 0.1)
        return total

    def _cap(self, key: str) -> float:
        return {"restricted_zone": ScorerConfig.CAP_ZONE,
                "monitoring_zone": ScorerConfig.CAP_ZONE,
                "loitering":       ScorerConfig.CAP_LOITERING,
                "re_entry":        ScorerConfig.CAP_REENTRY,
                "movement":        ScorerConfig.CAP_MOVEMENT}.get(key, 100.0)

    def _dominant(self) -> str:
        pos = {k: v for k, v in self.contributors.items() if v > 0 and k != "decay"}
        return max(pos, key=pos.get) if pos else "none"

    def top_contributors(self, n: int = 4) -> List[Tuple[str, float]]:
        return sorted(
            [(k, round(v, 1)) for k, v in self.contributors.items() if abs(v) > 0.5],
            key=lambda x: abs(x[1]), reverse=True
        )[:n]

    def dominant_signal_labels(self) -> List[str]:
        LABELS = {
            "restricted_zone": "Restricted Zone", "monitoring_zone": "Monitoring Zone",
            "loitering": "Loitering", "re_entry": "Re-entry",
            "movement": "Movement Pattern", "decay": "Risk Decay",
        }
        return [LABELS.get(s.split(":")[0], s) for s in self.active_signals][:3]

    def to_dict(self) -> Dict:
        return {
            "track_id": self.track_id, "cls": self.cls,
            "score": round(self.score, 1), "risk_level": self.risk_level,
            "peak_score": round(self.peak_score, 1), "peak_risk": self.peak_risk,
            "trend": self.trend, "active_signals": self.active_signals,
            "dominant_signals": self.dominant_signal_labels(),
            "contributors": {k: round(v, 1) for k, v in self.contributors.items()},
            "top_contributors": self.top_contributors(),
            "escalation_history": [{
                "video_ts": e.video_ts, "from_level": e.from_level,
                "to_level": e.to_level, "score": round(e.score, 1),
                "trigger": e.trigger, "direction": e.direction,
            } for e in self.escalation_history],
            "timeline": [{"ts": p.video_ts, "score": p.score, "level": p.risk_level,
                          "dominant": p.dominant, "marker": p.event_marker}
                         for p in self.timeline],
            "current_zone": self.current_zone,
            "zone_dwell_secs": round(self.zone_dwell_secs, 1),
            "incident_count": self.incident_count,
            "reentry_count": self.reentry_count,
            "color": RISK_COLOR[self.risk_level],
            "severity": RISK_SEVERITY[self.risk_level],
        }


class BehaviorScorer:
    def __init__(self, policy_registry=None):
        self._profiles: Dict[int, RiskProfile] = {}
        self._last_frame_time: float = time.time()
        self._reentry_times: Dict[int, float] = {}
        self._policy = policy_registry

    def score(
        self,
        stable_tracks:     List[Any],
        zone_results:      List[Any],
        loitering_signals: List[Any],
        frame_number:      int,
        timestamp:         float,
        movement_signals:  Optional[Dict[int, List[Any]]] = None,
    ) -> Tuple[Dict[int, RiskProfile], List[Dict]]:

        now = time.time()
        dt  = max(0.01, min(1.0, now - self._last_frame_time))
        self._last_frame_time = now

        escalations: List[Dict] = []
        active_ids = {t.track_id for t in stable_tracks}

        zone_map   = {zr.track_id: zr.inside_zones for zr in zone_results}
        loiter_map = {s.track_id: s for s in loitering_signals}
        mov_map    = movement_signals or {}

        for t in stable_tracks:
            if getattr(t, "frame_count", 0) < ScorerConfig.MIN_TRACK_AGE_FRAMES:
                continue

            profile = self._get_or_create(t)

            signals:      List[str]       = []
            frame_deltas: Dict[str,float] = {}
            marker:       Optional[str]   = None

            # ── Zone presence with independent dwell tracking ─────────────
            zones = zone_map.get(t.track_id, [])
            current_zone = zones[0]["zone_name"] if zones else None
            profile.current_zone = current_zone
            profile.update_zone_dwell(current_zone, dt)

            for z in zones:
                zname = z["zone_name"]
                ztype = z["zone_type"]
                # Suppress micro-overlaps
                if profile.zone_dwell_secs < ScorerConfig.MIN_ZONE_DWELL_SECONDS:
                    continue
                mult = self._policy.risk_multiplier(zname) if self._policy else (
                    2.0 if ztype == "restricted" else 1.2
                )
                if ztype == "restricted":
                    frame_deltas["restricted_zone"] = (
                        frame_deltas.get("restricted_zone", 0) +
                        ScorerConfig.BASE_ZONE_RESTRICTED * mult
                    )
                    signals.append(f"restricted_zone:{zname}")
                    if not any("zone_entry" in (p.event_marker or "") for p in profile.timeline[-3:]):
                        marker = "zone_entry"
                elif ztype in ("monitoring", "entry", "exit", "public_corridor"):
                    frame_deltas["monitoring_zone"] = (
                        frame_deltas.get("monitoring_zone", 0) +
                        ScorerConfig.BASE_ZONE_MONITORING * mult
                    )
                    signals.append(f"monitoring_zone:{zname}")

            # ── Context-aware loitering ───────────────────────────────────
            if t.track_id in loiter_map:
                sig = loiter_map[t.track_id]
                if sig.state in ("STARTED", "ACTIVE"):
                    zone_allows = True
                    if self._policy and profile.current_zone:
                        zone_allows = self._policy.is_loitering_suspicious(
                            profile.current_zone, t.cls, sig.dwell_seconds, True
                        )
                    if zone_allows:
                        mult = (self._policy.risk_multiplier(profile.current_zone)
                                if self._policy and profile.current_zone else 1.0)
                        frame_deltas["loitering"] = (
                            frame_deltas.get("loitering", 0) +
                            ScorerConfig.BASE_LOITERING * mult
                        )
                        signals.append(f"loitering:{sig.zone_name}")
                        if sig.state == "STARTED":
                            marker = "loitering"

            # ── Movement intelligence ─────────────────────────────────────
            for msig in mov_map.get(t.track_id, []):
                if msig.confidence < ScorerConfig.MIN_CONFIDENCE:
                    continue
                skey = f"mov:{msig.pattern}"
                if skey not in profile._signal_first_seen:
                    profile._signal_first_seen[skey] = timestamp
                elif timestamp - profile._signal_first_seen[skey] >= ScorerConfig.MIN_PERSISTENCE_SECONDS:
                    delta = ScorerConfig.BASE_MOVEMENT * msig.confidence * msig.score_contribution
                    frame_deltas["movement"] = frame_deltas.get("movement", 0) + delta
                    signals.append(f"movement:{msig.pattern}")

            # Clean stale persistence timers
            for skey in list(profile._signal_first_seen.keys()):
                if not any(skey.endswith(s.split(":")[-1]) for s in signals):
                    del profile._signal_first_seen[skey]

            # ── Refined re-entry (suppressed unless existing evidence) ─────
            if (hasattr(t, "state") and
                str(t.state) in ("RECOVERED", "TrackState.RECOVERED") and
                t.track_id not in self._reentry_times):
                self._reentry_times[t.track_id] = now
                profile.reentry_count += 1
                # Only contribute if track already has meaningful risk evidence
                if (profile.score >= ScorerConfig.REENTRY_MIN_SCORE and
                        profile.zone_dwell_secs >= ScorerConfig.REENTRY_MIN_ZONE_DWELL):
                    frame_deltas["re_entry"] = (
                        frame_deltas.get("re_entry", 0) +
                        ScorerConfig.BASE_REENTRY / max(dt, 0.1)
                    )
                    signals.append("re_entry")
                    marker = "re_entry"

            # ── Weighted evidence accumulation ────────────────────────────
            evidence = profile.compute_evidence(signals)
            profile._evidence_score = evidence
            profile.active_signals  = signals

            prev_level = profile.update_score(frame_deltas, dt, timestamp)

            if marker and profile.timeline:
                profile.timeline[-1].event_marker = marker

            # ── Escalation with evidence gate ─────────────────────────────
            if profile.risk_level != prev_level:
                direction = ("up" if self._level_order(profile.risk_level) >
                             self._level_order(prev_level) else "down")
                trigger   = self._build_trigger(profile, signals, direction)

                # Block upward escalation without sufficient evidence weight
                if (direction == "up" and
                        evidence < ScorerConfig.EVIDENCE_ESCALATION_THRESHOLD):
                    profile.risk_level = prev_level  # revert
                    profile._raw_score = min(
                        profile._raw_score,
                        {"elevated": ScorerConfig.SUSPICIOUS_THRESHOLD - 0.1,
                         "suspicious": ScorerConfig.CRITICAL_THRESHOLD - 0.1,
                         }.get(prev_level, profile._raw_score)
                    )
                else:
                    esc = EscalationEvent(
                        timestamp=now, video_ts=timestamp,
                        from_level=prev_level, to_level=profile.risk_level,
                        score=profile.score, trigger=trigger,
                        contributors=dict(profile.contributors),
                        direction=direction,
                    )
                    profile.escalation_history.append(esc)
                    if direction == "up" and profile.risk_level in (
                            RiskLevel.SUSPICIOUS, RiskLevel.CRITICAL):
                        profile.incident_count += 1
                        escalations.append(
                            self._make_event(profile, t, frame_number, timestamp, trigger)
                        )
                    elif direction == "down":
                        escalations.append(
                            self._make_deescalation_event(
                                profile, t, frame_number, timestamp, trigger
                            )
                        )

        # Decay absent tracks
        for tid in list(self._profiles.keys()):
            if tid not in active_ids:
                p = self._profiles[tid]
                decay = RiskLevel.decay_rate(p.risk_level) * 0.1
                floor = p._memory_floor
                p._raw_score = max(floor, p._raw_score - decay)
                p.score      = max(floor, p.score - decay * ScorerConfig.SMOOTH_ALPHA_FALL)
                p.risk_level = RiskLevel.from_score(p.score)
                p._memory_floor = max(0.0, p._memory_floor - ScorerConfig.MEMORY_DECAY_RATE * 0.1)
                if p.score <= 0 and p._memory_floor <= 0:
                    del self._profiles[tid]

        return dict(self._profiles), escalations

    def get_suspicious_tracks(self) -> List[Dict]:
        return sorted(
            [p.to_dict() for p in self._profiles.values()
             if p.score >= ScorerConfig.ELEVATED_THRESHOLD],
            key=lambda x: x["score"], reverse=True
        )

    def reset(self):
        self._profiles.clear()
        self._reentry_times.clear()

    def _get_or_create(self, track: Any) -> RiskProfile:
        if track.track_id not in self._profiles:
            self._profiles[track.track_id] = RiskProfile(
                track_id=track.track_id, cls=track.cls
            )
        return self._profiles[track.track_id]

    def _level_order(self, level: str) -> int:
        return {"normal": 0, "elevated": 1, "suspicious": 2, "critical": 3}.get(level, 0)

    def _build_trigger(self, profile: RiskProfile, signals: List[str], direction: str) -> str:
        labels = profile.dominant_signal_labels()
        if direction == "down":
            return f"De-escalated to {profile.risk_level.upper()} — risk cooling ({profile.score:.0f}/100)"
        if not labels:
            return f"Risk reached {profile.score:.0f}/100"
        return f"Escalated to {profile.risk_level.upper()} — " + " + ".join(labels[:2])

    def _make_event(self, profile: RiskProfile, track: Any,
                    frame_number: int, timestamp: float, trigger: str) -> Dict:
        return {
            "event_type": "suspicious_behavior",
            "frame_number": frame_number,
            "video_timestamp_seconds": timestamp,
            "confidence": profile.score / 100.0,
            "bounding_box": track.bbox,
            "extra_data": {
                "visible": True,
                "severity": RISK_SEVERITY[profile.risk_level],
                "track_id": profile.track_id,
                "risk_score": round(profile.score, 1),
                "risk_level": profile.risk_level,
                "trend": profile.trend,
                "active_signals": profile.active_signals,
                "dominant_signals": profile.dominant_signal_labels(),
                "contributors": {k: round(v, 1) for k, v in profile.contributors.items()},
                "top_contributors": profile.top_contributors(),
                "trigger": trigger,
                "escalation_history": [{
                    "video_ts": e.video_ts, "from": e.from_level, "to": e.to_level,
                    "score": round(e.score, 1), "trigger": e.trigger,
                    "direction": e.direction,
                } for e in profile.escalation_history],
                "reentry_count": profile.reentry_count,
                "zone_dwell_secs": round(profile.zone_dwell_secs, 1),
                "incident_count": profile.incident_count,
                "message": f"Track #{profile.track_id} {trigger}",
            }
        }

    def _make_deescalation_event(self, profile: RiskProfile, track: Any,
                                  frame_number: int, timestamp: float, trigger: str) -> Dict:
        ev = self._make_event(profile, track, frame_number, timestamp, trigger)
        ev["event_type"] = "risk_cooling"
        ev["extra_data"]["visible"] = False
        ev["extra_data"]["severity"] = "info"
        ev["extra_data"]["direction"] = "down"
        return ev
