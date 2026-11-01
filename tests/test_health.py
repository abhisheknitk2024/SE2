"""Chunk 0: the skeleton must boot, report health honestly, and fail in one shape."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from relay.app import create_app
from relay.config import Settings


def test_healthz_is_liveness_only(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_db_and_schema(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "ok", "schema_version": 1}


def test_liveness_and_readiness_disagree_when_db_is_down() -> None:
    """The whole point of splitting the probes.

    A pod whose database is unreachable must stay alive (no restart loop) while
    being pulled out of the load balancer. Same process, two answers.
    """
    broken = Settings(
        database_url="postgresql://postgres@/postgres?host=/nonexistent-relay-socket",
        env="test",
        log_level="WARNING",
    )
    with TestClient(create_app(broken)) as client:
        assert client.get("/healthz").status_code == 200

        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["status"] == "unavailable"
        assert ready.json()["db"] == "unavailable"


def test_readyz_refuses_traffic_when_schema_is_behind(client: TestClient, monkeypatch) -> None:
    """Deployed the app but forgot to migrate -> not ready, instead of 500s."""
    from relay import migrations

    monkeypatch.setattr(migrations, "EXPECTED_SCHEMA_VERSION", 99)

    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["db"] == "ok"
    assert body["schema_version"] == 1
    assert body["expected_schema_version"] == 99


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    first = client.get("/healthz")
    second = client.get("/healthz")
    assert first.headers["x-request-id"]
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_valid_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-Id": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"


def test_hostile_request_id_is_replaced_not_echoed(client: TestClient) -> None:
    hostile = "x" * 200
    response = client.get("/healthz", headers={"X-Request-Id": hostile})
    assert response.headers["x-request-id"] != hostile
    assert len(response.headers["x-request-id"]) == 32


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]


def test_unhandled_exception_is_opaque_and_enveloped(settings: Settings) -> None:
    """Internal detail goes to logs, never to the caller."""

    def boom() -> None:
        raise RuntimeError("connection string postgresql://user:hunter2@db leaked")

    app: FastAPI = create_app(settings)
    app.add_api_route("/boom", boom, methods=["GET"])

    # raise_server_exceptions=False: assert on what a real client would receive.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "internal server error"
    assert "hunter2" not in response.text
