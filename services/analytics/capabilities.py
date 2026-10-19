"""Additional transparent, modality-aware P4 analytics capabilities."""
from __future__ import annotations
import math, random, statistics
from collections import Counter,defaultdict
from .engine import AnalysisError, finite, is_gaze, parts, quality_for

# Registry metadata is intentionally declarative: integrations can inspect task and
# modality requirements before choosing a model, without importing model internals.
MODEL_REGISTRY={
 'ridge':{'task':'regression','required_modalities':'selected predictors','gaze_optional':True,'fallback':'mean'},
 'logistic':{'task':'classification','required_modalities':'selected predictors','gaze_optional':True,'fallback':'majority'},
 'mean':{'task':'regression','required_modalities':[],'gaze_optional':True,'fallback':None},
 'majority':{'task':'classification','required_modalities':[],'gaze_optional':True,'fallback':None},
 'ensemble':{'task':'regression or classification','required_modalities':'selected predictors','gaze_optional':True,'fallback':'mean or majority'},
}

def predict_with_saved_result(result,records):
 """Reuse stored fitted linear/logistic model metadata on new FeatureRecords."""
 from .engine import is_gaze,parts,quality_for
 experiment=result.get('results',{}).get('ml_experiment',{}).get('experiment',{})
 fitted=result.get('results',{}).get('ml_experiment',{}).get('baseline_comparison',{})
 predictors=experiment.get('predictors') or []; policy=experiment.get('modality_policy','best_available');norm=experiment.get('normalization',{});means=norm.get('mean',{});sds=norm.get('sd',{});medians=norm.get('training_medians',{})
 if not predictors or not fitted:raise AnalysisError('model_artifact_unavailable','Saved result has no reusable fitted model')
 output={};minimum=.5
 for name,payload in fitted.items():
  model=payload.get('model',{});kind=model.get('kind')
  if kind not in {'ridge_regression','logistic_regression'}:continue
  predictions=[];excluded=0
  for i,record in enumerate(records):
   row=[];invalid=False
   for feature in predictors:
    raw=record.get('features',{}).get(feature);value,_,mod,_,_=parts(raw);gaze=is_gaze(feature,mod)
    if policy=='gaze_only' and not gaze or policy=='non_gaze_only' and gaze:raise AnalysisError('modality_violation',f'Saved model policy does not permit feature {feature}')
    if gaze:
     quality=quality_for(record,feature,raw)
     if quality is None or not finite(quality) or quality<minimum:invalid=True;break
    if value is None:value=medians.get(feature)
    if not finite(value):invalid=True;break
    row.append((float(value)-means[feature])/(sds[feature] or 1.))
   if invalid:excluded+=1;continue
   if kind=='ridge_regression':
    coef=model['coefficients'];pred=model['intercept']+sum(a*b for a,b in zip(row,coef)); predictions.append({'opaque_record_token':__import__('hashlib').sha256(str(record.get('record_id') or record.get('session_id') or i).encode()).hexdigest()[:16],'prediction':pred})
   else:
    logits=[sum(a*b for a,b in zip(coef,row))+intercept for coef,intercept in zip(model['coefficients'],model['intercepts'])];mx=max(logits);probs=[math.exp(x-mx) for x in logits];total=sum(probs);probs=[x/total for x in probs];idx=max(range(len(probs)),key=probs.__getitem__);predictions.append({'opaque_record_token':__import__('hashlib').sha256(str(record.get('record_id') or record.get('session_id') or i).encode()).hexdigest()[:16],'prediction':model['classes'][idx],'probabilities':dict(zip(model['classes'],probs))})
  output[name]={'status':'succeeded','model_version':experiment.get('model_version'),'analysis_version':experiment.get('analysis_version'),'input_modality_policy':policy,'predictions':predictions,'excluded_input_n':excluded}
 return {'status':'succeeded' if output else 'unavailable','source_result_id':result.get('result_id'),'study_id':result.get('study_id'),'models':output,'warning':'Predictions reuse a model fitted on the source result; validate transfer to this new cohort before research interpretation.'}

def _values(records, feature, policy='best_available', threshold=.5):
 out=[]; dropped=0
 for r in records:
  raw=r.get('features',{}).get(feature); val,unit,mod,_,_=parts(raw)
  gaze=is_gaze(feature,mod)
  if policy=='gaze_only' and not gaze or policy=='non_gaze_only' and gaze: continue
  if gaze:
   q=quality_for(r,feature,raw)
   if q is not None and (not finite(q) or not 0<=float(q)<=1):raise AnalysisError('invalid_feature_quality',f'{feature} quality must be between 0 and 1')
   if q is None or float(q)<threshold:dropped+=1;continue
  if finite(val):out.append((float(val),unit,r))
 return out,dropped

def anomaly_detection(records,p,policy='best_available'):
 features=p.get('features') or ([p['feature']] if p.get('feature') else [])
 threshold=float(p.get('robust_z_threshold',3.5)); quality=float(p.get('gaze_min_quality',.5))
 if not features or not math.isfinite(threshold) or threshold<=0:raise AnalysisError('invalid_anomaly_settings','Select features and a positive robust_z_threshold')
 result={}; flagged={}
 for name in features:
  rows,dropped=_values(records,name,policy,quality); vals=[x[0] for x in rows]
  units={unit for _,unit,_ in rows}
  if len(units)>1:result[name]={'status':'incompatible_units','n':len(rows),'reason':'Anomaly scores are not pooled across incompatible or missing units'};continue
  if len(vals)<4:result[name]={'status':'insufficient_data','n':len(vals),'dropped_quality_n':dropped};continue
  med=statistics.median(vals); mad=statistics.median(abs(v-med) for v in vals)
  if mad==0: scores=[0. if v==med else math.inf for v in vals]
  else:scores=[.67448975*(v-med)/mad for v in vals]
  found=[]
  for (value,unit,rec),score in zip(rows,scores):
   if abs(score)>=threshold:
    token=str(rec.get('record_id') or rec.get('session_id') or 'row')
    found.append({'opaque_record_token':__import__('hashlib').sha256(token.encode()).hexdigest()[:16],'value':value,'unit':unit,'robust_z':score})
  result[name]={'status':'succeeded','n':len(vals),'median':med,'mad':mad,'threshold':threshold,'outlier_n':len(found),'outliers':found,'dropped_quality_n':dropped,'method':'median absolute deviation robust z-score'}
 return {'status':'succeeded' if any(v['status']=='succeeded' for v in result.values()) else 'insufficient_data','features':result,'modality_policy':policy,'interpretation_limit':'Flags are review candidates, not exclusions or proof of invalid observations.'}

def feature_selection(records,p,policy='best_available'):
 target=p.get('target'); features=p.get('features') or []
 if not target or not features:raise AnalysisError('invalid_feature_selection','target and features are required')
 def rawval(rec,name):
  raw=rec.get('features',{}).get(name); return raw.get('value') if isinstance(raw,dict) else raw
 y=[]
 for rec in records:
  v=rawval(rec,target)
  if finite(v):y.append((str(rec.get('participant_id') or rec.get('session_id') or rec.get('record_id')),float(v)))
 yy=dict(y); ranked=[]
 for name in features:
  xs,_=_values(records,name,policy,float(p.get('gaze_min_quality',.5)))
  units={unit for _,unit,_ in xs}
  if len(units)>1:ranked.append({'feature':name,'status':'incompatible_units','n':len(xs)});continue
  pairs=[(v,yy.get(str(r.get('participant_id') or r.get('session_id') or r.get('record_id')))) for v,_,r in xs]; pairs=[pair for pair in pairs if pair[1] is not None]
  if len(pairs)<3:ranked.append({'feature':name,'status':'insufficient_data','n':len(pairs)});continue
  x=[a for a,_ in pairs]; yv=[b for _,b in pairs]; mx=statistics.fmean(x); my=statistics.fmean(yv); denom=math.sqrt(sum((a-mx)**2 for a in x)*sum((b-my)**2 for b in yv)); corr=sum((a-mx)*(b-my) for a,b in pairs)/denom if denom else None
  ranked.append({'feature':name,'status':'succeeded','n':len(pairs),'absolute_correlation':abs(corr) if corr is not None else None,'correlation':corr})
 ranked.sort(key=lambda x:(x['absolute_correlation'] is None,-(x['absolute_correlation'] or 0),x['feature']))
 return {'status':'succeeded','target':target,'ranking':ranked,'selected': [x['feature'] for x in ranked[:int(p.get('top_k',len(ranked)))] if x['status']=='succeeded'],'method':'univariate Pearson screening','warning':'Exploratory ranking; use training-only nested selection for confirmatory prediction.','modality_policy':policy}

def dimensionality_reduction(records,p,policy='best_available'):
 names=p.get('features') or []; dimensions=max(1,min(2,int(p.get('n_components',2))))
 if len(names)<dimensions:raise AnalysisError('invalid_reduction','features must contain at least n_components features')
 matrix=[]; tokens=[]; units_by_feature={name:set() for name in names}
 for i,r in enumerate(records):
  row=[]
  for name in names:
   raw=r.get('features',{}).get(name); val,_,mod,_,_=parts(raw); gaze=is_gaze(name,mod)
   if policy=='gaze_only' and not gaze or policy=='non_gaze_only' and gaze:row=[];break
   if gaze:
    q=quality_for(r,name,raw)
    if q is None or not finite(q) or q<float(p.get('gaze_min_quality',.5)):row=[];break
   if not finite(val):row=[];break
   units_by_feature[name].add(parts(raw)[1])
   row.append(float(val))
  if len(row)==len(names):matrix.append(row);tokens.append(str(r.get('record_id') or r.get('session_id') or f'row-{i}'))
 if any(len(units)>1 for units in units_by_feature.values()):return {'status':'unsupported_design','reason':'PCA will not pool feature values with incompatible or missing units'}
 if len(matrix)<3:return {'status':'insufficient_data','n':len(matrix),'reason':'At least three complete observations are required'}
 means=[statistics.fmean(row[j] for row in matrix) for j in range(len(names))]; sds=[statistics.stdev(row[j] for row in matrix) or 1. for j in range(len(names))]; z=[[(row[j]-means[j])/sds[j] for j in range(len(names))] for row in matrix]
 cov=[[sum(row[i]*row[j] for row in z)/(len(z)-1) for j in range(len(names))] for i in range(len(names))]
 vectors=[]; eigen=[]
 for comp in range(dimensions):
  v=[1/math.sqrt(len(names))]*len(names)
  for _ in range(300):
   nxt=[sum(cov[i][j]*v[j] for j in range(len(names))) for i in range(len(names))]
   for old in vectors:
    dot=sum(a*b for a,b in zip(nxt,old)); nxt=[a-dot*b for a,b in zip(nxt,old)]
   norm=math.sqrt(sum(a*a for a in nxt))
   if norm<1e-12:break
   nxt=[a/norm for a in nxt]
   if min(sum((a-b)**2 for a,b in zip(v,nxt)),sum((a+b)**2 for a,b in zip(v,nxt)))<1e-16:v=nxt;break
   v=nxt
  lam=sum(v[i]*sum(cov[i][j]*v[j] for j in range(len(names))) for i in range(len(names)))
  if lam<=1e-12:break
  vectors.append(v);eigen.append(lam)
 total=sum(max(0.,cov[i][i]) for i in range(len(names))) or 1.
 scores=[[sum(row[j]*v[j] for j in range(len(names))) for v in vectors] for row in z]
 import hashlib
 return {'status':'succeeded','method':'standardized PCA via power iteration','features':names,'n':len(matrix),'components':[{'eigenvalue':v,'explained_variance_ratio':v/total,'loadings':dict(zip(names,vec))} for v,vec in zip(eigen,vectors)],'scores':[{'opaque_record_token':hashlib.sha256(t.encode()).hexdigest()[:16],'coordinates':s} for t,s in zip(tokens,scores)],'modality_policy':policy,'warning':'Exploratory projection; components are not validated constructs.'}

def outlier_generation(records,p,policy='best_available'):
 features=p.get('features') or []; factor=float(p.get('iqr_factor',1.5)); limit=max(1,min(100,int(p.get('max_generated',20))))
 if not features or not finite(factor) or factor<=0:raise AnalysisError('invalid_outlier_generation','features and positive iqr_factor are required')
 generated=[]
 for name in features:
  rows,_=_values(records,name,policy,float(p.get('gaze_min_quality',.5))); vals=sorted(x[0] for x in rows)
  if len({unit for _,unit,_ in rows})>1:continue
  if len(vals)<4:continue
  q1=vals[int((len(vals)-1)*.25)];q3=vals[int((len(vals)-1)*.75)];iqr=q3-q1
  if not iqr:continue
  for side,bound in [('low',q1-factor*iqr),('high',q3+factor*iqr)]:
   generated.append({'feature':name,'value':bound,'unit':rows[0][1],'synthetic':True,'generation_rule':f'{side} 1.5-IQR candidate boundary'})
   if len(generated)>=limit:break
  if len(generated)>=limit:break
 return {'status':'succeeded' if generated else 'insufficient_data','synthetic_outliers':generated,'n':len(generated),'modality_policy':policy,'warning':'Generated boundary cases are synthetic stress-test data, not participant observations; never merge into research measurements.'}

def temporal_analysis(records,p,policy='best_available'):
 feature=p.get('feature'); time_field=p.get('timestamp_field','occurred_at')
 if not feature:raise AnalysisError('invalid_temporal_analysis','feature is required')
 rows,_=_values(records,feature,policy,float(p.get('gaze_min_quality',.5))); by=defaultdict(list)
 from datetime import datetime
 for value,unit,rec in rows:
  stamp=rec.get(time_field)
  if not stamp:continue
  try:t=datetime.fromisoformat(str(stamp).replace('Z','+00:00')).timestamp()
  except ValueError:continue
  group=str(rec.get('session_id') or rec.get('participant_id') or 'all');by[group].append((t,value,unit))
 trends={}
 for group,vals in by.items():
  vals.sort();
  if len(vals)<3:continue
  ts=[x[0] for x in vals];vs=[x[1] for x in vals]; mt=statistics.fmean(ts);mv=statistics.fmean(vs);den=sum((t-mt)**2 for t in ts)
  if not den:continue
  slope=sum((t-mt)*(v-mv) for t,v in zip(ts,vs))/den
  trends[group]={'n':len(vals),'slope_per_second':slope,'unit':vals[0][2],'start':vals[0][0],'end':vals[-1][0]}
 return {'status':'succeeded' if trends else 'insufficient_data','feature':feature,'timestamp_field':time_field,'group_n':len(trends),'trends':trends,'warning':'Exploratory within-session linear trend summary, not a temporal prediction model.'}

def cross_validation(records,p,policy='best_available'):
 from .advanced import run_experiment
 groups=sorted({str(r.get('participant_id') or r.get('session_id') or r.get('record_id') or f'row-{i}') for i,r in enumerate(records)})
 folds=max(3,min(len(groups),int(p.get('folds',5))))
 if len(groups)<folds+2:return {'status':'insufficient_data','reason':'Grouped cross-validation requires at least folds+2 independent groups','group_n':len(groups),'folds':folds}
 rng=random.Random(int(p.get('seed',0)));rng.shuffle(groups);buckets=[groups[i::folds] for i in range(folds)]; scores=[]
 for i,test_groups in enumerate(buckets):
  result=run_experiment(records,{**p,'_test_groups':test_groups},policy)
  if result.get('status')!='succeeded':scores.append({'fold':i+1,'status':'insufficient_data','reason':result.get('reason')});continue
  results=result['baseline_comparison']; task=result['experiment']['task']; metric='rmse' if task=='regression' else 'balanced_accuracy'
  scores.append({'fold':i+1,'status':'succeeded','test_group_n':result['experiment']['test_group_n'],'models':{name:{'metric':metric,'value':model['metrics'].get(metric)} for name,model in results.items()}})
 valid=[x for x in scores if x['status']=='succeeded']
 return {'status':'succeeded' if valid else 'insufficient_data','method':'grouped cross-validation','folds':scores,'fold_count':folds,'seed':p.get('seed',0),'warning':'Outer fold groups are held out; preprocessing is fit on each fold training set. Hyperparameter selection requires nested validation for unbiased estimates.'}

def model_selection(records,p,policy='best_available'):
 from .advanced import run_experiment
 if not p.get('_inner_selection'):
  groups=sorted({str(r.get('participant_id') or r.get('session_id') or r.get('record_id') or f'row-{i}') for i,r in enumerate(records)})
  outer_folds=max(3,min(int(p.get('outer_folds',3)),max(3,len(groups)//3)))
  if len(groups)>=outer_folds+6:
   rng=random.Random(int(p.get('seed',0)));rng.shuffle(groups);buckets=[groups[i::outer_folds] for i in range(outer_folds)];nested=[]
   for index,outer_test in enumerate(buckets):
    outer_train=[r for i,r in enumerate(records) if str(r.get('participant_id') or r.get('session_id') or r.get('record_id') or f'row-{i}') not in set(outer_test)]
    inner=model_selection(outer_train,{**p,'_inner_selection':True},policy)
    if inner.get('status')!='succeeded':nested.append({'fold':index+1,'status':'insufficient_data','reason':inner.get('reason')});continue
    evaluated=run_experiment(records,{**p,'models':[inner['best_model']],'alpha':inner['best_alpha'],'_test_groups':outer_test},policy)
    if evaluated.get('status')!='succeeded':nested.append({'fold':index+1,'status':'insufficient_data','reason':evaluated.get('reason')});continue
    metric='rmse' if evaluated['experiment']['task']=='regression' else 'balanced_accuracy';value=evaluated['baseline_comparison'][inner['best_model']]['metrics'].get(metric)
    nested.append({'fold':index+1,'status':'succeeded','inner_selected_model':inner['best_model'],'inner_selected_alpha':inner['best_alpha'],'outer_metric':metric,'outer_value':value,'outer_test_group_n':evaluated['experiment']['test_group_n']})
   valid=[f for f in nested if f.get('status')=='succeeded' and f.get('outer_value') is not None]
   if valid:
    votes=Counter((f['inner_selected_model'],f['inner_selected_alpha']) for f in valid);selected,count=votes.most_common(1)[0]
    return {'status':'succeeded','validation_strategy':'nested_grouped_cross_validation','best_model':selected[0],'best_alpha':selected[1],'selection_frequency':count/len(valid),'outer_fold_results':nested,'outer_metric_mean':statistics.fmean(f['outer_value'] for f in valid),'warning':'Outer folds estimate the complete inner selection procedure. Final refit is left to the authorized experiment runner.'}
   return {'status':'insufficient_data','validation_strategy':'nested_grouped_cross_validation','outer_fold_results':nested,'reason':'No outer fold produced a valid selected-model evaluation'}
 models=p.get('candidate_models',['ridge'] if p.get('task','regression')=='regression' else ['logistic'])
 alphas=p.get('alpha_grid',[.01,.1,1.,10.]);
 if not isinstance(models,list) or not models or any(m not in {'ridge','logistic','ensemble'} for m in models):raise AnalysisError('invalid_model_selection','candidate_models must use ridge, logistic, or ensemble')
 if not isinstance(alphas,list) or not alphas or any(not finite(a) or a<=0 for a in alphas):raise AnalysisError('invalid_model_selection','alpha_grid must contain positive finite values')
 runs=[]
 for model in models:
  for alpha in alphas:
   try:
    result=run_experiment(records,{**p,'models':[model],'alpha':alpha},policy)
    if result.get('status')!='succeeded':runs.append({'model':model,'alpha':alpha,'status':result.get('status'),'reason':result.get('reason')});continue
    task=result['experiment']['task'];metric='rmse' if task=='regression' else 'balanced_accuracy'; candidate=result['baseline_comparison'].get(model,{}).get('metrics',{}).get(metric)
    if candidate is None:runs.append({'model':model,'alpha':alpha,'status':'insufficient_data','reason':'Selected candidate metric unavailable'});continue
    value=candidate;runs.append({'model':model,'alpha':alpha,'status':'succeeded','metric':metric,'value':value,'result':result})
   except AnalysisError as e:runs.append({'model':model,'alpha':alpha,'status':'unsupported','reason':str(e)})
 valid=[r for r in runs if r['status']=='succeeded']
 if not valid:return {'status':'insufficient_data','candidates':[{k:v for k,v in r.items() if k!='result'} for r in runs],'reason':'No candidate model could be evaluated'}
 lower_is_better=valid[0]['metric']=='rmse';best=sorted(valid,key=lambda r:(r['value'] if lower_is_better else -r['value'],r['model'],r['alpha']))[0]
 return {'status':'succeeded','selection_criterion':best['metric'],'best_model':best['model'],'best_alpha':best['alpha'],'best_value':best['value'],'selected_result':best['result'],'candidates':[{k:v for k,v in r.items() if k!='result'} for r in runs],'warning':'Selection uses the held-out evaluation score and is optimistic; use nested grouped CV for confirmatory model comparison.'}
