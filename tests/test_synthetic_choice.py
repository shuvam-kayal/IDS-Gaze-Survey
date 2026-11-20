import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.analytics.choice_model import (
    load_model,
    predict_choice,
    save_model,
    train_choice_model,
)
from services.analytics.integration import create_analytics_router
from services.analytics.synthetic_choice_data import generate_choice_data, validate_choice_data


def test_generator_seed_validation_and_target_exclusion():
    a=generate_choice_data(seed=3,participants=20,trials_per_participant=2)
    assert a==generate_choice_data(seed=3,participants=20,trials_per_participant=2)
    validate_choice_data(a)
    assert all("selected_candidate_id" not in c["features"] for r in a for c in r["candidate_set"])


def test_training_group_split_artifact_and_prediction(tmp_path):
    data=generate_choice_data(seed=8,participants=60,trials_per_participant=3)
    artifact=train_choice_model(data,seed=8,epochs=30)
    assert artifact["training"]["split"]=="participant_group_holdout"
    participants = {r["participant_id"] for r in data}
    test_n = artifact["training"]["test_participants"]
    import random
    split = sorted(participants)
    random.Random(8).shuffle(split)
    held_out = set(split[:test_n])
    assert not (held_out & (participants - held_out))
    path=tmp_path/"model.json";save_model(path,artifact);loaded=load_model(path)
    result=predict_choice(loaded,{k:v for k,v in data[0].items() if k!="selected_candidate_id"})
    assert len(result["candidate_probabilities"])==len(data[0]["candidate_set"])
    assert sum(x["probability"] for x in result["candidate_probabilities"])==pytest.approx(1)
    with pytest.raises(FileNotFoundError):load_model(tmp_path/"absent.json")


def _test_app():
    app=FastAPI()
    app.include_router(create_analytics_router(get_feature_provider=lambda:None,get_repository=lambda:None,get_study_authorizer=lambda:lambda _:True))
    return TestClient(app)


def _request():
    return {"participant_id":"new-p","session_id":"new-s","study_id":"study-a","trial_id":"trial-new",
            "candidate_set":[
                {"candidate_id":"a","features":{"preference":.8,"price":.2,"category_match":1,"click_count":2,"scroll_depth":.7,"review_time_s":8,"backtracks":0}},
                {"candidate_id":"b","features":{"preference":.1,"price":.7,"category_match":0,"click_count":1,"scroll_depth":.3,"review_time_s":3,"backtracks":2}},
                {"candidate_id":"c","features":{"preference":.3,"price":.4,"category_match":1,"click_count":1,"scroll_depth":.5,"review_time_s":5,"backtracks":1}}]}


def test_prediction_api_missing_artifact(monkeypatch):
    from services.analytics import integration
    def missing(_path):
        raise FileNotFoundError("not trained")
    monkeypatch.setattr(integration, "load_model", missing)
    response=_test_app().post("/v1/analytics/choice/predict",json=_request())
    assert response.status_code==503
    assert response.json()["detail"]["code"]=="model_not_trained"


def test_prediction_api_success_probabilities_and_ranking(tmp_path,monkeypatch):
    from services.analytics import integration
    training=generate_choice_data(seed=13,participants=40,trials_per_participant=2)
    artifact=train_choice_model(training,seed=13,epochs=20)
    path=tmp_path/"model.json";save_model(path,artifact)
    monkeypatch.setattr(integration,"load_model",lambda _path:load_model(path))
    response=_test_app().post("/v1/analytics/choice/predict",json=_request())
    assert response.status_code==200,response.text
    body=response.json(); probabilities=body["candidate_probabilities"]
    assert body["predicted_candidate_id"]==probabilities[0]["candidate_id"]
    assert {x["candidate_id"] for x in probabilities}=={"a","b","c"}
    assert [x["probability"] for x in probabilities]==sorted((x["probability"] for x in probabilities),reverse=True)
    assert all(0<=x["probability"]<=1 for x in probabilities)
    assert sum(x["probability"] for x in probabilities)==pytest.approx(1)
    assert body["model_status"]=="synthetic_demonstration"
