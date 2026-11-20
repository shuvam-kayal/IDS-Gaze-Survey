import array
import json

import pytest

from services.analytics.neuma import (
    NeuMaDataError,
    load_neuma_page_records,
    predict_neuma_artifact,
    save_neuma_artifact,
    train_neuma_page_model,
)


def _fixture_dataset(tmp_path):
    root = tmp_path / "neuma"
    eye = root / "sub-S01" / "eye_tracker"
    eye.mkdir(parents=True)
    (eye / "sub-S01_task-unnamed_events.tsv").write_text(
        "onset\tduration\tsample\tvalue\n"
        "0\t1\t0\tCategory:IMG=ID:FYLLADIO_1.tif=Type:Leaflet_Images_1\n"
        "3\t1\t1800\tMouseButtonLeft pressed\n"
        "4\t1\t2400\tCategory:IMG=ID:FYLLADIO_2.tif=Type:Leaflet_Images_1\n"
        "8\t1\t4800\tEOE\n",
        encoding="utf-8",
    )
    (eye / "sub-S01_task-unnamed_et.json").write_text(
        json.dumps({"SamplingFrequency": 600}), encoding="utf-8"
    )
    values = array.array("f", [0.5, 0.4, 3.0, 0.6, 0.4, 3.1] * 4800)
    with (eye / "sub-S01_task-unnamed_et.fdt").open("wb") as handle:
        values.tofile(handle)
    return root


def _records():
    records = []
    for participant in range(12):
        for page in range(2):
            selected = int((participant + page) % 3 != 0)
            features = {
                "page_number": float(page + 1),
                "selected_any": selected,
            }
            for name in (
                "gaze_valid_rate",
                "gaze_left_x_mean", "gaze_left_x_sd", "gaze_left_y_mean", "gaze_left_y_sd",
                "gaze_left_pupil_mean", "gaze_left_pupil_sd", "gaze_right_x_mean", "gaze_right_x_sd",
                "gaze_right_y_mean", "gaze_right_y_sd", "gaze_right_pupil_mean", "gaze_right_pupil_sd",
            ):
                features[name] = {"value": 0.8 + participant / 100, "modality": "gaze", "quality": 0.8}
            records.append({
                "record_id": f"r-{participant}-{page}",
                "participant_id": f"p-{participant}",
                "features": features,
            })
    return records


def test_loader_extracts_page_target_and_preserves_pre_outcome_cutoff(tmp_path):
    records = load_neuma_page_records(_fixture_dataset(tmp_path))
    assert len(records) == 2
    assert records[0]["target"] == 1
    assert records[0]["neuma"]["prediction_cutoff_s"] == 2.0
    assert records[1]["target"] == 0
    assert records[1]["neuma"]["prediction_cutoff_s"] == 6.0
    assert records[0]["features"]["gaze_left_x_mean"]["modality"] == "gaze"


def test_product_target_is_rejected_explicitly(tmp_path):
    with pytest.raises(NeuMaDataError) as error:
        load_neuma_page_records(_fixture_dataset(tmp_path), target="selected_product")
    assert error.value.code == "unsupported_target"


def test_training_reports_grouped_holdout_and_cross_validation():
    result = train_neuma_page_model(_records())
    assert result["status"] == "succeeded"
    assert result["experiment"]["validation_strategy"] == "participant_group_holdout"
    assert result["experiment"]["train_group_n"] > 0
    assert result["experiment"]["test_group_n"] > 0
    assert result["grouped_cross_validation"]["method"] == "grouped cross-validation"


def test_artifact_round_trip_supports_inference(tmp_path):
    result = train_neuma_page_model(_records())
    artifact = tmp_path / "model.json"
    save_neuma_artifact(artifact, result)
    prediction = predict_neuma_artifact(artifact, _records()[:2])
    assert prediction["status"] == "succeeded"
    assert len(prediction["models"]["logistic"]["predictions"]) == 2
