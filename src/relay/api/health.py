"""Operational endpoints.

Two probes, two questions -- conflating them is a classic outage amplifier:

* ``/healthz``  (liveness): is this process alive? Must not touch the database.
  If it did, a 30-second database blip would make the orchestrator kill every API
  process at once, turning a slow dependency into a total outage.
* ``/readyz``   (readiness): can this process serve traffic right now? Checks the
  database *and* that the schema is the version this build expects. A pod that
  starts before migrations finish should be pulled out of the load balancer, not
  crash-loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from relay import migrations
from relay.log import get_logger

log = get_logger("relay.health")

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    db = request.app.state.db
    try:
        version = db.schema_version(timeout=1.0)
    except Exception:
        # Expected and temporary (restart, failover). A warning, not an error:
        # an alert on this line would page someone for a routine deploy.
        log.warning("readyz.database_unavailable", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "db": "unavailable", "schema_version": None},
        )

    if version != migrations.EXPECTED_SCHEMA_VERSION:
        log.warning(
            "readyz.schema_out_of_date",
            extra={"applied": version, "expected": migrations.EXPECTED_SCHEMA_VERSION},
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "db": "ok",
                "schema_version": version,
                "expected_schema_version": migrations.EXPECTED_SCHEMA_VERSION,
            },
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "db": "ok", "schema_version": version},
    )
