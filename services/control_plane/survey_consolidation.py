"""Deterministic survey merge with explicit provenance and timing metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def consolidate_survey(session_id: str, assignments: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the frozen contract plan and a provenance/timing detail sidecar.

    Identical IDs deduplicate only when their question semantics are identical.
    The version and authoring order are provenance, not question semantics.
    """
    order: list[str] = []
    plans: dict[str, dict[str, Any]] = {}
    study_ids: list[str] = []
    timing_rules: list[dict[str, Any]] = []
    for assignment in assignments:
        config = assignment["study_config"]
        study_id = assignment["study_id"]
        study_ids.append(study_id)
        raw = config.get("question_config", {})
        questions = raw.get("questions", raw.get("items", []))
        question_version = raw.get("question_set_version", raw.get("config_version", config.get("question_set_version", "")))
        policy = config.get("survey_policy", {})
        timing = policy.get("timing", "after_exposure")
        timing_rules.append({"study_id": study_id, "question_set_version": question_version,
                             "timing": timing, "timing_rules": config.get("timing_rules", {})})
        for idx, question in enumerate(questions):
            question_id = question["question_id"]
            semantics = {key: value for key, value in question.items() if key not in {"version", "order"}}
            semantic_key = json.dumps(semantics, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            policy_mode = policy.get("consolidation", "keep_study_scoped")
            dedupe_key = question_id if policy_mode == "deduplicate_by_question_id" else f"{study_id}:{question_id}"
            existing = plans.get(dedupe_key)
            if existing is not None and existing["semantic_key"] == semantic_key:
                existing["origins"].append({"study_id": study_id, "question_set_version": question_version,
                                            "question_version": question.get("version", ""), "order": idx})
                continue
            public_id = question_id
            if existing is not None:
                suffix = hashlib.sha256(f"{study_id}:{question_version}:{semantic_key}".encode()).hexdigest()[:12]
                public_id = f"{question_id}@{suffix}"
                while public_id in order:
                    public_id += "x"
                dedupe_key = f"{dedupe_key}:{study_id}:{question_version}:{suffix}"
            else:
                # Preserve first-occurrence ID even when later studies opt into keep-study-scoped.
                if question_id in order:
                    suffix = hashlib.sha256(f"{study_id}:{question_version}:{semantic_key}".encode()).hexdigest()[:12]
                    public_id = f"{question_id}@{suffix}"
                    dedupe_key = f"{dedupe_key}:{suffix}"
            order.append(public_id)
            plans[dedupe_key] = {"public_id": public_id, "semantic_key": semantic_key,
                "question": question, "origins": [{"study_id": study_id,
                    "question_set_version": question_version, "question_version": question.get("version", ""), "order": idx}]}
    origins_by_id = {value["public_id"]: value["origins"] for value in plans.values()}
    return {
        "survey_plan": {"schema_version": "1.0.0", "survey_plan_id": f"survey-plan:{session_id}",
                        "session_id": session_id, "study_ids": study_ids, "question_ids": order,
                        "presentation": "end_of_session"},
        "details": {"schema_version": "1.0.0", "survey_plan_id": f"survey-plan:{session_id}",
                    "questions": [{"question_id": value["public_id"], "question": value["question"],
                                   "origins": value["origins"]}
                                  for value in (plans[key] for key in plans)],
                    "question_origins": origins_by_id, "timing_rules": timing_rules},
    }
