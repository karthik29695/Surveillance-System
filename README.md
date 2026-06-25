# 👁️ SurveillanceAI — Intelligent Video Surveillance Platform

![Project Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg?style=for-the-badge&logo=fastapi)
![React](https://img.shields.io/badge/React-18-61dafb.svg?style=for-the-badge&logo=react)
![YOLOv8](https://img.shields.io/badge/YOLO-v8-yellow.svg?style=for-the-badge)

> *An end-to-end AI-powered surveillance system that transforms passive CCTV footage into actionable behavioral intelligence. Built from scratch with a layered intelligence architecture, real-time streaming, explainable risk scoring, and an operator-focused dashboard.*

---

## 🎯 What This Project Actually Does

SurveillanceAI processes live webcam/RTSP feeds and uploaded video files through a multi-stage intelligence pipeline. It doesn't just detect objects — it understands behavior. The system tracks individuals across frames, determines whether their behavior is suspicious given their context and location, explains *why* it reached that conclusion, and surfaces only meaningful security incidents to operators.

A person standing in a waiting area is not flagged. The same person standing motionless in a restricted zone for 20 seconds, then pacing, is escalated to CRITICAL with a full behavioral narrative explaining each contributing signal.

---

## 🧠 Intelligence Architecture

The core design principle is strict **layer separation** — each layer has exactly one responsibility and passes structured data to the next. No layer performs logic that belongs to another.

```text
Raw Frames
    │
    ▼
┌─────────────────────────────┐
│   YOLOv8 Object Detector    │  Raw detections: class, bbox, confidence
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   CentroidTracker (IoU)     │  Stable track IDs across frames
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Track Stabilization Layer │  State machine: NEW→ACTIVE→LOST→RECOVERED→TERMINATED
│                             │  Grace-period lifecycle, occlusion recovery
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Zone Intelligence         │  cv2.pointPolygonTest per track per zone
│   + Zone Policy Registry    │  Per-zone behavioral policy (thresholds, risk multipliers)
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Loitering Intelligence    │  Zone-aware temporal analysis
│                             │  Context: staff_area disables loitering,
│                             │  restricted zone fires at 12s, waiting area at 180s
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Movement Intelligence     │  Trajectory-based pattern detection:
│                             │  pacing, circling, hovering, erratic movement, running
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Behavior Scorer           │  Contextual weighted risk score (0–100)
│                             │  risk += base × zone_multiplier × confidence
│                             │  Contributor caps, exponential smoothing,
│                             │  risk memory floor, severity-based decay,
│                             │  weighted evidence gate (blocks single-signal escalation)
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Explainability Layer      │  Converts scores into human-readable reasoning:
│                             │  contributor breakdown, escalation history,
│                             │  risk timeline, behavioral narrative
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Event Intelligence Engine │  Lifecycle management: STARTED→ACTIVE→ENDED
│                             │  Cooldown registry, persistence validation,
│                             │  event aggregation, severity hierarchy
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│   Database + UI             │  Only visible security incidents persisted
│                             │  INFO/LOW tracking events suppressed
└─────────────────────────────┘
```

---

## ✨ Key Features

### 🧩 Behavioral Intelligence
- **Context-Aware Loitering** — Zone type determines whether stationary presence is suspicious. Seven zone types (Restricted, Monitoring, Entry, Exit, Staff Area, Waiting Area, Public Corridor) each carry independent thresholds, risk multipliers, and behavioral policies.
- **Movement Intelligence** — Trajectory analysis detects pacing, circling, hovering, erratic movement, and running. Signals require minimum confidence and must persist for configurable seconds before contributing to risk.
- **Suspicious Behavior Scoring** — Normalized 0–100 risk score built from multiple weighted signals. Escalation requires accumulated evidence across multiple signal types — a single re-entry or brief zone overlap cannot trigger a CRITICAL alert on its own.
- **Risk Memory** — Tracks that previously reached high risk levels decay toward a memory floor rather than resetting instantly, reflecting realistic behavioral persistence.

### 🛡️ Track Stabilization
- Five-state machine (NEW → ACTIVE → LOST → RECOVERED → TERMINATED) with configurable grace periods before exit events fire.
- Spatial proximity recovery — temporarily lost tracks that reappear nearby are recovered rather than spawning duplicate IDs and triggering false entry/exit events.
- Significantly reduces "Person Appeared" and "Person Left" noise in crowded scenes.

### 🗣️ Explainable AI
Every suspicious track comes with a full explanation:
```text
Track #13 — Risk Score: 84/100 [CRITICAL] ▲ escalating
Contributors:
  ⏱  Loitering              +41.2
  🚫  Restricted Zone        +22.8
  ↩️  Re-entry                +8.0
  📉  Risk Decay              -6.1

Escalation History:
  00:12 ↑ Escalated to ELEVATED — Restricted Zone Presence
  00:27 ↑ Escalated to SUSPICIOUS — Loitering + Restricted Zone
  00:41 ↑ Escalated to CRITICAL — Loitering + Restricted Zone + Re-entry
```

### 🔄 Event Lifecycle Management
- Every incident transitions through STARTED → ACTIVE → ENDED states
- Cooldown registry prevents event spam (crowd_detected: 10s cooldown, loitering: 30s)
- Persistence validation: behavior must be continuously true for N seconds before firing
- Severity hierarchy: INFO / LOW / MEDIUM / HIGH / CRITICAL controls what appears in the UI

### 📡 Live Stream Pipeline
- WebSocket-based live stream with full intelligence pipeline running in real-time
- Async YOLO inference in ThreadPoolExecutor so the frame loop is never blocked
- `LatestFrameBuffer` background thread — always holds only the newest frame, HLS burst frames discarded automatically
- Strict deadline-based frame pacing (no burst delivery)
- Achieves 25–30 FPS on local webcam, 15–20 FPS on network/HLS sources
- Compatible with webcam (integer index), RTSP streams, and YouTube HLS streams via yt-dlp
- In-app pipeline profiler showing per-stage millisecond breakdown

### 🎥 Annotated Video Output
- Full YOLO + tracking + zone overlays written to MP4 for uploaded footage
- Bounding boxes colored by risk level (gray → yellow → orange → red)
- Zone overlays with semi-transparent polygon fills
- HUD showing timestamp, frame number, activity score, adaptive recording mode
- Event banners at frame bottom: `LOITERING DETECTED #13 @ 14.2s`

### 🗺️ Zone Configuration UI
- Interactive polygon drawing directly on video frame preview
- Click to place vertices, visual dashed preview as polygon forms
- Seven zone types, each with a visible policy card explaining its behavior
- Zones stored persistently and auto-loaded when streams start
- Reprocess existing feeds with updated zones without re-uploading

### 👷 Operator / Developer Modes
- **Operator Mode** — Shows only meaningful security incidents (zone breach, loitering, crowd anomaly, suspicious behavior, object left behind). No tracking noise.
- **Developer Mode** — Raw event log with track IDs, lifecycle states, internal transitions, and debug overlays.

---

## 💻 Tech Stack

| Layer | Technology |
|---|---|
| Object Detection | YOLOv8 (ultralytics) |
| Deep Learning Runtime | PyTorch |
| Computer Vision | OpenCV |
| Backend Framework | FastAPI |
| Database | SQLAlchemy + SQLite |
| Real-time Streaming | WebSocket (FastAPI native) |
| Frontend Framework | React 18 + Vite |
| State Management | Zustand |
| Styling | Tailwind CSS |
| HTTP Client | Axios |

---

## 📂 Project Structure

```text
surveillance-system/
├── backend/
│   └── app/
│       ├── api/routes/
│       │   ├── video.py          # Upload, process, download, reprocess
│       │   ├── stream.py         # WebSocket live stream (v8)
│       │   ├── events.py         # Incident filtering API
│       │   ├── zones.py          # Zone CRUD
│       │   ├── alerts.py
│       │   ├── faces.py
│       │   └── admin.py          # DB management
│       ├── models/models.py      # SQLAlchemy table definitions
│       ├── schemas/schemas.py    # Pydantic I/O models
│       ├── core/
│       │   ├── config.py         # All settings via .env
│       │   └── database.py
│       └── services/
│           ├── detection/
│           │   ├── yolo_detector.py
│           │   ├── tracker.py                  # CentroidTracker
│           │   ├── track_stabilizer.py         # State machine
│           │   ├── zone_intelligence.py        # Spatial layer
│           │   ├── zone_policy.py              # Behavioral policies
│           │   ├── loitering_intelligence.py   # Temporal analysis
│           │   ├── movement_intelligence.py    # Trajectory patterns
│           │   ├── behavior_scorer.py          # Risk scoring
│           │   ├── explainability_layer.py     # Reasoning engine
│           │   └── event_intelligence_engine.py # Lifecycle management
│           ├── recording/
│           │   ├── annotated_writer.py         # Video rendering
│           │   └── adaptive_recorder.py
│           └── profiler.py                     # Pipeline profiler
└── frontend/
    └── src/
        ├── pages/
        │   ├── Dashboard.jsx          # Incident-focused KPI dashboard
        │   ├── VideoUpload.jsx        # Upload + processing management
        │   ├── VideoPlayer.jsx        # Annotated video player + timeline
        │   ├── LiveStream.jsx         # Real-time stream + risk profiles
        │   ├── EventTimeline.jsx      # Operator/Developer mode timeline
        │   ├── ZoneEditor.jsx         # Polygon zone drawing UI
        │   └── SuspectManager.jsx
        ├── components/
        │   ├── AlertBanner.jsx        # Fixed-position real-time alerts
        │   └── RiskIntelligencePanel.jsx  # Per-track risk explanation
        ├── store/surveillanceStore.js # Zustand global state
        ├── services/api.js            # Axios API client
        └── hooks/useStream.js
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- FFmpeg (for HLS/YouTube stream support)

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Initialize database
python -c "from app.core.database import engine, Base; from app.models import models; Base.metadata.create_all(bind=engine)"

# Start server
uvicorn app.main:app --reload --port 8000
```

API documentation available at `http://localhost:8000/docs`

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

App available at `http://localhost:3000`

### Live Stream Usage
```bash
# For YouTube live streams, get a fresh stream URL first
yt-dlp -g "https://youtube.com/watch?v=VIDEO_ID"
# Paste the output URL into the Live Stream source field
```

---

## 📈 How Risk Escalation Works

The system requires **multiple behavioral signals** before escalating a track. A single weak signal cannot trigger a CRITICAL alert.

| Scenario | Expected Outcome |
|---|---|
| Person walks through restricted zone | ELEVATED briefly, decays quickly |
| Person stands still in restricted zone | ELEVATED, persists |
| Person stands still + loitering confirmed | SUSPICIOUS |
| Person loitering + pacing movement | CRITICAL |
| Re-entry alone in crowded scene | No escalation (insufficient evidence) |
| Person in staff area, standing still | No alert (policy: loitering disabled) |
| Behavior stops, person leaves | Gradual cooldown: CRITICAL → SUSPICIOUS → ELEVATED → NORMAL |

Risk scores are smoothed (exponential weighted average) so they rise and fall gradually rather than spiking frame-to-frame.

---

## 🚨 Incident Severity Hierarchy

| Severity | Events | UI Visibility |
|---|---|---|
| 🔴 **CRITICAL** | Zone breach (restricted), Suspicious behavior | Alert banner + dashboard |
| 🟠 **HIGH**     | Loitering, Object left behind | Alert banner + dashboard |
| 🟡 **MEDIUM**   | Crowd detected, Zone breach (monitoring) | Dashboard + timeline |
| 🟢 **LOW**      | Vehicle entered, Re-entry | Timeline only |
| ⚪ **INFO**     | Person appeared, Track lifecycle | Developer mode only |

Only MEDIUM and above events are written to the database. Low-level tracking transitions are processed internally but never persisted or shown in the operator UI.

---

## ⏱️ Pipeline Performance

Measured on a standard CPU (no GPU):

| Source | Typical FPS | Notes |
|---|---|---|
| Local webcam | 25–30 FPS | Full intelligence pipeline |
| RTSP camera | 20–25 FPS | Network-dependent |
| YouTube HLS | 15–20 FPS | Via yt-dlp URL |

YOLO inference runs in a background `ThreadPoolExecutor` so the frame loop is never blocked. The `LatestFrameBuffer` always discards stale frames, ensuring real-time responsiveness over historical completeness.

The built-in pipeline profiler (accessible in the Live Stream UI) shows per-stage millisecond breakdowns in real time.

---

## 🤔 Design Decisions Worth Noting

**Why separate intelligence layers rather than one monolithic detector?**
Each layer has one responsibility and a clean interface. Adding a new behavior (e.g., crowd density heatmaps) means adding one new layer — nothing else changes. YOLO never needs to know about zones. The tracker never needs to know about loitering thresholds.

**Why suppress tracking events from the operator UI?**
In a busy scene, a naive system generates hundreds of "Person Appeared" and "Person Left" events per minute. These have zero operational value and bury the real incidents. The severity hierarchy ensures operators see only what matters.

**Why does a restricted zone alone not trigger CRITICAL?**
Because someone walking through a restricted zone quickly is different from someone standing there for 30 seconds while pacing. The weighted evidence system requires behavioral accumulation — the same design principle used in fraud detection systems.

**Why risk memory / decay floor?**
A person who scored 85 (CRITICAL) five minutes ago and has since left the area should not instantly return to 0. That would be behaviorally naive. The memory floor reflects realistic threat persistence and gives operators time to review before the system forgets.

---

## 🔮 Future Roadmap

- [ ] GPU inference support (CUDA)
- [ ] Crowd density heatmaps
- [ ] Path analysis and trajectory visualization
- [ ] Suspect face recognition pipeline (architecture already stubbed)
- [ ] PDF incident reports export
- [ ] Multi-camera unified dashboard
- [ ] PostgreSQL + Redis for production deployment
- [ ] Restricted zone breach email/webhook notifications
