"""Run the API with: ``PYTHONPATH=src:. python -m apps.api`` (from repo root)."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "apps.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["apps/api", "src"],
    )
