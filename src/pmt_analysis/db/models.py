from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

TABLE_NAME = "measurements"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pmt_id          TEXT    NOT NULL,
    board_id        INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    run_id          TEXT    NOT NULL,
    measurement_time TEXT,
    dark_count_rate  REAL,
    spe_gain        REAL,
    after_pulse_probability REAL,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_measurements_pmt_id ON {TABLE_NAME}(pmt_id);
CREATE INDEX IF NOT EXISTS idx_measurements_run_id ON {TABLE_NAME}(run_id);
"""


@dataclass
class MeasurementRecord:
    pmt_id: str
    board_id: int
    channel_id: int
    run_id: str
    measurement_time: Optional[str] = None
    dark_count_rate: Optional[float] = None
    spe_gain: Optional[float] = None
    after_pulse_probability: Optional[float] = None
    notes: Optional[str] = None


COLUMN_RENAMES = {
    "dark_rate": "dark_count_rate",
    "gain": "spe_gain",
    "afterpulse_prob": "after_pulse_probability",
}

REQUIRED_COLUMNS = {
    "dark_count_rate": "REAL",
    "spe_gain": "REAL",
    "after_pulse_probability": "REAL",
    "notes": "TEXT",
}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cur = conn.execute(f"PRAGMA table_info({TABLE_NAME})")
    columns = {row[1] for row in cur.fetchall()}

    for old_name, new_name in COLUMN_RENAMES.items():
        if old_name in columns and new_name not in columns:
            conn.execute(
                f"ALTER TABLE {TABLE_NAME} RENAME COLUMN {old_name} TO {new_name}"
            )
            columns.discard(old_name)
            columns.add(new_name)

    for col_name, col_type in REQUIRED_COLUMNS.items():
        if col_name not in columns:
            conn.execute(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col_name} {col_type}"
            )

    conn.commit()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _migrate_schema(conn)
