"""Multi-format export endpoints (markdown, json, html).

Stub router -- endpoints implemented in Task 2.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["export"])
