import argparse
import json
from pathlib import Path

from services.analytics.choice_model import load_model, predict_choice, save_model, train_choice_model
from services.analytics.synthetic_choice_data import generate_choice_data, save_choice_data

parser=argparse.ArgumentParser()
parser.add_argument("--seed",type=int,default=17)
parser.add_argument("--participants",type=int,default=300)
parser.add_argument("--trials",type=int,default=5)
parser.add_argument("--data",type=Path,default=Path("artifacts/analytics/synthetic_choice/data.jsonl"))
parser.add_argument("--model",type=Path,default=Path("artifacts/analytics/synthetic_choice/model.json"))
args=parser.parse_args()
records=generate_choice_data(seed=args.seed,participants=args.participants,trials_per_participant=args.trials)
save_choice_data(args.data,records)
artifact=train_choice_model(records,seed=args.seed)
save_model(args.model,artifact)
loaded=load_model(args.model)
print(json.dumps({"records":len(records),"evaluation":loaded["evaluation"],"model":str(args.model),"round_trip_prediction":predict_choice(loaded,{**records[0],"selected_candidate_id":None})},indent=2))
