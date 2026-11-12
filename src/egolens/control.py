"""Start/stop only this checkout's configured processes; never stop unrelated GPU jobs."""
import json,os,pathlib,subprocess,sys,time,urllib.request,signal,socket
from egolens.settings import ROOT,CONFIG_PATH,load_config,resolve_path,executable_path,state_dir
MODULES={'visual':'egolens.services.visual','tracker':'egolens.services.tracker','web':'egolens.web'}
def healthy(name,cfg):
    port=cfg[{'visual':'visual_port','tracker':'tracker_port','web':'web_port'}[name]]
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}'+('/api/health' if name=='web' else '/'),timeout=2) as r:d=json.load(r)
        return bool(d.get('web') if name=='web' else d.get('ready'))
    except Exception:return False

def control(action,names):
    cfg=load_config();folder=state_dir();folder.mkdir(parents=True,exist_ok=True);p=folder/'services.json'
    saved=json.loads(p.read_text()) if p.exists() else {}
    for name in names:
        ready=healthy(name,cfg);record=saved.get(name,{})
        if action=='status':print(name,'ready' if ready else 'offline',flush=True);continue
        if action=='stop':
            pid=record.get('pid');proc=pathlib.Path('/proc')/str(pid)
            if pid and proc.exists():
                cmd=(proc/'cmdline').read_bytes()
                if MODULES[name].encode() not in cmd or (proc/'cwd').resolve()!=ROOT:raise RuntimeError('PID no longer belongs to this checkout; refusing to stop it')
                os.killpg(pid,signal.SIGTERM)
                for _ in range(40):
                    if not healthy(name,cfg):break
                    time.sleep(.1)
                print(name,'stopped',flush=True)
            elif ready:raise RuntimeError(name+' is running but is not owned by this controller')
            else:print(name,'offline',flush=True)
            saved.pop(name,None);p.write_text(json.dumps(saved,indent=2));continue
        if ready:print(name,'already ready',flush=True);continue
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),EGOLENS_ROOT=str(ROOT),EGOLENS_CONFIG=str(CONFIG_PATH),PYTHONUNBUFFERED='1',OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4')
        if name!='web':
            gpu=str(cfg['gpu_'+name]);allowed={r['pid'] for r in saved.values() if r.get('gpu')==gpu}
            check=subprocess.run(['nvidia-smi',f'--id={gpu}','--query-compute-apps=pid','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True)
            active={int(line.strip()) for line in check.stdout.splitlines() if line.strip().isdigit()}
            if active-allowed:raise RuntimeError(f'Configured GPU {gpu} has unrelated processes; choose an available GPU')
            env['CUDA_VISIBLE_DEVICES']=gpu
        else:env['CUDA_VISIBLE_DEVICES']=''
        python=executable_path(cfg['python_'+('api' if name=='web' else name)])
        if not python.is_file():raise ValueError('Configure python_'+('api' if name=='web' else name)+' to an installed environment')
        logs=folder/'logs';logs.mkdir(exist_ok=True);log=logs/(name+'.log')
        if log.exists() and log.stat().st_size>5*1024**2:log.replace(log.with_suffix('.previous.log'))
        with log.open('a') as f:proc=subprocess.Popen([str(python),'-m',MODULES[name]],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        saved[name]={'pid':proc.pid,'gpu':env['CUDA_VISIBLE_DEVICES'],'started':time.time()};p.write_text(json.dumps(saved,indent=2));print(name,'starting',proc.pid,'log:',log.relative_to(ROOT) if log.is_relative_to(ROOT) else log,flush=True)

def doctor():
    import shutil
    cfg=load_config();checks={}
    for key in ['model_path','sam2_checkpoint']:
        checks[key]=bool(cfg[key]) and resolve_path(cfg[key]).exists()
    for key in ['python_api','python_visual','python_tracker']:checks[key]=executable_path(cfg[key]).is_file()
    for binary in ['ffmpeg','ffprobe','nvidia-smi']:checks[binary]=bool(shutil.which(binary))
    checks['memory_file']=resolve_path(cfg['memory_file']).is_file()
    checks['answer_api_key']=bool(os.getenv('DEEPSEEK_API_KEY'))
    for name,ok in checks.items():print(('OK      ' if ok else 'MISSING ')+name)
    print('No model was started. Model weights, CUDA/GPU and environment paths are operator configuration.')
    return all(checks.values())
