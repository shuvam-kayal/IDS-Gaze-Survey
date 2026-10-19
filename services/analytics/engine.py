"""Person 4 analytics engine: validated FeatureRecord input, modality-aware statistics, reports and persistence."""
from __future__ import annotations
import base64,hashlib,json,math,random,re,statistics,sqlite3,uuid
from contextlib import contextmanager
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
ANALYSIS_VERSION='p4-analytics/1.0.0'
SUPPORTED={'descriptive','correlation','group_comparison','paired_comparison','multiple_comparison','baseline','ml_experiment','modality_comparison','clustering','aoi_summary','aoi_comparison','discrepancy','gaze_interaction_comparison','attention_importance_comparison','heatmap','report','anomaly_detection','dimensionality_reduction','feature_selection','outlier_generation','temporal_analysis','cross_validation','model_selection'}
GAZE_WORDS=('gaze','fixation','dwell','ttff','attention','aoi','scanpath','saccade','heatmap')
class AnalysisError(ValueError):
 def __init__(self,code,message,status='invalid_request'): super().__init__(message); self.code=code; self.status=status
def finite(v): return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(float(v))
def ident(v,n):
 if not isinstance(v,str) or not v.strip() or len(v)>200: raise AnalysisError('invalid_field',f'{n} must be a non-empty string of at most 200 characters')
 return v.strip()
def parts(raw):
 if isinstance(raw,dict): return raw.get('value'),raw.get('unit'),raw.get('modality'),raw.get('type') or raw.get('kind'),raw.get('aoi_id')
 return raw,None,None,None,None
def is_gaze(name,modality=None): return str(modality or '').lower()=='gaze' or any(w in name.lower() for w in GAZE_WORDS)
def incompatible_units(rows):
 units={r.get('unit') for r in rows if r.get('value') is not None}
 return len(units)>1
def quality_for(record,name,raw):
 value=raw.get('quality') if isinstance(raw,dict) else None
 if value is None and isinstance(record.get('feature_quality'),dict):value=record['feature_quality'].get(name)
 return value
def record_key(record,index):
 return str(record.get('record_id') or f"{record.get('session_id') or 'record'}#{index}")
def validate_request(r):
 if not isinstance(r,dict): raise AnalysisError('invalid_request','Request body must be a JSON object')
 allowed={'request_id','study_id','feature_set_version','modality_policy','analysis_types','parameters','feature_records'}
 unknown=sorted(set(r)-allowed)
 if unknown:raise AnalysisError('unknown_fields','Unsupported request field(s): '+', '.join(unknown))
 for k in ('request_id','study_id','feature_set_version','modality_policy','analysis_types'):
  if k not in r: raise AnalysisError('missing_fields',f'Missing required field: {k}')
 out=dict(r)
 for k in ('request_id','study_id','feature_set_version'): out[k]=ident(r[k],k)
 if r['modality_policy'] not in {'best_available','gaze_only','non_gaze_only'}: raise AnalysisError('unsupported_modality_policy','modality_policy must be best_available, gaze_only, or non_gaze_only')
 if not isinstance(r['analysis_types'],list) or not r['analysis_types'] or any(not isinstance(x,str) for x in r['analysis_types']): raise AnalysisError('invalid_analysis_types','analysis_types must be a non-empty list of strings')
 if len(set(r['analysis_types']))!=len(r['analysis_types']):raise AnalysisError('invalid_analysis_types','analysis_types must not contain duplicates')
 bad=sorted(set(r['analysis_types'])-SUPPORTED)
 if bad: raise AnalysisError('unsupported_analysis',f'Unsupported analysis type(s): {", ".join(bad)}')
 if not isinstance(r.get('parameters',{}),dict): raise AnalysisError('invalid_parameters','parameters must be an object')
 if not isinstance(r.get('feature_records',[]),list): raise AnalysisError('invalid_feature_records','feature_records must be a list')
 out['parameters']=r.get('parameters',{}); out['feature_records']=r.get('feature_records',[]); return out
def validate_result(r):
 required={'schema_version','result_id','request_id','request_fingerprint','study_id','status','analysis_version','generated_at','data_scope','metadata','results','warnings','limitations'}
 missing=required-set(r) if isinstance(r,dict) else required
 if missing:raise AnalysisError('invalid_result','AnalysisResult is missing: '+', '.join(sorted(missing)),'failed')
 if r.get('schema_version')!='1.0.0' or r['status'] not in {'succeeded','no_data','insufficient_data'}:raise AnalysisError('invalid_result','AnalysisResult has an unsupported schema version or status','failed')
 for key in ('request_id','study_id','analysis_version'):
  if not isinstance(r.get(key),str) or not r[key].strip():raise AnalysisError('invalid_result',f'AnalysisResult {key} must be a non-empty string','failed')
 try:uuid.UUID(r['result_id'])
 except (ValueError,TypeError,AttributeError):raise AnalysisError('invalid_result','AnalysisResult result_id must be a UUID','failed')
 if not re.fullmatch(r'[a-f0-9]{64}',str(r['request_fingerprint'])):raise AnalysisError('invalid_result','AnalysisResult request_fingerprint must be a SHA-256 hex digest','failed')
 if not isinstance(r['data_scope'],dict) or not isinstance(r['metadata'],dict) or not isinstance(r['results'],dict):raise AnalysisError('invalid_result','AnalysisResult scope, metadata and results must be objects','failed')
 scope_required={'study_id','feature_set_version','record_n','record_fingerprint','feature_versions'}
 meta_required={'modality','modality_policy','sample_size','analysis_unit','unique_unit_n','feature_names','gaze_values_excluded'}
 if scope_required-set(r['data_scope']) or meta_required-set(r['metadata']):raise AnalysisError('invalid_result','AnalysisResult scope or metadata is missing required contract fields','failed')
 if r['data_scope']['study_id']!=r['study_id'] or not all(isinstance(r['data_scope'][k],str) for k in ('feature_set_version','record_fingerprint')) or not isinstance(r['data_scope']['feature_versions'],list) or not isinstance(r['data_scope']['record_n'],int) or r['data_scope']['record_n']<0:raise AnalysisError('invalid_result','AnalysisResult data scope has invalid field types or inconsistent Study ID','failed')
 if r['metadata']['modality'] not in {'gaze','non_gaze','mixed'} or r['metadata']['modality_policy'] not in {'best_available','gaze_only','non_gaze_only'} or not isinstance(r['metadata']['sample_size'],int) or r['metadata']['sample_size']<0 or not isinstance(r['metadata']['unique_unit_n'],int) or r['metadata']['unique_unit_n']<0 or not isinstance(r['metadata']['feature_names'],list) or not isinstance(r['metadata']['gaze_values_excluded'],int):raise AnalysisError('invalid_result','AnalysisResult metadata contains invalid values','failed')
 if not isinstance(r['warnings'],list) or not all(isinstance(x,str) for x in r['warnings']) or not isinstance(r['limitations'],list) or not all(isinstance(x,str) for x in r['limitations']):raise AnalysisError('invalid_result','AnalysisResult warnings and limitations must be string arrays','failed')
 try:datetime.fromisoformat(str(r['generated_at']).replace('Z','+00:00'))
 except (ValueError,TypeError):raise AnalysisError('invalid_result','AnalysisResult generated_at must be an ISO-8601 timestamp','failed')
 return r
def scope_records(records,req):
 out=[]; warnings=[]
 for i,r in enumerate(records):
  if not isinstance(r,dict): warnings.append(f'Record {i} is not an object and was excluded'); continue
  if r.get('study_id') not in (None,req['study_id']): continue
  if r.get('study_id') is None:warnings.append(f'Record {i} has no study_id; request scope cannot be independently verified')
  if r.get('feature_set_version') not in (None,req['feature_set_version']): raise AnalysisError('feature_version_mismatch',f'Record {i} feature_set_version does not match the requested version')
  if r.get('feature_set_version') is None:warnings.append(f'Record {i} has no feature_set_version; compatibility is assumed from the authorized store query')
  if not isinstance(r.get('features'),dict): warnings.append(f'Record {i} has no features object and was excluded'); continue
  out.append(r)
 return out,warnings
def filter_records(records,params):
 f=params.get('filters') or {}
 if not isinstance(f,dict):raise AnalysisError('invalid_filters','parameters.filters must be an object')
 allowed={'participant_ids','session_ids','record_ids','group_field','group_values','time_from','time_to','timestamp_field'}
 extra=set(f)-allowed
 if extra:raise AnalysisError('invalid_filters','Unsupported filter(s): '+', '.join(sorted(extra)))
 def dt(value,label):
  if value is None:return None
  try:
   parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
   return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
  except (ValueError,OverflowError):raise AnalysisError('invalid_filters',label+' must be an ISO-8601 timestamp')
 start=dt(f.get('time_from'),'time_from'); end=dt(f.get('time_to'),'time_to')
 if start and end and start>end:raise AnalysisError('invalid_filters','time_from must not be after time_to')
 id_fields={'participant_ids':'participant_id','session_ids':'session_id','record_ids':'record_id'}
 for key in id_fields:
  if key in f and not isinstance(f[key],list):raise AnalysisError('invalid_filters',key+' must be a list')
 ids={id_fields[key]:set(map(str,f[key])) for key in id_fields if key in f}
 if 'group_values' in f and not isinstance(f['group_values'],list):raise AnalysisError('invalid_filters','group_values must be a list')
 gf=f.get('group_field'); gv=set(map(str,f.get('group_values',[]))) if 'group_values' in f else None
 if bool(gf)!=bool(gv):raise AnalysisError('invalid_filters','group_field and non-empty group_values must be supplied together')
 if gv is not None and not gv:raise AnalysisError('invalid_filters','group_values cannot be empty')
 tf=f.get('timestamp_field','occurred_at')
 if not isinstance(tf,str):raise AnalysisError('invalid_filters','timestamp_field must be a feature or record field name')
 selected=[]
 for r in records:
  if any(str(r.get(k,'')) not in vals for k,vals in ids.items()):continue
  if gv is not None:
   val=r.get('features',{}).get(gf,r.get(gf)); val=parts(val)[0] if isinstance(val,dict) else val
   if str(val) not in gv:continue
  bound=start or end
  if bound:
   raw=r.get(tf)
   if raw is None:continue
   when=dt(raw,tf)
   if start and when<start or end and when>end:continue
  selected.append(r)
 selection_fingerprint=hashlib.sha256(json.dumps(f,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
 return selected,{'enabled':bool(f),'input_record_n':len(records),'selected_record_n':len(selected),'excluded_record_n':len(records)-len(selected),'has_time_filter':bool(start or end),'time_from':f.get('time_from'),'time_to':f.get('time_to'),'timestamp_field':tf if start or end else None,'has_group_filter':gv is not None,'group_field':gf if gv is not None else None,'group_values':sorted(gv) if gv is not None else None,'has_id_filter':bool(ids),'selection_fingerprint':selection_fingerprint}
def modality_of(records):
 m=set()
 for r in records:
  raw=r.get('modality',r.get('modalities',[])); m.update([raw.lower()] if isinstance(raw,str) else [str(x).lower() for x in raw] if isinstance(raw,list) else [])
 g=any('gaze' in x for x in m); ng=any(x in {'interaction','survey','timing','non_gaze','non-gaze'} for x in m)
 return 'mixed' if g and ng else 'gaze' if g else 'non_gaze'
def collect(records,policy,params):
 fields=defaultdict(list); warnings=[]; excluded=0; low_quality=0; missing_quality=0; include=params.get('features'); min_quality=params.get('gaze_min_quality',.5)
 if not finite(min_quality) or not 0<=float(min_quality)<=1:raise AnalysisError('invalid_quality_threshold','gaze_min_quality must be between 0 and 1')
 if include is not None and (not isinstance(include,list) or any(not isinstance(x,str) for x in include)): raise AnalysisError('invalid_feature_selection','parameters.features must be a list of names')
 contextual=[params.get(k) for k in ('group_by','x','y','feature','target','gaze_feature','survey_feature') if isinstance(params.get(k),str)]
 selected_names=include if include is not None else sorted({name for rec in records for name in rec.get('features',{})})
 names=list(dict.fromkeys(selected_names+contextual))
 for rec_index,rec in enumerate(records):
  row_key=record_key(rec,rec_index)
  for name in names:
   raw=rec['features'].get(name,rec.get(name))
   val,unit,mod,kind,aoi=parts(raw); gaze=is_gaze(name,mod)
   if policy=='gaze_only' and not gaze: continue
   if policy=='non_gaze_only' and gaze: excluded+=1; continue
   quality=quality_for(rec,name,raw) if gaze else None
   quality_excluded=False
   if quality is not None:
    if not finite(quality) or not 0<=float(quality)<=1:raise AnalysisError('invalid_feature_quality',f'Feature {name} quality must be a number between 0 and 1')
    if gaze and float(quality)<float(min_quality):val=None; low_quality+=1; quality_excluded=True
   elif gaze and val is not None:missing_quality+=1
   if gaze and val is None and not quality_excluded:excluded+=1
   group=str(rec.get('participant_id') or rec.get('session_id') or rec.get('record_id') or row_key)
   fields[name].append({'value':val,'unit':unit if isinstance(unit,str) else None,'modality':'gaze' if gaze else mod or 'non_gaze','kind':kind,'aoi_id':aoi,'row':row_key,'group':group,'record':rec,'quality':quality})
 if not fields: warnings.append('No features are available for the requested modality policy')
 if excluded: warnings.append(f'{excluded} gaze feature value(s) were missing, below quality threshold, or excluded by modality policy')
 if low_quality:warnings.append(f'{low_quality} gaze feature value(s) were below gaze_min_quality={float(min_quality):g} and were excluded')
 if missing_quality:warnings.append(f'Quality was not supplied for {missing_quality} observed gaze feature value(s); their quality could not be assessed')
 names=[n for n,rs in fields.items() if any(x['value'] is not None for x in rs)]
 observed_modalities={r['modality'] for rows in fields.values() for r in rows if r['value'] is not None}
 modality='gaze' if policy=='gaze_only' else 'non_gaze' if policy=='non_gaze_only' else ('mixed' if 'gaze' in observed_modalities and len(observed_modalities)>1 else 'gaze' if 'gaze' in observed_modalities else 'non_gaze')
 return fields,{'modality':modality,'feature_names':sorted(names),'gaze_values_excluded':excluded,'gaze_low_quality_excluded':low_quality,'gaze_quality_missing_n':missing_quality,'gaze_min_quality':float(min_quality)},warnings
def summary(rows):
 vals=[float(x['value']) for x in rows if finite(x['value'])]; missing=len(rows)-len(vals); source_n=sum(x.get('source_observation_n',1) for x in rows); source_missing=sum(x.get('source_missing_n',0) for x in rows)
 present=[x['value'] for x in rows if x['value'] is not None]; types={'numeric' if finite(v) else 'boolean' if isinstance(v,bool) else 'categorical' for v in present}
 if len(types)>1:return {'kind':'mixed','n':len(present),'missing_n':len(rows)-len(present),'source_observation_n':source_n,'source_missing_observation_n':source_missing,'type_counts':dict(Counter('numeric' if finite(v) else 'boolean' if isinstance(v,bool) else 'categorical' for v in present)),'unit':None}
 if vals:
  s=sorted(vals)
  def q(p):
   pos=(len(s)-1)*p; lo=int(pos); hi=min(lo+1,len(s)-1); f=pos-lo; return s[lo]*(1-f)+s[hi]*f
  return {'kind':'numeric','n':len(vals),'missing_n':missing,'unit_n':len({x['group'] for x in rows if x['value'] is not None}),'source_observation_n':source_n,'source_missing_observation_n':source_missing,'mean':statistics.fmean(vals),'median':statistics.median(vals),'sd':statistics.stdev(vals) if len(vals)>1 else None,'min':min(vals),'max':max(vals),'quantiles':{'q25':q(.25),'q75':q(.75)},'unit':next((x['unit'] for x in rows if x['unit']),None),'modality':rows[0]['modality']}
 cats=Counter(str(x['value']) for x in rows if x['value'] is not None); n=sum(cats.values())
 if not n:return {'kind':'unavailable','n':0,'missing_n':missing,'source_observation_n':source_n,'source_missing_observation_n':source_missing,'unit':next((x['unit'] for x in rows if x['unit']),None)}
 return {'kind':'categorical','n':n,'missing_n':missing,'unit_n':len({x['group'] for x in rows if x['value'] is not None}),'source_observation_n':source_n,'source_missing_observation_n':source_missing,'counts':dict(sorted(cats.items())),'proportions':{k:v/n for k,v in sorted(cats.items())} if n else {},'unit':None}
def aggregate_rows(rows,unit):
 if unit in (None,'feature_record'):return rows
 key={'participant':'participant_id','session':'session_id','trial':'trial_id'}.get(unit)
 if key is None:raise AnalysisError('unsupported_summary_unit','summary_unit must be feature_record, participant, session, or trial')
 grouped=defaultdict(list)
 for row in rows:
  rec=row['record']; identity=rec.get(key)
  if identity is not None:grouped[str(identity)].append(row)
 out=[]
 for identity,values in sorted(grouped.items()):
  observed=[v['value'] for v in values if v['value'] is not None]
  if observed and all(finite(v) for v in observed):value=statistics.fmean(float(v) for v in observed)
  elif observed:
   counts=Counter(map(str,observed)); value=sorted(k for k,n in counts.items() if n==max(counts.values()))[0]
  else:value=None
  first=values[0]; out.append({**first,'value':value,'group':identity,'row':identity,'source_observation_n':len(values),'source_missing_n':len(values)-len(observed),'record':first['record']})
 return out
def discrepancy(fields,parameters,other_kind='survey'):
 gaze=parameters.get('gaze_feature'); other=parameters.get('survey_feature') or parameters.get('interaction_feature') or parameters.get('importance_feature')
 if not gaze or not other or gaze not in fields or other not in fields:return {'status':'insufficient_data','reason':f'Select gaze_feature and {other_kind}_feature from the available features'}
 if not any(r['modality']=='gaze' for r in fields[gaze]):return {'status':'invalid_request','reason':'gaze_feature must be a gaze-derived FeatureRecord'}
 if other_kind=='interaction' and not any(r['modality']=='interaction' for r in fields[other]):return {'status':'invalid_request','reason':'interaction_feature must be interaction-derived'}
 if other_kind=='importance' and any(r['modality']=='gaze' for r in fields[other]):return {'status':'invalid_request','reason':'importance_feature must be a non-gaze measure'}
 if len({r['unit'] for r in fields[gaze]})>1 or len({r['unit'] for r in fields[other]})>1:return {'status':'insufficient_data','reason':'Features with mixed or missing units cannot be standardized safely'}
 gmap={r['row']:r['value'] for r in fields[gaze] if finite(r['value'])}; smap={r['row']:r['value'] for r in fields[other] if finite(r['value'])}; pairs=[(float(gmap[k]),float(smap[k])) for k in sorted(set(gmap)&set(smap))]
 if len(pairs)<3:return {'status':'insufficient_data','reason':'At least three paired records are required','n':len(pairs)}
 gx,sy=map(list,zip(*pairs)); gm,sm=statistics.fmean(gx),statistics.fmean(sy); gd=statistics.stdev(gx) if len(gx)>1 else 0.; sd=statistics.stdev(sy) if len(sy)>1 else 0.
 if not gd or not sd:return {'status':'insufficient_data','reason':'Both features must vary to compare standardized discrepancies','n':len(pairs)}
 gz=[(x-gm)/gd for x in gx]; sz=[(x-sm)/sd for x in sy]; delta=[b-a for a,b in zip(gz,sz)]; relationship=correlation(fields,{'x':gaze,'y':other,'method':'spearman'})
 return {'status':'succeeded','gaze_feature':gaze,'comparison_feature':other,'comparison_kind':{'survey':'gaze_vs_self_report','interaction':'gaze_vs_interaction','importance':'attention_vs_stated_importance'}[other_kind],'survey_feature':other if other_kind=='survey' else None,'n':len(pairs),'missing_pair_n':max(len(fields[gaze]),len(fields[other]))-len(pairs),'standardization':'within-selected-sample z scores; positive discrepancy means comparison-feature z score exceeds gaze-feature z score','mean_standardized_discrepancy':statistics.fmean(delta),'sd_standardized_discrepancy':statistics.stdev(delta) if len(delta)>1 else None,'spearman_association':relationship,'interpretation_limit':'Exploratory disagreement measure; different constructs and scales are not interchangeable, and discrepancy is not a validated psychological score.'}
def betacf(a,b,x):
 qab=a+b; qap=a+1; qam=a-1; c=1.; d=1-qab*x/qap; d=1e-30 if abs(d)<1e-30 else d; d=1/d; h=d
 for m in range(1,201):
  m2=2*m; aa=m*(b-m)*x/((qam+m2)*(a+m2)); d=1+aa*d; d=1e-30 if abs(d)<1e-30 else d; c=1+aa/c; c=1e-30 if abs(c)<1e-30 else c; d=1/d; h*=d*c
  aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2)); d=1+aa*d; d=1e-30 if abs(d)<1e-30 else d; c=1+aa/c; c=1e-30 if abs(c)<1e-30 else c; d=1/d; delta=d*c; h*=delta
  if abs(delta-1)<3e-14: break
 return h
def ibeta(a,b,x):
 if x<=0:return 0.
 if x>=1:return 1.
 bt=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
 return bt*betacf(a,b,x)/a if x<(a+1)/(a+b+2) else 1-bt*betacf(b,a,1-x)/b
def tp(t,df): return min(1.,max(0.,ibeta(df/2,.5,df/(df+t*t)))) if df>0 else 1.
def corr(x,y):
 if len(x)<2:return None
 mx=statistics.fmean(x); my=statistics.fmean(y); dx=[v-mx for v in x]; dy=[v-my for v in y]; sx=math.sqrt(sum(v*v for v in dx)); sy=math.sqrt(sum(v*v for v in dy))
 return sum(a*b for a,b in zip(dx,dy))/(sx*sy) if sx and sy else None
def ranks(v):
 ix=sorted(range(len(v)),key=v.__getitem__); out=[0.]*len(v); i=0
 while i<len(ix):
  j=i+1
  while j<len(ix) and v[ix[j]]==v[ix[i]]:j+=1
  for k in ix[i:j]:out[k]=(i+1+j)/2
  i=j
 return out
def correlation(fields,p):
 names=p.get('features') or list(fields); xn=p.get('x') or (names[0] if names else None); yn=p.get('y') or (names[1] if len(names)>1 else None)
 if xn not in fields or yn not in fields:return {'status':'insufficient_data','reason':'Select two available numeric features','n':0}
 if any(incompatible_units(fields[n]) for n in (xn,yn)):return {'status':'insufficient_data','reason':'Selected feature contains mixed or missing units among observed values','n':0}
 ymap={r['row']:r['value'] for r in fields[yn] if finite(r['value'])}; pairs=[(float(r['value']),float(ymap[r['row']])) for r in fields[xn] if finite(r['value']) and r['row'] in ymap]
 if len(pairs)<3:return {'status':'insufficient_data','method':'pearson','x':xn,'y':yn,'n':len(pairs),'reason':'At least three paired observations are required'}
 method=str(p.get('method','pearson')).lower()
 if method not in {'pearson','spearman'}:raise AnalysisError('unsupported_correlation','Correlation method must be pearson or spearman')
 x,y=map(list,zip(*pairs)); r=corr(ranks(x),ranks(y)) if method=='spearman' else corr(x,y)
 if r is None:return {'status':'insufficient_data','method':method,'x':xn,'y':yn,'n':len(pairs),'reason':'A feature is constant'}
 df=len(pairs)-2; tstat=abs(r)*math.sqrt(df/max(1e-15,1-r*r)) if abs(r)<1 else float('inf'); pvalue=tp(tstat,df)
 ci=[math.tanh(math.atanh(max(-.999999999,min(.999999999,r)))-1.96/math.sqrt(len(pairs)-3)),math.tanh(math.atanh(max(-.999999999,min(.999999999,r)))+1.96/math.sqrt(len(pairs)-3))] if len(pairs)>3 else None
 return {'status':'succeeded','method':method,'x':xn,'y':yn,'n':len(pairs),'pairwise_complete_n':len(pairs),'pairwise_excluded_n':max(len(fields[xn]),len(fields[yn]))-len(pairs),'missing_data_policy':'pairwise_complete','correlation':r,'p_value':pvalue,'p_value_approximation':'t-distribution approximation','confidence_interval_95':ci,'warnings':['Association only; correlation does not establish causation','Inference and Fisher confidence interval are approximate, especially for Spearman']+(['Small paired sample; estimate is unstable'] if len(pairs)<10 else [])}
def welch(a,b,seed):
 if len(a)<2 or len(b)<2:return {'status':'insufficient_data','n_a':len(a),'n_b':len(b),'reason':'Each group needs at least two observations'}
 ma,mb=statistics.fmean(a),statistics.fmean(b); va,vb=statistics.variance(a),statistics.variance(b); se2=va/len(a)+vb/len(b)
 if se2<=0:return {'status':'insufficient_data','n_a':len(a),'n_b':len(b),'reason':'No within-group variation'}
 df=se2**2/((va/len(a))**2/(len(a)-1)+(vb/len(b))**2/(len(b)-1)); t=(ma-mb)/math.sqrt(se2); pooled=math.sqrt(((len(a)-1)*va+(len(b)-1)*vb)/(len(a)+len(b)-2)); rng=random.Random(seed); boot=[]
 for _ in range(1000):boot.append(statistics.fmean(rng.choices(a,k=len(a)))-statistics.fmean(rng.choices(b,k=len(b))))
 boot.sort(); return {'status':'succeeded','method':'welch_t_test','n_a':len(a),'n_b':len(b),'mean_a':ma,'mean_b':mb,'mean_difference':ma-mb,'t':t,'degrees_of_freedom':df,'p_value':tp(t,df),'cohens_d':(ma-mb)/pooled if pooled else None,'bootstrap_95_ci':[boot[24],boot[974]],'warnings':(['Small group; interpret cautiously'] if min(len(a),len(b))<10 else [])}
def group_comparison(fields,p,seed):
 f=p.get('feature'); g=p.get('group_by')
 if f not in fields or g not in fields:return {'status':'insufficient_data','reason':'Set feature and group_by to available features'}
 if incompatible_units(fields[f]):return {'status':'insufficient_data','reason':'Compared feature contains mixed or missing units among observed values'}
 labels={r['row']:r['value'] for r in fields[g] if r['value'] is not None}; grouped=defaultdict(lambda:defaultdict(list)); subject_conditions=defaultdict(set)
 for r in fields[f]:
  if r['row'] in labels and finite(r['value']):
   label=str(labels[r['row']]); grouped[label][r['group']].append(float(r['value'])); subject_conditions[r['group']].add(label)
 if any(len(x)>1 for x in subject_conditions.values()):return {'status':'unsupported_design','reason':'Participants occur in both groups; this independent-groups method cannot treat repeated observations as independent'}
 groups={label:[statistics.fmean(values) for values in people.values()] for label,people in grouped.items()}
 names=sorted(groups)
 if len(names)!=2:return {'status':'insufficient_data','reason':'Exactly two independent groups are supported','group_count':len(names)}
 out=welch(groups[names[0]],groups[names[1]],seed); out.update({'feature':f,'group_by':g,'group_a':names[0],'group_b':names[1],'unit':next((r['unit'] for r in fields[f] if r['unit']),None)}); out.setdefault('warnings',[]).append('Independent-group Welch comparison; verify study design and multiplicity plan'); return out
def split_groups(rows,seed):
 gs=sorted({r['group'] for r in rows}); random.Random(seed).shuffle(gs)
 if len(gs)<3:return set(),set()
 n=max(1,round(len(gs)*.2)); n=min(n,len(gs)-2); return set(gs[n:]),set(gs[:n])
def baseline(fields,p,seed):
 target=p.get('target'); predictors=p.get('features') or [n for n in fields if n!=target]
 if target not in fields:return {'status':'insufficient_data','reason':'Set target to an available feature'}
 ys={r['row']:r for r in fields[target] if r['value'] is not None}; rows=[{'group':r['group'],'row':row,'y':r['value']} for row,r in ys.items()]; train_g,test_g=split_groups(rows,seed)
 if not train_g:return {'status':'insufficient_data','reason':'At least three independent participant/session groups are required for leakage-safe holdout evaluation','n_groups':len(ys)}
 train=[r['y'] for r in rows if r['group'] in train_g]; test=[r['y'] for r in rows if r['group'] in test_g]
 if not train or not test:return {'status':'insufficient_data','reason':'No valid target values in train or held-out groups'}
 numeric=all(finite(v) for v in train+test)
 if numeric:
  pred=statistics.fmean(train); err=[float(v)-pred for v in test]; mean_test=statistics.fmean(float(v) for v in test); den=sum((float(v)-mean_test)**2 for v in test)
  metrics={'mae':statistics.fmean(abs(e) for e in err),'rmse':math.sqrt(statistics.fmean(e*e for e in err)),'r2':1-sum(e*e for e in err)/den if den else None}; baseline_info={'kind':'training_mean_predictor','prediction':pred}; task='regression'
 else:
  pred=Counter(map(str,train)).most_common(1)[0][0]; correct=sum(str(v)==pred for v in test); metrics={'accuracy':correct/len(test),'correct_n':correct}; baseline_info={'kind':'training_majority_class_predictor','prediction':pred}; task='classification'
 grouped=any(r['record'].get('participant_id') for rs in fields.values() for r in rs)
 return {'status':'succeeded','task':task,'target':target,'predictors_requested':predictors,'baseline':baseline_info,'metrics':metrics,'validation':{'strategy':'participant_group_holdout' if grouped else 'session_group_holdout','seed':seed,'train_group_n':len(train_g),'test_group_n':len(test_g),'train_n':len(train),'test_n':len(test)},'warnings':['Transparent baseline only; not evidence of useful predictive performance','Preprocessing/model fitting must be confined to training data']}
def aoi_summary(fields,records=None):
 aois=defaultdict(lambda:defaultdict(list))
 for name,rs in fields.items():
  for r in rs:
   if not finite(r['value']):continue
   aid=r['aoi_id'] or r['record'].get('aoi_id'); m=re.search(r'aoi[:_.-]([^:_.-]+)',name,re.I)
   if not aid and m:aid=m.group(1)
   if aid and any(x in name.lower() for x in ('dwell','ttff','revisit','fixation','attention')):
    metric=name; aois[str(aid)][metric].append({'value':float(r['value']),'unit':r.get('unit')})
 if not aois:return {'status':'unavailable','reason':'No AOI-tagged gaze FeatureRecords are available','aoi_count':0,'missing_geometry_record_n':sum(not isinstance(r.get('spatial'),dict) or not (r['spatial'].get('geometry_version') or r['spatial'].get('aoi_geometry')) for r in (records or []))}
 def distribution(v):
  ordered=sorted(v); bins=max(2,min(20,int(math.sqrt(len(v)) or 2))); lo=ordered[0]; hi=ordered[-1]; counts=[0]*bins
  if lo==hi:counts=[len(v)]
  else:
   for x in v:counts[min(bins-1,int((x-lo)/((hi-lo)/bins)))]+=1
  return {'n':len(v),'min':lo,'max':hi,'q25':ordered[int((len(v)-1)*.25)],'q75':ordered[int((len(v)-1)*.75)],'histogram':counts,'histogram_bins':bins,'range':[lo,hi]}
 out={}
 for a,ms in sorted(aois.items()):
  out[a]={}
  for m,v in ms.items():
   units={x['unit'] for x in v}
   if len(units)>1:out[a][m]={'status':'incompatible_units','n':len(v),'unit_n':len(units),'reason':'AOI values with different or missing units are not pooled'};continue
   vals=[x['value'] for x in v]
   out[a][m]={'status':'succeeded','n':len(v),'mean':statistics.fmean(vals),'median':statistics.median(vals),'unit':next(iter(units)),'distribution':distribution(vals)}
 versions=sorted({str(r.get('spatial',{}).get('geometry_version')) for r in (records or []) if isinstance(r.get('spatial'),dict) and r['spatial'].get('geometry_version')})
 geometry_hashes=set(); configured=set()
 for r in (records or []):
  s=r.get('spatial',{}) if isinstance(r.get('spatial'),dict) else {}; geom=s.get('aoi_geometry',s.get('geometry'))
  if isinstance(geom,(dict,list)):
   geometry_hashes.add(hashlib.sha256(json.dumps(geom,sort_keys=True,default=str).encode()).hexdigest())
   configured.update(map(str,geom.keys())) if isinstance(geom,dict) else None
 missing_geometry=sum(not isinstance(r.get('spatial'),dict) or not (r['spatial'].get('geometry_version') or r['spatial'].get('aoi_geometry')) for r in (records or []))
 observed=set(aois); missing_aois=sorted(observed-configured) if configured else []
 changed=len(versions)>1 or len(geometry_hashes)>1
 return {'status':'succeeded','aoi_count':len(out),'aois':out,'geometry_versions':versions,'geometry_payload_count':len(geometry_hashes),'geometry_changed_during_scope':changed,'missing_geometry_record_n':missing_geometry,'observed_aois_missing_from_geometry':missing_aois,'warnings':['Definitions and AOI geometry versions come from upstream P3 provenance']+(['AOI geometry is missing on some selected records; do not compare their spatial attribution as if geometry were constant'] if missing_geometry else [])+(['AOI geometry changed during the selected scope; disaggregate or inspect versions before comparing'] if changed else [])+([f'{len(missing_aois)} observed AOI(s) are absent from available geometry'] if missing_aois else [])}
def heatmap(records,p,policy='best_available'):
 if policy=='non_gaze_only':return {'status':'unavailable','reason':'Heatmaps require gaze coordinates and are disabled by non_gaze_only modality policy'}
 pts=[]; q=[]; geometries=set(); systems=set(); geometry_payloads={}; quality_excluded_record_n=0; quality_unavailable_record_n=0; contributing=[]
 minimum=int(p.get('heatmap_min_points',20)); threshold=float(p.get('heatmap_min_quality',.5)); size=max(4,min(64,int(p.get('heatmap_grid_size',24))))
 if minimum<1 or not 0<=threshold<=1:raise AnalysisError('invalid_heatmap_settings','heatmap_min_points must be positive and heatmap_min_quality must be between 0 and 1')
 for r in records:
  s=r.get('spatial')
  if not isinstance(s,dict) or not isinstance(s.get('points'),list) or not s['points']:continue
  quality=s.get('quality')
  if quality is None:quality_unavailable_record_n+=1;continue
  if not finite(quality) or not 0<=float(quality)<=1:raise AnalysisError('invalid_spatial_quality','spatial.quality must be a number between 0 and 1')
  if float(quality)<threshold:quality_excluded_record_n+=1;continue
  geometry=s.get('aoi_geometry',s.get('geometry'))
  if s.get('geometry_version'):geometries.add(str(s['geometry_version']))
  if s.get('coordinate_system'):systems.add(str(s['coordinate_system']))
  if isinstance(geometry,(dict,list)):
   geometry_payloads[hashlib.sha256(json.dumps(geometry,sort_keys=True,default=str).encode()).hexdigest()]=geometry
  valid_record_points=[]
  for x in s['points']:
   if isinstance(x,dict) and finite(x.get('x')) and finite(x.get('y')):valid_record_points.append((float(x['x']),float(x['y'])))
  if valid_record_points:
   pts.extend(valid_record_points);q.append(float(quality));contributing.append(r)
 if not pts:return {'status':'unavailable','reason':'No coordinate-level points with an observed quality score at or above threshold are available','required':'coordinate-level gaze, adequate point quality, AOI geometry/version, and coordinate system','quality_excluded_record_n':quality_excluded_record_n,'quality_unavailable_record_n':quality_unavailable_record_n}
 if len(pts)<minimum:return {'status':'insufficient_data','reason':f'Only {len(pts)} quality-approved points; at least {minimum} required','point_n':len(pts),'quality_excluded_record_n':quality_excluded_record_n,'quality_unavailable_record_n':quality_unavailable_record_n}
 if not geometries or not systems or not geometry_payloads:return {'status':'unavailable','reason':'AOI geometry, geometry version, and coordinate system are required','point_n':len(pts)}
 if len(geometries)!=1 or len(systems)!=1:return {'status':'unsupported_design','reason':'Selected records contain different AOI geometry versions or coordinate systems; aggregate them separately','point_n':len(pts),'geometry_versions':sorted(geometries),'coordinate_systems':sorted(systems)}
 if not q:return {'status':'insufficient_data','reason':'Gaze quality is absent or below threshold','quality_mean':None,'threshold':threshold}
 grid=[[0]*size for _ in range(size)]; valid=[]
 for x,y in pts:
  if 0<=x<=1 and 0<=y<=1:grid[min(size-1,int(y*size))][min(size-1,int(x*size))]+=1; valid.append((x,y))
 if len(valid)<minimum:return {'status':'insufficient_data','reason':'Too few normalized coordinates in [0,1]','point_n':len(valid)}
 stable_geometry=len(geometry_payloads)==1; overlay_ok=stable_geometry and next(iter(systems)) in {'normalized_viewport','normalized_screen','normalized'}
 sessions=sorted({str(r.get('session_id')) for r in contributing if r.get('session_id')})
 return {'status':'succeeded','coordinate_system':next(iter(systems)),'geometry_version':next(iter(geometries)),'aggregation_scope':'all quality-approved selected sessions','session_n':len(sessions),'point_n':len(valid),'quality_mean':statistics.fmean(q),'quality_threshold':threshold,'quality_excluded_record_n':quality_excluded_record_n,'quality_unavailable_record_n':quality_unavailable_record_n,'grid_size':size,'counts':grid,'aoi_geometry':next(iter(geometry_payloads.values())) if stable_geometry else None,'geometry_payload_count':len(geometry_payloads),'overlay_status':'available' if overlay_ok else 'unavailable_geometry_changed_or_non_normalized','warnings':['Binned observed counts do not imply gaze certainty between samples']+(['Some selected records had no quality score; their points were excluded'] if quality_unavailable_record_n else [])+(['Some records fell below the heatmap quality threshold and were excluded'] if quality_excluded_record_n else [])+(['AOI geometry changed within the selected records; the heatmap is shown without an AOI overlay'] if not stable_geometry else [])}
def json_pointer(*parts):
 return '/'+'/'.join(str(x).replace('~','~0').replace('/','~1') for x in parts)
def make_report(req,result):
 recs=[]
 for name,s in result['results'].get('descriptive',{}).items():
  if s.get('missing_n',0):recs.append({'type':'data_quality_observation','text':f"{name} has {s['missing_n']} missing values among {s['n']+s['missing_n']} analysis units.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','descriptive',name,'missing_n'),'result_section':'descriptive','metric':name,'field':'missing_n','value':s['missing_n']},'claim_level':'descriptive','automated_suggestion':True})
  if s.get('kind')=='numeric' and s.get('n',0)>=5 and s.get('mean',0)>0 and any(token in name.lower() for token in ('friction','error_rate','retry','abandon','latency')):
   recs.append({'type':'interaction_friction_observation','text':f"{name} has a positive mean ({s['mean']:.3g}, n={s['n']}); inspect the relevant page or interaction context before drawing a design conclusion.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','descriptive',name,'mean'),'metric':name,'value':s['mean'],'n':s['n']},'claim_level':'descriptive','automated_suggestion':True})
  by_group=s.get('by_group',{})
  numeric_groups={label:value for label,value in by_group.items() if value.get('kind')=='numeric' and value.get('n',0)>0}
  if len(numeric_groups)>=2:
   labels=sorted(numeric_groups,key=lambda label:numeric_groups[label]['mean'])
   low,high=labels[0],labels[-1]
   if low!=high:
    group_field=result['data_scope'].get('analysis_parameters',{}).get('group_by','group')
    recs.append({'type':'group_comparison_observation','text':f"For {name}, {group_field}={high} has the highest observed mean ({numeric_groups[high]['mean']:.3g}, n={numeric_groups[high]['n']}) and {group_field}={low} the lowest ({numeric_groups[low]['mean']:.3g}, n={numeric_groups[low]['n']}). This is descriptive; review the design and uncertainty before interpretation.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','descriptive',name,'by_group'),'metric':name,'group_field':group_field,'high_group':high,'low_group':low},'claim_level':'descriptive','automated_suggestion':True})
 aois=result['results'].get('aoi_summary',{}).get('aois',{}); dwell=[]
 for aid,metrics in aois.items():
  measure=next((v for k,v in metrics.items() if 'dwell' in k.lower()),None)
  if measure and measure.get('n',0):dwell.append((aid,measure))
 if len(dwell)>=2:
  ranked=sorted(dwell,key=lambda x:x[1]['mean']); low=dwell and ranked[0]; high=ranked[-1]
  if low[0]!=high[0]:
   for aid,measure,kind in ((high[0],high[1],'highest_observed_dwell'),(low[0],low[1],'lowest_observed_dwell')):
     recs.append({'type':'aoi_observation','text':f"AOI {aid} has the {kind.replace('_',' ')} in the selected sample (mean {measure['mean']:.3g}, n={measure['n']}). Review this evidence in the study context; it does not establish preference or attention by itself.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','aoi_summary','aois',aid),'result_section':'aoi_summary','metric':'dwell','value':measure['mean'],'n':measure['n']},'claim_level':'descriptive','automated_suggestion':True})
 for aid,measure in dwell:
   if measure['mean']==0 and measure.get('n',0)>=5:recs.append({'type':'zero_dwell_observation','text':f"AOI {aid} has zero measured dwell across {measure['n']} valid observations. Confirm AOI visibility and measurement quality before interpreting this as ignored content.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','aoi_summary','aois',aid),'metric':'dwell','value':0,'n':measure['n']},'claim_level':'descriptive','automated_suggestion':True})
 discrepancy_result=result['results'].get('discrepancy',{})
 if discrepancy_result.get('status')=='succeeded':recs.append({'type':'attention_response_discrepancy','text':f"The selected gaze feature {discrepancy_result['gaze_feature']} and self-report feature {discrepancy_result['survey_feature']} have a mean within-sample standardized discrepancy of {discrepancy_result['mean_standardized_discrepancy']:.3g} across {discrepancy_result['n']} paired records. This exploratory comparison uses different constructs and is not a validated psychological score.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','discrepancy','mean_standardized_discrepancy'),'metric':'mean_standardized_discrepancy','value':discrepancy_result['mean_standardized_discrepancy'],'n':discrepancy_result['n']},'claim_level':'descriptive','automated_suggestion':True})
 clustering=result['results'].get('clustering',{})
 if clustering.get('status')=='succeeded':recs.append({'type':'exploratory_behavioral_pattern','text':f"Exploratory clustering produced {clustering.get('cluster_count')} data-driven clusters from {clustering.get('n')} observations. Review cluster profiles and stability; clusters are not psychological categories.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results','clustering','cluster_sizes'),'metric':'cluster_sizes','value':clustering.get('cluster_sizes'),'n':clustering.get('n')},'claim_level':'exploratory','automated_suggestion':True})
 if result['metadata']['modality']=='non_gaze':recs.append({'type':'modality_caveat','text':'This result does not establish gaze-based attention.','evidence':{'result_section':'metadata','metric':'modality','value':result['metadata']['modality']},'claim_level':'descriptive','automated_suggestion':True})
 if result['metadata']['modality']=='mixed':recs.append({'type':'modality_caveat','text':'Gaze and non-gaze measures in this result should be interpreted separately; they are not equivalent.','evidence':{'result_section':'metadata','metric':'modality','value':'mixed'},'claim_level':'descriptive','automated_suggestion':True})
 if req['parameters'].get('gaze_required') is True and result['metadata']['modality']=='non_gaze':recs.append({'type':'modality_coverage_followup','text':'This request marks gaze as required by study policy, but selected records contain no usable gaze modality. Check the authorized study modality policy and collection/quality coverage before interpreting gaze-dependent results.','evidence':{'result_id':result['result_id'],'json_pointer':'/metadata/gaze_values_excluded','metric':'gaze_values_excluded','value':result['metadata']['gaze_values_excluded']},'claim_level':'descriptive','automated_suggestion':True})
 for analysis_type,label in (('gaze_interaction_comparison','gaze/interaction'),('attention_importance_comparison','attention/stated importance')):
  comparison=result['results'].get(analysis_type,{})
  if comparison.get('status')=='succeeded':recs.append({'type':analysis_type,'text':f"The {label} comparison has a mean standardized difference of {comparison['mean_standardized_discrepancy']:.3g} across {comparison['n']} paired records. This is exploratory and does not establish causation or equivalence of constructs.",'evidence':{'result_id':result['result_id'],'json_pointer':json_pointer('results',analysis_type,'mean_standardized_discrepancy'),'metric':'mean_standardized_discrepancy','value':comparison['mean_standardized_discrepancy'],'n':comparison['n']},'claim_level':'descriptive','automated_suggestion':True})
 return {'study_scope':{'study_id':req['study_id'],'feature_set_version':req['feature_set_version'],'analysis_parameters':result['data_scope'].get('analysis_parameters'),'filter_summary':result['data_scope'].get('filter_summary'),'record_fingerprint':result['data_scope'].get('record_fingerprint'),'feature_versions':result['data_scope'].get('feature_versions')},'sample_size':result['metadata']['sample_size'],'independent_unit':result['metadata']['independent_unit'],'unique_unit_n':result['metadata']['unique_unit_n'],'modality':result['metadata']['modality'],'modality_policy':result['metadata']['modality_policy'],'analysis_version':ANALYSIS_VERSION,'core_metrics':result['results'].get('descriptive',{}),'uncertainty':{k:v for k,v in result['results'].items() if k in {'correlation','group_comparison','paired_comparison','multiple_comparison','baseline','ml_experiment','modality_comparison','discrepancy','gaze_interaction_comparison','attention_importance_comparison','aoi_comparison'}},'data_quality':result['results'].get('data_quality'),'limitations':result['limitations'],'recommendations':recs,'generated_at':result['generated_at']}
def readiness(fields):
 quality={}; warnings=[]
 for name,rows in sorted(fields.items()):
  present=[r['value'] for r in rows if r['value'] is not None]; missing=len(rows)-len(present); rate=missing/len(rows) if rows else 0; unique=len({json.dumps(v,sort_keys=True,default=str) for v in present}); types={'numeric' if finite(v) else 'boolean' if isinstance(v,bool) else 'categorical' for v in present}; units=sorted({r['unit'] for r in rows if r['unit']})
  cats=Counter(map(str,present)) if types=={'categorical'} else Counter(); balance={'counts':dict(cats),'minimum_cell_n':min(cats.values()) if cats else None,'maximum_cell_n':max(cats.values()) if cats else None,'largest_to_smallest_ratio':(max(cats.values())/min(cats.values())) if cats and min(cats.values()) else None}
  nums=sorted(float(v) for v in present if finite(v)); q1=nums[int((len(nums)-1)*.25)] if nums else None; q3=nums[int((len(nums)-1)*.75)] if nums else None; outliers=sum(v<q1-1.5*(q3-q1) or v>q3+1.5*(q3-q1) for v in nums) if len(nums)>=4 else 0
  quality[name]={'n':len(rows),'missing_n':missing,'missing_rate':rate,'constant':bool(present) and unique==1,'distinct_n':unique,'observed_types':sorted(types),'units':units,'category_balance':balance if cats else None,'iqr_outlier_n':outliers,'outlier_rule':'1.5 IQR fences; flag only, never automatic exclusion'}
  if rate>=.5:warnings.append(f'{name} has high missingness ({rate:.0%})')
  if present and unique==1:warnings.append(f'{name} is constant in the selected sample')
  if len(types)>1:warnings.append(f'{name} contains mixed value types; numeric summaries are not reported')
  if len(units)>1:warnings.append(f'{name} contains mixed units; values are not converted or pooled safely')
  if cats and len(cats)>1 and max(cats.values())/min(cats.values())>=4:warnings.append(f'{name} categories are imbalanced (largest/smallest count ratio {max(cats.values())/min(cats.values()):.1f})')
  if cats and len(cats)>1 and min(cats.values())<5:warnings.append(f'{name} has a sparse category cell smaller than five')
  if outliers:warnings.append(f'{name} has {outliers} IQR-rule outlier candidate(s); inspect before analysis (not excluded automatically)')
 return {'features':quality,'warnings':warnings}
def analyze(request,feature_records=None):
 from .advanced import paired_comparison, compare_many, aoi_comparison, run_experiment, modality_comparison, kmeans, histogram
 from .capabilities import anomaly_detection,dimensionality_reduction,feature_selection,outlier_generation,temporal_analysis,cross_validation,model_selection
 req=validate_request(request); records=req['feature_records'] if feature_records is None else feature_records
 if not isinstance(records,list):raise AnalysisError('invalid_feature_records','feature_records must be a list')
 records,sw=scope_records(records,req)
 records,filter_summary=filter_records(records,req['parameters'])
 p=req['parameters']; collect_p=dict(p)
 if isinstance(p.get('features'),list):collect_p['features']=list(dict.fromkeys(p['features']+[p[k] for k in ('group_by','x','y','feature','target','gaze_feature','survey_feature','interaction_feature','importance_feature') if isinstance(p.get(k),str)]))
 fields,meta,cw=collect(records,req['modality_policy'],collect_p); seed=int(p.get('seed',0)); warnings=sw+cw
 if not records:warnings.append('No FeatureRecords matched Study and feature-set version')
 results={}
 analysis_types=list(dict.fromkeys(req['analysis_types']))
 if 'report' in analysis_types and 'descriptive' not in analysis_types: analysis_types.append('descriptive')
 for k in analysis_types:
  if k=='descriptive':
   summary_unit=p.get('summary_unit','feature_record')
   unit_field={'participant':'participant_id','session':'session_id','trial':'trial_id'}.get(summary_unit)
   if summary_unit not in {'feature_record','participant','session','trial'}:raise AnalysisError('unsupported_summary_unit','summary_unit must be feature_record, participant, session, or trial')
   if unit_field:
    excluded_units=sum(not r.get(unit_field) for r in records)
    if excluded_units:warnings.append(f'{excluded_units} record(s) lacked {unit_field} and were excluded from {summary_unit}-level descriptive aggregation')
   results[k]={n:summary(aggregate_rows(rs,summary_unit)) for n,rs in sorted(fields.items())}
   for n,rs in fields.items():
    units={x['unit'] for x in rs if x['value'] is not None}
    if incompatible_units(rs):results[k][n]={'kind':'unit_mismatch','n':sum(x['value'] is not None for x in rs),'missing_n':sum(x['value'] is None for x in rs),'units':sorted(str(x) for x in units),'reason':'Observed values mix units or include unlabelled units; values are not pooled'}
   if p.get('include_histograms',True):
    for n,rs in fields.items():
     if results[k][n]['kind']=='numeric':results[k][n]['histogram']=histogram(aggregate_rows(rs,summary_unit),p.get('histogram_bins',10))
   group_name=p.get('group_by')
   if group_name in fields:
    group_map={r['row']:str(r['value']) for r in fields[group_name] if r['value'] is not None}
    for name,rows in fields.items():
     if name==group_name:continue
     grouped_rows=defaultdict(list)
     for row in rows:
      if row['row'] in group_map:grouped_rows[group_map[row['row']]].append(row)
     if grouped_rows:
      results[k][name]['by_group']={label:summary(aggregate_rows(values,summary_unit)) for label,values in sorted(grouped_rows.items())}
      for label,values in grouped_rows.items():
       if results[k][name]['by_group'][label]['kind']=='numeric':results[k][name]['by_group'][label]['histogram']=histogram(aggregate_rows(values,summary_unit),p.get('histogram_bins',10))
  elif k=='correlation':results[k]=correlation(fields,p)
  elif k=='group_comparison':results[k]=group_comparison(fields,p,seed)
  elif k=='paired_comparison':results[k]=paired_comparison(records,p,seed,req['modality_policy'])
  elif k=='multiple_comparison':results[k]=compare_many(fields,p,seed)
  elif k=='baseline':results[k]=baseline(fields,p,seed)
  elif k=='ml_experiment':results[k]=run_experiment(records,p,req['modality_policy'])
  elif k=='modality_comparison':results[k]=modality_comparison(records,p)
  elif k=='discrepancy':results[k]=discrepancy(fields,p)
  elif k=='gaze_interaction_comparison':results[k]=discrepancy(fields,p,'interaction')
  elif k=='attention_importance_comparison':results[k]=discrepancy(fields,p,'importance')
  elif k=='clustering':results[k]=kmeans(records,p,req['modality_policy'])
  elif k=='aoi_summary':results[k]=aoi_summary(fields,records)
  elif k=='aoi_comparison':results[k]=aoi_comparison(records,p,seed,req['modality_policy'])
  elif k=='heatmap':results[k]=heatmap(records,p,req['modality_policy'])
  elif k=='anomaly_detection':results[k]=anomaly_detection(records,p,req['modality_policy'])
  elif k=='dimensionality_reduction':results[k]=dimensionality_reduction(records,p,req['modality_policy'])
  elif k=='feature_selection':results[k]=feature_selection(records,p,req['modality_policy'])
  elif k=='outlier_generation':results[k]=outlier_generation(records,p,req['modality_policy'])
  elif k=='temporal_analysis':results[k]=temporal_analysis(records,p,req['modality_policy'])
  elif k=='cross_validation':results[k]=cross_validation(records,p,req['modality_policy'])
  elif k=='model_selection':results[k]=model_selection(records,p,req['modality_policy'])
 quality=readiness(fields)
 warnings.extend(quality['warnings'])
 results['data_quality']=quality
 versions=sorted({str(r['feature_set_version']) for r in records if r.get('feature_set_version') is not None}); fingerprint=hashlib.sha256(json.dumps(records,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest(); request_fingerprint=hashlib.sha256(json.dumps(req,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
 primary_names=p.get('features') if isinstance(p.get('features'),list) else meta['feature_names']
 selected_row_keys={row['row'] for name in primary_names for row in fields.get(name,[]) if row['value'] is not None}
 selected_n=len(selected_row_keys)
 selected_records=[r for i,r in enumerate(records) if record_key(r,i) in selected_row_keys]
 selected_units={r.get('participant_id') or r.get('session_id') or r.get('record_id') for r in selected_records}-{None}
 modality=meta['modality']; limitations=['Raw gaze/provider normalization and measurement definitions remain owned by P3.','Associations do not establish causality.','Synthetic fixtures are software examples, not research evidence.']
 if modality=='non_gaze':limitations.append('No gaze-only claim is supported; gaze-dependent results may be unavailable.')
 if modality=='mixed':limitations.append('Mixed-modality metrics are not directly equivalent; interpret gaze-dependent and non-gaze results separately.')
 if selected_n<10:warnings.append('Small analysis sample; estimates may be unstable')
 partial_types=[]
 for analysis_type in req['analysis_types']:
  component=results.get(analysis_type,{})
  if isinstance(component,dict) and component.get('status') not in (None,'succeeded'):partial_types.append(analysis_type)
 if partial_types:warnings.append('Some requested analyses were unavailable, insufficient or unsupported: '+', '.join(partial_types))
 result={'schema_version':'1.0.0','result_id':str(uuid.uuid4()),'request_id':req['request_id'],'request_fingerprint':request_fingerprint,'study_id':req['study_id'],'status':'no_data' if not records else 'insufficient_data' if selected_n==0 else 'succeeded','analysis_version':ANALYSIS_VERSION,'generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'data_scope':{'study_id':req['study_id'],'feature_set_version':req['feature_set_version'],'record_n':len(records),'record_fingerprint':fingerprint,'feature_versions':versions,'analysis_types':req['analysis_types'],'filter_summary':filter_summary,'analysis_parameters':{k:v for k,v in req['parameters'].items() if k!='filters' and not any(token in k.lower() for token in ('participant_id','session_id','record_id'))}},'metadata':{'modality':modality,'modality_policy':req['modality_policy'],'sample_size':selected_n,'selected_record_n':selected_n,'analysis_unit':p.get('summary_unit','feature_record'),'independent_unit':'participant' if selected_records and all(r.get('participant_id') for r in selected_records) else 'session_or_record','unique_unit_n':len(selected_units),'feature_names':meta['feature_names'],'gaze_values_excluded':meta['gaze_values_excluded'],'gaze_low_quality_excluded':meta['gaze_low_quality_excluded'],'gaze_quality_missing_n':meta['gaze_quality_missing_n'],'gaze_min_quality':meta['gaze_min_quality'],'result_completeness':'partial' if partial_types else 'complete','partial_analysis_types':partial_types,'validation_strategy':'participant/session group holdout for baseline'},'results':results,'warnings':warnings,'limitations':limitations}
 if 'report' in req['analysis_types']:result['report']=make_report(req,result)
 return validate_result(result)
class ResultStore:
 """SQLite local result store. Production deployments should inject the shared result-store repository."""
 def __init__(self,path):
  self.path=str(path); Path(self.path).parent.mkdir(parents=True,exist_ok=True)
  with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS analysis_results(result_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,study_id TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL, UNIQUE(request_id,study_id))'); db.execute('CREATE INDEX IF NOT EXISTS ix_results_study_created ON analysis_results(study_id,created_at)')
 @contextmanager
 def connect(self):
  db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
  try:
   yield db
   db.commit()
  finally: db.close()
 def save(self,r):
  with self.connect() as db:db.execute('INSERT OR IGNORE INTO analysis_results VALUES(?,?,?,?,?)',(r['result_id'],r['request_id'],r['study_id'],r['generated_at'],json.dumps(r,sort_keys=True,separators=(',',':'))))
 def get(self,rid):
  with self.connect() as db:row=db.execute('SELECT payload FROM analysis_results WHERE result_id=?',(rid,)).fetchone()
  return json.loads(row['payload']) if row else None
 def get_by_request(self,request_id,study_id):
  with self.connect() as db:row=db.execute('SELECT payload FROM analysis_results WHERE request_id=? AND study_id=? ORDER BY created_at DESC LIMIT 1',(request_id,study_id)).fetchone()
  return json.loads(row['payload']) if row else None
 def list(self,sid,limit=50):
  limit=max(1,min(int(limit),200))
  with self.connect() as db:rows=db.execute('SELECT payload FROM analysis_results WHERE study_id=? ORDER BY created_at DESC LIMIT ?',(sid,limit)).fetchall()
  return [json.loads(r['payload']) for r in rows]
 def list_page(self,sid,limit=50,cursor=None):
  limit=max(1,min(int(limit),100)); params=[sid]; where='study_id=?'
  if cursor:
   try:
    created,rid=base64.urlsafe_b64decode(cursor.encode()).decode().split('\0',1)
    datetime.fromisoformat(created.replace('Z','+00:00')); uuid.UUID(rid)
   except (ValueError,UnicodeError,TypeError):raise AnalysisError('invalid_cursor','cursor is malformed')
   where+=' AND (created_at < ? OR (created_at = ? AND result_id < ?))'; params.extend([created,created,rid])
  params.append(limit+1)
  with self.connect() as db:rows=db.execute(f'SELECT result_id,created_at,payload FROM analysis_results WHERE {where} ORDER BY created_at DESC,result_id DESC LIMIT ?',params).fetchall()
  more=len(rows)>limit; rows=rows[:limit]; payloads=[json.loads(r['payload']) for r in rows]; next_cursor=None
  if more and rows:
   last=rows[-1]; next_cursor=base64.urlsafe_b64encode((last['created_at']+'\0'+last['result_id']).encode()).decode()
  result_rows=[{'result_id':r.get('result_id'),'request_id':r.get('request_id'),'study_id':r.get('study_id'),'generated_at':r.get('generated_at'),'status':r.get('status'),'analysis_version':r.get('analysis_version'),'schema_version':r.get('schema_version'),'data_scope':{'feature_set_version':r.get('data_scope',{}).get('feature_set_version'),'analysis_types':r.get('data_scope',{}).get('analysis_types')},'metadata':{k:r.get('metadata',{}).get(k) for k in ('modality','modality_policy','sample_size','unique_unit_n','result_completeness')}} for r in payloads]
  return {'results':result_rows,'next_cursor':next_cursor,'limit':limit}
