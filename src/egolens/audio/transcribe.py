"""Optional offline Whisper + Silero VAD ingestion; no downloaded weights are bundled."""
def transcribe(video,start_stamp):
    import json,torch,whisper
    from silero_vad import get_speech_timestamps
    from egolens.settings import load_config,resolve_path,allowed_video
    from egolens.audio.evidence import reliable_asr_segment,clock_seconds
    cfg=load_config();p=resolve_path(video)
    if not allowed_video(p):raise ValueError('Video outside configured media_roots')
    if not cfg['whisper_checkpoint'] or not cfg['silero_checkpoint']:raise ValueError('Configure local whisper_checkpoint and silero_checkpoint first')
    torch.set_num_threads(4);vad=torch.jit.load(str(resolve_path(cfg['silero_checkpoint'])),map_location='cpu').eval()
    model=whisper.load_model(str(resolve_path(cfg['whisper_checkpoint'])),device='cuda' if torch.cuda.is_available() else 'cpu')
    audio=whisper.load_audio(str(p));segments=[]
    regions=get_speech_timestamps(torch.from_numpy(audio),vad,sampling_rate=16000,threshold=.5,min_speech_duration_ms=300,min_silence_duration_ms=300,speech_pad_ms=150,max_speech_duration_s=10)
    for region in regions:
        lo,hi=region['start'],region['end'];result=model.transcribe(audio[lo:hi],language=cfg['asr_language'],temperature=0,condition_on_previous_text=False,word_timestamps=True,beam_size=3,verbose=None)
        for raw in result['segments']:
            item={k:raw[k] for k in ['start','end','text','avg_logprob','no_speech_prob','compression_ratio']};item['start']=max(lo/16000,item['start']+lo/16000);item['end']=min(hi/16000,item['end']+lo/16000)
            if item['end']>item['start'] and reliable_asr_segment(item,expected_language=cfg['asr_language']):segments.append(item)
    record={'clip_id':p.stem,'video':str(p),'segments':segments,'source_signature':{'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns},'clip_start_seconds':clock_seconds(start_stamp),'source':'whisper+silero-vad','alignment':'source-media-seconds'}
    out=resolve_path(cfg['audio_memory']);out.parent.mkdir(parents=True,exist_ok=True);records=json.loads(out.read_text()) if out.exists() else [];records=[r for r in records if r['clip_id']!=p.stem]+[record];out.write_text(json.dumps(records,ensure_ascii=False,indent=2));print('Speech segments:',len(segments))
