"""Timestamped speech evidence, separate from visible facts."""
import re


def clock_seconds(stamp,fps=30):
    s=str(stamp).zfill(8)
    return int(s[:2])*3600+int(s[2:4])*60+int(s[4:6])+int(s[6:])/fps


def srt_seconds(stamp):
    h,m,s=stamp.replace(',','.').split(':')
    return int(h)*3600+int(m)*60+float(s)


def parse_srt(text):
    records=[]
    for block in re.split(r'\n\s*\n',text.replace('\r','').lstrip('\ufeff').strip()):
        lines=block.splitlines()
        timing=next((i for i,x in enumerate(lines) if '-->' in x),None)
        if timing is None:continue
        start,end=lines[timing].split('-->')
        utterances=lines[timing+1:]
        # Official files may contain Chinese speech + its English translation.
        chinese=[x for x in utterances if re.search('[\u4e00-\u9fff]',x)]
        if chinese:utterances=chinese
        speaker=None;parts=[]
        for line in utterances:
            match=re.match(r'^([^:：]{1,25})[:：]\s*(.*)$',line.strip())
            if match:speaker=match.group(1);line=match.group(2)
            parts.append(line.strip())
        value=' '.join(x for x in parts if x)
        if value:records.append(dict(start=srt_seconds(start.strip()),end=srt_seconds(end.strip()),speaker=speaker,text=value))
    return records


def window_speech(segments,window,clip_start=0,source='asr'):
    lo,hi=window
    result=[]
    for s in segments:
        # No full utterance may leak from outside a narrowly recalled window.
        if s['start']>=lo-.1 and s['end']<=hi+.1:
            result.append(dict(start=max(lo,s['start']),end=min(hi,s['end']),
                               absolute_start=clip_start+max(lo,s['start']),
                               absolute_end=clip_start+min(hi,s['end']),text=s['text'],
                               source=source,claim_type='heard_speech_not_visual_fact',speaker=s.get('speaker')))
    return result


def speech_prompt(segments):
    if not segments:return 'No reliable speech transcription is available for this interval.'
    lines=[f"[{s['start']:.2f}-{s['end']:.2f}s] {s['text']}" for s in segments]
    return ('Time-aligned speech transcript (ASR may contain errors). These are spoken statements, '
            'not visual confirmation of actions or object identity. Do not infer unseen events solely '
            'from speech. Do not assign an unverified speaker identity.\n'+'\n'.join(lines))


def reliable_asr_segment(segment,expected_language='zh'):
    text=segment['text'].strip()
    if not text:return False
    no_speech=segment.get('no_speech_prob',0);confidence=segment.get('avg_logprob',0)
    if no_speech>=.9 or confidence<-.9 or segment.get('compression_ratio',0)>2.4:return False
    chars=re.findall('[\u4e00-\u9fff]',text)
    if no_speech>.6 and len(chars)<=4:return False
    if expected_language=='zh' and no_speech>.75 and len(chars)<3:return False
    if len(text)>20:
        grams=[text[i:i+6] for i in range(len(text)-5)]
        if len(set(grams))/len(grams)<.35:return False
    return True


class SpeechStore:
    def __init__(self,path):
        import pathlib,json
        self.path=pathlib.Path(path)
        self.records={x['clip_id']:x for x in json.loads(self.path.read_text())} if self.path.exists() else {}
        self.mtime=self.path.stat().st_mtime_ns if self.path.exists() else None

    def evidence(self,video,window):
        import pathlib,json
        if self.path.exists() and self.path.stat().st_mtime_ns!=self.mtime:
            records=json.loads(self.path.read_text())
            self.records={x['clip_id']:x for x in records};self.mtime=self.path.stat().st_mtime_ns
        p=pathlib.Path(video).resolve();record=self.records.get(p.stem)
        if not record:return []
        if pathlib.Path(record['video']).resolve()!=p:raise ValueError('Speech/video source mismatch')
        signature=record.get('source_signature')
        if signature and (p.stat().st_size!=signature['size'] or p.stat().st_mtime_ns!=signature['mtime_ns']):
            raise ValueError('Speech evidence stale after video change')
        start=record.get('clip_start_seconds')
        if start is None:start=clock_seconds(p.stem.rsplit('_',1)[-1])
        return window_speech(record['segments'],window,start,record['source'])
