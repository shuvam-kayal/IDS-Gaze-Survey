"""Local analytics HTTP adapter. For deployment mount behind the project's authenticated API."""
from __future__ import annotations
import json,os,csv,io,threading,uuid,ipaddress
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .engine import AnalysisError,ResultStore,analyze,validate_request
from .capabilities import MODEL_REGISTRY,predict_with_saved_result

HERE=Path(__file__).resolve().parents[2]
UI=HERE/'apps'/'researcher-console'/'src'/'features'/'analytics'/'index.html'
class Handler(BaseHTTPRequestHandler):
 store=ResultStore(os.environ.get('P4_RESULTS_DB',str(HERE/'var'/'analysis-results.sqlite3')))
 executor=ThreadPoolExecutor(max_workers=max(1,min(4,int(os.environ.get('P4_ANALYTICS_WORKERS','2')))))
 jobs={}; jobs_lock=threading.Lock(); job_timers={}; job_timeout_seconds=max(.05,float(os.environ.get('P4_ANALYTICS_JOB_TIMEOUT_SECONDS','120'))); authorizer=None
 def authorize(self,action,study_id):
  if self.authorizer is not None:
   try:return bool(self.authorizer(self,action,study_id))
   except Exception:return False
  try:return ipaddress.ip_address(self.client_address[0]).is_loopback
  except (ValueError,TypeError):return False
 def deny_unless_authorized(self,action,study_id):
  if self.authorize(action,study_id):return False
  self.send_json(403,{'status':'forbidden','error':{'code':'study_access_denied','message':'Study access is not authorized'}})
  return True
 def send_json(self,status,payload):
  body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
 def do_GET(self):
  path=urlparse(self.path).path
  if path=='/' or path=='/analytics':
   body=UI.read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
  if path=='/health':return self.send_json(200,{'status':'ok','analysis_version':'p4-analytics/1.0.0'})
  if path=='/v1/analytics/models':return self.send_json(200,{'registry_version':'p4-model-registry/1.0.0','models':MODEL_REGISTRY})
  if path=='/fixtures/synthetic_feature_records.json':
   f=(HERE/'fixtures'/'synthetic_feature_records.json').read_bytes(); self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(f))); self.end_headers(); self.wfile.write(f); return
  if path.startswith('/v1/analytics/results/'):
   rid=path.rsplit('/',1)[-1]
   if rid.endswith('.csv'):
    result=self.store.get(rid[:-4])
    if not result:return self.send_json(404,{'status':'not_found','error':{'code':'result_not_found','message':'No result exists for this identifier'}})
    if self.deny_unless_authorized('export',result['study_id']):return
    rows=[]
    for feature,summary in result.get('results',{}).get('descriptive',{}).items():
     rows.append({'feature':feature,'kind':summary.get('kind'),'n':summary.get('n'),'missing_n':summary.get('missing_n'),'mean':summary.get('mean'),'median':summary.get('median'),'sd':summary.get('sd'),'unit':summary.get('unit')})
    def safe_cell(value):
     if isinstance(value,str) and value.lstrip(' \t\r\n')[:1] in {'=','+','-','@'}:return "'"+value
     return value
    rows=[{key:safe_cell(value) for key,value in row.items()} for row in rows]
    buf=io.StringIO(); writer=csv.DictWriter(buf,fieldnames=['feature','kind','n','missing_n','mean','median','sd','unit']); writer.writeheader(); writer.writerows(rows); body=buf.getvalue().encode()
    self.send_response(200); self.send_header('Content-Type','text/csv; charset=utf-8'); self.send_header('Content-Disposition',f'attachment; filename="analysis-{result["result_id"]}.csv"'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body); return
   result=self.store.get(rid)
   if not result:return self.send_json(404,{'status':'not_found','error':{'code':'result_not_found','message':'No result exists for this identifier'}})
   if self.deny_unless_authorized('result_read',result['study_id']):return
   return self.send_json(200,result)
  if path.startswith('/v1/analytics/jobs/'):
   jid=path.rsplit('/',1)[-1]
   with self.jobs_lock:job=self.jobs.get(jid)
   if job and self.deny_unless_authorized('job_read',job['study_id']):return
   return self.send_json(200,job) if job else self.send_json(404,{'status':'not_found','error':{'code':'job_not_found','message':'No analysis job exists for this identifier'}})
  if path=='/v1/analytics/results':
   q=parse_qs(urlparse(self.path).query); sid=q.get('study_id',[''])[0]
   if not sid:return self.send_json(400,{'status':'invalid_request','error':{'code':'missing_study_id','message':'study_id query parameter is required'}})
   if self.deny_unless_authorized('result_list',sid):return
   try:limit=int(q.get('limit',['50'])[0])
   except ValueError:return self.send_json(400,{'status':'invalid_request','error':{'code':'invalid_limit','message':'limit must be an integer'}})
   try:return self.send_json(200,self.store.list_page(sid,limit,q.get('cursor',[None])[0]))
   except AnalysisError as e:return self.send_json(400,{'status':e.status,'error':{'code':e.code,'message':str(e)}})
  if path=='/v1/analytics/compare':
   q=parse_qs(urlparse(self.path).query); left=self.store.get(q.get('left_id',[''])[0]); right=self.store.get(q.get('right_id',[''])[0])
   if not left or not right:return self.send_json(404,{'status':'not_found','error':{'code':'result_not_found','message':'Both result identifiers must exist'}})
   reasons=[]
   if self.deny_unless_authorized('result_read',left['study_id']) or self.deny_unless_authorized('result_read',right['study_id']):return
   for field in ('study_id','analysis_version'):
    if left.get(field)!=right.get(field):reasons.append(field+' differs')
   for field in ('feature_set_version','analysis_types','analysis_parameters'):
    if left.get('data_scope',{}).get(field)!=right.get('data_scope',{}).get(field):reasons.append(field+' differs')
   lf=left.get('data_scope',{}).get('filter_summary',{}); rf=right.get('data_scope',{}).get('filter_summary',{})
   if lf.get('selection_fingerprint')!=rf.get('selection_fingerprint'):reasons.append('filter/time selection differs')
   if (lf.get('has_group_filter'),lf.get('group_field'),lf.get('group_values'))!=(rf.get('has_group_filter'),rf.get('group_field'),rf.get('group_values')):reasons.append('group filter differs')
   if left.get('metadata',{}).get('modality')!=right.get('metadata',{}).get('modality'):reasons.append('modality differs')
   a=left.get('results',{}).get('descriptive',{}); b=right.get('results',{}).get('descriptive',{})
   common=sorted(set(a)&set(b)); metrics={}
   for name in common:
     if a[name].get('kind')==b[name].get('kind')=='numeric' and a[name].get('unit')==b[name].get('unit') and isinstance(a[name].get('mean'),(int,float)) and isinstance(b[name].get('mean'),(int,float)):metrics[name]={'left_mean':a[name]['mean'],'right_mean':b[name]['mean'],'mean_delta':b[name]['mean']-a[name]['mean'],'unit':a[name].get('unit')}
   return self.send_json(200,{'status':'not_comparable' if reasons else 'comparable','reasons':reasons,'left_result_id':left['result_id'],'right_result_id':right['result_id'],'study_id':left['study_id'],'time_scope':{'left':{k:lf.get(k) for k in ('time_from','time_to','timestamp_field')},'right':{k:rf.get(k) for k in ('time_from','time_to','timestamp_field')}},'descriptive_mean_differences':metrics,'warning':'Descriptive differences are not an inferential test; results must share compatible study, version, modality, analysis parameters and group scope.'})
  return self.send_json(404,{'status':'not_found','error':{'code':'not_found','message':'Route not found'}})
 def do_POST(self):
  path=urlparse(self.path).path
  if path.startswith('/v1/analytics/models/') and path.endswith('/predict'):
   rid=path.split('/')[-2]; result=self.store.get(rid)
   if not result:return self.send_json(404,{'status':'not_found','error':{'code':'model_result_not_found','message':'Saved model result was not found'}})
   if self.deny_unless_authorized('model_use',result['study_id']):return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if length<=0 or length>10_000_000:raise AnalysisError('invalid_body','Request body must be between 1 byte and 10 MB')
    data=json.loads(self.rfile.read(length))
    if not isinstance(data,dict) or not isinstance(data.get('feature_records'),list):raise AnalysisError('invalid_feature_records','Body must include a feature_records array')
    return self.send_json(200,predict_with_saved_result(result,data['feature_records']))
   except json.JSONDecodeError:return self.send_json(400,{'status':'invalid_request','error':{'code':'invalid_json','message':'Request body is not valid JSON'}})
   except AnalysisError as e:return self.send_json(422,{'status':e.status,'error':{'code':e.code,'message':str(e)}})
  if path not in {'/v1/analytics/analyze','/v1/analytics/jobs'}:return self.send_json(404,{'status':'not_found','error':{'code':'not_found','message':'Route not found'}})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length<=0 or length>10_000_000:raise AnalysisError('invalid_body','Request body must be between 1 byte and 10 MB')
   request=json.loads(self.rfile.read(length)); request=validate_request(request)
   if self.deny_unless_authorized('analysis_run',request['study_id']):return
   if path=='/v1/analytics/jobs':
    fp=__import__('hashlib').sha256(json.dumps(request,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    previous=self.store.get_by_request(request['request_id'],request['study_id'])
    if previous:
     if previous.get('request_fingerprint')!=fp:return self.send_json(409,{'status':'conflict','error':{'code':'idempotency_conflict','message':'request_id was already used with a different payload'}})
     return self.send_json(200,{'job_id':previous['result_id'],'status':'succeeded','request_id':request['request_id'],'study_id':request['study_id'],'request_fingerprint':fp,'created_at':previous['generated_at'],'completed_at':previous['generated_at'],'result_id':previous['result_id']})
    with self.jobs_lock:
     duplicate=next((job for job in self.jobs.values() if job.get('request_id')==request['request_id'] and job.get('study_id')==request['study_id']),None)
     if duplicate:
      if duplicate.get('request_fingerprint')!=fp:return self.send_json(409,{'status':'conflict','error':{'code':'idempotency_conflict','message':'request_id is already running with a different payload'}})
      return self.send_json(202,duplicate)
     jid=str(uuid.uuid4()); record={'job_id':jid,'request_id':request['request_id'],'study_id':request['study_id'],'request_fingerprint':fp,'status':'queued','created_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
     self.jobs[jid]=record
     if len(self.jobs)>500:
      terminal=[key for key,value in self.jobs.items() if value.get('status') in {'succeeded','failed'}]
      for old in terminal[:max(0,len(self.jobs)-500)]:self.jobs.pop(old,None)
     timer=threading.Timer(self.job_timeout_seconds,self._expire_job,args=(jid,)); timer.daemon=True; self.job_timers[jid]=timer; timer.start()
    self.executor.submit(self._run_job,jid,request)
    return self.send_json(202,record)
   existing=self.store.get_by_request(request['request_id'],request['study_id'])
   request_fingerprint=__import__('hashlib').sha256(json.dumps(request,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
   if existing:
    if existing.get('request_fingerprint')!=request_fingerprint:return self.send_json(409,{'status':'conflict','error':{'code':'idempotency_conflict','message':'request_id was already used with a different payload'}})
    return self.send_json(200,existing)
   result=analyze(request); self.store.save(result); result=self.store.get_by_request(request['request_id'],request['study_id']) or result
   return self.send_json(200,result)
  except json.JSONDecodeError:return self.send_json(400,{'status':'invalid_request','error':{'code':'invalid_json','message':'Request body is not valid JSON'}})
  except AnalysisError as e:return self.send_json(422,{'status':e.status,'error':{'code':e.code,'message':str(e)}})
  except (ValueError,TypeError) as e:return self.send_json(422,{'status':'invalid_request','error':{'code':'invalid_parameters','message':str(e)}})
  except Exception:return self.send_json(500,{'status':'failed','error':{'code':'analysis_failed','message':'Analysis failed unexpectedly. Check server logs using the request ID.'}})
 def _run_job(self,jid,request):
  with self.jobs_lock:
   if jid not in self.jobs or self.jobs[jid]['status']=='failed':return
   self.jobs[jid]['status']='running'
  try:
   result=analyze(request)
   with self.jobs_lock:
    if self.jobs.get(jid,{}).get('status')=='failed':return
    self.store.save(result)
    self.jobs[jid].update({'status':'succeeded','result_id':result['result_id'],'completed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
    timer=self.job_timers.pop(jid,None)
    if timer:timer.cancel()
  except Exception as exc:
   with self.jobs_lock:
    if self.jobs.get(jid,{}).get('status')!='failed':self.jobs[jid].update({'status':'failed','error':{'code':getattr(exc,'code','analysis_failed'),'message':str(exc)},'completed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
    timer=self.job_timers.pop(jid,None)
    if timer:timer.cancel()
 def _expire_job(self,jid):
  with self.jobs_lock:
   job=self.jobs.get(jid)
   if not job or job.get('status') in {'succeeded','failed'}:return
   job.update({'status':'failed','error':{'code':'analysis_timeout','message':f'Analysis exceeded the configured {self.job_timeout_seconds:g}-second job deadline. The worker may finish cleanup in the background.'},'completed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
   self.job_timers.pop(jid,None)
 def log_message(self,fmt,*args):
  # Avoid writing request body, identifiers, or feature values to logs.
  print('analytics-http:',fmt%args)
def main():
 host=os.environ.get('P4_HOST','127.0.0.1'); port=int(os.environ.get('P4_PORT','8084'))
 if host.lower() not in {'127.0.0.1','::1','localhost'} and Handler.authorizer is None:raise RuntimeError('Binding outside loopback requires an injected P2/integrator Handler.authorizer')
 print(f'Person 4 analytics UI/API listening at http://{host}:{port} (local demonstration only)')
 ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=='__main__':main()
