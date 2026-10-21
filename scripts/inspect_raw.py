"""Inspect raw BIXI trip files WITHOUT assuming a schema.

Step 2, stage 1: find out what the real files look like before writing any cleaning code.

Usage (from the project root, with:  pip install -e ".[data]"):
    python scripts/inspect_raw.py              # reads data/raw/**/*.csv
    python scripts/inspect_raw.py path/to/dir

Prints a report and saves it to data/processed/raw_inspection.txt. Paste that file back
so the cleaning rules can be written against the real columns.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import duckdb


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def inspect_file(con: duckdb.DuckDBPyConnection, path: Path, lines: list[str]) -> tuple[str, ...]:
    con.execute(
        "CREATE OR REPLACE TEMP VIEW t AS SELECT * FROM read_csv("
        f"{quote_literal(path.as_posix())}, header=true, sample_size=-1, ignore_errors=true)"
    )
    columns = [(row[0], row[1]) for row in con.execute("DESCRIBE t").fetchall()]
    row_count = con.execute("SELECT count(*) FROM t").fetchone()[0]

    lines.append(f"\n=== {path.name} ===")
    lines.append(f"rows: {row_count:,}   columns: {len(columns)}")
    lines.append(f"{'column':<34}{'type':<14}{'nulls':>10}{'~distinct':>12}   min .. max")

    for name, dtype in columns:
        col = quote_identifier(name)
        nulls, distinct, low, high = con.execute(
            f"SELECT count(*) - count({col}), approx_count_distinct({col}), "
            f"min({col}), max({col}) FROM t"
        ).fetchone()
        lines.append(f"{name:<34}{dtype:<14}{nulls:>10,}{distinct:>12,}   {low} .. {high}")

    lines.append("sample rows:")
    for row in con.execute("SELECT * FROM t LIMIT 3").fetchall():
        lines.append(f"  {row}")

    return tuple(name for name, _ in columns)


def main() -> int:
    raw_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")
    files = sorted(raw_dir.rglob("*.csv"))
    if not files:
        print(f"No CSV files found under {raw_dir}. Unzip the BIXI downloads there first.")
        return 1

    con = duckdb.connect()
    lines: list[str] = [f"BIXI raw data inspection: {len(files)} file(s) under {raw_dir}"]
    schema_groups: dict[tuple[str, ...], list[str]] = defaultdict(list)

    for path in files:
        try:
            schema_groups[inspect_file(con, path, lines)].append(path.name)
        except duckdb.Error as error:
            lines.append(f"\n=== {path.name} ===\nFAILED to read: {error}")

    lines.append("\n=== schema groups (files sharing identical column names) ===")
    for index, (columns, names) in enumerate(schema_groups.items(), start=1):
        lines.append(f"group {index}: {len(names)} file(s): {', '.join(names)}")
        lines.append(f"  columns: {', '.join(columns)}")

    report = "\n".join(lines)
    print(report)

    out_path = Path("data/processed/raw_inspection.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nSaved report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
