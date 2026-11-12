"""One configured native Qwen model, shared by global and selected-region queries."""
import json,time,pathlib,os
from http.server import HTTPServer,BaseHTTPRequestHandler
from decord import VideoReader,cpu
from transformers import AutoProcessor
from egolens.settings import load_config,resolve_path,allowed_video
from egolens.vision.qwen import Qwen25VideoBackend
from egolens.vision.selected import load_target,answer as selected_answer
from egolens.audio.evidence import SpeechStore,speech_prompt
config=load_config();path=resolve_path(config['model_path'])
if not config['model_path'] or not path.is_dir():raise SystemExit('Configure model_path to a local Qwen2.5-VL directory')
backend=Qwen25VideoBackend(path,dtype=config['torch_dtype'],attention=config['attention_implementation'],local_only=config['local_models_only'])
detail=Qwen25VideoBackend.__new__(Qwen25VideoBackend);detail.model=backend.model;detail.path=str(path)
detail.processor=AutoProcessor.from_pretrained(path,local_files_only=config['local_models_only'],min_pixels=128*28*28,max_pixels=560*560)
speech_store=SpeechStore(resolve_path(config['audio_memory']));cache={}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ready":true,"backend":"qwen2.5_vl_native"}')
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<100000:raise ValueError('invalid request size')
            d=json.loads(self.rfile.read(n));p=resolve_path(d['video'])
            if not allowed_video(p):raise ValueError('video outside configured media_roots')
            vr=VideoReader(str(p),ctx=cpu(0),num_threads=1);duration=(len(vr)-1)/vr.get_avg_fps();window=d.get('window',[0,duration]);window=[max(0,float(window[0])),min(duration,float(window[1]))]
            if window[1]<=window[0]:raise ValueError('invalid time window')
            question=d['question'];budget=max(32,min(512,int(d.get('max_new_tokens',256))));detailed=bool(d.get('detail',False))
            use_audio=bool(d.get('audio_enabled',config['audio_enabled']));speech=speech_store.evidence(p,window) if use_audio else []
            ref=d.get('target_ref') or {};track_ref=ref.get('track_ref') or {}
            key=(str(p),p.stat().st_mtime_ns,tuple(window),question,detailed,budget,use_audio,json.dumps(speech,sort_keys=True),json.dumps(ref,sort_keys=True))
            if d.get('cache',True) and key in cache:result=dict(cache[key],cache_hit=True)
            else:
                if use_audio:question+='\n'+(speech_prompt(speech) if speech else 'No reliable speech is available. Use visual evidence for visual questions; unknown for unsupported speech-only questions.')
                if track_ref.get('m5_target_id'):result=selected_answer(backend,p,window,question,load_target(track_ref,p),budget)
                elif track_ref:raise ValueError('Only explicit dynamic target references are supported; no predefined target fallback')
                else:result=(detail if detailed else backend)(p,window,question,max_new_tokens=budget)
                result.update(cache_hit=False,video=str(p),window=window,detail=detailed,audio_mode='asr_text' if use_audio else 'off',audio_evidence=speech,audio_error=None)
                if d.get('cache',True):cache[key]=result
                if len(cache)>128:cache.pop(next(iter(cache)))
            data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        except Exception as e:
            self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':type(e).__name__+': '+str(e)}).encode())
    def log_message(self,*args):pass
print('EGOLENS_VISUAL_READY',flush=True)
HTTPServer(('127.0.0.1',config['visual_port']),Handler).serve_forever()
