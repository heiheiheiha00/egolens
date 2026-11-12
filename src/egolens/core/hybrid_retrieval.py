"""Dense visual navigation + bilingual lexical/ASR recall; no answer labels."""
import collections, math, pathlib, re
import numpy as np
from egolens.core.feedback_rag import select_candidates
from egolens.core.time_utils import recording_seconds

# Small transparent retrieval vocabulary, not ASR corrections or factual aliases.
# In particular 麦克 is NOT rewritten to Mac, and a nickname is not an identity.
CONCEPTS = {
    'computer': r'computer|laptop|macbook|\bmac\b|电脑|電腦|笔记本|筆記本',
    'dismantle': r'disassembl\w*|dismantl\w*|taken apart|take apart|拆',
    'assemble': r'reassembl\w*|put.{0,12}back together|装回|裝回|组装|組裝',
    'memory': r'\bram\b|memory (?:stick|module|upgrade)|内存|內存',
    'quarantine': r'quarantin\w*|隔离|隔離',
    'hotel': r'hotel\w*|酒店|旅馆|旅館',
    'tool': r'tool\w*|screwdriver\w*|工具|螺丝刀|螺絲刀',
    'yellow': r'yellow|黄色|黃色|黄柄|黃柄',
    'indoor': r'indoor\w*|inside|室内|室內|屋内|屋內',
    'outdoor': r'outdoor\w*|outside|patio|deck|室外|户外|戶外|露台',
    'table': r'table\w*|desk\w*|桌|台面',
    'carry': r'carr\w*|hold\w*|walk\w*|mov\w*|拿着|拿著|走向|走到|移动|移動',
    'board': r'checkerboard|checkered board|chessboard|calibration board|格板|棋盘|棋盤|格纹|格紋',
    'kitchen': r'kitchen\w*|厨房|廚房',
    'bed': r'\bbed\b|bedding|bedroom\w*|床|卧室|臥室',
    'cable': r'cable\w*|wire\w*|线缆|線纜|电线|電線|连接线|連接線',
    'speech': r'conversation\w*|\btalk\w*|\bsaid\b|\bspeech\b|谈话|談話|说过|說過',
    'rack': r'rack\w*|shelf|shelves|架子|货架|貨架',
    'window': r'window\w*|窗',
    'sink': r'\bsink\b|水槽|洗碗池',
    'flower': r'flower\w*|vase\w*|花瓶|鲜花|鮮花',
    'phone': r'phone\w*|手机|手機',
}
STOP = set('the a an and or of to in on at by for from with is are was were be been this that these those '
           'it its i my me we you your what which where when who how does did do can could please '
           'video videos clip clips recording recordings recorded episode available find show shows '
           'related relevant locate day minute minutes only evidence as about being has have had than then '
           'not never any some into while during say says said mention mentioned mentions moment '
           'happened got go going done get looking known so still even largest greatest biggest'.split())

def terms(text):
    text = text.lower()
    values = [w for w in re.findall(r'[a-z][a-z0-9]*', text) if w not in STOP]
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        values += [run[i:i+2] for i in range(len(run)-1)]
    values += ['c:' + name for name, pattern in CONCEPTS.items() if re.search(pattern, text)]
    return values

class HybridClipIndex:
    def __init__(self, entries, embedding_function, speech_store=None):
        self.embed = embedding_function
        self.entries, self.records, self.lexical = [], [], []
        self.warnings = []
        for source in entries:
            entry = dict(source)
            texts = [(entry['text'], None)]
            path = pathlib.Path(entry['video_path'])
            sig = entry.get('navigation_source_signature')
            valid = sig and path.is_file() and path.stat().st_size == sig['size'] and path.stat().st_mtime_ns == sig['mtime_ns']
            windows = entry.get('navigation_windows', []) if valid else []
            if entry.get('navigation_windows') and not valid:
                self.warnings.append(entry['clip_id'] + ': stale micro-navigation ignored')
            texts += [(w['text'], [w['start'],w['end']]) for w in windows]
            for text, window in texts:
                words = text.split()
                for i in range(0, len(words), 40):
                    record = {'clip_id': entry['clip_id'], 'text': ' '.join(words[i:i+40])}
                    record['coarse']=window is None
                    if window:record['window']=window
                    if record['text']:
                        self.records.append(record)
                        self.lexical.append(record)
            speech = []
            if speech_store is not None:
                offset = entry.get('media_offset', 0)
                try:
                    speech = speech_store.evidence(path, [offset, offset + entry['duration']])
                except (ValueError, OSError):
                    self.warnings.append(entry['clip_id'] + ': stale/mismatched speech ignored')
            for i, utterance in enumerate(speech):
                # Adjacent phrases recover a spoken referent split by ASR segmentation.
                context = [s for s in speech[max(0, i-1):i+2]
                           if abs(s['absolute_start'] - utterance['absolute_start']) <= 10]
                start=recording_seconds(entry['start_time'])
                self.lexical.append({'clip_id': entry['clip_id'], 'text': 'speech: ' + ' '.join(s['text'] for s in context),
                                     'window':[min(s['absolute_start'] for s in context)-start,
                                               max(s['absolute_end'] for s in context)-start]})
            # The original coarse summary remains; small windows supplement navigation.
            if windows:
                entry['text'] += '\nShort visual navigation windows: ' + ' '.join(
                    f"[{w['start']}-{w['end']}s] {w['text']}" for w in windows)
            self.entries.append(entry)
        vectors = np.asarray(self.embed([r['text'] for r in self.records]), dtype=np.float32)
        self.vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
        self.counts = [collections.Counter(terms(r['text'])) for r in self.lexical]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))
        df = collections.Counter(t for c in self.counts for t in c)
        self.idf = {t: math.log(1 + (len(self.counts) - n + .5) / (n + .5)) for t, n in df.items()}

    def search(self, question, day, stamp, limit=3, hard_scope=None):
        vector = np.asarray(self.embed([question])[0], dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-8)
        dense, meta = select_candidates(self.entries, self.records, self.vectors @ vector,
                                        question, day, stamp, len(self.entries), hard_scope=hard_scope)
        eligible = {e['clip_id']: e for e in dense}
        def within_available(record):
            entry=eligible.get(record['clip_id']);window=record.get('window')
            return bool(entry) and (window is None or
                entry.get('window_start',0)-.1<=window[0]<window[1]<=entry['duration']+.1)
        dense_scores=self.vectors@vector
        dense_scores=np.asarray([s if within_available(r) else -1.0 for r,s in zip(self.records,dense_scores)])
        coarse_scores=np.asarray([s if r.get('coarse') else -1.0 for r,s in zip(self.records,dense_scores)])
        coarse,_=select_candidates(self.entries,self.records,coarse_scores,question,day,stamp,len(self.entries),hard_scope=hard_scope)
        dense,meta=select_candidates(self.entries,self.records,dense_scores,question,day,stamp,len(self.entries),hard_scope=hard_scope)
        query = set(terms(question))
        core={t for t in query if t.startswith('c:') and t not in {'c:speech','c:carry'}}
        lexical = collections.defaultdict(float)
        coverage=collections.defaultdict(int);transitions=set();visual_concepts=collections.defaultdict(set)
        object_concepts=core&{'c:tool','c:computer','c:board','c:phone','c:bed','c:flower','c:cable'}
        for record, counts, length in zip(self.lexical, self.counts, self.lengths):
            ident = record['clip_id']
            if not within_available(record):
                continue
            score = sum((3 if t.startswith('c:') else 1) * self.idf.get(t, 0) * counts[t] * 2.2 /
                        (counts[t] + 1.2 * (.25 + .75 * length / max(self.average_length, 1)))
                        for t in query if counts[t])
            lexical[ident] = max(lexical[ident], score)
            coverage[ident]=max(coverage[ident],len(core&counts.keys()))
            if 'coarse' in record:visual_concepts[ident].update(t for t in counts if t.startswith('c:'))
            if {'c:indoor','c:outdoor'}<=core and re.search(
                    r'(?:indoor|inside|室内|室內).{0,100}(?:outdoor|outside|室外|户外|戶外)',record['text'],re.I) and object_concepts<=counts.keys():
                transitions.add(ident)
        lexical_rank = {ident: i+1 for i, (ident, value) in enumerate(
            sorted(lexical.items(), key=lambda x: (-x[1], x[0]))) if value > 0}
        ranked = []
        for i, entry in enumerate(dense):
            ident = entry['clip_id']
            lr = lexical_rank.get(ident)
            score = 1 / (20 + i+1) + (1.4 / (20 + lr) if lr else 0)
            ranked.append(dict(entry, score=score, retrieval_match={
                'dense_rank': i+1, 'lexical_rank': lr, 'lexical_score': lexical.get(ident, 0)}))
        ranked.sort(key=lambda e: (-e['score'], e['clip_id']))
        # Preserve a concrete multi-concept lexical hit instead of allowing a
        # generic visually similar scene to crowd all three candidate slots.
        anchors=[]
        best_lex=next(iter(lexical_rank),None)
        if best_lex and coverage[best_lex]>=2:anchors.append(best_lex)
        candidates=[e for e in ranked if e['clip_id'] in transitions]
        transition=max(candidates,key=lambda e:(len(core&visual_concepts[e['clip_id']]),e['score']))['clip_id'] if candidates else None
        if transition:
            # For an explicit from/to event, keep the conjunction ahead of a
            # static scene that matches only the object or the destination.
            # Adjacent windows provide boundary context, not competing events.
            primary=next(e for e in ranked if e['clip_id']==transition)
            start=recording_seconds(primary['start_time'])
            neighbors=[e for e in ranked if e['clip_id']!=transition and e['video_path']==primary['video_path'] and
                       min(abs(recording_seconds(e['end_time'])-start),
                           abs(recording_seconds(e['start_time'])-recording_seconds(primary['end_time'])))<=.1]
            anchors=[transition]+[e['clip_id'] for e in neighbors[:2]]
        if not anchors:
            # Short captions sometimes hallucinate a checkered floor instead of
            # a carried patterned object. With no concrete lexical cue, preserve
            # the original coarse channel rather than crowding it out entirely.
            anchors=[e['clip_id'] for e in coarse[:2]]
        by_id={e['clip_id']:e for e in ranked}
        ranked=[by_id[k] for k in anchors]+[e for e in ranked if e['clip_id'] not in anchors]
        if transition:
            ranked=[dict(e,retrieval_role='primary_transition' if e['clip_id']==transition else
                         'boundary_context' if e['clip_id'] in anchors else 'alternative') for e in ranked]
        meta.update(unique_budget=limit, policy='dense+lexical-ASR-RRF-with-concrete-cue-reservation',
                    reserved_cues=anchors,stale_index_warnings=self.warnings)
        return ranked[:limit], meta

    def search_scoped(self, question, day, stamp, limit=3, hard_scope=None):
        return self.search(question, day, stamp, limit, hard_scope)
