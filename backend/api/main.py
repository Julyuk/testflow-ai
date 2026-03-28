"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

import asyncio

from backend.config.settings import settings
from backend.api.routes import sessions, pipeline, integrations
from backend.models.database import create_tables
import backend.events as ev


@asynccontextmanager
async def lifespan(app: FastAPI):
    ev.set_main_loop(asyncio.get_event_loop())
    create_tables()
    yield


app = FastAPI(
    title="TestFlow AI",
    description="AI-powered automated testing framework for web applications",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["Integrations"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
