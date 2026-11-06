"""Train and apply reusable screenshot-to-page-rating models."""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

from PIL import Image

from .advanced import run_experiment
from .capabilities import cross_validation

SCHEMA_VERSION = "p4-page-quality/1.0.0"
TARGETS = ("US", "AE", "TRU", "TYP", "EXMPL", "AVG")


class PageQualityError(ValueError):
    pass


def _image_features(path: Path) -> dict[str, float]:
    image = Image.open(path).convert("RGB")
    image.thumbnail((128, 256))
    pixels = list(image.getdata())
    channels = [[p[i] / 255 for p in pixels] for i in range(3)]
    lum = [0.2126*r + 0.7152*g + 0.0722*b for r,g,b in zip(*channels)]
    rows, cols = image.height, image.width
    row_means = [statistics.fmean(lum[y*cols:(y+1)*cols]) for y in range(rows)]
    edges = [abs(lum[y*cols+x]-lum[y*cols+x-1]) for y in range(rows) for x in range(1,cols)]
    return {
        "image_width": float(rows), "image_height": float(cols),
        "brightness_mean": statistics.fmean(lum),
        "brightness_sd": statistics.pstdev(lum),
        "brightness_top": statistics.fmean(lum[:max(1,len(lum)//3)]),
        "brightness_middle": statistics.fmean(lum[len(lum)//3:2*len(lum)//3]),
        "brightness_bottom": statistics.fmean(lum[2*len(lum)//3:]),
        "layout_band_variation": statistics.pstdev(row_means),
        "horizontal_edge_density": statistics.fmean(edges) if edges else 0.0,
        "red_mean": statistics.fmean(channels[0]),
        "green_mean": statistics.fmean(channels[1]),
        "blue_mean": statistics.fmean(channels[2]),
        "color_variation": statistics.fmean(statistics.pstdev(c) for c in channels),
        "aspect_ratio": float(image.width / image.height) if image.height else 0.0,
    }


def load_page_quality_dataset(dataset_root: str | Path) -> list[dict[str, Any]]:
    root = Path(dataset_root)
    if not root.is_dir():
        raise PageQualityError(f"Dataset directory not found: {root}")
    records = []
    for domain_dir in sorted(root.glob("dataverse_files_*")):
        for ratings_path in sorted(domain_dir.glob("ratings.avg.*.txt")):
            domain = ratings_path.name.removeprefix("ratings.avg.").removesuffix(".txt")
            with ratings_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            if not rows or not {"stimulusId", *TARGETS}.issubset(rows[0]):
                raise PageQualityError(f"Unexpected rating schema: {ratings_path}")
            for row in rows:
                stimulus = row["stimulusId"]
                matches = list(domain_dir.glob(f"**/{stimulus}"))
                if len(matches) != 1:
                    raise PageQualityError(f"Expected one screenshot for {stimulus} in {domain_dir}; found {len(matches)}")
                features = _image_features(matches[0])
                features["domain"] = domain
                for target in TARGETS:
                    try:
                        score = float(row[target])
                    except (ValueError, TypeError):
                        continue
                    if math.isfinite(score):
                        records.append({"record_id": f"{domain}:{stimulus}:{target}", "page_id": stimulus,
                                        "site_group": domain, "target_name": target,
                                        "features": {**features, "rating": score}, "target": score})
    if not records:
        raise PageQualityError("No valid page ratings found")
    return records


def train_page_quality(records: list[dict[str, Any]], target_name: str = "US", seed: int = 19) -> dict[str, Any]:
    if target_name not in TARGETS:
        raise PageQualityError(f"Unsupported target {target_name}; choose one of {TARGETS}")
    selected = [r for r in records if r["target_name"] == target_name]
    # Screenshot identity is the grouped unit; repeated rows are never divided across folds.
    page_records = []
    for row in selected:
        page_records.append({**row, "participant_id": row["page_id"],
                             "features": {**row["features"], "rating": row["target"]}})
    features = [k for k in page_records[0]["features"] if k != "rating"]
    params = {"target": "rating", "features": features, "task": "regression",
              "models": ["ridge"], "seed": seed, "include_predictions": True,
              "intended_use": "exploratory page rating prediction"}
    holdout = run_experiment(page_records, params)
    cv = cross_validation(page_records, {**params, "folds": 5}, "best_available")
    return {"status": holdout.get("status"), "schema_version": SCHEMA_VERSION,
            "dataset": "web-design-prototypicality", "target": target_name,
            "prediction_unit": "screenshot", "features": features,
            "holdout": holdout, "grouped_cross_validation": cv,
            "limitations": ["Ratings are aggregate screenshot scores scaled within raters.",
                            "Domain is a coarse category, not a website identity.",
                            "Visual pixel features are not semantic or interaction features."]}


def save_page_quality_model(path: str | Path, result: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"artifact_version": SCHEMA_VERSION, "result": result}, indent=2), encoding="utf-8")


def load_page_quality_model(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("artifact_version") != SCHEMA_VERSION:
        raise PageQualityError("Unsupported page-quality artifact version")
    return payload["result"]


def predict_page_quality(result: dict[str, Any], feature_rows: list[dict[str, Any]]) -> dict[str, Any]:
    from .capabilities import predict_with_saved_result
    return predict_with_saved_result({"study_id": "page-quality", "results": {"ml_experiment": result["holdout"]}}, feature_rows)
