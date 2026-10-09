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
