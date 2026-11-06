"""Reproducible synthetic choice contexts; never represents real participants."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "synthetic-choice/1.0.0"
CHOICE_FEATURES = ("preference", "price", "category_match", "click_count", "scroll_depth", "review_time_s", "backtracks")


def generate_choice_data(*, seed: int = 17, participants: int = 300, trials_per_participant: int = 5,
                         min_candidates: int = 3, max_candidates: int = 6,
                         missing_rate: float = 0.05) -> list[dict[str, Any]]:
    if participants < 10 or trials_per_participant < 1 or min_candidates < 2 or max_candidates < min_candidates:
        raise ValueError("invalid synthetic dataset dimensions")
    if not 0 <= missing_rate < 1:
        raise ValueError("missing_rate must be in [0, 1)")
    rng = random.Random(seed)
    out = []
    for p in range(participants):
        pref = rng.uniform(-1.2, 1.2)
        price_sensitivity = rng.uniform(0.2, 1.5)
        for trial in range(trials_per_participant):
            n = rng.randint(min_candidates, max_candidates)
            candidates = []
            utilities = []
            for c in range(n):
                category = rng.randint(0, 2)
                price = rng.uniform(0, 1)
                preference = max(-1., min(1., pref + rng.gauss(0, .55)))
                match = float((category == (p % 3)))
                clicks = max(0, rng.gauss(1.2 + 1.8 * max(0, preference), .9))
                scroll = max(0, rng.gauss(.45 + .25 * clicks, .2))
                review = max(0, rng.gauss(4 + 2.2 * clicks + preference, 2.0))
                backtracks = max(0, rng.gauss(.8 + (1-preference), .8))
                x = {"preference": preference, "price": price, "category_match": match,
                     "click_count": clicks, "scroll_depth": scroll, "review_time_s": review,
                     "backtracks": backtracks}
                for k in x:
                    if rng.random() < missing_rate:
                        x[k] = None
                # Choice generation uses latent complete values with noise. No target indicator is exported.
                utilities.append(1.15 * preference + .7 * match - price_sensitivity * price
                                 + .18 * clicks + .08 * review - .12 * backtracks + rng.gammavariate(1, 1))
                candidates.append({"candidate_id": f"item-{c}", "features": x})
            selected = max(range(n), key=utilities.__getitem__)
            out.append({"participant_id": f"synthetic-p-{p}", "session_id": f"synthetic-s-{p}",
                        "study_id": f"synthetic-study-{p % 3}", "trial_id": f"trial-{trial}",
                        "candidate_set": candidates, "selected_candidate_id": f"item-{selected}",
                        "label_timing": "choice_event_after_features", "data_origin": "synthetic"})
    return out


def validate_choice_data(records: list[dict[str, Any]]) -> None:
    seen = set()
    required = {"participant_id", "session_id", "study_id", "trial_id", "candidate_set", "selected_candidate_id", "label_timing", "data_origin"}
    for i, row in enumerate(records):
        if required - row.keys():
            raise ValueError(f"record {i} missing required fields")
        key = (row["participant_id"], row["session_id"], row["study_id"], row["trial_id"])
        if key in seen:
            raise ValueError(f"duplicate choice context at record {i}")
        seen.add(key)
        candidates = row["candidate_set"]
        ids = [c.get("candidate_id") for c in candidates]
        if len(ids) < 2 or len(set(ids)) != len(ids) or row["selected_candidate_id"] not in ids:
            raise ValueError(f"invalid candidate set or target at record {i}")
        if row["label_timing"] != "choice_event_after_features":
            raise ValueError("target must occur after predictors")
        for candidate in candidates:
            features = candidate.get("features", {})
            if set(features) != set(CHOICE_FEATURES):
                raise ValueError("candidate features must match the versioned schema")
            if any(v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v)) for v in features.values()):
                raise ValueError("features must be finite numbers or null")


def save_choice_data(path: str | Path, records: list[dict[str, Any]]) -> None:
    validate_choice_data(records)
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n", encoding="utf-8")


def load_choice_data(path: str | Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_choice_data(records)
    return records
