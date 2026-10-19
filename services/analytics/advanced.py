"""Extended Person 4 inference and ML evaluation primitives (standard library only)."""
from __future__ import annotations
import math, random, statistics, hashlib
from collections import Counter, defaultdict
from .engine import AnalysisError, finite, is_gaze, tp, split_groups, quality_for, incompatible_units, parts

def numeric_value(raw):
    return raw.get('value') if isinstance(raw,dict) else raw

def feature_modality(name, raw):
    return raw.get('modality') if isinstance(raw,dict) else ('gaze' if is_gaze(name) else 'non_gaze')

def paired_comparison(records, parameters, seed=0, policy='best_available'):
    """Paired t comparison on participant-level matched condition values."""
    feature=parameters.get('feature'); condition=parameters.get('group_by'); levels=parameters.get('levels')
    if not feature or not condition: return {'status':'insufficient_data','reason':'Set feature and group_by'}
    by_subject=defaultdict(dict)
    min_quality=parameters.get('gaze_min_quality',.5)
    if not finite(min_quality) or not 0<=float(min_quality)<=1:raise AnalysisError('invalid_quality_threshold','gaze_min_quality must be between 0 and 1')
    units=set(); excluded_quality=0
    for rec in records:
        fs=rec.get('features',{}); raw=fs.get(feature); cond=numeric_value(fs.get(condition))
        value,unit,mod,_,_=parts(raw); units.add(unit if value is not None else None)
        gaze=is_gaze(feature,mod or feature_modality(feature,raw))
        if policy=='gaze_only' and not gaze or policy=='non_gaze_only' and gaze:return {'status':'invalid_request','reason':f'Feature {feature} is not allowed by modality policy {policy}'}
        quality=quality_for(rec,feature,raw) if gaze else None
        if quality is not None and (not finite(quality) or not 0<=float(quality)<=1):raise AnalysisError('invalid_feature_quality',f'Feature {feature} quality must be between 0 and 1')
        val=numeric_value(raw)
        if gaze and quality is not None and float(quality)<float(min_quality):val=None; excluded_quality+=1
        subject=rec.get('participant_id') or rec.get('session_id') or rec.get('record_id')
        if subject is not None and cond is not None and finite(val): by_subject[str(subject)].setdefault(str(cond),[]).append(float(val))
    if len(units)>1:return {'status':'insufficient_data','reason':'Paired feature mixes labeled and unlabeled units or contains incompatible units','units':sorted(str(x) for x in units)}
    names=list(map(str,levels)) if isinstance(levels,list) and len(levels)==2 else sorted({k for d in by_subject.values() for k in d})
    if len(names)!=2: return {'status':'insufficient_data','reason':'Paired test needs exactly two specified or observed conditions'}
    diffs=[statistics.fmean(d[names[1]])-statistics.fmean(d[names[0]]) for d in by_subject.values() if names[0] in d and names[1] in d]
    n=len(diffs)
    if n<2:return {'status':'insufficient_data','reason':'At least two matched participant pairs are required','n_pairs':n}
    mean=statistics.fmean(diffs); sd=statistics.stdev(diffs)
    if not sd:return {'status':'insufficient_data','reason':'Paired differences have no variation','n_pairs':n}
    t=mean/(sd/math.sqrt(n)); df=n-1; p=tp(abs(t),df); d=mean/sd
    rng=random.Random(seed); boot=sorted(statistics.fmean(rng.choices(diffs,k=n)) for _ in range(1200))
    return {'status':'succeeded','method':'paired_t_test','feature':feature,'condition':condition,'condition_a':names[0],'condition_b':names[1],'n_pairs':n,'mean_difference':mean,'sd_difference':sd,'t':t,'degrees_of_freedom':df,'p_value':p,'cohens_dz':d,'bootstrap_95_ci':[boot[29],boot[1169]],'excluded_low_quality_n':excluded_quality,'warnings':['Paired difference only; direction is condition_b minus condition_a']+(['Low-quality gaze observations were excluded'] if excluded_quality else [])+(['Small paired sample; interpret cautiously'] if n<10 else [])}

def adjust_pvalues(items, method='holm'):
    """Return multiplicity-adjusted p-values mapped to item keys."""
    if method not in {'holm','bonferroni','bh'}: raise AnalysisError('unsupported_correction','Correction must be holm, bonferroni, or bh')
    pairs=[(key,float(p)) for key,p in items.items() if p is not None and math.isfinite(float(p))]
    m=len(pairs)
    if not m:return {}
    ordered=sorted(pairs,key=lambda x:x[1]); out={}
    if method=='bonferroni': return {k:min(1.,p*m) for k,p in pairs}
    if method=='holm':
        running=0.
        for rank,(key,p) in enumerate(ordered):
            running=max(running,min(1.,(m-rank)*p)); out[key]=running
        return out
    running=1.
    for rank in range(m-1,-1,-1):
        key,p=ordered[rank]; running=min(running,min(1.,p*m/(rank+1))); out[key]=running
    return out

def compare_many(fields, parameters, seed=0):
    """Run requested numeric group tests and apply the pre-specified family correction."""
    features=parameters.get('features') or [parameters.get('feature')]
    grouping=parameters.get('group_by'); correction=parameters.get('correction','holm')
    if not grouping: return {'status':'insufficient_data','reason':'group_by is required'}
    tests={}
    for feature in features:
        if not feature or feature not in fields or grouping not in fields: continue
        if incompatible_units(fields[feature]):
            tests[feature]={'status':'insufficient_data','reason':'Feature contains mixed units'}; continue
        labels={r['row']:r['value'] for r in fields[grouping] if r['value'] is not None}
        values=defaultdict(lambda:defaultdict(list)); subject_levels=defaultdict(set)
        for row in fields[feature]:
            label=labels.get(row['row'])
            if label is None or not finite(row['value']): continue
            group=str(label); values[group][row['group']].append(float(row['value'])); subject_levels[row['group']].add(group)
        if any(len(v)>1 for v in subject_levels.values()):
            tests[feature]={'status':'unsupported_design','reason':'Repeated participants cross groups; use the paired comparison'}; continue
        levels=sorted(values)
        if len(levels)==2:
            from .engine import welch
            res=welch([statistics.fmean(v) for v in values[levels[0]].values()],[statistics.fmean(v) for v in values[levels[1]].values()],seed)
            res.update({'feature':feature,'group_a':levels[0],'group_b':levels[1],'n_groups':{k:len(values[k]) for k in levels}}); tests[feature]=res
        else:
            tests[feature]={'status':'unsupported_design','reason':'This engine currently supports exactly two independent groups per feature','group_count':len(levels)}
    raw={k:v.get('p_value') for k,v in tests.items() if v.get('status')=='succeeded'}
    adjusted=adjust_pvalues(raw,correction)
    for name,p in adjusted.items(): tests[name]['p_value_adjusted']=p; tests[name]['correction']=correction
    return {'status':'succeeded' if tests else 'insufficient_data','method_family':'Welch independent groups','correction':correction,'family_size':len(raw),'tests':tests,'warnings':['Correction applies only to the tests included in this request. Choose the analysis family before inspecting results.'] if len(raw)>1 else []}

def aoi_comparison(records,parameters,seed=0,policy='best_available'):
    """Compare one gaze measure across AOIs, paired by participant when fully matched."""
    feature=parameters.get('feature'); correction=parameters.get('correction','holm')
    if not feature:return {'status':'insufficient_data','reason':'feature is required'}
    grouped=defaultdict(lambda:defaultdict(list)); units=set(); excluded_quality=0; min_quality=parameters.get('gaze_min_quality',.5)
    if not finite(min_quality) or not 0<=float(min_quality)<=1:raise AnalysisError('invalid_quality_threshold','gaze_min_quality must be between 0 and 1')
    for i,rec in enumerate(records):
        raw=rec.get('features',{}).get(feature); value=numeric_value(raw)
        unit=raw.get('unit') if isinstance(raw,dict) else None
        if value is not None:units.add(unit)
        if not is_gaze(feature,feature_modality(feature,raw)):return {'status':'invalid_request','reason':'AOI comparison requires a gaze-derived feature'}
        if policy=='non_gaze_only':return {'status':'invalid_request','reason':'AOI comparison is unavailable under non_gaze_only policy'}
        quality=quality_for(rec,feature,raw)
        if quality is not None and (not finite(quality) or not 0<=float(quality)<=1):raise AnalysisError('invalid_feature_quality',f'Feature {feature} quality must be between 0 and 1')
        if quality is not None and float(quality)<float(min_quality):value=None; excluded_quality+=1
        aid=(raw.get('aoi_id') if isinstance(raw,dict) else None) or rec.get('aoi_id')
        if aid is None:continue
        subject=rec.get('participant_id') or rec.get('session_id') or rec.get('record_id') or f'row-{i}'
        if finite(value):grouped[str(aid)][str(subject)].append(float(value))
    if len(units)>1:return {'status':'insufficient_data','reason':'AOI feature contains mixed or unlabeled units','units':sorted(str(x) for x in units)}
    names=sorted(grouped)
    if len(names)<2:return {'status':'insufficient_data','reason':'At least two AOI-tagged groups are required','aoi_n':len(names)}
    means={a:{s:statistics.fmean(v) for s,v in people.items()} for a,people in grouped.items()}; tests={}
    for i,a in enumerate(names):
        for b in names[i+1:]:
            common=set(means[a])&set(means[b]); key=f'{a} vs {b}'
            if common and (common!=set(means[a]) or common!=set(means[b])):
                tests[key]={'status':'unsupported_design','reason':'Partially overlapping participants across AOIs; paired and independent assumptions both fail'}; continue
            if common:
                diffs=[means[b][s]-means[a][s] for s in sorted(common)]; n=len(diffs)
                if n<2 or statistics.stdev(diffs)==0:tests[key]={'status':'insufficient_data','n_pairs':n,'reason':'Paired test needs at least two variable participant differences'}; continue
                sd=statistics.stdev(diffs); t=statistics.fmean(diffs)/(sd/math.sqrt(n));
                from .engine import tp
                boot=sorted(statistics.fmean(random.Random(seed+j).choices(diffs,k=n)) for j in range(1000))
                tests[key]={'status':'succeeded','method':'paired_t_test','n_pairs':n,'mean_difference':statistics.fmean(diffs),'cohens_dz':statistics.fmean(diffs)/sd,'p_value':tp(abs(t),n-1),'bootstrap_95_ci':[boot[24],boot[974]]}
            else:
                from .engine import welch
                tests[key]=welch(list(means[a].values()),list(means[b].values()),seed+i)
    adjusted=adjust_pvalues({k:v.get('p_value') for k,v in tests.items() if v.get('status')=='succeeded'},correction)
    for k,p in adjusted.items():tests[k]['p_value_adjusted']=p;tests[k]['correction']=correction
    return {'status':'succeeded' if adjusted else 'insufficient_data','feature':feature,'aoi_n':len(names),'aois':names,'tests':tests,'family_correction':correction,'family_size':len(adjusted),'excluded_low_quality_n':excluded_quality,'warnings':['AOI comparisons are exploratory; repeated measures are paired only when participant sets match completely.']+(['Low-quality gaze observations were excluded'] if excluded_quality else [])}

def histogram(rows, bins=10):
    vals=[float(x['value']) for x in rows if finite(x['value'])]
    if not vals:return {'status':'unavailable','n':0,'bins':[]}
    bins=max(2,min(50,int(bins))); lo=min(vals); hi=max(vals)
    if lo==hi:return {'status':'succeeded','n':len(vals),'edges':[lo,hi],'counts':[len(vals)]}
    width=(hi-lo)/bins; counts=[0]*bins
    for v in vals: counts[min(bins-1,int((v-lo)/width))]+=1
    return {'status':'succeeded','n':len(vals),'edges':[lo+i*width for i in range(bins)]+[hi],'counts':counts}

def _solve(a,b):
    n=len(b); m=[list(map(float,a[i]))+[float(b[i])] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col]))
        if abs(m[pivot][col])<1e-12: m[pivot][col]+=1e-8
        m[col],m[pivot]=m[pivot],m[col]; d=m[col][col]; m[col]=[v/d for v in m[col]]
        for row in range(n):
            if row==col:continue
            f=m[row][col]; m[row]=[x-f*y for x,y in zip(m[row],m[col])]
    return [m[i][-1] for i in range(n)]

def _dataset(records, target, predictors, policy, parameters=None):
    rows=[]; dropped_gaze=0; low_quality=0; missing_quality=0
    min_quality=(parameters or {}).get('gaze_min_quality',.5)
    if not finite(min_quality) or not 0<=float(min_quality)<=1:raise AnalysisError('invalid_quality_threshold','gaze_min_quality must be between 0 and 1')
    for i,rec in enumerate(records):
        features=rec.get('features',{}); y=numeric_value(features.get(target))
        target_gaze=is_gaze(target,feature_modality(target,features.get(target)))
        if policy=='non_gaze_only' and target_gaze:raise AnalysisError('modality_violation',f'Gaze target {target} is not allowed in non_gaze_only mode')
        if policy=='gaze_only' and not target_gaze:raise AnalysisError('modality_violation',f'Non-gaze target {target} is not allowed in gaze_only mode')
        if y is None:continue
        if isinstance(y,bool) or not isinstance(y,(int,float,str)):raise AnalysisError('target_type','ML target must be numeric or categorical text')
        if target_gaze:
            target_quality=quality_for(rec,target,features.get(target))
            if target_quality is not None and (not finite(target_quality) or not 0<=float(target_quality)<=1):raise AnalysisError('invalid_feature_quality',f'Target {target} quality must be between 0 and 1')
            if target_quality is None:missing_quality+=1
            elif float(target_quality)<float(min_quality):dropped_gaze+=1; low_quality+=1; continue
        x={}; rejected=False
        for name in predictors:
            raw=features.get(name); val=numeric_value(raw); modality=feature_modality(name,raw)
            gaze=is_gaze(name,modality)
            if policy=='non_gaze_only' and gaze: raise AnalysisError('modality_violation',f'Gaze feature {name} is not allowed in non_gaze_only mode')
            if policy=='gaze_only' and not gaze: raise AnalysisError('modality_violation',f'Non-gaze feature {name} is not allowed in gaze_only mode')
            if gaze:
                quality=quality_for(rec,name,raw)
                if quality is not None and (not finite(quality) or not 0<=float(quality)<=1):raise AnalysisError('invalid_feature_quality',f'Feature {name} quality must be between 0 and 1')
                if quality is None and val is not None:missing_quality+=1
                elif quality is not None and float(quality)<float(min_quality):val=None; low_quality+=1
            if gaze and val is None: rejected=True; break
            if val is not None and not finite(val): raise AnalysisError('invalid_ml_feature',f'ML feature {name} must be numeric for this model')
            x[name]=float(val) if val is not None else None
        if rejected:dropped_gaze+=1; continue
        group=str(rec.get('participant_id') or rec.get('session_id') or rec.get('record_id') or f'row-{i}')
        rows.append({'x':x,'y':float(y) if isinstance(y,(int,float)) and not isinstance(y,bool) else str(y),'group':group,'record':rec})
    return rows,dropped_gaze,low_quality,missing_quality

def _prep(train,test,predictors,gaze_names):
    medians={}; means={}; sds={}
    for name in predictors:
        vals=[r['x'][name] for r in train if r['x'][name] is not None]
        if not vals: raise AnalysisError('feature_unavailable',f'Feature {name} has no training values')
        medians[name]=statistics.median(vals); means[name]=statistics.fmean(vals); sds[name]=statistics.stdev(vals) if len(vals)>1 else 1.
        if sds[name]==0:sds[name]=1.
    def transform(rows):
        out=[]
        for r in rows:
            if any(r['x'][n] is None for n in gaze_names):continue
            out.append([((r['x'][n] if r['x'][n] is not None else medians[n])-means[n])/sds[n] for n in predictors])
        return out
    return transform(train),transform(test),means,sds,medians

def _class_metrics(y,pred,probs,labels):
    n=len(y); correct=sum(a==b for a,b in zip(y,pred)); per={};
    for label in labels:
        tpv=sum(a==label and b==label for a,b in zip(y,pred)); fp=sum(a!=label and b==label for a,b in zip(y,pred)); fn=sum(a==label and b!=label for a,b in zip(y,pred)); support=sum(a==label for a in y)
        precision=tpv/(tpv+fp) if tpv+fp else 0.; recall=tpv/(tpv+fn) if tpv+fn else 0.; f1=2*precision*recall/(precision+recall) if precision+recall else 0.
        per[label]={'support':support,'precision':precision,'recall':recall,'f1':f1}
    brier=None; calibration=None
    if probs and len(labels)==2:
        pos=labels[1]
        if len(probs)!=n or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not 0<=v<=1 for v in probs):
            raise AnalysisError('invalid_probabilities','Binary predicted probabilities must be finite values in [0,1] and match the target length')
        observed=[1. if y[i]==pos else 0. for i in range(n)]
        brier=statistics.fmean((observed[i]-probs[i])**2 for i in range(n))
        # Equal-width reliability bins; empty bins are omitted and each bin
        # reports the observed support so users can judge calibration precision.
        bins=[]
        for index in range(10):
            members=[i for i,p in enumerate(probs) if (index/10<=p<(index+1)/10) or (index==9 and p==1.)]
            if members:bins.append({'lower':index/10,'upper':(index+1)/10,'n':len(members),'mean_predicted_probability':statistics.fmean(probs[i] for i in members),'observed_positive_rate':statistics.fmean(observed[i] for i in members)})
        ece=sum(b['n']/n*abs(b['mean_predicted_probability']-b['observed_positive_rate']) for b in bins) if n else None
        calibration={'method':'10 equal-width bins','positive_class':pos,'expected_calibration_error':ece,'maximum_calibration_error':max((abs(b['mean_predicted_probability']-b['observed_positive_rate']) for b in bins),default=None),'bins':bins,'caveat':'Exploratory calibration estimates; small held-out samples can make bins unstable.'}
    return {'accuracy':correct/n if n else None,'macro_f1':statistics.fmean(x['f1'] for x in per.values()) if per else None,'balanced_accuracy':statistics.fmean(x['recall'] for x in per.values()) if per else None,'per_class':per,'brier_score':brier,'calibration':calibration}

def _cluster_metric_interval(y,pred,groups,numeric,seed,replicates=800):
    """Bootstrap independent test groups, preserving all rows in each sampled group."""
    by=defaultdict(list)
    for i,g in enumerate(groups):by[g].append(i)
    names=sorted(by)
    if len(names)<3:return {'status':'unavailable','reason':'At least three held-out groups are required for a group bootstrap interval'}
    rng=random.Random(seed); values=[]
    for _ in range(replicates):
        sampled=[rng.choice(names) for _ in names]; idx=[i for g in sampled for i in by[g]]
        if numeric:
            err=[float(y[i])-float(pred[i]) for i in idx]; values.append(math.sqrt(statistics.fmean(e*e for e in err)))
        else:
            metrics=_class_metrics([y[i] for i in idx],[pred[i] for i in idx],None,sorted(set(y))); values.append(metrics['balanced_accuracy'])
    values.sort(); return {'metric':'rmse' if numeric else 'balanced_accuracy','level':.95,'lower':values[int(.025*replicates)],'upper':values[min(replicates-1,int(.975*replicates))],'method':'participant/session cluster bootstrap','replicates':replicates,'test_group_n':len(names)}

def _subgroup_audit(test_rows,y,pred,numeric,field):
    groups=defaultdict(list)
    for i,row in enumerate(test_rows):
        value=row['record'].get('features',{}).get(field,row['record'].get(field)); value=numeric_value(value)
        if value is not None:groups[str(value)].append(i)
    out={}
    for label,idx in sorted(groups.items()):
        if len(idx)<5:out[label]={'status':'suppressed','n':len(idx),'reason':'Subgroup cells smaller than five are suppressed'}; continue
        if numeric:
            err=[float(y[i])-float(pred[i]) for i in idx]; out[label]={'status':'succeeded','n':len(idx),'mae':statistics.fmean(abs(e) for e in err),'rmse':math.sqrt(statistics.fmean(e*e for e in err))}
        else:out[label]={'status':'succeeded','n':len(idx),**_class_metrics([y[i] for i in idx],[pred[i] for i in idx],None,sorted(set(y)))}
    return {'field':field,'groups':out,'caveat':'Exploratory sample-specific performance differences; not a fairness certification.'}

def _fit_predict(model,xtrain,ytrain,xtest,seed,alpha=1.):
    labels=sorted(set(map(str,ytrain)))
    if model in {'majority','mean'}:
        if all(isinstance(y,(int,float)) and not isinstance(y,bool) for y in ytrain):
            pred=[statistics.fmean(ytrain)]*len(xtest); return pred,None,{'kind':'mean_predictor'}
        label=Counter(map(str,ytrain)).most_common(1)[0][0]; return [label]*len(xtest),None,{'kind':'majority_class_predictor','class':label}
    if not xtest:return [],None,{}
    p=len(xtrain[0]) if xtrain else 0
    if p==0: raise AnalysisError('insufficient_features','No usable predictor features remain')
    if model=='ridge':
        if not all(isinstance(y,(int,float)) and not isinstance(y,bool) for y in ytrain):raise AnalysisError('target_type','Ridge requires a numeric target')
        ym=statistics.fmean(ytrain); centered=[float(y)-ym for y in ytrain]; xt=[x+[1.] for x in xtrain]; a=[[sum(row[i]*row[j] for row in xt)+(alpha if i==j and i<p else 0.) for j in range(p+1)] for i in range(p+1)]; b=[sum(row[i]*y for row,y in zip(xt,centered)) for i in range(p)]+[sum(centered)]; coef=_solve(a,b); pred=[ym+sum(v*c for v,c in zip(x,coef[:-1]))+coef[-1] for x in xtest]; return pred,None,{'kind':'ridge_regression','alpha':alpha,'coefficients':coef[:-1],'intercept':ym+coef[-1]}
    if model=='logistic':
        if all(isinstance(y,(int,float)) and not isinstance(y,bool) for y in ytrain):
            ys=sorted(set(ytrain)); classes=[str(y) for y in ys]
        else: classes=sorted(set(map(str,ytrain)))
        if len(classes)<2:raise AnalysisError('target_cardinality','Logistic classification needs at least two target classes')
        encoded=[classes.index(str(y)) for y in ytrain]; k=len(classes); weights=[[0.]*(p+1) for _ in range(k)]; lr=.08; steps=600; n=len(xtrain)
        for _ in range(steps):
            grad=[[2*alpha*w for w in weights[c]] for c in range(k)]
            for x,y in zip(xtrain,encoded):
                xx=x+[1.]; logits=[sum(a*b for a,b in zip(weights[c],xx)) for c in range(k)]; mx=max(logits); es=[math.exp(z-mx) for z in logits]; probs=[e/sum(es) for e in es]
                for c in range(k):
                    err=probs[c]-(1. if c==y else 0.)
                    for j,v in enumerate(xx):grad[c][j]+=err*v
            for c in range(k):weights[c]=[w-lr*g/n for w,g in zip(weights[c],grad[c])]
        probs=[]; pred=[]
        for x in xtest:
            xx=x+[1.]; logits=[sum(a*b for a,b in zip(weights[c],xx)) for c in range(k)]; mx=max(logits); es=[math.exp(z-mx) for z in logits]; ps=[z/sum(es) for z in es]; pred.append(classes[max(range(k),key=ps.__getitem__)]); probs.append(ps[1] if k==2 else max(ps))
        return pred,probs,{'kind':'logistic_regression','alpha':alpha,'classes':classes,'coefficients':[w[:-1] for w in weights],'intercepts':[w[-1] for w in weights],'iterations':steps}
    raise AnalysisError('unsupported_model',f'Unsupported model: {model}')

def run_experiment(records,parameters,policy='best_available'):
    """Grouped holdout evaluation for a baseline plus one or more simple supervised models."""
    recipes={'survey_behavior_prediction':{'task':'classification'},'product_choice_prediction':{'task':'classification'},'interaction_prediction':{'task':'classification'},'response_prediction':{'task':'regression'}}
    recipe=parameters.get('task_recipe')
    if recipe is not None:
        if recipe not in recipes:raise AnalysisError('unsupported_task_recipe','task_recipe must be one of '+', '.join(recipes))
        parameters={**parameters,**{k:v for k,v in recipes[recipe].items() if k not in parameters},'task_recipe':recipe}
    target=parameters.get('target'); predictors=parameters.get('features') or []; excluded=parameters.get('excluded_features',[])
    if not isinstance(excluded,list) or any(not isinstance(x,str) for x in excluded):raise AnalysisError('invalid_ml_features','excluded_features must be a list of feature names')
    overlap=set(predictors)&set(excluded)
    if overlap:raise AnalysisError('invalid_ml_features','A feature cannot be both included and excluded: '+', '.join(sorted(overlap)))
    if not target or not predictors: return {'status':'insufficient_data','reason':'Set target and at least one predictor feature'}
    if not isinstance(predictors,list) or any(not isinstance(x,str) or not x for x in predictors) or len(set(predictors))!=len(predictors):raise AnalysisError('invalid_ml_features','features must be a list of unique non-empty feature names')
    if target in predictors:raise AnalysisError('target_leakage','The target cannot also be included as a predictor')
    unit=parameters.get('unit_of_prediction','feature_record')
    if unit not in {'feature_record','session','participant'}:raise AnalysisError('invalid_prediction_unit','unit_of_prediction must be feature_record, session, or participant')
    if unit in {'participant','session'}:
        id_key='participant_id' if unit=='participant' else 'session_id'; ids=[r.get(id_key) for r in records]
        if any(not x for x in ids) or len(set(map(str,ids)))!=len(ids):raise AnalysisError('invalid_prediction_unit',f'{unit} prediction requires exactly one FeatureRecord per {unit}; aggregate upstream or use feature_record')
    seed=int(parameters.get('seed',0)); alpha=float(parameters.get('alpha',1.))
    if not math.isfinite(alpha) or alpha<=0:raise AnalysisError('invalid_hyperparameter','alpha must be a finite positive number')
    rows,dropped_gaze,low_quality_gaze,missing_quality=_dataset(records,target,predictors,policy,parameters)
    forced_test=set(parameters.get('_test_groups',[]))
    if forced_test:
        all_groups={r['group'] for r in rows}; test_g=all_groups&forced_test; train_g=all_groups-test_g
    else:train_g,test_g=split_groups(rows,seed)
    if not train_g:return {'status':'insufficient_data','reason':'At least three independent participant/session groups are required','group_n':len({r['group'] for r in rows})}
    train=[r for r in rows if r['group'] in train_g]; test=[r for r in rows if r['group'] in test_g]; numeric_target=all(isinstance(r['y'],(int,float)) and not isinstance(r['y'],bool) for r in rows); task=parameters.get('task','regression' if numeric_target else 'classification'); model_names=parameters.get('models',['ridge'] if task=='regression' else ['logistic']);
    if not isinstance(model_names,list) or not model_names or any(not isinstance(x,str) for x in model_names) or len(set(model_names))!=len(model_names) or any(x not in {'ridge','logistic','ensemble'} for x in model_names):raise AnalysisError('invalid_models','models must be unique ridge, logistic, or ensemble names')
    gaze_names=[n for n in predictors if any(is_gaze(n,feature_modality(n,r['record'].get('features',{}).get(n))) for r in rows)]
    xtrain,xtest,means,sds,medians=_prep(train,test,predictors,gaze_names); usable_test=[r for r in test if not any(r['x'][n] is None for n in gaze_names)]; ytrain=[r['y'] for r in train if not any(r['x'][n] is None for n in gaze_names)]; ytest=[r['y'] for r in usable_test]
    if not ytrain or not ytest:return {'status':'insufficient_data','reason':'No usable held-out rows after enforcing required gaze availability','dropped_gaze_missing_n':dropped_gaze}
    numeric=(task=='regression' and all(isinstance(y,(int,float)) and not isinstance(y,bool) for y in ytrain+ytest));
    if task not in {'regression','classification'}:raise AnalysisError('unsupported_task','task must be regression or classification')
    if task=='classification':ytrain=list(map(str,ytrain)); ytest=list(map(str,ytest))
    target_missing_n=sum(numeric_value(r.get('features',{}).get(target)) is None for r in records)
    availability={}
    for name in predictors:
        observed=sum(numeric_value(r.get('features',{}).get(name)) is not None for r in records)
        modality='gaze' if any(is_gaze(name,feature_modality(name,r.get('features',{}).get(name))) for r in records) else 'non_gaze'
        availability[name]={'modality':modality,'available_record_n':observed,'missing_record_n':len(records)-observed,'availability_rate':observed/len(records) if records else 0.}
    imputed_missing={'train':{n:sum(r['x'][n] is None for r in train if not any(r['x'][g] is None for g in gaze_names)) for n in predictors},'test':{n:sum(r['x'][n] is None for r in usable_test) for n in predictors}}
    results={}; baseline_model='mean' if numeric else 'majority';
    if numeric and any(m=='logistic' for m in model_names):raise AnalysisError('model_task_mismatch','logistic is a classification model')
    if not numeric and any(m=='ridge' for m in model_names):raise AnalysisError('model_task_mismatch','ridge is a regression model')
    baseline_pred,_,baseline_info=_fit_predict(baseline_model,[],ytrain,[[] for _ in ytest],seed)
    if numeric:
        base_err=[float(a)-float(baseline_pred[i]) for i,a in enumerate(ytest)]; baseline_metrics={'mae':statistics.fmean(abs(x) for x in base_err),'rmse':math.sqrt(statistics.fmean(x*x for x in base_err))}
    else: baseline_metrics=_class_metrics(list(map(str,ytest)),list(map(str,baseline_pred)),None,sorted(set(map(str,ytrain+ytest))))
    test_groups=[r['group'] for r in usable_test]
    def prediction_payload(predictions):
        return [{'unit_token':hashlib.sha256(row['group'].encode()).hexdigest()[:16],'record_token':hashlib.sha256(str(row['record'].get('record_id') or row['record'].get('session_id') or row['group']).encode()).hexdigest()[:16],'observed':ytest[i],'predicted':predictions[i]} for i,row in enumerate(usable_test)]
    results['baseline']={'model':baseline_info,'metrics':baseline_metrics,'uncertainty':_cluster_metric_interval(ytest,baseline_pred,test_groups,numeric,seed+41)}
    if parameters.get('include_predictions') is True:results['baseline']['heldout_predictions']=prediction_payload(baseline_pred)
    audit_field=parameters.get('audit_group');
    if audit_field:results['baseline']['subgroup_audit']=_subgroup_audit(usable_test,ytest,baseline_pred,numeric,audit_field)
    for name in model_names:
        if name=='ensemble':
            members=['ridge','mean'] if numeric else ['logistic','majority']
            fitted=[_fit_predict(member,xtrain if member not in {'mean','majority'} else [],ytrain,xtest if member not in {'mean','majority'} else [[] for _ in xtest],seed,alpha) for member in members]
            member_predictions=[item[0] for item in fitted]
            if numeric:pred=[statistics.fmean(row) for row in zip(*member_predictions)]
            else:pred=[Counter(row).most_common(1)[0][0] for row in zip(*member_predictions)]
            prob=None;model_info={'kind':'simple_ensemble','members':members,'aggregation':'mean prediction' if numeric else 'majority vote'}
        else:pred,prob,model_info=_fit_predict(name,xtrain,ytrain,xtest,seed,alpha)
        if numeric:
            err=[float(a)-float(b) for a,b in zip(ytest,pred)]; mean=statistics.fmean(float(y) for y in ytest); den=sum((float(y)-mean)**2 for y in ytest); metrics={'mae':statistics.fmean(abs(x) for x in err),'rmse':math.sqrt(statistics.fmean(x*x for x in err)),'r2':1-sum(x*x for x in err)/den if den else None}
        else: metrics=_class_metrics(list(map(str,ytest)),list(map(str,pred)),prob,sorted(set(map(str,ytrain+ytest))))
        coeff=model_info.get('coefficients'); importance={f:sum(abs(c[i]) for c in coeff)/len(coeff) if coeff and isinstance(coeff[0],list) else abs(coeff[i]) for i,f in enumerate(predictors)} if coeff else {}
        results[name]={'model':model_info,'metrics':metrics,'uncertainty':_cluster_metric_interval(ytest,pred,test_groups,numeric,seed+42),'feature_weights':importance,'explanation_label':'Associational model weights, not causal effects'}
        if parameters.get('include_predictions') is True:results[name]['heldout_predictions']=prediction_payload(pred)
        if audit_field:results[name]['subgroup_audit']=_subgroup_audit(usable_test,ytest,pred,numeric,audit_field)
    test_signature=hashlib.sha256('\n'.join(sorted(r['group']+'|'+str(r['record'].get('record_id') or r['record'].get('session_id') or r['group']) for r in usable_test)).encode()).hexdigest()
    import platform
    library_versions={'python':platform.python_version(),'implementation':'Python standard library'}
    return {'status':'succeeded','experiment':{'target':target,'task':task,'task_recipe':recipe,'unit_of_prediction':unit,'intended_use':parameters.get('intended_use','exploratory research only; no individual-level decisions'),'predictors':predictors,'excluded_features':excluded,'modality_policy':policy,'seed':seed,'model_version':'p4-baselines/1.0.0','analysis_version':'p4-analytics/1.0.0','library_versions':library_versions,'feature_set_versions':sorted({str(r.get('feature_set_version')) for r in records if r.get('feature_set_version') is not None}),'validation_strategy':'participant_group_holdout' if any(r.get('participant_id') for r in records) else 'session_group_holdout','train_group_n':len(train_g),'test_group_n':len({r['group'] for r in usable_test}),'test_cohort_fingerprint':test_signature,'train_n':len(ytrain),'test_n':len(ytest),'input_record_n':len(records),'target_missing_n':target_missing_n,'feature_availability':availability,'imputed_missing_by_feature':imputed_missing,'preprocessing':'training-only median imputation and standardization; missing or low-quality required gaze values are excluded, never imputed','normalization':{'mean':means,'sd':sds,'training_medians':medians}},'baseline_comparison':results,'dropped_gaze_missing_n':dropped_gaze,'dropped_gaze_low_quality_n':low_quality_gaze,'gaze_quality_unavailable_value_n':missing_quality,'warnings':['Held-out evaluation only; no performance claim is justified by synthetic fixtures.','Weights and predictive associations do not establish causality.']+(['Gaze feature quality was not supplied for some observations and could not be assessed'] if missing_quality else [])}

def modality_comparison(records,parameters):
    target=parameters.get('target'); non_gaze=parameters.get('non_gaze_features') or []; gaze=parameters.get('gaze_features') or []
    if not target or not non_gaze or not gaze:return {'status':'insufficient_data','reason':'target, non_gaze_features and gaze_features are required'}
    common={k:v for k,v in parameters.items() if k not in {'non_gaze_features','gaze_features','features'}}
    baseline=run_experiment(records,{**common,'features':non_gaze},'non_gaze_only')
    enhanced=run_experiment(records,{**common,'features':list(dict.fromkeys(non_gaze+gaze))},'best_available')
    if baseline.get('status')!='succeeded' or enhanced.get('status')!='succeeded':return {'status':'insufficient_data','non_gaze':baseline,'gaze_enhanced':enhanced,'reason':'Both evaluation paths need sufficient data'}
    a=baseline['experiment']; b=enhanced['experiment']; same=a['test_cohort_fingerprint']==b['test_cohort_fingerprint'] and a['test_n']==b['test_n'] and a['target']==b['target']
    reasons=[] if same else ['Held-out participant/session cohort differs because required gaze values are missing or excluded']
    task=baseline['experiment']['task']
    metric='rmse' if task=='regression' else 'balanced_accuracy'; deltas={}
    if same:
        for name in set(baseline['baseline_comparison'])&set(enhanced['baseline_comparison']):
            av=baseline['baseline_comparison'][name]['metrics'].get(metric); bv=enhanced['baseline_comparison'][name]['metrics'].get(metric)
            if isinstance(av,(int,float)) and isinstance(bv,(int,float)):deltas[name]={'metric':metric,'non_gaze':av,'gaze_enhanced':bv,'delta':bv-av}
    return {'status':'succeeded','comparison_status':'comparable' if same else 'not_comparable','target':target,'evaluation_metric':metric,'metric_differences':deltas,'reasons':reasons,'non_gaze':baseline,'gaze_enhanced':enhanced,'interpretation_limit':'An incremental metric difference is associational, sample-dependent, and not causal or a general claim that gaze improves prediction.'}

def kmeans(records,parameters,policy='best_available'):
    names=parameters.get('features') or []; k=max(2,min(8,int(parameters.get('n_clusters',3)))); seed=int(parameters.get('seed',0))
    if not names:return {'status':'insufficient_data','reason':'Select numeric clustering features'}
    rows, dropped, _, _=_dataset(records,names[0],names,policy,parameters)
    if len(rows)<k:return {'status':'insufficient_data','reason':'Fewer usable rows than clusters','n':len(rows)}
    x,_,means,sds,medians=_prep(rows,rows,names,[n for n in names if any(is_gaze(n,feature_modality(n,r['record'].get('features',{}).get(n))) for r in rows)])
    if len(x)<k:return {'status':'insufficient_data','reason':'Too few rows with required gaze features','n':len(x)}
    rng=random.Random(seed); centers=[x[i][:] for i in rng.sample(range(len(x)),k)]; labels=[0]*len(x)
    for _ in range(100):
        new=[]
        for row in x:new.append(min(range(k),key=lambda c:sum((a-b)**2 for a,b in zip(row,centers[c]))))
        updated=[]
        for c in range(k):
            members=[x[i] for i,l in enumerate(new) if l==c]
            updated.append([statistics.fmean(r[j] for r in members) for j in range(len(names))] if members else centers[c])
        if new==labels and updated==centers:break
        labels,centers=new,updated
    counts=dict(Counter(labels)); profile={str(c):{n:centers[c][j]*sds[n]+means[n] for j,n in enumerate(names)} for c in range(k)}
    return {'status':'succeeded','method':'kmeans','n':len(x),'cluster_count':k,'cluster_sizes':counts,'centroids_original_units':profile,'features':names,'seed':seed,'input_modality':policy,'interpretation_limit':'Clusters are exploratory patterns, not fixed psychological types.','warnings':['Inspect stability and subgroup sensitivity before interpretation.']}
