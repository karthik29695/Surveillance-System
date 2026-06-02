import cv2, os, time
from typing import Optional
from app.core.config import settings

class AdaptiveRecorder:
    def __init__(self):
        self.mode = "idle"
        self.last_activity_time = time.time()
        self.writer: Optional[cv2.VideoWriter] = None

    def should_process_frame(self, frame_number: int, activity_score: float) -> bool:
        if activity_score >= settings.ACTIVITY_SCORE_THRESHOLD:
            self.mode = "active"
            self.last_activity_time = time.time()
        elif time.time() - self.last_activity_time > settings.IDLE_THRESHOLD_SECONDS:
            self.mode = "idle"
        skip = settings.FRAME_SKIP_IDLE if self.mode == "idle" else settings.FRAME_SKIP_ACTIVE
        return (frame_number % (skip + 1)) == 0

    def start_recording(self, output_path: str, fps: float, width: int, height: int):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    def write_frame(self, frame):
        if self.writer and self.mode == "active":
            self.writer.write(frame)

    def stop_recording(self):
        if self.writer:
            self.writer.release()
            self.writer = None

    @property
    def current_mode(self) -> str:
        return self.mode
