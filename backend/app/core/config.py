from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    APP_NAME: str = "AI Surveillance System"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    DATABASE_URL: str = "sqlite:///./surveillance.db"
    UPLOAD_DIR: str = "./uploads"
    RECORDINGS_DIR: str = "./recordings"
    FACES_DB_DIR: str = "./faces_db"
    MAX_UPLOAD_SIZE_MB: int = 500
    YOLO_MODEL: str = "yolov8n.pt"
    YOLO_CONFIDENCE: float = 0.45
    YOLO_DEVICE: str = "cpu"
    TARGET_CLASSES: List[str] = [
        "person", "car", "truck", "bus", "motorcycle",
        "bicycle", "backpack", "handbag", "suitcase", "bottle"
    ]
    FRAME_SKIP_IDLE: int = 10
    FRAME_SKIP_ACTIVE: int = 1
    IDLE_THRESHOLD_SECONDS: int = 30
    ACTIVITY_SCORE_THRESHOLD: float = 0.3
    FACE_RECOGNITION_ENABLED: bool = True
    FACE_MATCH_TOLERANCE: float = 0.6
    ALERT_COOLDOWN_SECONDS: int = 60

    class Config:
        env_file = ".env"

settings = Settings()
