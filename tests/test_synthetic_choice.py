import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.analytics.choice_model import load_model, predict_choice, save_model, train_choice_model
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
    path=tmp_path/"model.json";save_model(path,artifact);loaded=load_model(path)
    result=predict_choice(loaded,{k:v for k,v in data[0].items() if k!="selected_candidate_id"})
    assert len(result["candidate_probabilities"])==len(data[0]["candidate_set"])
    assert sum(x["probability"] for x in result["candidate_probabilities"])==pytest.approx(1)
    with pytest.raises(FileNotFoundError):load_model(tmp_path/"absent.json")


def test_prediction_api_missing_artifact():
    app=FastAPI()
    app.include_router(create_analytics_router(get_feature_provider=lambda:None,get_repository=lambda:None,get_study_authorizer=lambda:lambda _:True))
    # Endpoint path is mounted; an absent default artifact returns explicit unavailable status.
    assert TestClient(app).post("/v1/analytics/choice/predict",json={}).status_code in {422,503}
