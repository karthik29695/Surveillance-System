"""
Zone Policy System — Phase 1: Context-Aware Loitering
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional

ZONE_TYPE_DEFAULTS = {
    "restricted":     {"loitering_enabled":True,  "loiter_threshold_seconds":12.0,  "risk_multiplier":2.0,  "allowed_stationary_presence":False, "expected_behavior":"transit_only"},
    "monitoring":     {"loitering_enabled":True,  "loiter_threshold_seconds":25.0,  "risk_multiplier":1.2,  "allowed_stationary_presence":False, "expected_behavior":"monitored_transit"},
    "entry":          {"loitering_enabled":True,  "loiter_threshold_seconds":40.0,  "risk_multiplier":0.8,  "allowed_stationary_presence":False, "expected_behavior":"brief_transit"},
    "exit":           {"loitering_enabled":True,  "loiter_threshold_seconds":40.0,  "risk_multiplier":0.8,  "allowed_stationary_presence":False, "expected_behavior":"brief_transit"},
    "staff_area":     {"loitering_enabled":False, "loiter_threshold_seconds":300.0, "risk_multiplier":0.1,  "allowed_stationary_presence":True,  "expected_behavior":"staff_presence"},
    "waiting_area":   {"loitering_enabled":False, "loiter_threshold_seconds":180.0, "risk_multiplier":0.2,  "allowed_stationary_presence":True,  "expected_behavior":"waiting_expected"},
    "public_corridor":{"loitering_enabled":True,  "loiter_threshold_seconds":45.0,  "risk_multiplier":0.6,  "allowed_stationary_presence":False, "expected_behavior":"normal_transit"},
}

@dataclass
class ZonePolicy:
    zone_name:                  str
    zone_type:                  str
    loitering_enabled:          bool  = True
    loiter_threshold_seconds:   float = 20.0
    risk_multiplier:            float = 1.0
    allowed_stationary_presence:bool  = False
    expected_behavior:          str   = "transit"
    allowed_object_classes:     List[str] = field(default_factory=list)

    @classmethod
    def from_zone_dict(cls, zone: Dict) -> "ZonePolicy":
        ztype    = zone.get("zone_type", "monitoring")
        defaults = ZONE_TYPE_DEFAULTS.get(ztype, ZONE_TYPE_DEFAULTS["monitoring"])
        override = zone.get("policy") or {}
        return cls(
            zone_name=zone.get("zone_name","unknown"),
            zone_type=ztype,
            loitering_enabled=override.get("loitering_enabled", defaults["loitering_enabled"]),
            loiter_threshold_seconds=override.get("loiter_threshold_seconds", defaults["loiter_threshold_seconds"]),
            risk_multiplier=override.get("risk_multiplier", defaults["risk_multiplier"]),
            allowed_stationary_presence=override.get("allowed_stationary_presence", defaults["allowed_stationary_presence"]),
            expected_behavior=override.get("expected_behavior", defaults["expected_behavior"]),
            allowed_object_classes=override.get("allowed_object_classes", []),
        )

    def is_loitering_suspicious(self, cls: str, dwell: float, stationary: bool) -> bool:
        if not self.loitering_enabled:            return False
        if self.allowed_stationary_presence:      return False
        if self.allowed_object_classes and cls not in self.allowed_object_classes: return False
        return stationary and dwell >= self.loiter_threshold_seconds

    def to_dict(self) -> Dict:
        return {"zone_name":self.zone_name,"zone_type":self.zone_type,
                "loitering_enabled":self.loitering_enabled,
                "loiter_threshold_seconds":self.loiter_threshold_seconds,
                "risk_multiplier":self.risk_multiplier,
                "allowed_stationary_presence":self.allowed_stationary_presence,
                "expected_behavior":self.expected_behavior}

class ZonePolicyRegistry:
    def __init__(self, zone_dicts: List[Dict]):
        self._p: Dict[str, ZonePolicy] = {
            z.get("zone_name",""): ZonePolicy.from_zone_dict(z) for z in zone_dicts
        }

    def get(self, name: str) -> Optional[ZonePolicy]:
        return self._p.get(name)

    def risk_multiplier(self, name: str) -> float:
        p = self._p.get(name); return p.risk_multiplier if p else 1.0

    def is_loitering_suspicious(self, zone_name: str, cls: str, dwell: float, stationary: bool) -> bool:
        p = self._p.get(zone_name)
        if not p: return stationary and dwell >= 20.0
        return p.is_loitering_suspicious(cls, dwell, stationary)

    def reload(self, zone_dicts: List[Dict]): self.__init__(zone_dicts)
