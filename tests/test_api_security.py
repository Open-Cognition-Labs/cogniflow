"""Phase 4 baseline security: bearer-token auth, token-scoped access, rate limits, upload caps,
fail-loud misconfiguration. Exercises the Playground API with FastAPI's TestClient. None of these
need a running FalkorDB (every security check rejects BEFORE the backend is built) or an LLM.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

_MAIN = Path(__file__).resolve().parents[1] / "cogniflow-api" / "main.py"
_H = {"Authorization": "Bearer secret"}


def _load_main():
    spec = importlib.util.spec_from_file_location("cfapi_sec", _MAIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def secured():
    """The API with a token configured, so auth is enforced (not open/dev mode)."""
    main = _load_main()
    main._AUTH_TOKENS = {"secret"}
    main._AUTH_OPEN = False
    main._SESSIONS.clear()
    main._RATE.clear()
    return main


def test_health_is_public(secured) -> None:
    assert TestClient(secured.app).get("/api/health").status_code == 200


def test_protected_routes_401_without_token(secured) -> None:
    c = TestClient(secured.app)
    assert c.get("/api/plugins").status_code == 401
    assert c.post("/api/session").status_code == 401
    assert c.post("/api/answer", json={"session_id": "s", "query": "q"}).status_code == 401


def test_valid_token_allowed_and_bad_token_401(secured) -> None:
    c = TestClient(secured.app)
    assert c.get("/api/plugins", headers=_H).status_code == 200
    assert c.get("/api/plugins", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/plugins", headers={"Authorization": "secret"}).status_code == 401


def test_scoped_access_closes_the_day_one_hole(secured) -> None:
    # THE day-one vulnerability: a caller must NOT read or wipe a group it doesn't own.
    secured._AUTH_TOKENS = {"secret", "other"}
    c = TestClient(secured.app)
    sid = c.post("/api/session", headers=_H).json()["session_id"]  # owned by "secret"
    other = {"Authorization": "Bearer other"}
    assert c.post(f"/api/reset?session_id={sid}", headers=other).status_code == 403
    assert c.get(f"/api/audit/current?session_id={sid}", headers=other).status_code == 403
    # the owner is authorized (reaches the handler, not a 403)
    assert c.post(f"/api/reset?session_id={sid}", headers=_H).status_code == 200


def test_invalid_session_id_422(secured) -> None:
    c = TestClient(secured.app)
    assert c.post("/api/reset?session_id=bad%20id%21", headers=_H).status_code == 422


def test_upload_wrong_type_415(secured) -> None:
    r = TestClient(secured.app).post(
        "/api/ingest",
        data={"session_id": "s1"},
        files={"file": ("x.exe", b"data", "application/octet-stream")},
        headers=_H,
    )
    assert r.status_code == 415


def test_upload_too_large_413(secured) -> None:
    secured._MAX_UPLOAD = 100
    r = TestClient(secured.app).post(
        "/api/ingest",
        data={"session_id": "s2"},
        files={"file": ("x.txt", b"x" * 200, "text/plain")},
        headers=_H,
    )
    assert r.status_code == 413


def test_rate_limit_429(secured) -> None:
    secured._RATE.clear()
    secured._RATE_LIMIT = 2
    req = types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"))
    secured._rate_limit(req, None)
    secured._rate_limit(req, None)
    with pytest.raises(secured.HTTPException) as e:
        secured._rate_limit(req, None)
    assert e.value.status_code == 429


def test_safe_config_redacts_secrets(secured) -> None:
    safe = secured._safe_config(
        {"embedder": "bge-m3", "embedder_api_key": "sk-secret", "gen": {"api_key": "x"}}
    )
    assert safe["embedder_api_key"] == "***"  # never echo a provider key
    assert safe["embedder"] == "bge-m3"
    assert "gen" not in safe


def test_open_mode_runs_without_auth() -> None:
    # default env (no COGNIFLOW_API_TOKENS) -> open/dev mode; endpoints don't 401 (startup warned)
    main = _load_main()
    main._SESSIONS.clear()
    assert TestClient(main.app).get("/api/plugins").status_code == 200


def test_refuses_to_start_open_on_public_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    # fail-loud: unauthenticated + non-loopback bind must refuse to start, never silently open
    monkeypatch.setenv("COGNIFLOW_BIND_HOST", "0.0.0.0")
    monkeypatch.delenv("COGNIFLOW_API_TOKENS", raising=False)
    monkeypatch.delenv("COGNIFLOW_ALLOW_OPEN", raising=False)
    with pytest.raises(RuntimeError):
        _load_main()
