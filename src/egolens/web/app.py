"""Local M5 UI/API. Media and credentials remain on the server."""
import pathlib,json,uuid,time,hashlib,threading,subprocess,os,urllib.request,shutil,sqlite3,io,base64
import secrets
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse,RedirectResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from egolens.settings import ROOT as R,load_config,resolve_path,state_dir,memory_entries
config=load_config();OUT=state_dir();OUT.mkdir(parents=True,exist_ok=True)
for n in ['frames','targets','sessions','jobs']:(OUT/n).mkdir(exist_ok=True)
app=FastAPI();pool=ThreadPoolExecutor(max_workers=3);guard=threading.RLock();sam_lock=threading.Lock();frame_lock=threading.Lock();session_locks={};local=threading.local()
catalog={};entries={}
for e in memory_entries():
    path=pathlib.Path(e['video_path']).resolve();vid=hashlib.sha256(str(path).encode()).hexdigest()[:12]
    if vid not in catalog:
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True));v=next(s for s in info['streams'] if s['codec_type']=='video')
        catalog[vid]={'id':vid,'path':str(path),'name':e.get('title',path.stem),'day':e['date'],'duration':float(info['format']['duration']),'width':v['width'],'height':v['height'],'long':float(info['format']['duration'])>120}
        entries[vid]=[]
    entries[vid].append(e)
for vid,data in entries.items():(OUT/f'index_{vid}.json').write_text(json.dumps(data,ensure_ascii=False))
QUERY_DAY='DAY'+str(max([int(v['day'].replace('DAY','')) for v in catalog.values()]+[0])+1)

@app.middleware('http')
async def private_demo(request,call_next):
    token=os.getenv('DEMO_ACCESS_TOKEN','')
    protected=request.url.path.startswith(('/api/','/demo')) and request.url.path!='/api/health'
    if protected and token:
        try:
            kind,value=request.headers.get('Authorization','').split(' ',1)
            password=base64.b64decode(value).decode().split(':',1)[1] if kind.lower()=='basic' else ''
        except Exception:password=''
        if not secrets.compare_digest(password,token):return Response('Private demo: sign in with the operator password.',status_code=401,headers={'WWW-Authenticate':'Basic realm="EgoLens demo", charset="UTF-8"'})
    return await call_next(request)

@app.get('/api/health')
def health():
    result={'web':True,'vision':False,'tracker':False,'answer_key_configured':bool(os.getenv('DEEPSEEK_API_KEY'))}
    for name,url in [('vision',config['visual_service']),('tracker',config['tracker_service'])]:
        try:
            with urllib.request.urlopen(url,timeout=1) as r:result[name]=r.status==200
        except Exception:pass
    result['ready']=all(result[k] for k in ['vision','tracker','answer_key_configured']) and bool(catalog)
    return result

@app.get('/api/demos')
def recorded_demos():
    return {'mode':'recorded','items':json.loads((R/'site/site.json').read_text())['demos']}

def atomic(path,data):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False));os.replace(tmp,path)
def session(sid):
    if not __import__('re').fullmatch('[a-f0-9]{32}',sid):raise HTTPException(400,'会话无效')
    p=OUT/'sessions'/f'{sid}.json'
    if not p.exists():raise HTTPException(404,'会话不存在')
    return json.loads(p.read_text())
def target(sid,tid):
    s=session(sid)
    if tid not in s['targets']:raise HTTPException(404,'此目标不属于当前会话')
    p=OUT/'targets'/tid;return json.loads((p/f"r{s['targets'][tid]}.json").read_text())
def save_target(t):
    if not t.get('thumbnail'):
        seed=t['prompts'][-1]['frame'];f=next((f for f in t['frames'] if f['frame']==seed and f['bbox']),None)
        path=pathlib.Path(t['frames_dir'])/f'{seed:05d}.jpg'
        if f and path.exists():
            from PIL import Image
            image=Image.open(path);x1,y1,x2,y2=f['bbox'];image=image.crop((max(0,x1-5),max(0,y1-5),min(image.width,x2+5),min(image.height,y2+5)));image.thumbnail((96,96));buf=io.BytesIO();image.save(buf,format='JPEG');t['thumbnail']=base64.b64encode(buf.getvalue()).decode()
    p=OUT/'targets'/t['id'];p.mkdir(exist_ok=True);atomic(p/f"r{t['revision']}.json",t)
    s=session(t['session']);s['targets'][t['id']]=t['revision'];atomic(OUT/'sessions'/f"{t['session']}.json",s)
def job(kind,fn):
    ident=uuid.uuid4().hex;record={'id':ident,'kind':kind,'state':'queued','created':time.time(),'message':'已排队'}
    atomic(OUT/'jobs'/f'{ident}.json',record)
    def update(**kw):record.update(kw);atomic(OUT/'jobs'/f'{ident}.json',record)
    def run():
        try:
            if (OUT/'jobs'/f'{ident}.cancel').exists():
                update(state='canceled',message='任务已取消');return
            update(state='running',message='正在处理');result=fn(ident,update)
            if (OUT/'jobs'/f'{ident}.cancel').exists():update(state='canceled',message='任务已取消')
            else:update(state='done',result=result,message='完成',seconds=time.time()-record['created'])
        except Exception as e:
            update(state='canceled' if (OUT/'jobs'/f'{ident}.cancel').exists() else 'failed',message=str(e)[:300])
    pool.submit(run);return record
def getvideo(vid):
    if vid not in catalog:raise HTTPException(404,'视频不存在')
    return catalog[vid]
def prepare(vid,seconds):
    v=getvideo(vid);seconds=max(0,min(seconds,v['duration']-.1));start=max(0,int((seconds-15)//30)*30);duration=min(60,v['duration']-start)
    key=f'{vid}_{start}';folder=OUT/'frames'/key
    with frame_lock:
        if not (folder/'meta.json').exists():
            folder.mkdir(exist_ok=True)
            subprocess.run(['ffmpeg','-loglevel','error','-y','-ss',str(start),'-i',v['path'],'-t',str(duration),'-vf',"fps=5,scale=640:-2",'-q:v','3','-start_number','0',str(folder/'%05d.jpg')],check=True)
            from PIL import Image
            w,h=Image.open(folder/'00000.jpg').size;n=len(list(folder.glob('*.jpg')))
            atomic(folder/'meta.json',{'key':key,'video_id':vid,'start':start,'duration':duration,'fps':5,'count':n,'width':w,'height':h})
        meta=json.loads((folder/'meta.json').read_text());os.utime(folder,None)
    frame=min(meta['count']-1,max(0,round((seconds-start)*5)))
    return folder,meta,frame
def sam(t,propagate=False,cancel_file=None):
    if not pathlib.Path(t['frames_dir']).exists():prepare(t['video_id'],t['chunk_start']+30)
    d={'frames':t['frames_dir'],'object_id':t['object_id'],'prompts':t['prompts'],'propagate':propagate,'cancel_file':str(cancel_file) if cancel_file else None}
    req=urllib.request.Request(config['tracker_service'],data=json.dumps(d).encode(),headers={'Content-Type':'application/json'})
    with sam_lock:
        with urllib.request.urlopen(req,timeout=240) as response:r=json.load(response)
    for f in r['frames']:f['time_s']=t['chunk_start']+f['frame']/5;f['object_id']=t['object_id']
    return r
class Prompt(BaseModel):
    session:str;video_id:str;time:float=Field(ge=0);target_id:str|None=None
    points:list[list[float]]|None=None;labels:list[int]|None=None;box:list[float]|None=None
class TargetRequest(BaseModel):session:str;target_id:str
class Query(BaseModel):
    session:str;video_id:str;question:str=Field(min_length=1,max_length=1000);target_id:str|None=None
@app.get('/api/videos')
def videos():return [{k:v for k,v in x.items() if k!='path'} for x in catalog.values()]
@app.post('/api/sessions')
def new_session():
    ident=uuid.uuid4().hex;atomic(OUT/'sessions'/f'{ident}.json',{'id':ident,'targets':{},'created':time.time()});return {'id':ident}
@app.get('/api/sessions/{sid}')
def get_session(sid:str):
    s=session(sid);return {'id':sid,'targets':[target(sid,tid) for tid in s['targets']]}
def cards(result):
    result_cards=[]
    ref=result.get('resolution',{}).get('state',{}).get('entity_ref') or {};tr=ref.get('track_ref') or {}
    for o in result.get('observations',[]):
        vid=next((k for k,v in catalog.items() if pathlib.Path(v['path'])==pathlib.Path(o['source_path']).resolve()),None)
        result_cards.append({'id':o['evidence_id'],'video_id':vid,'start':o.get('media_offset',0)+o['window'][0],'end':o.get('media_offset',0)+o['window'][1],'text':o['observation'],'speech':o.get('speech_evidence',[]),'selected_region_used':o.get('raw',{}).get('selected_region_used',False),'target_object_id':o.get('raw',{}).get('target_object_id'),'target_id':ref.get('id'),'target_revision':tr.get('revision')})
    return result_cards
@app.get('/api/sessions/{sid}/history')
def history(sid:str,video_id:str):
    session(sid);getvideo(video_id);path=OUT/'conversations.sqlite'
    if not path.exists():return []
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT question,answer,result,state FROM turns WHERE session=? ORDER BY number',(sid+'_'+video_id,)).fetchall()[-50:]
    output=[]
    for q,a,r,s in rows:
        result=json.loads(r);state=json.loads(s);ref=state.get('entity_ref') or {}
        output.append({'question':q,'answer':a,'evidence':cards(result),'target_id':ref.get('id'),'revision':(ref.get('track_ref') or {}).get('revision'),'seconds':result.get('elapsed_seconds',0)})
    return output
@app.get('/api/videos/{vid}/media')
def media(vid:str):return FileResponse(getvideo(vid)['path'],media_type='video/mp4')
@app.get('/api/videos/{vid}/frame')
def frame(vid:str,t:float=0):
    folder,m,idx=prepare(vid,t);return {'frame':idx,'time':m['start']+idx/5,'chunk':m,'url':f'/api/frames/{m["key"]}/{idx}'}
@app.get('/api/frames/{key}/{idx}')
def image(key:str,idx:int):
    if not __import__('re').fullmatch('[a-f0-9]{12}_\d+',key) or idx<0:raise HTTPException(400,'帧无效')
    return FileResponse(OUT/'frames'/key/f'{idx:05d}.jpg',media_type='image/jpeg')
@app.post('/api/targets/preview')
def preview(d:Prompt):
    session(d.session);v=getvideo(d.video_id)
    if not d.target_id and d.box is None and d.labels and not any(d.labels):raise HTTPException(400,'请先使用正点或框选，再添加负点')
    if d.box is not None:
        if len(d.box)!=4 or not all(0<=x<=1 for x in d.box) or not(d.box[0]<d.box[2] and d.box[1]<d.box[3]):raise HTTPException(400,'框坐标无效')
    elif not d.points or not d.labels or len(d.points)!=len(d.labels) or any(len(p)!=2 or any(not 0<=x<=1 for x in p) for p in d.points) or any(x not in [0,1] for x in d.labels):raise HTTPException(400,'点坐标无效')
    def work(jid,update):
        update(message='准备当前视频区间');folder,m,idx=prepare(d.video_id,d.time)
        with guard:
            if d.target_id:
                t=target(d.session,d.target_id)
                if t['video_id']!=d.video_id or t['frames_dir']!=str(folder):raise ValueError('补点请在当前目标的已处理区间内进行，或新建目标')
                t['revision']+=1;t.pop('thumbnail',None)
            else:
                s=session(d.session);oid=max([target(d.session,x)['object_id'] for x in s['targets']] or [0])+1
                p=pathlib.Path(v['path']);t={'id':uuid.uuid4().hex,'session':d.session,'video_id':d.video_id,'object_id':oid,'revision':1,'label':f'目标 {oid}','source_path':v['path'],'source_signature':{'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns},'frames_dir':str(folder),'chunk_start':m['start'],'chunk_end':m['start']+m['duration'],'tracking_width':m['width'],'tracking_height':m['height'],'prompts':[]}
            p={'frame':idx,'points':d.points,'labels':d.labels,'box':d.box}
            previous=next((x for x in t['prompts'] if x['frame']==idx),None)
            if previous and d.points and previous.get('points'):
                p['points']=previous['points']+d.points;p['labels']=previous['labels']+d.labels
            if previous and d.points and previous.get('box') is not None:p['box']=previous['box']
            t['prompts']=[x for x in t['prompts'] if x['frame']!=idx]+[p];t['confirmed']=False;t['seed_time']=m['start']+idx/5
            update(message='SAM2生成分割预览');result=sam(t)
            if (OUT/'jobs'/f'{jid}.cancel').exists():raise InterruptedError('分割预览已取消')
            t['frames']=result['frames'];t['preview_seconds']=result['seconds'];save_target(t)
        return t
    return job('preview',work)
@app.post('/api/targets/track')
def track(d:TargetRequest):
    t=target(d.session,d.target_id)
    with guard:t['confirmed']=True;save_target(t)
    def work(jid,update):
        update(message='SAM2前向与回溯追踪');result=sam(t,True,OUT/'jobs'/f'{jid}.cancel')
        with guard:
            if target(d.session,t['id'])['revision']!=t['revision']:raise ValueError('选区已更新，此次旧追踪结果已隔离')
            t['frames']=result['frames'];t['tracking_seconds']=result['seconds'];save_target(t)
        return t
    return job('tracking',work)
@app.get('/api/targets/{tid}')
def get_target(tid:str,session_id:str):return target(session_id,tid)
@app.get('/api/jobs/{jid}')
def get_job(jid:str):
    if not __import__('re').fullmatch('[a-f0-9]{32}',jid):raise HTTPException(400,'任务无效')
    p=OUT/'jobs'/f'{jid}.json'
    if not p.exists():raise HTTPException(404,'任务不存在')
    return json.loads(p.read_text())
@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str):
    with guard:
        get_job(jid);(OUT/'jobs'/f'{jid}.cancel').touch()
    return {'canceled':True}
@app.post('/api/query')
def query(d:Query):
    session(d.session);getvideo(d.video_id);t=target(d.session,d.target_id) if d.target_id else None
    if t and (t['video_id']!=d.video_id or not t['confirmed']):raise HTTPException(400,'请先确认当前视频中的目标')
    def work(jid,update):
        lock=session_locks.setdefault(d.session,threading.Lock())
        with lock:
            from egolens.runtime import build
            cache=getattr(local,'engines',{});local.engines=cache
            if d.video_id not in cache:
                update(message='载入视频索引与会话服务');cache[d.video_id]=build(OUT/'conversations.sqlite',cache=False,memory_file=str(OUT/f'index_{d.video_id}.json'))
            engine,usage,visual=cache[d.video_id];u,v=len(usage),len(visual)
            tr={'id':t['id'],'label':'user-selected object','aliases':[t['label']],
                'selection_context':f"Explicit click at source media {t['seed_time']:.2f}s; tracked interval {t['chunk_start']:.2f}-{t['chunk_end']:.2f}s. The nickname is unverified.",
                'anchor_clips':[e['clip_id'] for e in entries[d.video_id] if e.get('media_offset',0)<=t['seed_time']<e.get('media_offset',0)+e['duration']],
                'track_ref':{'m5_target_id':t['id'],'source_path':t['source_path'],'object_id':t['object_id'],'revision':t['revision']}} if t else None
            if t:
                from egolens.core.time_utils import recording_seconds
                base=recording_seconds(entries[d.video_id][0]['start_time'])-entries[d.video_id][0].get('media_offset',0);day=int(catalog[d.video_id]['day'][3:])
                minute=int((base+t['seed_time'])//60)*60
                tr['tracking_scope']={'days':[day],'interval':[base+t['chunk_start'],base+t['chunk_end']]}
                tr['local_speech_scope']={'days':[day],'interval':[minute,minute+60]}
            valid=lambda:not (OUT/'jobs'/f'{jid}.cancel').exists() and (not t or target(d.session,t['id'])['revision']==t['revision'])
            update(message='检索片段、核对画面与语音，再组织回答')
            r=engine.run(d.question,d.session+'_'+d.video_id,QUERY_DAY,'23595900',target_ref=tr,commit_guard=valid,commit_lock=guard,release_selection=not bool(t))
            if not valid():raise ValueError('任务已取消或目标已修订，结果未写入当前记忆')
            evidence=cards(r)
            return {'answer':r['answer']['answer'],'evidence':evidence,'target_id':t['id'] if t else None,'revision':t['revision'] if t else None,'api_usage':usage[u:],'visual_usage':visual[v:],'seconds':r['elapsed_seconds'],'resolution':r['resolution']}
    return job('query',work)
# Static routes are registered after API routes below.
@app.on_event('startup')
def recover_and_maintain():
    for p in (OUT/'jobs').glob('*.json'):
        r=json.loads(p.read_text())
        if r['state'] in ['running','queued']:r.update(state='failed',message='服务已重启，请重试此任务');atomic(p,r)
    def clean():
        while True:
            time.sleep(120)
            with frame_lock:
                if not sam_lock.acquire(blocking=False):continue
                try:
                    folders=sorted((p for p in (OUT/'frames').iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True)
                    total=0
                    for i,p in enumerate(folders):
                        size=sum(x.stat().st_size for x in p.rglob('*') if x.is_file());total+=size
                        if i>0 and (total>1024**3 or time.time()-p.stat().st_mtime>3600):
                            assert p.resolve().is_relative_to((OUT/'frames').resolve());shutil.rmtree(p)
                    files=sorted((OUT/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                    for p in files[200:]:
                        if time.time()-p.stat().st_mtime>86400 and json.loads(p.read_text())['state'] not in ['running','queued']:p.unlink()
                finally:sam_lock.release()
    threading.Thread(target=clean,daemon=True).start()

@app.get('/demo')
def demo_redirect():return RedirectResponse('/demo/')

@app.get('/app.js')
def workspace_js():return FileResponse(pathlib.Path(__file__).parent/'workspace/app.js')

@app.get('/style.css')
def workspace_css():return FileResponse(pathlib.Path(__file__).parent/'workspace/style.css')

@app.get('/favicon.svg')
def favicon():return FileResponse(pathlib.Path(__file__).parent/'workspace/favicon.svg')

app.mount('/demo',StaticFiles(directory=str(pathlib.Path(__file__).parent/'workspace'),html=True),name='workspace')
app.mount('/',StaticFiles(directory=str(R/'site'),html=True),name='project')
