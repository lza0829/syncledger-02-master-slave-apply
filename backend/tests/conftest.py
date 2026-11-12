from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Fresh DATA_DIR per test: DB + working fixtures materialized from seeds."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.delenv("FIXTURES_DIR", raising=False)
    from app.seed import init_db

    init_db()
    return data_dir


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def pair_id_by_code(client, code: str) -> int:
    pairs = client.get("/api/pairs").json()
    return next(p["id"] for p in pairs if p["code"] == code)


def reconcile(client, pair_code: str) -> dict:
    resp = client.post("/api/reconcile", json={"pair_id": pair_id_by_code(client, pair_code)})
    assert resp.status_code == 200, resp.text
    return resp.json()
