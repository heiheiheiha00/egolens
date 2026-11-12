"""Task roles are independent of conversational transitions and object class labels."""
import re

def task_requirements(original, english='', intent='general'):
    text=original+' '+english
    roles=[]
    if re.search(r'最初|起点|来源|出门前|哪里(?:拿|取)|从哪|original location|origin|before going outside|where.*(?:get|pick up)',text,re.I):roles.append('origin')
    if re.search(r'最后(?:一次|可见|位置|放)|末次|终点|片尾|结尾|last visib|final location|at the end',text,re.I):roles.append('ending')
    if intent=='sequence' and not ('before_action' in roles):roles=['origin','ending']
    compare=bool(re.search(r'比较|一样|相同|是否.*同一处|same.*(?:location|place)|same as|compare',text,re.I)) and len(roles)>1
    if not roles:roles=[intent if intent in {'origin','ending','before','speech','identity','sequence'} else 'general']
    return {'operation':'compare' if compare else 'sequence' if len(roles)>1 else 'lookup','roles':roles}

def tokens(text):
    return {w.rstrip('s') for w in re.findall(r'[a-z0-9]+',str(text).lower()) if w not in {'the','a','an','object','item','of','on','in'}}

def bind_entity(plan,old,turn):
    previous=(old or {}).get('entity_ref')
    same=previous and not plan.get('topic_change') and bool(tokens(plan['state']['object']) & tokens((old or {}).get('object','')))
    if plan.get('selected_entity'):return dict({'anchor_clips':[],'track_ref':None},**plan['selected_entity'])
    if same:return dict({'anchor_clips':[],'track_ref':None},**previous)
    return {'id':f'entity_{turn}', 'label':plan['state']['object'], 'anchor_clips':[],
            'selection_context':plan.get('selection_context',''), 'track_ref':None,'association':'candidate_not_cross_clip_identity'}
