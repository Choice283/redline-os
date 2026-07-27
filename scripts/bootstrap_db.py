#!/usr/bin/env python3
"""Create (or upgrade) the Redline OS SQLite database.

Usage:
    python scripts/bootstrap_db.py [path/to/redline.db]

Defaults to REDLINE_DB_PATH from the environment, or ./redline.db.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redline_core.db.database import Database  # noqa: E402


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REDLINE_DB_PATH", "./redline.db")
    print(f"Bootstrapping Redline OS database at: {db_path}")
    db = Database(db_path).connect()
    db.init_schema()
    db.close()
    print("Done.")


if __name__ == "__main__":
    main()
