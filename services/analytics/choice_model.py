"""Choice-set conditional-logit training and inference."""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from .synthetic_choice_data import CHOICE_FEATURES, GENERATOR_VERSION, validate_choice_data

MODEL_VERSION = "p4-conditional-choice/1.0.0"
MISSING_FEATURE = "__missing__"


def _prepare(records: list[dict[str, Any]], means: dict[str, float] | None = None, scales: dict[str, float] | None = None):
    if means is None:
        vals = {f: [float(c["features"][f]) for r in records for c in r["candidate_set"] if c["features"][f] is not None] for f in CHOICE_FEATURES}
        means = {f: sum(v)/len(v) if v else 0. for f,v in vals.items()}
        scales = {f: (sum((x-means[f])**2 for x in v)/len(v))**.5 or 1. for f,v in vals.items()}
    out = []
    for r in records:
        candidates=[]
        for c in r["candidate_set"]:
            row=[]
            for f in CHOICE_FEATURES:
                value=c["features"][f]
                row.extend([0. if value is None else (float(value)-means[f])/scales[f], float(value is None)])
            candidates.append(row)
        out.append((r,candidates))
    return out,means,scales


def _softmax(scores):
    m=max(scores); ex=[math.exp(s-m) for s in scores]; z=sum(ex); return [v/z for v in ex]


def _score(weights, x): return sum(w*v for w,v in zip(weights,x))


def _predict_one(weights, record, means, scales):
    prepared,_,_=_prepare([record],means,scales); row, xs=prepared[0]
    probabilities=_softmax([_score(weights,x) for x in xs]); order=sorted(range(len(xs)),key=lambda i:probabilities[i],reverse=True)
    return {"predicted_candidate_id":row["candidate_set"][order[0]]["candidate_id"],
            "candidate_probabilities":[{"candidate_id":row["candidate_set"][i]["candidate_id"],"probability":probabilities[i]} for i in order],
            "confidence":probabilities[order[0]]}


def predict_choice(artifact: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    required={"participant_id","session_id","study_id","trial_id","candidate_set"}
    if required-set(context): raise ValueError("choice context is missing identifiers or candidate_set")
    probe={**context,"selected_candidate_id":context["candidate_set"][0].get("candidate_id"),"label_timing":"choice_event_after_features","data_origin":"inference"}
    validate_choice_data([probe])
    prediction=_predict_one(artifact["weights"],probe,artifact["means"],artifact["scales"])
    return {**prediction,"target":"selected_candidate_id","model_version":artifact["model_version"],
            "model_status":"synthetic_demonstration","warning":"Trained on synthetic data; not validated on real participants."}


def _metrics(records,weights,means,scales):
    top=top3=loss=0.; confusion=Counter(); actuals=[]
    for r in records:
        pred=_predict_one(weights,r,means,scales); probs=pred["candidate_probabilities"]
        truth=r["selected_candidate_id"]; ranked=[x["candidate_id"] for x in probs]
        top += ranked[0]==truth; top3 += truth in ranked[:3]
        prob=next(x["probability"] for x in probs if x["candidate_id"]==truth); loss-=math.log(max(prob,1e-12))
        confusion[(truth,ranked[0])]+=1; actuals.append((truth,ranked[0]))
    n=len(records)
    return {"choice_set_top1_accuracy":top/n,"top3_accuracy":top3/n,"mean_log_loss":loss/n,
            "random_choice_expected_top1":sum(1/len(r["candidate_set"]) for r in records)/n,
            "confusion_pairs":{f"{a}->{b}":v for (a,b),v in confusion.items()},"n_contexts":n}


def train_choice_model(records: list[dict[str, Any]], *, seed: int = 17, epochs: int = 300, learning_rate: float = .04, l2: float = .02):
    validate_choice_data(records)
    groups=sorted({r["participant_id"] for r in records}); rng=random.Random(seed); rng.shuffle(groups)
    if len(groups)<10: raise ValueError("at least 10 participant groups required")
    ntest=max(2,round(len(groups)*.2)); test_groups=set(groups[:ntest]); train=[r for r in records if r["participant_id"] not in test_groups]; test=[r for r in records if r["participant_id"] in test_groups]
    assert not ({r["participant_id"] for r in train}&{r["participant_id"] for r in test})
    prepared,means,scales=_prepare(train); dim=len(prepared[0][1][0]); weights=[0.]*dim
    for epoch in range(epochs):
        grads=[0.]*dim
        for record,xs in prepared:
            probs=_softmax([_score(weights,x) for x in xs]); actual=next(i for i,c in enumerate(record["candidate_set"]) if c["candidate_id"]==record["selected_candidate_id"])
            for j in range(dim): grads[j]+=sum((probs[i]-(1. if i==actual else 0.))*xs[i][j] for i in range(len(xs)))
        rate=learning_rate/(1+epoch/epochs)
        weights=[w-rate*(g/len(prepared)+l2*w) for w,g in zip(weights,grads)]
    metrics=_metrics(test,weights,means,scales)
    artifact={"artifact_version":"synthetic-choice-artifact/1.0.0","model_version":MODEL_VERSION,"model_kind":"conditional_logit",
              "features":[x for f in CHOICE_FEATURES for x in (f,f+"__missing")],"source_features":list(CHOICE_FEATURES),
              "weights":weights,"means":means,"scales":scales,"target":"selected_candidate_id","candidate_formulation":"variable-size conditional choice softmax",
              "dataset":{"origin":"synthetic","generator_version":GENERATOR_VERSION,"record_count":len(records),"participant_count":len(groups)},
              "training":{"seed":seed,"epochs":epochs,"learning_rate":learning_rate,"l2":l2,"train_participants":len(groups)-ntest,"test_participants":len(test_groups),"split":"participant_group_holdout"},
              "evaluation":{"synthetic_only":True,"test":metrics,"baseline":{"most_popular_train_item_not_comparable_across_new IDs":"choice-set uniform probability baseline","expected_top1":metrics["random_choice_expected_top1"]}},
              "limitations":["Synthetic data only; metrics do not estimate real participant performance.","Identifiers and target labels are not predictors.","Synthetic mechanisms must be replaced/validated with consented real observations."]}
    return artifact


def save_model(path: str | Path, artifact: dict[str, Any]):
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); temp=target.with_suffix(target.suffix+".tmp")
    temp.write_text(json.dumps(artifact,indent=2),encoding="utf-8"); temp.replace(target)


def load_model(path: str | Path):
    p=Path(path)
    if not p.is_file(): raise FileNotFoundError(f"Choice model is not trained or available: {p}")
    artifact=json.loads(p.read_text(encoding="utf-8"))
    if artifact.get("artifact_version")!="synthetic-choice-artifact/1.0.0" or artifact.get("model_version")!=MODEL_VERSION:
        raise ValueError("unsupported choice model artifact")
    return artifact
