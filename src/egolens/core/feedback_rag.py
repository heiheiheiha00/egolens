"""Bounded, evidence-seeking RAG. Summaries navigate; video observations answer."""
import json
import re
import numpy as np
from egolens.core.time_utils import recording_seconds


def seconds(stamp):
    return recording_seconds(stamp)


def parse_json(text):
    clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    result = json.loads(clean)
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object')
    return result


def explicit_scope(question, query_day):
    """Only user-stated day/minute can hard-filter. LLM ranges are soft hints."""
    days = {int(x) for x in re.findall(r'DAY\s*(\d+)', question, re.I)}
    minute = re.search(r'(?<!\d)(\d{1,2}):(\d{2})(?!:)', question)
    interval = None
    if minute:
        hour, minute_value = map(int, minute.groups())
        if hour < 24 and minute_value < 60:
            start = hour*3600+minute_value*60
            interval = (start, start+60)
            if not days:
                days = {int(str(query_day).replace('DAY', ''))}
    return days, interval


def select_candidates(entries, sentence_records, scores, question, query_day, query_time, limit=3, hard_scope=None):
    days, interval = explicit_scope(question, query_day)
    if hard_scope is not None:
        days, interval = set(hard_scope.get('days',[])), hard_scope.get('interval')
    qday = int(str(query_day).replace('DAY', ''))
    eligible = {}
    for entry in entries:
        day = int(entry['date'].replace('DAY', ''))
        lo, hi = seconds(entry['start_time']), seconds(entry['end_time'])
        if day > qday or (day == qday and lo >= seconds(query_time)):
            continue
        if days and day not in days:
            continue
        # Overlap, rather than requiring a whole clip to fit a generated range.
        if interval and not (lo < interval[1] and hi > interval[0]):
            continue
        available = min(entry['duration'], seconds(query_time)-lo) if day == qday else entry['duration']
        window_start=0.0
        if hard_scope is not None and interval:
            window_start=max(0.0,interval[0]-lo)
            available=min(available,interval[1]-lo)
        eligible[entry['clip_id']] = dict(entry, score=-1.0, duration=available, window_start=window_start)
    for record, score in zip(sentence_records, scores):
        ident = record['clip_id']
        if ident in eligible:
            eligible[ident]['score'] = max(eligible[ident]['score'], float(score))
    ranked = sorted(eligible.values(), key=lambda x: (-x['score'], x['clip_id']))
    return ranked[:limit], {'explicit_days': sorted(days), 'explicit_interval': interval,
                            'eligible_clips': len(eligible), 'unique_budget': limit}


class ClipIndex:
    def __init__(self, entries, embedding_function):
        self.entries = entries
        self.embed = embedding_function
        self.records = []
        for entry in entries:
            # Short chunks preserve late facts despite CLIP's short text context.
            pieces = re.split(r'(?<=[.!?])\s+|\n+', entry['text'])
            for piece in pieces:
                words = piece.split()
                for start in range(0, len(words), 40):
                    self.records.append({'clip_id': entry['clip_id'], 'text': ' '.join(words[start:start+40])})
        vectors = np.asarray(self.embed([x['text'] for x in self.records]), dtype=np.float32)
        self.vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)

    def search(self, question, day, time, limit=3):
        vector = np.asarray(self.embed([question])[0], dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-8)
        return select_candidates(self.entries, self.records, self.vectors @ vector,
                                 question, day, time, limit)


class FeedbackRAG:
    def __init__(self, index, ask, visual, max_rounds=2, max_windows_per_round=2,audio_enabled=False,calibrated_evidence=False):
        self.index, self.ask, self.visual = index, ask, visual
        self.max_rounds = max_rounds
        self.max_windows_per_round = max_windows_per_round
        self.audio_enabled=audio_enabled
        self.calibrated_evidence=calibrated_evidence

    def run(self, question, day, time, feedback=True, context=None, intent=None, seed_observations=None, requirements=None, target_ref=None):
        selected, retrieval = self.index.search(question, day, time)
        # Five alternative unique clips for feedback, same hard user scope.
        alternatives, _ = self.index.search(question, day, time, limit=5)
        catalog = {x['clip_id']: x for x in alternatives}
        observations=[dict(o,evidence_id=f'M{i+1}') for i,o in enumerate(seed_observations or [])]
        history, seen, feedback_searches = [], set(), []
        reference_repairs=0
        compound=bool(requirements and len(requirements.get('roles',[]))>1)
        temporal_end = not compound and (intent=='ending' or any(w in question.lower() for w in ['at the end', 'last visible']))
        latest = max(selected, key=lambda e:(int(e['date'][3:]),seconds(e['start_time']))) if selected else None

        def inspect(entry, window, subquestion, detailed, round_index):
            duration = entry['duration']
            lo, hi = max(entry.get('window_start',0.0), float(window[0])), min(duration-.04, float(window[1]))
            if hi-lo < .25:
                return
            # Rewording the question on identical frames is not new evidence.
            key = (entry['clip_id'], round(lo, 2), round(hi, 2))
            if key in seen:
                return
            seen.add(key)
            visual_question=subquestion
            original=(context or {}).get('current_user_question','')
            if self.calibrated_evidence and detailed and re.search(r'颜色|顏色|\bcolou?r\b',original,re.I):
                state=(context or {}).get('state',{})
                label=next((a for a in state.get('aliases',[]) if re.search('[\u4e00-\u9fff]',a)),state.get('object',''))
                if label:
                    if '手柄' in original and not re.search(r'手柄|handle',label,re.I):label+='的手柄'
                    visual_question=f'在这个窗口内，是否可见{label}？如果可见，{label}呈现什么颜色？'
            prompt = ('Inspect only the supplied video interval. Answer the narrow question from visible evidence, '
                      'in at most 80 words. State observed objects, surfaces, and hand movements; '
                      'separate uncertainty. Do not describe what normally happens or infer washing, returning, '
                      'repairing, switching on, or physical identity from context alone. If not visible say unknown. '
                      'The interval is part of an original recording, not a later event. Question: '+visual_question)
            if self.audio_enabled:
                prompt=('Use the supplied video and any time-aligned speech transcript to answer briefly. '
                        'Distinguish visible actions from what someone said. Speech may be erroneous or refer to another time; '
                        'a spoken suggestion does not establish that an action happened. Unknown speakers stay unknown. '
                        'Do not infer missing visual steps. Question: '+visual_question)
            if self.calibrated_evidence and detailed and visual_question==subquestion:
                prompt=('先检查本窗口中能否看见问题所指的物体。若可见，先报告可见的相关部分，再回答所问属性；'
                        '只把看不清的部分标为未知，不要推测画外动作或物体身份。\n'+prompt)
            kind = 'identity' if intent=='identity' or 'same ' in question.lower() or 'identity' in question.lower() else (
                'location' if any(w in question.lower() for w in ['where', 'resting on', 'surface']) else 'motion')
            extra={}
            if target_ref:
                local_ref=dict(target_ref)
                tr=local_ref.get('track_ref') or {}
                if tr and tr.get('source_path')!=entry['video_path']:local_ref['track_ref']=None;local_ref['association']='unverified_cross_clip_candidate'
                extra['target_ref']=local_ref
            offset=entry.get('media_offset',0)
            assist=not detailed and (not target_ref or bool(extra.get('target_ref',{}).get('track_ref')))
            raw = self.visual(entry['video_path'], prompt, window=[lo+offset, hi+offset], assist=assist,
                              detail=detailed, kind=kind,**extra)
            observations[:]=[o for o in observations if not(o.get('memory_reused') and o['clip_id']==entry['clip_id'] and o['window']==[lo,hi])]
            record = {'evidence_id': f'E{len(seen)}', 'clip_id': entry['clip_id'], 'source_path':entry['video_path'],
                      'date': entry['date'], 'clip_start': entry['start_time'], 'window': [lo, hi],
                      'question': subquestion, 'observation': raw['answer'], 'verified': False,
                      'round': round_index, 'detail': detailed, 'raw': raw}
            record['media_offset']=offset
            if visual_question!=subquestion:record['visual_question']=visual_question
            if target_ref:record['entity_ref']=extra.get('target_ref',target_ref)
            if self.audio_enabled:record['speech_evidence']=raw.get('audio_evidence',[])
            observations.append(record)

        for entry in selected[:2]:
            inspect(entry, [0, entry['duration']], question, False, 0)

        def judge(round_index):
            nonlocal reference_repairs
            relevant = observations
            if temporal_end and latest:
                relevant = [o for o in observations if o['clip_id']==latest['clip_id']]
                focused = [o for o in relevant if o['round']>0 and o['window'][1]>=latest['duration']-.2]
                # A prior hand view is context, not conflicting evidence of the
                # ending location. A dense ending check outranks a global sweep.
                if focused:relevant=focused
            evidence = [{k: v for k, v in x.items() if k != 'raw'} for x in relevant]
            if self.calibrated_evidence:
                for item in evidence:
                    # Persist the unverified status in the audit record; expose its
                    # actual meaning rather than a Boolean that reads like rejection.
                    item.pop('verified',None)
                    item['source_kind']='previous_model_observation' if item.get('memory_reused') else 'current_video_model_observation'
                    item['review_status']='automatic_observation_not_human_reviewed'
            navigation = [{k: e[k] for k in ['clip_id', 'date', 'start_time', 'end_time', 'duration', 'text']} for e in alternatives]
            prompt = ('Return ONE JSON object. You are an evidence editor and a search controller. '
                      'Summaries are fallible NAVIGATION ONLY: never use them as answer evidence. '
                      'Only supplied direct video observations with evidence_id can support claims, and those '
                      'are also fallible. Reject an observation that merely reasons "interaction implies switched on", '
                      'or invents washing/returning/repairing without visible steps. A refusal does not prove absence. '
                      'Do not equate small bowls and plates without visual support. Identity after a gap is unknown. '
                      'Read date, clip_start, and window to place each observation in recording time. '
                      'Different places at different times are not automatically a contradiction. '
                      'For origin before going outside, later outdoor handling is not evidence of the origin; '
                      'for last visible location prefer the latest relevant visible interval, not an earlier hand view. '
                      'Never treat a similar object in an earlier clip as the selected object without support. '
                      'If observations conflict with each other or navigation, request a focused recheck rather '
                      'than choosing the convenient account. Keep an answer useful but omit unsupported details. '
                      'Schema: {"answer":"Chinese answer with evidence IDs, or explicitly unknown", '
                      '"claims":[{"text":"a supported claim","evidence_ids":["E1"]}], '
                      '"uncertain":["missing fact"], "requests":[{"clip_id":"from catalog", '
                      '"start":0,"end":6,"question":"neutral narrow visual question, no assumed answer"}]}. '
                      'Request at most two windows, each 2-10 seconds, to resolve concrete missing/contradictory '
                      'facts. For an origin inspect the early interval; for final location inspect the end; '
                      'for state-before-action inspect before the hand interaction. These are search heuristics, '
                      'not evidence. Do not repeat previously exhausted requests. If the question asks an event '
                      'sequence preserve the global chronology but do not fill gaps. '
                      f'Feedback round {round_index}/{self.max_rounds}; if final round, requests must be [].\n'
                      'Question: '+question+'\nDirect observations: '+json.dumps(evidence)+
                      '\nNavigation catalog: '+json.dumps(navigation))
            if self.audio_enabled:
                prompt=prompt.replace('Only supplied direct video observations with evidence_id can support claims, and those are also fallible.',
                    'Only supplied direct observations or timestamped speech_evidence with evidence_id can support claims; both are fallible.')
                prompt += ('\nAudio policy: direct observations may include a separate speech_evidence list from ASR. '
                           'Those timestamped spoken words can answer what was said, with evidence IDs, '
                           'but do not prove a visual action or physical identity. Prefer a correct speech quote '
                           'over a visual guess for questions about conversation. If no speech is available, do not invent it. '
                           'If a question asks what was said but speech_evidence is empty, a visual guess cannot answer it. '
                           'Missing ASR does not prove no speech happened. '
                           'Navigation summaries still cannot serve as answer evidence.')
            if self.calibrated_evidence:
                prompt=prompt.replace('If observations conflict with each other or navigation, request a focused recheck rather than choosing the convenient account.',
                    'If informative direct observations disagree about the SAME object, property and overlapping time, request a focused recheck. '
                    'A navigation summary is not a competing observation and cannot veto direct evidence.')
                prompt += ('\nEvidence calibration: automatic_observation_not_human_reviewed describes provenance, NOT rejection or low confidence. '
                           'A clear current video observation is sufficient to state the visible property with its source ID; '
                           'do not require a human label, a second independent source or agreement with navigation. '
                           'Unknown, missing detail or failure to mention a property is NOT contradictory evidence. '
                           'Distinguish these from an explicit incompatible observation of the same property and time. '
                           'A hypothetical alternative without visible support is not a reason to reject a clear observation. '
                           'Answer the supported part first and confine uncertainty to the unresolved property. '
                           'Answer only the requested facts. Do not concatenate different-clip observations into a new action chain '
                           'unless object continuity and that ordering are supported; a shared category does not establish continuity. '
                           'Uncertain cross-clip identity does not erase a visible location or color within one clip; '
                           'do not claim that identity itself is established. A speaker merely mentioning a device does not prove repair completion. '
                           'Retain safeguards for genuinely ambiguous objects, off-camera actions, missing passwords and unknown names. '
                           'Use concise natural answers; do not recite unverified-status disclaimers for every observed fact.')
            if context is not None:
                prompt += ('\nConversation context (not new factual evidence): '+json.dumps(context,ensure_ascii=False)+
                           '\nMemory observations marked memory_reused are previous fallible model observations. '
                           'Repeated observations of the same source/window are not independent evidence. '
                           'Use current direct evidence to correct earlier answers when warranted. '
                           'You may add revisions:[{turn:integer,reason:string,evidence_ids:[current E IDs]}] '
                           'only when the current evidence contradicts that earlier answer about the SAME object, time, and property. '
                           'Different states at different times and changing topics are not corrections. '
                           'Do not mark unrelated older turns as superseded. Explain actual corrections in the answer.')
                prompt += ('\nReturn at most 4 concise claims, each with text,evidence_ids,property,value,event_role,entity_id. '
                           'Properties can be location,appearance,screen_state,action,spoken_name,spoken_year,identity,other. '
                           'Do not invent an entity link from category similarity. User aliases are not verified classes. '
                           'Speech mentions/negations/plans must be described as speech, not completed visible actions. '
                           'Compare contradictions only for the same entity/property/overlapping time/event role. '
                           'Retain supported shared properties when a different property conflicts. A disagreement over holding '
                           'does not erase evidence of the table area. Resting state does not prove a visible put-down action. '
                           'Exclude later outdoor handling when deciding the earlier indoor origin; different times are not conflicting origins. '
                           'Do not assume an earlier black rectangle is the same selected outdoor object. '
                           'For Mac/Xiaomi separate the mentioned name, denial, spoken referent and selected visual object. '
                           'You may output claim_revisions:[{claim_id,reason,evidence_ids}] for a specific wrong memory claim, '
                           'using current evidence; do not retract unrelated correct properties or an entire turn. '
                           'Task requirements: '+json.dumps(requirements or {})+
                           '\nGlobal summaries remain navigation; answer the original full question, including every comparison operand.')
            valid_ids = {x['evidence_id'] for x in relevant}
            if context is not None:prompt+='\nOnly these current-turn evidence IDs may support claims: '+json.dumps(sorted(valid_ids))+'. Previous turn local IDs do not identify current evidence.'
            result = parse_json(self.ask(prompt, max_tokens=1600))
            invalid = [c for c in result.get('claims', []) if not c.get('evidence_ids') or
                       any(eid not in valid_ids for eid in c['evidence_ids'])]
            if invalid:
                if context is None:raise ValueError('Answer contains invalid evidence references')
                draft=result
                if reference_repairs<1:
                    reference_repairs+=1
                    result=parse_json(self.ask(prompt+'\nYour previous draft used invalid source IDs: '+json.dumps(draft)+
                        '\nRegenerate from the CURRENT supplied observations only. Do not rename or guess a source mapping. '
                        'Put unsupported claims under uncertain. Valid IDs: '+json.dumps(sorted(valid_ids)),max_tokens=1600))
                invalid_again=[c for c in result.get('claims',[]) if not c.get('evidence_ids') or not set(c['evidence_ids'])<=valid_ids]
                if invalid_again:
                    result={'answer':'当前证据引用未能通过核验，暂不能给出可靠结论。','claims':[],'uncertain':['source reference validation failed'],'requests':[]}
                result['citation_repair']={'invalid_draft':draft,'regenerated':not bool(invalid_again),'repair_budget_per_turn':1}
            result['decision_evidence_ids']=sorted(valid_ids)
            history.append(result)
            return result

        answer = judge(0)
        if feedback:
            # High precision temporal questions require a local check when the
            # editor offers none. This is driven by question wording, not labels.
            lower = question.lower()
            temporal_start = intent in {'origin','before'} or any(w in lower for w in ['before i interacted', 'before the hand', 'just before'])
            if compound:
                early=min(selected[:2],key=lambda e:(int(e['date'][3:]),seconds(e['start_time']))) if selected else None
                requests=[]
                if early and 'origin' in requirements['roles']:
                    requests.append(dict(clip_id=early['clip_id'],start=early.get('window_start',0),end=min(early['duration']-.04,early.get('window_start',0)+8),question='Inspect where the queried object is taken from before later movement. '+question))
                if latest and 'ending' in requirements['roles']:
                    requests.append(dict(clip_id=latest['clip_id'],start=max(latest.get('window_start',0),latest['duration']-8),end=latest['duration']-.04,question='Inspect the last visible object location and contact surface. '+question))
                answer['requests']=requests[:2]
                answer['request_source']='compound_roles_preserved'
            if temporal_end and latest:
                answer['requests'] = [dict(clip_id=latest['clip_id'],start=max(0,latest['duration']-6),end=latest['duration']-.04,
                    question=question+' Inspect only the ending interval. Locate the named object, its contact surface, and whether it is held or resting. Do not substitute another object. If not visible say unknown.')]
                answer['request_source']='latest_related_clip_ending_check'
            if not answer.get('requests') and (temporal_end or temporal_start):
                answer['requests'] = [dict(clip_id=e['clip_id'], start=max(0,e['duration']-6) if temporal_end else 0,
                    end=e['duration']-.04 if temporal_end else min(6,e['duration']-.04),
                    question=(question+' Inspect only this ending interval: locate the object named in the question, '
                              'describe the surface it touches and whether it is in a hand or resting. '
                              'Do not substitute another visible object; if the queried object is not visible say unknown.') if temporal_end else
                    ('Before any hand interaction in this interval, describe the visible object state and any image on the screen; '
                     'if the state before contact is not visible say unknown.')) for e in selected[:2]]
                answer['request_source']='question_temporal_precision_guard'
            for round_index in range(1, self.max_rounds+1):
                count = len(seen)
                for request in answer.get('requests', [])[:self.max_windows_per_round]:
                    if isinstance(request.get('question'), str):
                        # Requery navigation memory with the concrete gap while
                        # retaining original user day/time constraints.
                        extra, scope = self.index.search(question+' Missing visual fact: '+request['question'], day, time, limit=5)
                        feedback_searches.append({'round': round_index, 'query': request['question'],
                                                  'clips': [e['clip_id'] for e in extra], 'scope': scope})
                        for candidate in extra:
                            hard_days = retrieval.get('explicit_days', [])
                            hard_interval = retrieval.get('explicit_interval')
                            if hard_days and int(candidate['date'][3:]) not in hard_days:
                                continue
                            if hard_interval and not (seconds(candidate['start_time'])<hard_interval[1] and
                                                      seconds(candidate['end_time'])>hard_interval[0]):
                                continue
                            if candidate['clip_id'] not in catalog and len(catalog)<8:
                                catalog[candidate['clip_id']]=candidate
                                alternatives.append(candidate)
                    entry = catalog.get(request.get('clip_id'))
                    if not entry or not isinstance(request.get('question'), str):
                        continue
                    try:
                        lo, hi = float(request['start']), float(request['end'])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if not (entry.get('window_start',0.0) <= lo < hi <= entry['duration']+.1) or hi-lo > 10:
                        continue
                    inspect(entry, [lo, hi], request['question'], True, round_index)
                if len(seen) == count:
                    break
                answer = judge(round_index)
        return {'question': question, 'retrieval': retrieval, 'selected': [x['clip_id'] for x in selected],
                'observations': observations, 'history': history, 'answer': answer,
                'feedback_searches': feedback_searches, 'feedback_enabled': feedback,
                'max_rounds': self.max_rounds, 'feedback_policy_version': 4}
