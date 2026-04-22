import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.database import init_db, close_db
from core.redis_client import RedisClient
from api.routes import jobs, workers, metrics
from api import websocket as ws_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    logger.info("Starting coordinator...")
    try:
        await init_db()
        logger.info("Database initialized")
        await ws_api.start_background_tasks()
        logger.info("WebSocket pub/sub listener started")
        yield
    finally:
        logger.info("Shutting down coordinator...")
        await ws_api.stop_background_tasks()
        await close_db()
        RedisClient.close()
        logger.info("Coordinator stopped")


app = FastAPI(
    title="Multimedia Distributed Coordinator",
    description="Distributed multimedia processing platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(workers.router)
app.include_router(metrics.router)
app.include_router(ws_api.router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "coordinator"}


@app.get("/")
async def root():
    """API root"""
    return {
        "name": "Multimedia Distributed Coordinator",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.coordinator_host,
        port=settings.coordinator_port,
        reload=settings.debug,
    )
