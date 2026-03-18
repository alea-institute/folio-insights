"""FastAPI backend for folio-insights Review Viewer."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.db.session import get_db
from api.routes import corpus, review, source, tree, upload

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load extraction data on startup."""
    load_extraction()
    yield


app = FastAPI(title="folio-insights Review Viewer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8700"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tree.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
app.include_router(source.router, prefix="/api/v1")
app.include_router(corpus.router)
app.include_router(upload.router)

# ---------------------------------------------------------------------------
# In-memory extraction data store
# ---------------------------------------------------------------------------

_extraction_data: dict[str, dict[str, Any]] = {}
_output_dir: Path = Path("./output")
_default_corpus: str = "default"


def configure(output_dir: Path | str | None = None, corpus_name: str | None = None) -> None:
    """Configure the server before startup (used by CLI and tests)."""
    global _output_dir, _default_corpus
    if output_dir is not None:
        _output_dir = Path(output_dir)
    if corpus_name is not None:
        _default_corpus = corpus_name


def load_extraction(corpus: str | None = None) -> dict[str, Any]:
    """Load extraction JSON from disk into memory.

    Returns the loaded data dict.
    """
    corpus = corpus or _default_corpus
    extraction_path = _output_dir / corpus / "extraction.json"
    if extraction_path.exists():
        data = json.loads(extraction_path.read_text(encoding="utf-8"))
    else:
        data = {"corpus": corpus, "units": [], "total_units": 0}
    _extraction_data[corpus] = data
    return data


def get_extraction_data(corpus: str | None = None) -> dict[str, Any]:
    """Return extraction data for *corpus*, loading from disk if needed."""
    corpus = corpus or _default_corpus
    if corpus not in _extraction_data:
        load_extraction(corpus)
    return _extraction_data[corpus]


def set_extraction_data(corpus: str, data: dict[str, Any]) -> None:
    """Directly inject extraction data (used by tests)."""
    _extraction_data[corpus] = data


async def get_db_for_corpus(corpus: str | None = None) -> aiosqlite.Connection:
    """Return an aiosqlite connection for the given corpus."""
    corpus = corpus or _default_corpus
    db_path = _output_dir / corpus / "review.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return await get_db(db_path)


# ---------------------------------------------------------------------------
# Mount SvelteKit build (if available)
# ---------------------------------------------------------------------------

_viewer_build = Path(__file__).resolve().parent.parent / "viewer" / "build"
if _viewer_build.is_dir():
    app.mount("/", StaticFiles(directory=str(_viewer_build), html=True), name="viewer")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def serve(host: str = "0.0.0.0", port: int = 8700) -> None:
    """Start the review viewer server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    serve()
