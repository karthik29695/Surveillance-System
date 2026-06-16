# AI-Powered Intelligent Surveillance System

Intelligent video analytics platform combining YOLO object detection, adaptive recording, and face recognition.

## Tech Stack
- **Backend**: FastAPI, SQLAlchemy, OpenCV, YOLOv8 (ultralytics), face_recognition
- **Frontend**: React 18, Vite, Tailwind CSS, Zustand, Recharts
- **DB**: SQLite (swap to PostgreSQL for production)

## Project Structure
```
surveillance-system/
├── backend/
│   └── app/
│       ├── main.py                         # FastAPI app entry point
│       ├── core/config.py                  # All settings via .env
│       ├── core/database.py                # SQLAlchemy engine + session
│       ├── models/models.py                # DB table definitions
│       ├── schemas/schemas.py              # Pydantic request/response models
│       ├── api/routes/
│       │   ├── video.py                    # Upload & process video
│       │   ├── stream.py                   # WebSocket live stream
│       │   ├── events.py                   # Query detection events
│       │   ├── alerts.py                   # Alert management
│       │   └── faces.py                    # Suspect profiles
│       └── services/
│           ├── detection/yolo_detector.py  # YOLOv8 inference
│           ├── detection/event_analyzer.py # Raw detections → events
│           ├── recording/adaptive_recorder.py  # Smart frame skipping
│           └── face_recognition/face_service.py
├── frontend/
│   └── src/
│       ├── pages/Dashboard.jsx
│       ├── pages/VideoUpload.jsx
│       ├── pages/LiveStream.jsx
│       ├── pages/EventTimeline.jsx
│       ├── pages/SuspectManager.jsx
│       ├── store/surveillanceStore.js      # Zustand global state
│       ├── services/api.js                 # Axios API client
│       └── hooks/useStream.js              # WebSocket stream hook
└── scripts/
    ├── init_db.py
    └── start_dev.sh
```

## Quick Start

### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python ../scripts/init_db.py
uvicorn app.main:app --reload --port 8000
```
API docs at http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
npm run dev
```
App at http://localhost:3000

## Key Features Implemented

| Feature | Status | File |
|---|---|---|
| Video upload + background processing | ✅ | `routes/video.py` |
| YOLO object detection | ✅ | `services/detection/yolo_detector.py` |
| Event analysis (appeared/left/crowd/object) | ✅ | `services/detection/event_analyzer.py` |
| Adaptive frame skipping | ✅ | `services/recording/adaptive_recorder.py` |
| Face recognition (suspect DB) | ✅ | `services/face_recognition/face_service.py` |
| Live WebSocket stream | ✅ | `routes/stream.py` |
| Dashboard + Timeline UI | ✅ | `pages/` |
| Annotated video output (MP4 writing) | ✅ | `services/recording/annotated_writer.py` |

## Next Modules to Build
- [ ] Loitering detection (track person dwell time per zone)
- [ ] Restricted area breach (define polygon zones, trigger on entry)
- [ ] Email/webhook alert delivery
- [ ] PostgreSQL + Redis for production scale
- [ ] Camera grid view (multi-feed dashboard)
