"""One bounded SAM2 state, isolated from the language-model environment."""
import os,json,time,pathlib,io,base64
from http.server import HTTPServer,BaseHTTPRequestHandler
import numpy as np,torch
from PIL import Image
from sam2.build_sam import build_sam2_video_predictor
from egolens.settings import load_config,resolve_path,state_dir
config=load_config()
model=build_sam2_video_predictor(config['sam2_model_config'],str(resolve_path(config['sam2_checkpoint'])),device='cuda',hydra_overrides_extra=['++model.non_overlap_masks=true'])
state=None;loaded=None
def encode(mask):
    buf=io.BytesIO();Image.fromarray(np.uint8(mask)*255).save(buf,format='PNG');return base64.b64encode(buf.getvalue()).decode()
def run(d):
    global state,loaded
    folder=pathlib.Path(d['frames']).resolve()
    if not folder.is_relative_to((state_dir()/'frames').resolve()):raise ValueError('invalid frame source')
    start=time.perf_counter()
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        if loaded!=str(folder):
            state=None;torch.cuda.empty_cache()
            state=model.init_state(str(folder),offload_video_to_cpu=True,offload_state_to_cpu=True);loaded=str(folder)
        else:model.reset_state(state)
        oid=int(d['object_id']);w,h=state['video_width'],state['video_height']
        for p in d['prompts']:
            kw={}
            if p.get('box') is not None:kw['box']=np.asarray(p['box'],np.float32)*[w,h,w,h]
            if p.get('points'):kw.update(points=np.asarray(p['points'],np.float32)*[w,h],labels=np.asarray(p['labels'],np.int32))
            _,ids,logits=model.add_new_points_or_box(state,frame_idx=p['frame'],obj_id=oid,clear_old_points=True,**kw)
        preview=(logits[ids.index(oid),0]>0).cpu().numpy();frames={}
        def record(idx,mask):
            ys,xs=np.where(mask);frames[int(idx)]={'frame':int(idx),'bbox':[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)] if len(xs) else None,'mask':encode(mask) if len(xs) else None}
        record(d['prompts'][-1]['frame'],preview)
        if d.get('propagate'):
            seed=d['prompts'][-1]['frame']
            for reverse in [False,True]:
                for idx,ids,logits in model.propagate_in_video(state,start_frame_idx=seed,reverse=reverse):
                    if d.get('cancel_file') and pathlib.Path(d['cancel_file']).exists():raise InterruptedError('tracking canceled')
                    record(idx,(logits[ids.index(oid),0]>0).cpu().numpy())
        result=sorted(frames.values(),key=lambda f:f['frame']);missing=False;candidate=False
        anchors={p['frame'] for p in d['prompts']}
        for f in result:
            if f['frame'] in anchors:missing=False;candidate=False
            if not f['bbox']:missing=True;f['status']='lost_no_mask'
            else:
                if missing:candidate=True;missing=False
                f['status']='reappearance_unverified' if candidate else 'mask_active'
        return {'width':w,'height':h,'frames':result,'seconds':time.perf_counter()-start,'object_id':oid}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'{"ready":true}')
    def do_POST(self):
        try:
            d=json.loads(self.rfile.read(int(self.headers['Content-Length'])));r=run(d);status=200
        except Exception as e:r={'error':type(e).__name__+': '+str(e)};status=500
        self.send_response(status);self.end_headers();self.wfile.write(json.dumps(r).encode())
    def log_message(self,*args):pass
print('M5_SAM_READY',flush=True);HTTPServer(('127.0.0.1',config['tracker_port']),Handler).serve_forever()
