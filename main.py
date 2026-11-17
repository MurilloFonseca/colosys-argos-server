import asyncio
from _asyncio import Task
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import NoReturn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import client, criar_indices
from app.live import loop_trilhos, olho_vivo
from app.routers import auth, favoritos, linhas, relatos, tempo_real, trajetos


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await criar_indices()

    tarefa: Task[NoReturn] | None = (
        asyncio.create_task(loop_trilhos()) if settings.trilhos_api_key else None
    )

    yield

    if tarefa:
        tarefa.cancel()

    await olho_vivo.http.aclose()
    await client.close()


app = FastAPI(title="Colosys Argos", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, linhas, trajetos, tempo_real, favoritos, relatos):
    app.include_router(r.router)

@app.get("/health", tags=["geral"])
async def health() -> dict[str, bool]:
    return {"ok": True}
