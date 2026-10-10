#!/usr/bin/env python3
"""Звіт навчання на історії Office2. Джерело: fixtures/learning/*.json (знімок production) або --db (DATABASE_URL/OFFICE_DB_PATH). Нічого не змінює."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office2.learning import report as R
from office2.learning import trades as T


def load_fixture(path):
    rows = json.load(open(path))["signals"]
    return [T.from_office2(r) for r in rows]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "fixtures/learning/office2_delivered_2026-10-10.json")
    rep = R.build(load_fixture(path))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
