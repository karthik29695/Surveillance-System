from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import video, stream, events, alerts, faces, zones, admin
from app.core.config import settings

app = FastAPI(
    title="AI Surveillance System",
    description="Intelligent video analytics platform with real-time detection",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(video.router, prefix="/api/v1/video", tags=["Video"])
app.include_router(stream.router, prefix="/api/v1/stream", tags=["Stream"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(faces.router, prefix="/api/v1/faces", tags=["Face Recognition"])
app.include_router(zones.router, prefix="/api/v1/zones", tags=["Zones"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
