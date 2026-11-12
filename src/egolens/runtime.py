"""Conversation, hybrid retrieval and bounded feedback, without the old experiment tree."""
import json,os,time,pathlib,urllib.request,urllib.error
from egolens.settings import ROOT,load_config,resolve_path,memory_entries

def build(db_path,service=None,cache=False,memory_file=None):
    import open_clip,torch,numpy as np
    from egolens.core.episodic_memory import EpisodicMemory
    from egolens.core.conversational_rag import ConversationalRAG
    from egolens.core.hybrid_retrieval import HybridClipIndex
    from egolens.core.feedback_rag import ClipIndex
    from egolens.audio.evidence import SpeechStore
    config=load_config();cache_path=resolve_path(config['cache_dir']);cache_path.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('HF_HOME',str(cache_path/'huggingface'));os.environ.setdefault('TORCH_HOME',str(cache_path/'torch'))
    if memory_file:
        entries=json.loads(pathlib.Path(memory_file).read_text())
    else:entries=memory_entries()
    secret=os.getenv('DEEPSEEK_API_KEY','').strip()
    if not secret:raise ValueError('Set DEEPSEEK_API_KEY in the private .env file before querying')
    usage=[];visual_usage=[]
    def ask(prompt,max_tokens=1600):
        payload={'model':config['deepseek_model'],'messages':[{'role':'system','content':'Only supplied evidence supports facts. Prior model answers and source transcripts may contain errors.'},{'role':'user','content':prompt}],'temperature':0,'max_tokens':max_tokens,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'}}
        req=urllib.request.Request(config['deepseek_base_url'].rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
        start=time.perf_counter()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req,timeout=100) as r:data=json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code not in {429,500,502,503,504} or attempt==2:raise RuntimeError(f'Answer provider HTTP {e.code}') from None
                time.sleep(2*(attempt+1))
        usage.append({'model':data['model'],'usage':data.get('usage',{}),'seconds':time.perf_counter()-start,'finish_reason':data['choices'][0]['finish_reason']})
        if data['choices'][0]['finish_reason']=='length':raise ValueError('Truncated planner/answer JSON')
        return data['choices'][0]['message']['content']
    def visual(video,question,**kwargs):
        payload=dict(video=video,question=question,audio_enabled=config['audio_enabled'],cache=cache,**kwargs)
        req=urllib.request.Request(service or config['visual_service'],data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        start=time.perf_counter()
        with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
        if 'answer' not in result:raise RuntimeError('Visual service returned no answer')
        visual_usage.append({'seconds':time.perf_counter()-start,'cache_hit':result.get('cache_hit',False),'window':kwargs.get('window'),'video':pathlib.Path(video).name})
        return result
    checkpoint=config['embedding_checkpoint'];checkpoint_suffix=pathlib.Path(checkpoint).suffix;candidate=resolve_path(checkpoint)
    if candidate.is_file():checkpoint=str(candidate)
    safe_checkpoint=pathlib.Path(checkpoint).is_file() and checkpoint_suffix=='.safetensors'
    model,_,_=open_clip.create_model_and_transforms(config['embedding_model_name'],pretrained=None if safe_checkpoint else checkpoint,cache_dir=str(cache_path/'open_clip'))
    if safe_checkpoint:
        from safetensors.torch import load_file
        model.load_state_dict(load_file(checkpoint,device='cpu'),strict=True)
    model=model.to(config['embedding_device']).eval();tokenizer=open_clip.get_tokenizer(config['embedding_model_name'])
    def embed(texts):
        # Same OpenCLIP model/tokenizer/normalization as the former Chroma wrapper.
        with torch.no_grad():
            vector=model.encode_text(tokenizer(texts).to(config['embedding_device']))
            vector=vector/vector.norm(dim=-1,keepdim=True)
        return vector.cpu().numpy().tolist()
    index=HybridClipIndex(entries,embed,SpeechStore(resolve_path(config['audio_memory']))) if config['hybrid_retrieval'] else ClipIndex(entries,embed)
    return ConversationalRAG(index,ask,visual,EpisodicMemory(db_path),audio_enabled=config['audio_enabled'],calibrated_evidence=config['calibrated_evidence']),usage,visual_usage
