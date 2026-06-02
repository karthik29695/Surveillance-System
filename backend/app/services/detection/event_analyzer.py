import time
from typing import List, Dict, Optional
from collections import defaultdict

class EventAnalyzer:
    def __init__(self):
        self.previous_detections: Dict[str, List] = defaultdict(list)
        self.static_objects: Dict[str, Dict] = {}
        self.STATIC_THRESHOLD_SECONDS = 30

    def analyze(self, detections: List[Dict], frame_number: int, timestamp: float) -> List[Dict]:
        events = []
        curr_people = [d for d in detections if d["class"] == "person"]
        prev_people = self.previous_detections.get("person", [])

        if len(curr_people) > len(prev_people):
            events.append(self._make_event("person_appeared", "person", curr_people[-1], frame_number, timestamp))
        if len(curr_people) < len(prev_people) and prev_people:
            events.append(self._make_event("person_left", "person", prev_people[0], frame_number, timestamp))

        vehicle_classes = {"car", "truck", "bus", "motorcycle", "bicycle"}
        prev_vehicles = sum(len(self.previous_detections.get(c, [])) for c in vehicle_classes)
        curr_vehicles = [d for d in detections if d["class"] in vehicle_classes]
        if len(curr_vehicles) > prev_vehicles:
            events.append(self._make_event("vehicle_entered", curr_vehicles[-1]["class"], curr_vehicles[-1], frame_number, timestamp))

        if len(curr_people) >= 3:
            events.append(self._make_event("crowd_detected", "person", {"confidence": 1.0, "bbox": {}}, frame_number, timestamp, {"count": len(curr_people)}))

        unattended_classes = {"backpack", "handbag", "suitcase"}
        for det in detections:
            if det["class"] in unattended_classes:
                key = f"{det['class']}_{det['bbox']['x']//50}_{det['bbox']['y']//50}"
                if key in self.static_objects:
                    if timestamp - self.static_objects[key]["first_seen"] > self.STATIC_THRESHOLD_SECONDS:
                        events.append(self._make_event("object_left_behind", det["class"], det, frame_number, timestamp))
                        del self.static_objects[key]
                else:
                    self.static_objects[key] = {"first_seen": timestamp}

        for cls in set(d["class"] for d in detections):
            self.previous_detections[cls] = [d for d in detections if d["class"] == cls]

        return events

    def _make_event(self, event_type, entity, detection, frame_number, timestamp, extra=None):
        return {
            "event_type": event_type,
            "entity": entity,
            "frame_number": frame_number,
            "video_timestamp_seconds": timestamp,
            "confidence": detection.get("confidence", 1.0),
            "bounding_box": detection.get("bbox", {}),
            "metadata": extra or {},
        }

    def compute_activity_score(self, detections: List[Dict]) -> float:
        if not detections:
            return 0.0
        person_count = sum(1 for d in detections if d["class"] == "person")
        vehicle_count = sum(1 for d in detections if d["class"] in {"car", "truck", "bus"})
        return min(1.0, (person_count * 0.3) + (vehicle_count * 0.2) + (len(detections) * 0.05))
