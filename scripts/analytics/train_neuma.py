from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.analytics.neuma import (
    load_neuma_page_records,
    save_neuma_artifact,
    train_neuma_page_model,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the leakage-safe NeuMa page-selection model")
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("--artifact", type=Path, default=Path("artifacts/analytics/neuma/model.json"))
    parser.add_argument("--evaluation", type=Path, default=Path("artifacts/analytics/neuma/evaluation.json"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    records = load_neuma_page_records(args.dataset_dir)
    result = train_neuma_page_model(records, seed=args.seed)
    if result.get("status") != "succeeded":
        raise SystemExit(json.dumps(result, indent=2))
    save_neuma_artifact(args.artifact, result)
    args.evaluation.parent.mkdir(parents=True, exist_ok=True)
    args.evaluation.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "records": len(records), "artifact": str(args.artifact), "evaluation": str(args.evaluation)}, indent=2))


if __name__ == "__main__":
    main()
