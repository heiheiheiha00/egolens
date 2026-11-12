"""Prepare coarse visual navigation records. Summaries are never treated as proof."""
import json,pathlib,subprocess,urllib.request,os
from egolens.settings import ROOT,load_config,resolve_path,executable_path,allowed_video
from egolens.core.time_utils import recording_seconds

def stamp(seconds):
    seconds=int(seconds);return f'{seconds//3600:02d}{seconds%3600//60:02d}{seconds%60:02d}00'

def ingest(a):
    cfg=load_config();video=resolve_path(a.video)
    if not allowed_video(video):raise ValueError('Place the video under a configured media_roots directory')
    if not a.day.startswith('DAY') or not a.day[3:].isdigit():raise ValueError('--day must be DAY followed by a positive integer')
    base=recording_seconds(a.start)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(video)],text=True));duration=float(info['format']['duration'])
    output=resolve_path(cfg['memory_file']);output.parent.mkdir(parents=True,exist_ok=True)
    entries=json.loads(output.read_text()) if output.exists() else [];entries=[e for e in entries if pathlib.Path(e['video_path']).resolve()!=video]
    step=max(5,min(120,a.segment_seconds));offset=0
    while offset<duration-.1:
        end=min(duration,offset+step)
        payload={'video':str(video),'window':[offset,end],'question':'Describe the scene, salient objects, visible actions, locations and transitions in this exact interval. Include uncertainty, do not invent invisible steps. This description is navigation for later direct video verification.','audio_enabled':False,'cache':False,'max_new_tokens':384}
        req=urllib.request.Request(cfg['visual_service'],data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
        entries.append({'date':a.day,'start_time':stamp(base+offset),'end_time':stamp(base+end),'text':result['answer'],'global_overview':result['answer'],'video_path':str(video),'clip_id':f'{video.stem}_{int(offset):06d}','duration':end-offset,'media_offset':offset,'title':a.title or video.stem})
        temp=output.with_suffix('.tmp');temp.write_text(json.dumps(entries,ensure_ascii=False,indent=2));temp.replace(output);print('indexed',round(offset,1),round(end,1),flush=True);offset=end
    if a.transcribe:
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),CUDA_VISIBLE_DEVICES=str(cfg['gpu_audio']))
        subprocess.run([str(executable_path(cfg['python_audio'])),'-m','egolens','transcribe',str(video),'--start',a.start],cwd=ROOT,env=env,check=True)
    print('Index saved. Restart the web service to load the updated video catalog.')
