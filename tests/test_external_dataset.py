import pytest

from services.analytics.advanced import run_experiment
from services.analytics.external_dataset import (
    DATASET_ADAPTER_VERSION,
    ExternalDatasetConfig,
    ExternalDatasetError,
    import_csv,
)


def write_csv(tmp_path, text):
    path = tmp_path / "external.csv"
    path.write_text(text, encoding="utf-8")
    return path


def config(**overrides):
    values = {
        "dataset_id": "ux-study",
        "participant_column": "participant",
        "session_column": "session",
        "target_column": "effectiveness",
        "predictor_columns": ("clicks", "gaze.dwell_ms"),
        "modality": "gaze",
    }
    values.update(overrides)
    return ExternalDatasetConfig(**values)


def test_valid_csv_import_preserves_group_and_missing_gaze(tmp_path):
    path = write_csv(tmp_path, "participant,session,effectiveness,clicks,gaze.dwell_ms\np1,s1,4,2,120\np2,s2,3,1,\n")
    imported = import_csv(path, config())

    assert len(imported.records) == 2
    assert imported.records[0]["participant_id"] == "p1"
    assert imported.records[0]["session_id"] == "s1"
    assert imported.records[0]["features"]["effectiveness"] == 4.0
    assert imported.records[1]["features"]["gaze.dwell_ms"] == {"value": None, "modality": "gaze"}
    assert imported.diagnostics["adapter_schema_version"] == DATASET_ADAPTER_VERSION
    assert imported.diagnostics["accepted_rows"] == 2


def test_missing_file_has_stable_error(tmp_path):
    with pytest.raises(ExternalDatasetError) as error:
        import_csv(tmp_path / "missing.csv", config())
    assert error.value.code == "source_file_not_found"


def test_missing_required_columns_rejected(tmp_path):
    path = write_csv(tmp_path, "participant,effectiveness,clicks\np1,4,2\n")
    with pytest.raises(ExternalDatasetError) as error:
        import_csv(path, config())
    assert error.value.code == "missing_required_columns"
    assert "session" in error.value.details["missing_columns"]


def test_invalid_predictor_and_missing_target_are_counted(tmp_path):
    path = write_csv(tmp_path, "participant,session,effectiveness,clicks,gaze.dwell_ms\np1,s1,4,nope,1\np2,s2,,2,3\n")
    imported = import_csv(path, config())
    assert imported.records == ()
    assert imported.diagnostics["rejection_counts"] == {
        "invalid_non_numeric_predictor": 1,
        "missing_target": 1,
    }


def test_duplicate_and_missing_participant_ids_are_diagnosed(tmp_path):
    path = write_csv(tmp_path, "participant,session,effectiveness,clicks,gaze.dwell_ms\n,s1,4,2,1\np1,s1,4,2,1\np1,s1,4,2,1\np1,s2,3,1,2\n")
    imported = import_csv(path, config())
    assert imported.diagnostics["rejection_counts"]["missing_participant_id"] == 1
    assert imported.diagnostics["rejection_counts"]["duplicate_participant_session_row"] == 1
    assert imported.diagnostics["repeated_participant_id_count"] == 1
    assert len(imported.records) == 2


def test_target_leakage_rejected_at_configuration():
    with pytest.raises(ExternalDatasetError) as error:
        config(predictor_columns=("effectiveness", "clicks"))
    assert error.value.code == "target_leakage"


def test_diagnostics_match_accepted_and_rejected_rows(tmp_path):
    path = write_csv(tmp_path, "participant,session,effectiveness,clicks,gaze.dwell_ms\np1,s1,4,2,1\np2,s2,,2,1\n,s3,3,2,1\np3,s3,2,2,bad\n")
    imported = import_csv(path, config())
    diagnostics = imported.diagnostics
    assert diagnostics["total_rows"] == 4
    assert diagnostics["accepted_rows"] == 1
    assert diagnostics["rejected_rows"] == 3
    assert diagnostics["accepted_rows"] + diagnostics["rejected_rows"] == diagnostics["total_rows"]


def test_participant_ids_are_not_predictors_and_repeated_groups_are_preserved(tmp_path):
    path = write_csv(tmp_path, "participant,session,effectiveness,clicks,gaze.dwell_ms\np1,s1,4,2,1\np1,s2,3,1,2\np2,s3,2,1,\n")
    imported = import_csv(path, config())
    assert [record["participant_id"] for record in imported.records] == ["p1", "p1", "p2"]
    assert all("participant" not in record["features"] for record in imported.records)
    assert imported.diagnostics["missing_values_per_predictor"]["gaze.dwell_ms"] == 1


def test_imported_records_feed_existing_grouped_engine(tmp_path):
    rows = ["participant,session,effectiveness,clicks,gaze.dwell_ms"]
    rows.extend(f"p{i},s{i},{'yes' if i % 2 else 'no'},{i},{i * 10}" for i in range(12))
    imported = import_csv(write_csv(tmp_path, "\n".join(rows) + "\n"), config(modality=None))

    result = run_experiment(
        imported.records,
        {"target": "effectiveness", "features": ["clicks"], "task": "classification", "seed": 3},
        "non_gaze_only",
    )
    assert result["status"] == "succeeded"
    assert result["experiment"]["validation_strategy"] == "participant_group_holdout"
