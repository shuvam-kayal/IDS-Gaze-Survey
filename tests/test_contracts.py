import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "event-envelope.v1.schema.json": "event-envelope.json",
    "feature-record.v1.schema.json": "feature-record-non-gaze.json",
    "analysis-result.v1.schema.json": "analysis-result-non-gaze.json",
    "gaze-record.v1.schema.json": "canonical-sample.json",
    "session-bootstrap.v1.schema.json": "session-bootstrap.json",
    "aoi-config.v1.schema.json": "aoi-config.json",
    "question-config.v1.schema.json": "question-config.json",
    "event-ingestion-response.v1.schema.json": "event-ingestion-response.json",
    "event-error.v1.schema.json": "event-error-invalid.json",
    "provider-sample.v1.schema.json": "provider-sample.json",
    "geometry-snapshot.v1.schema.json": "geometry-snapshot.json",
    "geometry-snapshot.v2.schema.json": "geometry-snapshot-v2.json",
    "trial-exposure-start.v1.schema.json": "trial-exposure-start.json",
    "trial-exposure-end.v1.schema.json": "trial-exposure-end.json",
    "gaze-observation-association.v1.schema.json": "gaze-observation-association.json",
    "gaze-observation-ingestion.v1.schema.json": "gaze-observation-ingestion.json",
    "gaze-observation-ingestion.v1.1.schema.json": "gaze-observation-ingestion-v1.1.json",
    "gaze-observation-ingestion-response.v1.schema.json": "gaze-observation-ingestion-response.json",
    "survey-plan.v1.schema.json": "survey-plan.json",
}

def test_schemas_are_valid_and_examples_match():
    for path in (ROOT / "contracts/schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        example_name = EXAMPLES.get(path.name)
        if example_name:
            if path.name == "gaze-record.v1.schema.json":
                example_path = ROOT / "fixtures/gaze" / example_name
            else:
                example_path = ROOT / "contracts/examples" / example_name
            example = json.loads(example_path.read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)


def test_all_event_error_examples_match_error_contract():
    schema_path = ROOT / "contracts/schemas/event-error.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for example_path in (ROOT / "contracts/examples").glob("event-error-*.json"):
        validator.validate(json.loads(example_path.read_text()))


def test_ingestion_response_rejects_inconsistent_duplicate_flag():
    schema_path = ROOT / "contracts/schemas/event-ingestion-response.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    invalid = {
        "schema_version": "1.0.0",
        "event_id": "evt-demo-0001",
        "status": "accepted",
        "duplicate": True,
        "ingested_at": "2026-01-01T10:00:03Z",
    }
    assert list(validator.iter_errors(invalid))


def test_duplicate_ingestion_response_example_matches_contract():
    schema_path = ROOT / "contracts/schemas/event-ingestion-response.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    example = json.loads(
        (ROOT / "contracts/examples/event-ingestion-response-duplicate.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)


def test_trial_exposure_start_requires_one_study_and_trial_id():
    schema = json.loads((ROOT / "contracts/schemas/trial-exposure-start.v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = json.loads((ROOT / "contracts/examples/trial-exposure-start.json").read_text())
    validator.validate(valid)
    for invalid in (
        {**valid, "study_ids": ["study-a", "study-b"]},
        {**valid, "payload": {}},
        {**valid, "occurred_at": "2026-01-01T10:00:00"},
        {**valid, "event_type": "trial.started"},
    ):
        assert list(validator.iter_errors(invalid))


def test_geometry_v2_requires_study_id_and_rejects_invalid_version():
    schema = json.loads((ROOT / "contracts/schemas/geometry-snapshot.v2.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = json.loads((ROOT / "contracts/examples/geometry-snapshot-v2.json").read_text())
    validator.validate(valid)
    missing_study = {key: value for key, value in valid.items() if key != "study_id"}
    wrong_version = {**valid, "schema_version": "1.0.0"}
    assert list(validator.iter_errors(missing_study))
    assert list(validator.iter_errors(wrong_version))
