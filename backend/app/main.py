import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import API_PREFIX, APP_NAME, FRONTEND_DIST
from .database import init_database
from .summary.tasks import cleanup_expired_summary_tasks
from .tasks import cleanup_expired_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    cleanup_task = asyncio.create_task(cleanup_expired_tasks())
    summary_cleanup_task = asyncio.create_task(cleanup_expired_summary_tasks())
    yield
    cleanup_task.cancel()
    summary_cleanup_task.cancel()


app = FastAPI(title=APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=API_PREFIX)

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
