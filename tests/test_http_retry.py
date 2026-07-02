"""The transient-status backoff on the NVIDIA callers (generator/reranker) - CI-safe, no
network, no real sleeping. Hosted APIs rate-limit (429); a burst must not fail the call.
"""

from __future__ import annotations

import io
import urllib.error

import pytest

from cogniflow.generators import _urlopen_json


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


def test_retries_then_succeeds_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None) # no real backoff wait
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return _FakeResp(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert _urlopen_json(object(), 10, attempts=5) == {"ok": True}
    assert calls["n"] == 3 # failed twice, succeeded on the third


def test_non_retryable_status_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        raise _http_error(400) # a client error is not transient - do not retry

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        _urlopen_json(object(), 10, attempts=5)
    assert calls["n"] == 1 # tried once, no retry


def test_gives_up_after_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        raise _http_error(503)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        _urlopen_json(object(), 10, attempts=3)
    assert calls["n"] == 3 # exhausted all attempts, then raised
