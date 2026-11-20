import argparse
import json
from pathlib import Path

from services.analytics.page_quality import (
    load_page_quality_dataset,
    save_page_quality_model,
    train_page_quality,
)

parser = argparse.ArgumentParser()
parser.add_argument("dataset_root", type=Path)
parser.add_argument("--target", choices=("US", "AE", "TRU", "TYP", "EXMPL", "AVG"), default="US")
parser.add_argument("--artifact", type=Path, default=Path("artifacts/analytics/page_quality/model.json"))
args = parser.parse_args()
rows = load_page_quality_dataset(args.dataset_root)
result = train_page_quality(rows, target_name=args.target)
save_page_quality_model(args.artifact, result)
print(json.dumps({"status": result["status"], "target": result["target"], "artifact": str(args.artifact)}, indent=2))
