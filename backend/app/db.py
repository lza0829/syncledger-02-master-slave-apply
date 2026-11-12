from __future__ import annotations

import sqlite3

from app.config import DB_FILENAME, data_dir


def connect() -> sqlite3.Connection:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(d / DB_FILENAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
