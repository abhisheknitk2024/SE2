"""Configuration, read once at process start.

Twelve-factor: everything that differs between dev/test/prod is an environment
variable (prefix ``RELAY_``), never a code branch. Nothing here exists for a
feature that does not exist yet -- adding an unused knob is a guess, not a design.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RELAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"

    # Matches the cluster started by `make db` (scripts/dev_db.py) with no extra config.
    database_url: str = "postgresql://postgres@/postgres?host=/tmp/relay-pgdata"

    log_level: str = "INFO"

    # The pool is the only concurrency budget we have so far. Cap it explicitly:
    # an unbounded pool turns a slow database into an unbounded memory problem.
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
