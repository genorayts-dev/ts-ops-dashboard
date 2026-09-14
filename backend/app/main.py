from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import annotations, asdash, dashboard, gsheet, ingest, maps, plan, recv

app = FastAPI(title="TS본부 운영 대시보드 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(dashboard.router)
app.include_router(maps.router)
app.include_router(asdash.router)
app.include_router(gsheet.router)
app.include_router(annotations.router)
app.include_router(plan.router)
app.include_router(recv.router)


@app.get("/api/health")
def health():
    return {"ok": True, "parser_version": settings.parser_version}
