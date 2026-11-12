"""Dynamic target evidence within the requested media window only."""
import pathlib,json,re,time
import numpy as np,torch
from PIL import Image,ImageDraw
from decord import VideoReader,cpu
from egolens.settings import state_dir
def load_target(ref,video):
    ident=ref.get('m5_target_id','');revision=int(ref.get('revision',0))
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('invalid dynamic target')
    t=json.loads((state_dir()/'targets'/ident/f'r{revision}.json').read_text())
    p=pathlib.Path(video).resolve();sig=t['source_signature']
    if pathlib.Path(t['source_path']).resolve()!=p or p.stat().st_size!=sig['size'] or p.stat().st_mtime_ns!=sig['mtime_ns']:raise ValueError('target source changed')
    if t['object_id']!=int(ref['object_id']) or not t.get('confirmed'):raise ValueError('target ID or confirmation mismatch')
    return t
@torch.inference_mode()
def answer(backend,video,window,question,target,budget=256):
    start=time.perf_counter();vr=VideoReader(str(video),ctx=cpu(0),num_threads=1);fps=vr.get_avg_fps()
    idx=np.linspace(int(window[0]*fps),min(len(vr)-1,int(window[1]*fps)),16,dtype=int)
    frames=vr.get_batch(idx.tolist()).asnumpy();images=[];used=[]
    content=[{'type':'text','text':'Full scene within the requested interval:'},{'type':'video'}]
    candidates=[f for f in target.get('frames',[]) if f['bbox'] and window[0]-.02<=f['time_s']<=window[1]+.02]
    if candidates:
        positions=sorted(set([0,len(candidates)//2,len(candidates)-1]))
        for pos in positions:
            f=candidates[pos];im=Image.fromarray(vr[min(len(vr)-1,round(f['time_s']*fps))].asnumpy());w,h=im.size
            x1,y1,x2,y2=f['bbox'];x1,x2=x1/target['tracking_width']*w,x2/target['tracking_width']*w;y1,y2=y1/target['tracking_height']*h,y2/target['tracking_height']*h
            marked=im.copy();ImageDraw.Draw(marked).rectangle([x1,y1,x2,y2],outline='red',width=5)
            dx=max(12,(x2-x1)*.5);dy=max(12,(y2-y1)*.5)
            crop=im.crop((max(0,x1-dx),max(0,y1-dy),min(w,x2+dx),min(h,y2+dy)))
            images.extend([marked,crop]);used.append({'time_s':f['time_s'],'bbox':f['bbox'],'status':f['status']})
            content.extend([{'type':'text','text':f"User-selected object {target['object_id']} at media time {f['time_s']:.2f}s. Red box marks the predicted region, not part of the scene. Region association: {f['status']}. Full frame then context crop:"},{'type':'image'},{'type':'image'}])
    content.append({'type':'text','text':question+'\nAnswer about the USER-SELECTED REGION, not another similar object. The user nickname is not proof of class. Predicted masks, particularly after gaps or backward propagation, do not prove physical identity. Do not infer invisible actions. '+('No selected region is available in this interval; acknowledge uncertainty about the selected object.' if not used else '')})
    text=backend.processor.apply_chat_template([{'role':'user','content':content}],tokenize=False,add_generation_prompt=True)
    args=dict(text=[text],videos=[frames],fps=15/max(.1,(idx[-1]-idx[0])/fps),return_tensors='pt')
    if images:args['images']=images
    inputs=backend.processor(**args).to('cuda');torch.manual_seed(42)
    output=backend.model.generate(**inputs,do_sample=False,max_new_tokens=budget)
    response=backend.processor.batch_decode(output[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)[0]
    return {'answer':response,'backend':'Qwen2.5-VL-7B','target_evidence':used,'target_object_id':target['object_id'],'target_revision':target['revision'],'selected_region_used':bool(used),'frame_seconds':(idx/fps).tolist(),'total_seconds':time.perf_counter()-start,'pruning':False}
