"""Run once to create all database tables."""
import sys; sys.path.insert(0, "..")
from backend.app.core.database import engine, Base
from backend.app.models import models  # noqa - imports tables
Base.metadata.create_all(bind=engine)
print("Database initialized.")
