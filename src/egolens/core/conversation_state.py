"""Resolve language with the planner, validate hard scope in ordinary code."""
import json,re
from egolens.core.feedback_rag import parse_json
from egolens.core.time_utils import explicit_constraints
from egolens.core.evidence_policy import task_requirements

def resolve(question, previous, turns, ask, query_day, mode='memory',topic_catalog=None,selected_target=None):
    old = previous or {'scope':{'days':[], 'interval':None}, 'object':'', 'aliases':[], 'revision':0}
    prompt = '''Resolve a video conversation turn, not its answer. Return JSON only:
{"question_en":"self-contained English retrieval/visual question", "object":"short English object name",
 "aliases":["other referring names"], "topic_change":false,"clear_time_scope":false,
 "intent":"general|location|origin|ending|before|identity|speech|sequence|compare",
 "selection_context":"short user-stated scene/context identifying the object, not inferred facts",
 "revisit_turn":null,
 "needs_clarification":false,"clarification":"Chinese question if truly ambiguous",
 "correction":false,"reason":"brief resolution reason"}.
Keep original intent. Resolve pronouns from conversation; a topic change may introduce a new object.
For a comparison of initial and final locations preserve BOTH locations in question_en and use compare.
Do not collapse a comparison into asking only the last location. Never treat same-location as same-object identity.
The topic catalog indexes ORIGINAL user questions, entities and scopes, not factual answers.
For '第一轮/first turn' or return to an old topic, set revisit_turn to its catalog turn number.
If no unique computer/object is established, ask which one rather than assigning a nearby spoken name.
Aliases and a user category label are references, not proof of physical identity or class.
When the user merely gives a nickname to IT, retain the prior object descriptor and add the nickname
to aliases; this is not a topic change. Keep user-stated selection context (e.g. outdoor scene)
when referring to the same object; do not replace an outdoor selected object with an indoor lookalike.
Do not answer, add factual premises, infer a DAY/time, or turn a previous model answer into established fact.
For questions about what someone said, use speech intent. For last visible location use ending.
Pronouns inherit the object; do NOT silently inherit a previous question's before-going-outside,
after-action or other event restriction. DAY/minute scope is separately handled in code.
If the new user asks last visible location without saying before an event, search the END of the
available recorded episode, including later clips. Use before intent only for state before hand/contact;
other relative-before questions use general/sequence and retain the explicit event relation in question_en.
IMPORTANT: '最后回到DAY5/最后回顾/最后问一下' means finally return to a conversation topic,
NOT the ending of its video. Do not add an end-of-video restriction in question_en or intent.
Use identity only for SAME OBJECT questions, not merely what category an object is.
If multiple referents remain genuinely indistinguishable, request clarification instead of guessing.
User-specified DAY and clock time are handled outside you. A new topic alone does not clear a DAY scope;
clear_time_scope=true only when the user explicitly says to remove/change the time scope (e.g. all days).
User corrections change references; they do not establish a visual action.
'''
    # Plain-history baseline gets the same language resolver, but no persistent structured state.
    context = old if mode=='memory' else {'scope':{},'object':''}
    recent=turns[-20:] if mode=='history' else turns[-6:]
    prompt+='\nState: '+json.dumps(context,ensure_ascii=False)+'\nActual recent turns (fallible answers): '+json.dumps(recent,ensure_ascii=False)+'\nUser: '+question
    if topic_catalog:prompt+='\nOlder topic catalog: '+json.dumps(topic_catalog,ensure_ascii=False)
    if selected_target:
        prompt+='\nCURRENT EXPLICIT USER SELECTION: '+json.dumps(selected_target,ensure_ascii=False)+'. Resolve this/it/这个/它 using this selected region. Its nickname is not a verified class. Do not ask which object when this selection uniquely resolves the pronoun. Keep unrelated/another-object ambiguity explicit.'
    plan=parse_json(ask(prompt,max_tokens=900))
    if selected_target and not re.search(r'另一|另外|other one|which one',question,re.I):plan['needs_clarification']=False
    if not isinstance(plan.get('question_en'),str) or not plan['question_en'].strip():
        raise ValueError('Planner omitted question')
    explicit=explicit_constraints(question,query_day)
    # Both methods share the same trusted hard-scope safety. Do not handicap the
    # plain-history baseline by discarding a user's inherited DAY/minute.
    scope=dict(old['scope'])
    if plan.get('clear_time_scope') and re.search(r'不限|全部日期|所有天|取消.{0,6}时间|all days|any day|remove.*time',question,re.I):
        scope={'days':[], 'interval':None}
    if explicit['days']:
        # A newly specified day without a minute releases the previous minute range.
        scope['days']=explicit['days'];scope['interval']=explicit['interval']
    elif explicit['interval'] is not None:scope['interval']=explicit['interval']
    intent=plan.get('intent','general')
    # A destination lookup after an action is not a request for a whole event
    # chain. Expanding it to origin+ending invents extra requirements and turns
    # a visible room into an unnecessary unresolved-sequence refusal.
    destination_only=bool(re.search(r'(?:什么|哪个|哪一[个间]?)(?:房间|屋子)|(?:what|which) room',question,re.I)) and not bool(
        re.search(r'完整|全过程|按时间|依次|经历|顺序|sequence|chronolog|all steps',question,re.I))
    if destination_only:
        intent='location'
        plan['question_en']='What room does the camera wearer move into after the interaction with the '+str(plan.get('object','object'))+'? Answer only the visible destination room, not a full action sequence.'
    event_lookup=bool(re.search(r'找(?:到|出|回)?.{0,12}(?:视频|片段|过程)|哪段|什么时候|find.{0,35}(?:video|clip|moment)',question,re.I)) and not bool(
        re.search(r'完整|全过程|按时间|依次|经历|顺序|sequence|chronolog|all steps',question,re.I))
    if event_lookup and intent=='sequence':intent='general'
    if re.search(r'最后(?:再)?(?:回到|回顾|问|说)',question) and not re.search(r'片尾|视频.{0,4}结尾|最后(?:一次|可见|出现|位置)',question):
        intent='general'
    if intent not in {'general','location','origin','ending','before','identity','speech','sequence','compare'}:intent='general'
    requirements=task_requirements(question,'' if destination_only or event_lookup else plan['question_en'],intent)
    if len(requirements['roles'])>1:intent=requirements['operation']
    state={'scope':scope,'object':str(plan.get('object',''))[:160],
           'aliases':[str(x)[:100] for x in plan.get('aliases',[])[:8]],
           'revision':old.get('revision',0)+1,'intent':intent,
           'correction':bool(plan.get('correction')), 'reason':str(plan.get('reason',''))[:500]}
    # Remove model-generated hard restrictions; only scope derived above may hard-filter.
    query=re.sub(r'DAY\s*\d+|\d{1,2}:\d{2}(?::\d{2})?', ' ', plan['question_en'], flags=re.I)
    if intent=='ending' and len(requirements['roles'])==1 and re.search(r'哪|位置|where|location',question,re.I) and not re.search(r'之前|以前|before',question,re.I):
        query=f'Where was the {state["object"]} last visibly located at the end of the available recorded episode? Distinguish visible from inferred whereabouts.'
    state['requirements']=requirements
    if requirements['roles']==['origin','ending'] and requirements['operation']=='sequence':
        query=f'Summarize the visible sequence of the {state["object"]} across the available relevant recording: initial source, intermediate visible actions, and last visible location. Mark gaps; do not inherit a previous before-going-outside restriction.'
    if intent=='origin':plan['selection_context']=re.sub(r'before going outside|出门前|去室外之前','',plan.get('selection_context',''),flags=re.I).strip()
    plan.update(state=state,question_en=query.strip(),intent=intent,requirements=requirements)
    return plan
