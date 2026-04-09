"""main.py - PresalesAI Platform Backend"""
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Add parent to path for agent modules
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from database.connection import init_db, close_db
from api.routes.auth import router as auth_router
from api.routes.clients import router as clients_router
from api.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    for d in [settings.upload_dir, settings.proposal_dir, settings.chroma_persist_dir]:
        Path(d).mkdir(parents=True, exist_ok=True)
    await init_db()
    try:
        from models.router import get_llm_client
        get_llm_client()
        logger.info("LLM client ready")
    except Exception as e:
        logger.warning(f"LLM init: {e}")
    logger.info("Platform ready ✓")
    yield
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI Presales Platform with Zoho Solution Mapping",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list,
                    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

PREFIX = "/api/v1"
app.include_router(auth_router, prefix=PREFIX)
app.include_router(clients_router, prefix=PREFIX)
app.include_router(chat_router, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": settings.app_version}


@app.get("/")
async def root():
    return {"name": settings.app_name, "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
