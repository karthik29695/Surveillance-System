import os, pickle
import numpy as np
from typing import List, Dict
from app.core.config import settings

class FaceRecognitionService:
    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_names: List[str] = []
        self.known_ids: List[int] = []
        self._load_database()

    def _load_database(self):
        db_path = os.path.join(settings.FACES_DB_DIR, "encodings.pkl")
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                data = pickle.load(f)
                self.known_encodings = data.get("encodings", [])
                self.known_names = data.get("names", [])
                self.known_ids = data.get("ids", [])

    def _save_database(self):
        os.makedirs(settings.FACES_DB_DIR, exist_ok=True)
        db_path = os.path.join(settings.FACES_DB_DIR, "encodings.pkl")
        with open(db_path, "wb") as f:
            pickle.dump({"encodings": self.known_encodings, "names": self.known_names, "ids": self.known_ids}, f)

    def add_suspect(self, profile_id: int, name: str, image_path: str) -> bool:
        try:
            import face_recognition
            image = face_recognition.load_image_file(image_path)
            encodings = face_recognition.face_encodings(image)
            if not encodings:
                return False
            self.known_encodings.append(encodings[0])
            self.known_names.append(name)
            self.known_ids.append(profile_id)
            self._save_database()
            return True
        except Exception as e:
            print(f"[FaceService] Error: {e}")
            return False

    def recognize_faces(self, frame: np.ndarray) -> List[Dict]:
        if not settings.FACE_RECOGNITION_ENABLED or not self.known_encodings:
            return []
        try:
            import face_recognition
            rgb = frame[:, :, ::-1]
            locations = face_recognition.face_locations(rgb)
            encodings = face_recognition.face_encodings(rgb, locations)
            results = []
            for enc, loc in zip(encodings, locations):
                distances = face_recognition.face_distance(self.known_encodings, enc)
                best_idx = int(np.argmin(distances))
                top, right, bottom, left = loc
                matched = distances[best_idx] <= settings.FACE_MATCH_TOLERANCE
                results.append({
                    "matched": matched,
                    "profile_id": self.known_ids[best_idx] if matched else None,
                    "name": self.known_names[best_idx] if matched else "Unknown",
                    "confidence": float(1 - distances[best_idx]) if matched else 0.0,
                    "bbox": {"x": left, "y": top, "w": right-left, "h": bottom-top},
                })
            return results
        except Exception as e:
            print(f"[FaceService] Error: {e}")
            return []
