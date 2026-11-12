"""Native Qwen2.5-VL inference backend; matches EvidenceAssistant infer contract."""
import time
import numpy as np
import torch
from decord import VideoReader,cpu
from transformers import AutoProcessor,Qwen2_5_VLForConditionalGeneration
class Qwen25VideoBackend:
 def __init__(self,path,max_pixels=384*384,dtype="bfloat16",attention="sdpa",local_only=True):
  self.model=Qwen2_5_VLForConditionalGeneration.from_pretrained(path,torch_dtype=getattr(torch,dtype),device_map='cuda',attn_implementation=attention,local_files_only=local_only).eval()
  self.processor=AutoProcessor.from_pretrained(path,local_files_only=local_only,min_pixels=128*28*28,max_pixels=max_pixels)
  self.path=str(path)
 @torch.inference_mode()
 def __call__(self,video,window,question,max_new_tokens=256):
  start=time.perf_counter();vr=VideoReader(str(video),ctx=cpu(0),num_threads=1);fps=vr.get_avg_fps()
  idx=np.linspace(min(len(vr)-1,int(window[0]*fps)),min(len(vr)-1,int(window[1]*fps)),16,dtype=int)
  frames=vr.get_batch(idx.tolist()).asnumpy()
  effective_fps=15/((idx[-1]-idx[0])/fps) if idx[-1]>idx[0] else fps
  text=self.processor.apply_chat_template([{'role':'user','content':[{'type':'video'},{'type':'text','text':question}]}],tokenize=False,add_generation_prompt=True)
  inputs=self.processor(text=[text],videos=[frames],fps=effective_fps,return_tensors='pt').to('cuda')
  torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();t=time.perf_counter();torch.manual_seed(42)
  output=self.model.generate(**inputs,do_sample=False,max_new_tokens=max_new_tokens)
  torch.cuda.synchronize();answer=self.processor.batch_decode(output[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)[0]
  return dict(answer=answer,generated_tokens=int(output.shape[1]-inputs.input_ids.shape[1]),max_new_tokens=max_new_tokens,hit_token_limit=bool(output.shape[1]-inputs.input_ids.shape[1]>=max_new_tokens),frame_seconds=(idx/fps).tolist(),frame_indices=idx.tolist(),seconds=time.perf_counter()-t,total_seconds=time.perf_counter()-start,peak_gib=torch.cuda.max_memory_allocated()/2**30,backend='Qwen2.5-VL-7B',model_path=self.path,effective_fps=effective_fps,video_grid_thw=inputs.video_grid_thw.tolist(),pruning=False)
