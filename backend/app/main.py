from fastapi import FastAPI

from .database import Base, engine
from . import models

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RecoverAI",
    description="AI Revenue Recovery Agent",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}