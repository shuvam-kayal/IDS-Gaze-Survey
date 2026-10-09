import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def test_schemas_and_examples():
    for path in (ROOT / 'contracts/schemas').glob('*.schema.json'):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        name = {
            'event-envelope.v1.schema.json': 'event-envelope.json',
            'feature-record.v1.schema.json': 'feature-record-non-gaze.json',
        }.get(path.name)
        if name:
            example = json.loads((ROOT / 'contracts/examples' / name).read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
