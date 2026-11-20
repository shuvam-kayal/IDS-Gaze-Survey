"""Inspect the locally downloaded Mendeley e-shopping dataset.

This script is intentionally read-only. It prints schema/count diagnostics but
never prints participant identifiers or raw data rows and never writes output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV has no header")
            return list(reader.fieldnames), list(reader)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise RuntimeError(f"failed to parse {path}: {exc}") from exc


def _is_missing(value: str | None) -> bool:
    return value is None or value.strip().lower() in {"", "na", "n/a", "nan", "null", "none"}


def _numeric_summary(rows: list[dict[str, str]], columns: list[str]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for column in columns:
        numeric = missing = non_numeric = 0
        for row in rows:
            value = row.get(column)
            if _is_missing(value):
                missing += 1
                continue
            try:
                parsed = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                non_numeric += 1
                continue
            if not math.isfinite(parsed):
                non_numeric += 1
            else:
                numeric += 1
        summary[column] = {
            "numeric_n": numeric,
            "missing_n": missing,
            "non_numeric_n": non_numeric,
        }
    return summary


def _duplicate_count(rows: list[dict[str, str]], columns: list[str]) -> int:
    keys = [tuple(row.get(column, "") for column in columns) for row in rows]
    return len(keys) - len(set(keys))


def _inspect_notebook(path: Path) -> dict[str, object]:
    try:
        notebook = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"failed to parse {path}: {exc}") from exc
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise TypeError(f"failed to parse {path}: missing cells array")
    source = "".join(
        "".join(cell.get("source", []))
        for cell in cells
        if isinstance(cell, dict) and cell.get("cell_type") == "code"
    )
    return {
        "format": "Jupyter notebook JSON",
        "code_cell_n": sum(
            1 for cell in cells if isinstance(cell, dict) and cell.get("cell_type") == "code"
        ),
        "source_chars": len(source),
        "references": {
            "questionnaire.csv": "questionnaire.csv" in source,
            "behavior.csv": "behavior.csv" in source,
            "sus_formula": "sum(i) - 10" in source and "2.5" in source,
            "behavior_grouping": all(token in source for token in ("trial", "website")),
        },
    }


def inspect(dataset_dir: Path) -> None:
    if not dataset_dir.is_dir():
        raise RuntimeError(f"dataset directory does not exist: {dataset_dir}")
    files = sorted(path for path in dataset_dir.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"dataset directory contains no files: {dataset_dir}")

    print(f"dataset_dir={dataset_dir}")
    print("files:")
    for path in files:
        print(f"  {path.relative_to(dataset_dir)}\tsize_bytes={path.stat().st_size}\tformat={path.suffix or 'none'}")

    csv_data: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for path in files:
        if path.suffix.lower() == ".csv":
            columns, rows = _read_csv(path)
            csv_data[path.name] = (columns, rows)
            print(f"csv[{path.name}]: rows={len(rows)} columns={columns}")
            print(f"csv[{path.name}]: missingness={_numeric_summary(rows, columns)}")
            print(f"csv[{path.name}]: duplicate_full_rows={_duplicate_count(rows, columns)}")
        elif path.suffix.lower() == ".ipynb":
            print(f"notebook[{path.name}]: {_inspect_notebook(path)}")
        elif path.suffix.lower() in {".json", ".xlsx", ".xls"}:
            print(f"uninspected[{path.name}]: format={path.suffix}; no parser is used by this script")

    behavior = csv_data.get("behavior.csv")
    questionnaire = csv_data.get("questionnaire.csv")
    if behavior:
        columns, rows = behavior
        required = {"sub", "trial", "website"}
        if not required.issubset(columns):
            raise RuntimeError(f"behavior.csv missing required join columns: {sorted(required - set(columns))}")
        participants = {row["sub"].strip() for row in rows if row.get("sub", "").strip()}
        trials = Counter(row["trial"] for row in rows)
        websites = Counter(row["website"] for row in rows)
        participant_rows = Counter(row["sub"] for row in rows)
        participant_trial_website = Counter((row["sub"], row["trial"], row["website"]) for row in rows)
        print(f"behavior: participant_count={len(participants)}")
        print(f"behavior: row_count_by_participant={dict(sorted(Counter(participant_rows.values()).items()))}")
        print(f"behavior: trial_counts={dict(sorted(trials.items()))}")
        print(f"behavior: website_counts={dict(sorted(websites.items()))}")
        print(f"behavior: duplicate_participant_trial_website_rows={sum(n - 1 for n in participant_trial_website.values() if n > 1)}")
        print(f"behavior: blank_sub_n={sum(not row.get('sub', '').strip() for row in rows)}")
        print(f"behavior: participant_id_digest_set_size={len({_digest(value) for value in participants})}")

    if questionnaire:
        columns, rows = questionnaire
        print(f"questionnaire: row_count={len(rows)} sus_item_count={len(columns)}")
        print(f"questionnaire: row_widths={dict(sorted(Counter(len(row) for row in rows).items()))}")
        print(f"questionnaire: missingness={_numeric_summary(rows, columns)}")
        print(f"questionnaire: duplicate_full_rows={_duplicate_count(rows, columns)}")
        print("questionnaire: participant_id_column_present=False")

    if behavior and questionnaire:
        behavior_participants = {row["sub"].strip() for row in behavior[1] if row.get("sub", "").strip()}
        print(
            "join: behavior_participant_count="
            f"{len(behavior_participants)} questionnaire_row_count={len(questionnaire[1])} "
            "validated_key_join=False reason=questionnaire_has_no_participant_id"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path)
    args = parser.parse_args()
    try:
        inspect(args.dataset_dir)
    except (RuntimeError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
