"""Database helpers: a cached SQLAlchemy engine plus a couple of utilities
for running .sql files and round-tripping DataFrames to PostgreSQL.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

import config

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine for the project database."""
    engine = create_engine(config.sqlalchemy_url(), pool_pre_ping=True)
    return engine


def ping() -> bool:
    """Return True if the database is reachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Database not reachable: %s", exc)
        return False


def run_sql_file(path: str | Path) -> None:
    """Execute every statement in a .sql file against the database."""
    run_sql_file_text(Path(path).read_text())
    log.info("Executed SQL file: %s", path)


def run_sql_file_text(sql: str) -> None:
    """Execute every statement in a SQL string against the database."""
    with get_engine().begin() as conn:
        for statement in _split_statements(sql):
            if statement.strip():
                conn.execute(text(statement))


def _split_statements(sql: str) -> list[str]:
    """Naive splitter on semicolons that ignores comment-only fragments."""
    cleaned = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [s for s in cleaned.split(";") if s.strip()]


def read_sql(query: str) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn)


def write_df(df: pd.DataFrame, table: str, if_exists: str = "replace") -> int:
    """Write a DataFrame to a table; returns the number of rows written."""
    df.to_sql(table, get_engine(), if_exists=if_exists, index=False,
              method="multi", chunksize=10_000)
    log.info("Wrote %s rows -> %s", len(df), table)
    return len(df)
