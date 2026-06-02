"""
Explainability Layer
====================
Sits between BehaviorScorer and EIE/UI rendering.

Consumes RiskProfile data and produces human-readable structured
reasoning objects: RiskExplanation.

Does not score, detect, or persist. Only interprets and structures.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


CONTRIBUTOR_LABELS = {
    "restricted_zone":  "Restricted Zone Presence",
    "monitoring_zone":  "Monitoring Zone Presence",
    "loitering":        "Loitering Behavior",
    "re_entry":         "Suspicious Re-entry",
    "erratic_movement": "Erratic Movement Pattern",
    "crowd":            "Crowd Association",
    "decay":            "Risk Decay",
}

CONTRIBUTOR_ICONS = {
    "restricted_zone":  "🚫",
    "monitoring_zone":  "👁",
    "loitering":        "⏱",
    "re_entry":         "↩️",
    "erratic_movement": "↗️",
    "crowd":            "👥",
    "decay":            "📉",
}

TREND_ICONS = {
    "escalating": "▲",
    "cooling":    "▼",
    "stable":     "■",
}

TREND_COLORS = {
    "escalating": "text-red-400",
    "cooling":    "text-green-400",
    "stable":     "text-gray-400",
}


@dataclass
class ContributorEntry:
    key:    str
    label:  str
    icon:   str
    value:  float    # cumulative contribution
    is_positive: bool

    def to_dict(self) -> Dict:
        return {
            "key":         self.key,
            "label":       self.label,
            "icon":        self.icon,
            "value":       self.value,
            "is_positive": self.is_positive,
            "sign":        "+" if self.is_positive else "−",
        }


@dataclass
class EscalationEntry:
    video_ts:   float
    from_level: str
    to_level:   str
    score:      float
    trigger:    str

    def to_dict(self) -> Dict:
        mins  = int(self.video_ts // 60)
        secs  = int(self.video_ts % 60)
        ts_str = f"{mins:02d}:{secs:02d}"
        direction = "↑" if self._level_order(self.to_level) > self._level_order(self.from_level) else "↓"
        return {
            "ts_str":     ts_str,
            "video_ts":   self.video_ts,
            "from_level": self.from_level,
            "to_level":   self.to_level,
            "score":      self.score,
            "trigger":    self.trigger,
            "direction":  direction,
        }

    @staticmethod
    def _level_order(level: str) -> int:
        return {"normal":0,"elevated":1,"suspicious":2,"critical":3}.get(level,0)


@dataclass
class RiskExplanation:
    """
    Structured behavioral narrative for a single track.
    Consumed by UI and EIE for display and logging.
    """
    track_id:         int
    cls:              str
    score:            float
    risk_level:       str
    trend:            str
    trend_icon:       str
    trend_color:      str

    # Human-readable summary sentence
    summary:          str

    # Contributor breakdown (sorted by abs value)
    contributors:     List[ContributorEntry]

    # Escalation log
    escalations:      List[EscalationEntry]

    # Timeline points for chart rendering
    timeline:         List[Dict]    # [{ts, score, level, dominant, marker}]

    # Operational fields
    dominant_signals: List[str]
    current_zone:     Optional[str]
    zone_dwell_secs:  float
    incident_count:   int
    peak_score:       float
    reentry_count:    int
    color:            str

    def to_dict(self) -> Dict:
        return {
            "track_id":        self.track_id,
            "cls":             self.cls,
            "score":           self.score,
            "risk_level":      self.risk_level,
            "trend":           self.trend,
            "trend_icon":      self.trend_icon,
            "trend_color":     self.trend_color,
            "summary":         self.summary,
            "contributors":    [c.to_dict() for c in self.contributors],
            "escalations":     [e.to_dict() for e in self.escalations],
            "timeline":        self.timeline,
            "dominant_signals":self.dominant_signals,
            "current_zone":    self.current_zone,
            "zone_dwell_secs": self.zone_dwell_secs,
            "incident_count":  self.incident_count,
            "peak_score":      self.peak_score,
            "reentry_count":   self.reentry_count,
            "color":           self.color,
        }


class ExplainabilityLayer:
    """
    Converts RiskProfile objects into RiskExplanation objects.
    Call explain() each frame for elevated tracks only (score >= 25).
    """

    def explain(self, profiles: Dict[int, Any]) -> Dict[int, RiskExplanation]:
        """Returns RiskExplanation for each elevated track."""
        explanations: Dict[int, RiskExplanation] = {}
        for track_id, profile in profiles.items():
            if profile.score < 25.0:
                continue
            explanations[track_id] = self._build(profile)
        return explanations

    def explain_one(self, profile: Any) -> RiskExplanation:
        return self._build(profile)

    def _build(self, profile: Any) -> RiskExplanation:
        contributors = self._build_contributors(profile)
        escalations  = self._build_escalations(profile)
        summary      = self._build_summary(profile, contributors)
        trend        = getattr(profile, "trend", "stable")

        return RiskExplanation(
            track_id=profile.track_id,
            cls=profile.cls,
            score=round(profile.score, 1),
            risk_level=profile.risk_level,
            trend=trend,
            trend_icon=TREND_ICONS.get(trend, "■"),
            trend_color=TREND_COLORS.get(trend, "text-gray-400"),
            summary=summary,
            contributors=contributors,
            escalations=escalations,
            timeline=getattr(profile, "timeline", []),
            dominant_signals=profile.dominant_signal_labels() if hasattr(profile, "dominant_signal_labels") else [],
            current_zone=getattr(profile, "current_zone", None),
            zone_dwell_secs=round(getattr(profile, "zone_dwell_secs", 0), 1),
            incident_count=getattr(profile, "incident_count", 0),
            peak_score=round(getattr(profile, "peak_score", profile.score), 1),
            reentry_count=getattr(profile, "reentry_count", 0),
            color=getattr(profile, "color", "#ef4444") if hasattr(profile, "color")
                  else {"normal":"#4b5563","elevated":"#eab308","suspicious":"#f97316","critical":"#ef4444"}.get(profile.risk_level,"#ef4444"),
        )

    def _build_contributors(self, profile: Any) -> List[ContributorEntry]:
        raw = getattr(profile, "contributors", {})
        entries = []
        for key, value in raw.items():
            if abs(value) < 0.5:
                continue
            entries.append(ContributorEntry(
                key=key,
                label=CONTRIBUTOR_LABELS.get(key, key.replace("_"," ").title()),
                icon=CONTRIBUTOR_ICONS.get(key, "•"),
                value=round(abs(value), 1),
                is_positive=(key != "decay"),
            ))
        return sorted(entries, key=lambda e: (-e.value if e.is_positive else e.value), reverse=False)

    def _build_escalations(self, profile: Any) -> List[EscalationEntry]:
        raw = getattr(profile, "escalation_history", [])
        result = []
        for e in raw:
            if hasattr(e, "video_ts"):
                result.append(EscalationEntry(
                    video_ts=e.video_ts, from_level=e.from_level,
                    to_level=e.to_level, score=round(e.score,1), trigger=e.trigger,
                ))
            elif isinstance(e, dict):
                result.append(EscalationEntry(
                    video_ts=e.get("video_ts",0), from_level=e.get("from_level",""),
                    to_level=e.get("to_level",""), score=e.get("score",0), trigger=e.get("trigger",""),
                ))
        return result

    def _build_summary(self, profile: Any, contributors: List[ContributorEntry]) -> str:
        level  = profile.risk_level.upper()
        score  = round(profile.score, 1)
        trend  = getattr(profile, "trend", "stable")
        labels = [c.label for c in contributors if c.is_positive][:2]

        trend_phrase = {
            "escalating": "and escalating",
            "cooling":    "but cooling down",
            "stable":     "",
        }.get(trend, "")

        if not labels:
            return f"Track #{profile.track_id} risk score {score}/100 [{level}] {trend_phrase}".strip()

        reason = " and ".join(labels)
        return f"Track #{profile.track_id} flagged {trend_phrase} — {reason}. Risk: {score}/100 [{level}]".strip()
