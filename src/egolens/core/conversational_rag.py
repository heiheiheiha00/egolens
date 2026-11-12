"""M4 wrapper; shares the M3 model, retrieval and bounded feedback implementation."""
import json,time,re,pathlib,contextlib
import numpy as np
from egolens.core.feedback_rag import FeedbackRAG,select_candidates
from egolens.core.conversation_state import resolve
from egolens.core.time_utils import recording_seconds
from egolens.core.evidence_policy import bind_entity
from egolens.core.evidence_policy import tokens
from egolens.core.time_utils import explicit_constraints

class ScopedIndex:
    def __init__(self,base,scope):self.base,self.scope=base,scope
    def search(self,question,day,stamp,limit=3):
        if hasattr(self.base,'search_scoped'):
            return self.base.search_scoped(question,day,stamp,limit,hard_scope=self.scope)
        vector=np.asarray(self.base.embed([question])[0],dtype=np.float32);vector/=max(float(np.linalg.norm(vector)),1e-8)
        return select_candidates(self.base.entries,self.base.records,self.base.vectors@vector,question,day,stamp,limit,hard_scope=self.scope)

class ConversationalRAG:
    def __init__(self,index,ask,visual,memory,audio_enabled=True,calibrated_evidence=False):
        self.index,self.ask,self.visual,self.memory=index,ask,visual,memory
        self.audio_enabled=audio_enabled
        self.calibrated_evidence=calibrated_evidence
    def run(self,question,session,day,stamp,mode='memory',feedback=True,target_ref=None,commit_guard=None,commit_lock=None,release_selection=False):
        start=time.perf_counter();version,old,turns=self.memory.load(session)
        cutoff=(int(str(day).replace('DAY','')),recording_seconds(stamp))
        def eligible(t):
            return t.get('query_day') and (int(str(t['query_day']).replace('DAY','')),recording_seconds(t['query_time']))<=cutoff
        available=[x for x in turns if eligible(x)]
        if len(available)!=len(turns):old=None
        active=[x for x in available if x['status']!='superseded']
        if release_selection and old:
            old=dict(old);ref=dict(old.get('entity_ref') or {})
            if (ref.get('track_ref') or {}).get('m5_target_id'):ref['track_ref']=None;old['entity_ref']=ref
            if old.get('scope_from_selection'):old['scope']={'days':[],'interval':None}
        catalog=[{'turn':t['turn'],'question':t['question'][:240],'object':t.get('state',{}).get('object'),
                  'scope':t.get('state',{}).get('scope'),'entity_ref':t.get('state',{}).get('entity_ref')} for t in active]
        if len(catalog)>64:catalog=catalog[:8]+catalog[-56:]
        if mode=='memory' and re.search(r'第一轮|第一个问题|最早讨论|first (?:turn|question)',question,re.I) and available:
            old=available[0].get('state') or old
        extra={'selected_target':target_ref} if target_ref else {}
        plan=resolve(question,old,active,self.ask,day,mode=mode,topic_catalog=catalog if mode=='memory' else None,**extra)
        state=plan['state']
        selected_scope=None
        if target_ref and (target_ref.get('track_ref') or {}).get('m5_target_id'):
            speech=plan['intent']=='speech' or bool(re.search(r'谈话|对话|说了|说电脑|conversation|speech',question,re.I))
            local_speech=bool(re.search(r'这段|当前|刚才|相关谈话|this|current',question,re.I))
            selected_scope=target_ref.get('local_speech_scope') if speech and local_speech else target_ref.get('tracking_scope') if not speech else None
        revisit=plan.get('revisit_turn')
        if re.search(r'第一轮|第一个问题|first (?:turn|question)',question,re.I) and available:revisit=available[0]['turn']
        previous_topic=next((t for t in available if t['turn']==revisit),None)
        if previous_topic:
            st=previous_topic.get('state',{});explicit=explicit_constraints(question,day)
            same_target=not plan.get('topic_change') or bool(tokens(state['object']) & tokens(st.get('object','')))
            if mode=='memory' and st.get('entity_ref') and same_target and not release_selection:plan['selected_entity']=st['entity_ref']
            if not explicit['days'] and explicit['interval'] is None and st.get('scope') and not(release_selection and st.get('scope_from_selection')):state['scope']=st['scope']
            plan['resolved_topic_turn']=revisit
        if target_ref:plan['selected_entity']=target_ref
        # A historical topic's default scope cannot override a new explicit
        # browser selection. Keep user-written time constraints authoritative.
        if selected_scope:
            stated=explicit_constraints(question,day)
            if not stated['days'] or stated['days']==selected_scope['days']:
                interval=list(selected_scope['interval'])
                if stated['interval']:interval=[max(interval[0],stated['interval'][0]),min(interval[1],stated['interval'][1])]
                state['scope']={'days':selected_scope['days'],'interval':interval}
                state['scope_from_selection']=stated['interval'] is None
        state['schema_version']=2
        state['entity_ref']=bind_entity(plan,old,version+1)
        if release_selection and (state['entity_ref'].get('track_ref') or {}).get('m5_target_id'):state['entity_ref']['track_ref']=None
        if plan.get('needs_clarification'):
            result={'answer':{'answer':plan.get('clarification') or '你指的是哪一个物体？','claims':[],'uncertain':['ambiguous reference']},'observations':[],'selected':[],'clarification':True}
        else:
            seeds=self.memory.recall(session,state['object'],state['scope'],day,stamp,requirements=plan.get('requirements'),entity_ref=state['entity_ref'],question=question) if mode=='memory' else []
            if target_ref and (target_ref.get('track_ref') or {}).get('m5_target_id'):
                seeds=[o for o in seeds if o.get('entity_ref',{}).get('id')==target_ref['id'] and
                       (o.get('entity_ref',{}).get('track_ref') or {}).get('revision')==target_ref['track_ref']['revision']]
            history=active[-6:] if mode=='memory' else available[-20:]
            history=[dict(t,answer=re.sub(r'(?<![A-Za-z0-9_])[EM]\d+(?![A-Za-z0-9_])','旧轮引用',t['answer'])) for t in history]
            # Hard bound text history without retaining partial JSON records.
            while len(json.dumps(history,ensure_ascii=False))>12000:history=history[1:]
            context={'current_user_question':question,'state':state if mode=='memory' else {},'past_turns':history,
                     'history_policy':'Past answers are fallible; superseded answers cannot support facts. User labels do not prove visual class. Resolve uncertainty using direct evidence.'}
            if mode=='memory':
                context['topic_catalog']=catalog
                context['conversation_overview']=self.memory.overview(session,[t['turn'] for t in available])
            engine=FeedbackRAG(ScopedIndex(self.index,state['scope']),self.ask,self.visual,audio_enabled=self.audio_enabled,
                               calibrated_evidence=self.calibrated_evidence)
            result=engine.run(plan['question_en'],day,stamp,feedback=feedback,context=context,intent=plan['intent'],seed_observations=seeds,
                              requirements=plan.get('requirements'),target_ref=state['entity_ref'] if mode=='memory' else None)
            if not state['entity_ref']['anchor_clips']:state['entity_ref']['anchor_clips']=result.get('selected',[])[:1]
        result.update(original_question=question,session=session,mode=mode,resolution=plan,elapsed_seconds=time.perf_counter()-start,query_day=day,query_time=stamp)
        with commit_lock if commit_lock is not None else contextlib.nullcontext():
            if commit_guard is not None and not commit_guard():raise InterruptedError('query canceled or selected target revised before memory commit')
            result['turn']=self.memory.commit(session,version,state,question,result)
        return result
