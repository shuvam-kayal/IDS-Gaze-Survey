import json
import tempfile
import unittest
import threading
import time
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from pathlib import Path
from services.analytics.engine import AnalysisError, ResultStore, analyze
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=json.loads((ROOT/'fixtures'/'synthetic_feature_records.json').read_text(encoding='utf-8-sig'))
def request(types,policy='best_available',params=None,records=None):
 return {'request_id':'req-test','study_id':'study-demo-001','feature_set_version':'1.0.0','modality_policy':policy,'analysis_types':types,'parameters':params or {},'feature_records':FIXTURE if records is None else records}
class AnalyticsTests(unittest.TestCase):
 def test_descriptive_known_answer_and_missingness(self):
  req=json.loads((ROOT/'fixtures'/'analysis_request.json').read_text(encoding='utf-8-sig')); req['feature_records']=FIXTURE
  out=analyze(req); expected=json.loads((ROOT/'fixtures'/'analysis_expected.json').read_text(encoding='utf-8-sig'))['expected']; s=out['results']['descriptive']['response_time_ms']
  self.assertEqual(s['n'],expected['response_time_ms']['n']); self.assertEqual(s['missing_n'],expected['response_time_ms']['missing_n']); self.assertAlmostEqual(s['mean'],expected['response_time_ms']['mean'])
  gaze=analyze(request(['descriptive']))['results']['descriptive']['gaze_coverage']; self.assertEqual(gaze['n'],3); self.assertEqual(gaze['missing_n'],3)
 def test_gaze_only_does_not_fabricate_and_non_gaze_keeps_utility(self):
  no_gaze=[r for r in FIXTURE if 'gaze' not in r['modality']]
  out=analyze(request(['descriptive','aoi_summary','heatmap'],'gaze_only',records=no_gaze))
  self.assertEqual(out['metadata']['sample_size'],0)
  self.assertEqual(out['status'],'insufficient_data')
  self.assertEqual(out['results']['descriptive']['gaze_coverage']['kind'],'unavailable')
  self.assertEqual(out['results']['heatmap']['status'],'unavailable')
  ng=analyze(request(['descriptive','aoi_summary'],'non_gaze_only'))
  self.assertIn('response_time_ms',ng['results']['descriptive'])
  self.assertNotIn('aoi:hero:dwell_ms',ng['results']['descriptive'])
 def test_no_data_and_version_mismatch(self):
  self.assertEqual(analyze(request(['descriptive'],records=[]))['status'],'no_data')
  wrong=[dict(FIXTURE[0],feature_set_version='99.0.0')]
  with self.assertRaises(AnalysisError): analyze(request(['descriptive'],records=wrong))
 def test_correlation_and_small_group_state(self):
  records=[]
  for i,(x,y,g) in enumerate([(1,2,'A'),(2,4,'A'),(3,6,'B'),(4,8,'B')]):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':x,'y':y,'condition':g}})
  out=analyze(request(['correlation','group_comparison'],'non_gaze_only',{'x':'x','y':'y','feature':'x','group_by':'condition'},records))
  self.assertAlmostEqual(out['results']['correlation']['correlation'],1.0)
  self.assertIn('p_value',out['results']['group_comparison'])
 def test_baseline_uses_grouped_holdout(self):
  out=analyze(request(['baseline'],'non_gaze_only',{'target':'completion','seed':11}))
  self.assertEqual(out['results']['baseline']['validation']['strategy'],'participant_group_holdout')
  self.assertGreaterEqual(out['results']['baseline']['validation']['test_group_n'],1)
 def test_ml_rejects_target_predictor_leakage(self):
  records=[]
  for i in range(6):records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'outcome':i,'x':i+1}})
  with self.assertRaisesRegex(AnalysisError,'target cannot also be included'):
   analyze(request(['ml_experiment'],'non_gaze_only',{'target':'outcome','features':['outcome','x'],'task':'regression'},records))
 def test_extended_p4_ml_capabilities(self):
  records=[]
  for i in range(18):
   records.append({'record_id':f'r{i}','participant_id':f'p{i}','session_id':f's{i//6}','study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'occurred_at':f'2026-01-{(i%28)+1:02d}T00:00:00Z','features':{'x':float(i),'y':float(i*2+(20 if i==17 else 0)),'z':float(i%5),'outcome':float(i*2)}})
  def run(kind,params):return analyze(request([kind],'non_gaze_only',params,records))['results'][kind]
  anomaly=run('anomaly_detection',{'features':['y'],'robust_z_threshold':2.5});self.assertEqual(anomaly['status'],'succeeded');self.assertGreaterEqual(anomaly['features']['y']['outlier_n'],1)
  pca=run('dimensionality_reduction',{'features':['x','y','z'],'n_components':2});self.assertEqual(pca['status'],'succeeded');self.assertEqual(len(pca['components']),2)
  selection=run('feature_selection',{'target':'outcome','features':['x','z'],'top_k':1});self.assertEqual(selection['selected'][0],'x')
  synthetic=run('outlier_generation',{'features':['x'],'max_generated':2});self.assertTrue(all(x['synthetic'] for x in synthetic['synthetic_outliers']))
  temporal=run('temporal_analysis',{'feature':'x'});self.assertGreater(temporal['group_n'],0)
  cv=run('cross_validation',{'target':'outcome','features':['x','z'],'task':'regression','models':['ridge'],'folds':3,'seed':3});self.assertEqual(cv['status'],'succeeded')
  chosen=run('model_selection',{'target':'outcome','features':['x','z'],'task':'regression','candidate_models':['ridge','ensemble'],'alpha_grid':[.1,1.],'seed':3});self.assertEqual(chosen['status'],'succeeded');self.assertIn(chosen['best_model'],{'ridge','ensemble'});self.assertEqual(chosen['validation_strategy'],'nested_grouped_cross_validation')
 def test_saved_model_registry_and_reuse(self):
  from services.analytics.capabilities import MODEL_REGISTRY,predict_with_saved_result
  records=[]
  for i in range(12):records.append({'record_id':f'm{i}','participant_id':f'mp{i}','study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':float(i),'y':float(i*2)}})
  result=analyze(request(['ml_experiment'],'non_gaze_only',{'target':'y','features':['x'],'task':'regression','models':['ridge']},records))
  reused=predict_with_saved_result(result,records[:2]);self.assertEqual(reused['status'],'succeeded');self.assertIn('ridge',reused['models'])
  self.assertTrue(MODEL_REGISTRY['ridge']['gaze_optional'])
 def test_heatmap_requires_points_quality_and_geometry(self):
  base=request(['heatmap'],'best_available',{'heatmap_min_points':2,'heatmap_grid_size':4},[])
  self.assertEqual(analyze(base)['results']['heatmap']['status'],'unavailable')
  rec={'record_id':'h','study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze'],'features':{},'spatial':{'points':[{'x':.2,'y':.4},{'x':.8,'y':.9}],'quality':.9,'geometry_version':'aoi-v3','coordinate_system':'normalized_viewport','aoi_geometry':{'hero':{'x':0,'y':0,'width':1,'height':1}}}}
  base['feature_records']=[rec]
  result=analyze(base)['results']['heatmap']; self.assertEqual(result['status'],'succeeded'); self.assertEqual(sum(map(sum,result['counts'])),2)
 def test_report_contains_evidence_and_scope(self):
  out=analyze(request(['report']))
  self.assertIn('descriptive',out['results']); self.assertEqual(out['report']['study_scope']['study_id'],'study-demo-001')
  self.assertTrue(all('evidence' in r for r in out['report']['recommendations']))
 def test_store_round_trip(self):
  result=analyze(request(['descriptive']))
  with tempfile.TemporaryDirectory() as d:
   store=ResultStore(Path(d)/'results.sqlite3'); store.save(result)
   self.assertEqual(store.get(result['result_id'])['request_id'],'req-test')
   self.assertEqual(len(store.list('study-demo-001')),1)
 def test_result_history_keyset_pagination(self):
  with tempfile.TemporaryDirectory() as d:
   store=ResultStore(Path(d)/'page.sqlite3')
   for i in range(5):
    r=analyze(request(['descriptive'],records=FIXTURE)); r['request_id']=f'page-{i}'; r['result_id']=__import__('uuid').uuid4().__str__(); store.save(r)
   first=store.list_page('study-demo-001',2); second=store.list_page('study-demo-001',2,first['next_cursor']); third=store.list_page('study-demo-001',2,second['next_cursor'])
   ids=[r['result_id'] for p in (first,second,third) for r in p['results']]
   self.assertEqual(len(ids),5); self.assertEqual(len(set(ids)),5); self.assertIsNone(third['next_cursor'])
   self.assertNotIn('results',first['results'][0]); self.assertIn('metadata',first['results'][0])
   with self.assertRaises(AnalysisError):store.list_page('study-demo-001',2,'bad-cursor')
 def test_histograms_and_filter_summary(self):
  out=analyze(request(['descriptive'],'non_gaze_only',{'filters':{'participant_ids':['p01','p02']}}))
  s=out['results']['descriptive']['response_time_ms']; self.assertEqual(s['n'],2); self.assertEqual(sum(s['histogram']['counts']),2)
  self.assertEqual(out['data_scope']['filter_summary']['excluded_record_n'],4)
 def test_descriptive_aggregation_units_grouped_and_source_denominators(self):
  records=[]
  values=[('p1',0,'a'),('p1',100,'a'),('p2',100,'a'),('p3',100,'b'),('p4',100,'b')]
  for i,(participant,x,product) in enumerate(values):
   records.append({'record_id':f'r{i}','participant_id':participant,'session_id':'s'+participant,'trial_id':f't{i}','product_id':product,'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['interaction'],'features':{'score':x}})
  participant=analyze(request(['descriptive'],'non_gaze_only',{'features':['score'],'summary_unit':'participant','group_by':'product_id'},records))['results']['descriptive']['score']
  self.assertEqual(participant['n'],4); self.assertEqual(participant['source_observation_n'],5); self.assertAlmostEqual(participant['mean'],87.5)
  self.assertEqual(set(participant['by_group']),{'a','b'})
 def test_selected_absent_features_are_counted_missing_and_histograms_use_units(self):
  records=[]
  for i,(person,features) in enumerate([('p1',{'score':2}),('p1',{}),('p2',{'score':4}),('p3',{})]):
   records.append({'record_id':f'r{i}','participant_id':person,'session_id':f's{i}','study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':features})
  result=analyze(request(['descriptive'],'non_gaze_only',{'features':['score'],'summary_unit':'participant'},records))
  summary=result['results']['descriptive']['score']
  self.assertEqual(summary['n'],2); self.assertEqual(summary['missing_n'],1)
  self.assertEqual(summary['source_observation_n'],4); self.assertEqual(summary['source_missing_observation_n'],2)
  self.assertEqual(summary['histogram']['n'],2); self.assertEqual(sum(summary['histogram']['counts']),2)
 def test_missing_and_labeled_units_are_not_pooled(self):
  records=[]
  for i,value in enumerate([1,2,3,4]):
   raw={'value':value,'unit':'ms'} if i<3 else value
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':raw,'y':i}})
  result=analyze(request(['descriptive','correlation'],'non_gaze_only',{'features':['x','y'],'x':'x','y':'y'},records))
  self.assertEqual(result['results']['descriptive']['x']['kind'],'unit_mismatch')
  self.assertEqual(result['results']['correlation']['status'],'insufficient_data')
 def test_low_quality_gaze_values_are_excluded_and_reported(self):
  records=[]
  for i,(value,quality) in enumerate([(0.1,.2),(.7,.9),(None,None)]):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze'],'features':{'gaze_score':{'value':value,'unit':'ratio','modality':'gaze','quality':quality}}})
  result=analyze(request(['descriptive'],'gaze_only',{'features':['gaze_score']},records))
  s=result['results']['descriptive']['gaze_score']
  self.assertEqual((s['n'],s['missing_n']),(1,2))
  self.assertEqual(result['metadata']['gaze_low_quality_excluded'],1)
  self.assertEqual(result['metadata']['gaze_quality_missing_n'],0)
  self.assertEqual(result['metadata']['result_completeness'],'complete')
 def test_paired_and_aoi_analysis_cannot_bypass_modality_policy(self):
  records=[]
  for p in range(4):
   for c,value in [('a',p+1),('b',p+2)]:
    records.append({'record_id':f'{p}-{c}','participant_id':str(p),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze'],'features':{'dwell_ms':{'value':value,'unit':'ms','modality':'gaze','aoi_id':c},'condition':c}})
  pair=analyze(request(['paired_comparison'],'non_gaze_only',{'feature':'dwell_ms','group_by':'condition','levels':['a','b']},records))
  aoi=analyze(request(['aoi_comparison'],'non_gaze_only',{'feature':'dwell_ms'},records))
  self.assertEqual(pair['results']['paired_comparison']['status'],'invalid_request')
  self.assertEqual(aoi['results']['aoi_comparison']['status'],'invalid_request')
 def test_heatmap_uses_only_quality_approved_records(self):
  records=[]
  for i,(quality,x) in enumerate([(.9,.2),(.1,.8)]):
   records.append({'record_id':str(i),'session_id':f's{i}','study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze'],'features':{},'spatial':{'points':[{'x':x,'y':.5}]*3,'quality':quality,'geometry_version':'v1','coordinate_system':'normalized_viewport','aoi_geometry':{'hero':{'x':0,'y':0,'width':1,'height':1}}}})
  result=analyze(request(['heatmap'],'best_available',{'heatmap_min_points':2},records))['results']['heatmap']
  self.assertEqual(result['point_n'],3); self.assertEqual(result['quality_excluded_record_n'],1)
  self.assertEqual(result['session_n'],1)
 def test_requested_unavailable_component_marks_result_partial(self):
  result=analyze(request(['descriptive','heatmap'],'non_gaze_only',{'features':['response_time_ms']}))
  self.assertEqual(result['metadata']['result_completeness'],'partial')
  self.assertIn('heatmap',result['metadata']['partial_analysis_types'])
 def test_attention_self_report_discrepancy_has_construct_caveat(self):
  records=[]
  for i in range(8):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze','survey'],'features':{'gaze_attention':{'value':float(i+1),'unit':'ratio','modality':'gaze'},'importance_rating':i*i+1}})
  d=analyze(request(['discrepancy'],'best_available',{'gaze_feature':'gaze_attention','survey_feature':'importance_rating'},records))['results']['discrepancy']
  self.assertEqual(d['status'],'succeeded'); self.assertEqual(d['n'],8); self.assertIn('not a validated psychological score',d['interpretation_limit'])
 def test_architecture_attention_and_interaction_comparisons(self):
  records=[]
  for i in range(8):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze','interaction','survey'],'features':{'gaze_attention':{'value':float(i+1),'unit':'ratio','modality':'gaze'},'interaction_error':{'value':float((i+1)**2),'unit':'count','modality':'interaction'},'stated_importance':{'value':float(2*i+1),'unit':'rating','modality':'survey'}}})
  result=analyze(request(['gaze_interaction_comparison','attention_importance_comparison'],'best_available',{'gaze_feature':'gaze_attention','interaction_feature':'interaction_error','importance_feature':'stated_importance'},records))['results']
  self.assertEqual(result['gaze_interaction_comparison']['status'],'succeeded')
  self.assertEqual(result['gaze_interaction_comparison']['n'],8)
  self.assertEqual(result['attention_importance_comparison']['status'],'succeeded')
  self.assertEqual(result['attention_importance_comparison']['comparison_kind'],'attention_vs_stated_importance')
 def test_paired_comparison_aggregates_repeated_records_by_participant(self):
  records=[]
  for person,a,b in [('p1',2,4),('p2',3,6),('p3',5,8),('p4',6,10)]:
   for rep in (0,1):
    records.append({'record_id':f'{person}-{rep}','participant_id':person,'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'score':(a if rep==0 else a+2),'condition':'A'}})
    records.append({'record_id':f'{person}-b{rep}','participant_id':person,'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'score':(b if rep==0 else b+2),'condition':'B'}})
  result=analyze(request(['paired_comparison'],'non_gaze_only',{'feature':'score','group_by':'condition','levels':['A','B']},records))['results']['paired_comparison']
  self.assertEqual(result['n_pairs'],4); self.assertAlmostEqual(result['mean_difference'],3.0); self.assertEqual(result['method'],'paired_t_test')
 def test_multiple_comparison_reports_adjusted_pvalues(self):
  records=[]
  for i in range(12):
   group='A' if i<6 else 'B'; shift=0 if group=='A' else 5
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':i+shift,'y':i*2+shift,'arm':group}})
  result=analyze(request(['multiple_comparison'],'non_gaze_only',{'features':['x','y'],'group_by':'arm','correction':'holm'},records))['results']['multiple_comparison']
  self.assertEqual(result['family_size'],2); self.assertIn('p_value_adjusted',result['tests']['x'])
 def test_ml_experiment_grouped_holdout_and_categorical_target(self):
  records=[]
  for i in range(20):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'score':float(i%10),'outcome':'yes' if i%10>4 else 'no'}})
  result=analyze(request(['ml_experiment'],'non_gaze_only',{'target':'outcome','features':['score'],'task':'classification','seed':2},records))['results']['ml_experiment']
  self.assertEqual(result['status'],'succeeded'); self.assertEqual(result['experiment']['validation_strategy'],'participant_group_holdout')
  self.assertIn('balanced_accuracy',result['baseline_comparison']['logistic']['metrics'])
  calibration=result['baseline_comparison']['logistic']['metrics']['calibration']
  self.assertEqual(calibration['method'],'10 equal-width bins'); self.assertGreaterEqual(calibration['expected_calibration_error'],0); self.assertTrue(calibration['bins'])
 def test_ml_synthetic_fixture_has_reproducible_grouped_evaluation(self):
  f=json.loads((ROOT/'fixtures'/'ml_experiment.json').read_text(encoding='utf-8-sig')); records=[]
  for i,row in enumerate(f['records']):records.append({'record_id':f'ml-{i}','participant_id':row['participant_id'],'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['interaction'],'features':row['features']})
  first=analyze(request(['ml_experiment'],'non_gaze_only',f['analysis'],records))['results']['ml_experiment']; second=analyze(request(['ml_experiment'],'non_gaze_only',f['analysis'],records))['results']['ml_experiment']
  self.assertEqual(first['experiment']['validation_strategy'],'participant_group_holdout'); self.assertEqual(first['baseline_comparison'],second['baseline_comparison'])
 def test_ml_regression_and_exploratory_clustering(self):
  records=[]
  for i in range(15):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':float(i),'y':float(i*2+1)}})
  ml=analyze(request(['ml_experiment'],'non_gaze_only',{'target':'y','features':['x'],'task':'regression'},records))['results']['ml_experiment']
  self.assertIn('ridge',ml['baseline_comparison']); self.assertIn('rmse',ml['baseline_comparison']['ridge']['metrics'])
  cl=analyze(request(['clustering'],'non_gaze_only',{'features':['x','y'],'n_clusters':3,'seed':1},records))['results']['clustering']
  self.assertEqual(cl['status'],'succeeded'); self.assertEqual(sum(cl['cluster_sizes'].values()),15)
 def test_aoi_comparison_pairs_participants_and_corrects_family(self):
  records=[]
  for i in range(8):
   for aoi,value in [('hero',500+i*2),('footer',800+i*2+i%3)]:
    records.append({'record_id':f'{i}-{aoi}','participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['gaze'],'features':{'dwell_ms':{'value':value,'unit':'ms','modality':'gaze','aoi_id':aoi}}})
  result=analyze(request(['aoi_summary','aoi_comparison'],'best_available',{'feature':'dwell_ms','correction':'holm'},records))['results']
  self.assertEqual(result['aoi_comparison']['status'],'succeeded')
  pair=result['aoi_comparison']['tests']['footer vs hero']; self.assertEqual(pair['method'],'paired_t_test'); self.assertAlmostEqual(pair['mean_difference'],-300.875)
  self.assertEqual(result['aoi_summary']['aois']['hero']['dwell_ms']['distribution']['n'],8)
 def test_ml_uncertainty_and_subgroup_audit_are_explicit(self):
  records=[]
  for i in range(30):
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['survey'],'features':{'x':float(i%10),'outcome':float((i%10)*2),'arm':'a' if i<15 else 'b'}})
  result=analyze(request(['ml_experiment'],'non_gaze_only',{'target':'outcome','features':['x'],'task':'regression','audit_group':'arm','seed':4},records))['results']['ml_experiment']
  ridge=result['baseline_comparison']['ridge']; self.assertIn('uncertainty',ridge); self.assertIn('subgroup_audit',ridge); self.assertIn('not a fairness certification',ridge['subgroup_audit']['caveat'])
 def test_gaze_enhancement_compares_only_matching_cohorts(self):
  records=[]
  for i in range(24):
   fs={'x':float(i),'target':float(2*i+1),'gaze_score':float(i%7)}
   if i%4==0:fs['gaze_score']={'value':None,'unit':'ratio','modality':'gaze'}
   else:fs['gaze_score']={'value':float(i%7),'unit':'ratio','modality':'gaze'}
   records.append({'record_id':str(i),'participant_id':str(i),'study_id':'study-demo-001','feature_set_version':'1.0.0','modality':['interaction','gaze'] if i%4 else ['interaction'],'features':fs})
  p={'target':'target','non_gaze_features':['x'],'gaze_features':['gaze_score'],'task':'regression','seed':8}
  result=analyze(request(['modality_comparison'],'best_available',p,records))['results']['modality_comparison']
  self.assertEqual(result['comparison_status'],'not_comparable'); self.assertTrue(result['reasons'])
  complete=[dict(r,features={**r['features'],'gaze_score':{'value':float(i%7),'unit':'ratio','modality':'gaze'}}) for i,r in enumerate(records)]
  result=analyze(request(['modality_comparison'],'best_available',p,complete))['results']['modality_comparison']
  self.assertEqual(result['comparison_status'],'comparable'); self.assertIn('ridge',result['metric_differences'])
 def test_request_filter_timestamp_and_validation(self):
  records=[dict(r,occurred_at='2026-01-01T00:00:00Z') for r in FIXTURE]
  req=request(['descriptive'],'non_gaze_only',{'filters':{'time_from':'2026-01-01T00:00:00Z','time_to':'2026-01-01T23:59:59Z'}},records)
  self.assertEqual(analyze(req)['data_scope']['filter_summary']['selected_record_n'],6)
  req['parameters']['filters']={'time_from':'not-a-date'}
  with self.assertRaises(AnalysisError):analyze(req)
 def test_http_job_retrieval_csv_and_history(self):
  from services.analytics.server import Handler
  with tempfile.TemporaryDirectory() as d:
   class TestHandler(Handler):
    store=ResultStore(Path(d)/'http.sqlite3')
    jobs={}; jobs_lock=threading.Lock()
   http=ThreadingHTTPServer(('127.0.0.1',0),TestHandler); thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start(); base=f'http://127.0.0.1:{http.server_port}'
   try:
    body=json.dumps(request(['descriptive'],records=FIXTURE)).encode(); res=urlopen(Request(base+'/v1/analytics/jobs',body,{'Content-Type':'application/json'})); job=json.load(res); self.assertEqual(res.status,202)
    for _ in range(80):
     try:job=json.load(urlopen(base+'/v1/analytics/jobs/'+job['job_id']))
     except Exception:time.sleep(.02); continue
     if job['status'] in {'succeeded','failed'}:break
     time.sleep(.02)
    self.assertEqual(job['status'],'succeeded')
    result=json.load(urlopen(base+'/v1/analytics/results/'+job['result_id'])); self.assertEqual(result['status'],'succeeded')
    replay=urlopen(Request(base+'/v1/analytics/jobs',body,{'Content-Type':'application/json'})); self.assertEqual(replay.status,200); self.assertEqual(json.load(replay)['result_id'],job['result_id'])
    csv_response=urlopen(base+'/v1/analytics/results/'+job['result_id']+'.csv'); self.assertIn('text/csv',csv_response.headers['Content-Type']); self.assertIn(b'response_time_ms',csv_response.read())
    history=json.load(urlopen(base+'/v1/analytics/results?study_id=study-demo-001')); self.assertEqual(len(history['results']),1)
    self.assertNotIn('results',history['results'][0])
    second_records=[dict(r,features={**r['features'],'response_time_ms':{**r['features']['response_time_ms'],'value':r['features']['response_time_ms']['value']+10}}) for r in FIXTURE]
    second_req=request(['descriptive'],records=second_records); second_req['request_id']='req-second'; second=analyze(second_req); TestHandler.store.save(second)
    compared=json.load(urlopen(base+'/v1/analytics/compare?left_id='+job['result_id']+'&right_id='+second['result_id'])); self.assertEqual(compared['status'],'comparable'); self.assertAlmostEqual(compared['descriptive_mean_differences']['response_time_ms']['mean_delta'],10)
    timed_records=[dict(r,occurred_at='2026-05-01T00:00:00Z') for r in FIXTURE]
    timed=request(['descriptive'],'non_gaze_only',{'filters':{'time_from':'2026-05-01T00:00:00Z'}},timed_records); timed['request_id']='req-timed'; timed_result=analyze(timed); TestHandler.store.save(timed_result)
    incomparable=json.load(urlopen(base+'/v1/analytics/compare?left_id='+job['result_id']+'&right_id='+timed_result['result_id'])); self.assertEqual(incomparable['status'],'not_comparable'); self.assertIn('filter/time selection differs',incomparable['reasons'])
   finally:http.shutdown(); http.server_close(); thread.join(timeout=2)
 def test_server_timeout_is_exposed_as_failed_job(self):
  from services.analytics import server
  finished=threading.Event()
  def slow_analysis(req):
   finished.wait(timeout=2)
   return analyze(req)
  with tempfile.TemporaryDirectory() as d:
   class TimeoutHandler(server.Handler):
    store=ResultStore(Path(d)/'timeout.sqlite3')
    jobs={}; jobs_lock=threading.Lock(); job_timers={}; job_timeout_seconds=.05
    executor=server.ThreadPoolExecutor(max_workers=1)
   http=ThreadingHTTPServer(('127.0.0.1',0),TimeoutHandler); thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start(); base=f'http://127.0.0.1:{http.server_port}'
   try:
    body=json.dumps(request(['descriptive'])).encode()
    with patch('services.analytics.server.analyze',side_effect=slow_analysis):
     job=json.load(urlopen(Request(base+'/v1/analytics/jobs',body,{'Content-Type':'application/json'})))
     deadline=time.monotonic()+1
     while time.monotonic()<deadline:
      state=json.load(urlopen(base+'/v1/analytics/jobs/'+job['job_id']))
      if state['status']=='failed':break
      time.sleep(.01)
     self.assertEqual(state['status'],'failed'); self.assertEqual(state['error']['code'],'analysis_timeout')
     finished.set(); time.sleep(.05)
     self.assertIsNone(TimeoutHandler.store.get_by_request('req-test','study-demo-001'))
   finally:
    finished.set(); http.shutdown(); http.server_close(); thread.join(timeout=2); TimeoutHandler.executor.shutdown(wait=True,cancel_futures=True)
if __name__=='__main__': unittest.main()
