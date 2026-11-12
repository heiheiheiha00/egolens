"""Session-isolated, transactional, source-addressed observations; never ground truth."""
import hashlib,json,pathlib,re,sqlite3,time
from egolens.core.time_utils import recording_seconds
from egolens.core.evidence_policy import tokens

def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True)

class EpisodicMemory:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path),timeout=30)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,version INTEGER,state TEXT);
        CREATE TABLE IF NOT EXISTS turns(session TEXT,number INTEGER,question TEXT,answer TEXT,state TEXT,status TEXT,result TEXT,PRIMARY KEY(session,number));
        CREATE TABLE IF NOT EXISTS observations(session TEXT,id TEXT,turn INTEGER,object TEXT,day INTEGER,start REAL,end REAL,path TEXT,signature TEXT,payload TEXT,PRIMARY KEY(session,id));
        CREATE TABLE IF NOT EXISTS revisions(session TEXT,turn INTEGER,old_turn INTEGER,reason TEXT,support TEXT);
        CREATE TABLE IF NOT EXISTS facts(session TEXT,id TEXT,turn INTEGER,entity TEXT,property TEXT,value TEXT,role TEXT,support TEXT,status TEXT,text TEXT,PRIMARY KEY(session,id));
        CREATE TABLE IF NOT EXISTS fact_revisions(session TEXT,turn INTEGER,claim_id TEXT,reason TEXT,support TEXT);
        ''')
    def load(self,session):
        row=self.db.execute('SELECT version,state FROM sessions WHERE id=?',(session,)).fetchone()
        turns=[]
        for n,q,a,s,raw,st in self.db.execute('SELECT number,question,answer,status,result,state FROM turns WHERE session=? ORDER BY number',(session,)):
            result=json.loads(raw)
            revisions=[x[0] for x in self.db.execute('SELECT id FROM facts WHERE session=? AND turn=? AND status=?',(session,n,'superseded'))]
            turns.append({'turn':n,'question':q,'answer':a,'status':s,'query_day':result.get('query_day'),'query_time':result.get('query_time'),'state':json.loads(st),'withdrawn_claims':revisions})
        return (row[0],json.loads(row[1]),turns) if row else (0,None,[])
    def recall(self,session,object_name,scope,day,stamp,limit=4,requirements=None,entity_ref=None,question=''):
        qday=int(str(day).replace('DAY','')); cutoff=recording_seconds(stamp)
        words=set(re.findall(r'[a-z0-9]+',object_name.lower()))-{'the','a','object','item'}
        candidates=[]
        for row in self.db.execute('SELECT o.id,o.object,o.day,o.start,o.end,o.path,o.signature,o.payload FROM observations o JOIN turns t ON t.session=o.session AND t.number=o.turn WHERE o.session=? AND t.status!=?',(session,'superseded')):
            ident,obj,d,lo,hi,path,signature,payload=row
            if d>qday or (d==qday and hi>cutoff+.001):continue
            if scope.get('days') and d not in scope['days']:continue
            interval=scope.get('interval')
            # Reuse only evidence wholly inside a constrained window; never truncate a full-window claim.
            if interval and not(interval[0]<=lo and hi<=interval[1]):continue
            observation=json.loads(payload)
            same_entity=entity_ref and observation.get('entity_ref',{}).get('id')==entity_ref.get('id')
            overlap=len(tokens(object_name) & tokens(obj))
            if not overlap and not same_entity:continue
            p=pathlib.Path(path)
            if not p.exists() or signature!=f'{p.stat().st_size}:{p.stat().st_mtime_ns}':continue
            facts=[]
            for fid,entity,prop,value,role,support,status,text in self.db.execute('SELECT id,entity,property,value,role,support,status,text FROM facts WHERE session=? AND status=?',(session,'candidate')):
                if ident in json.loads(support) and (not entity_ref or entity in {entity_ref['id'],'unbound'}):
                    facts.append(dict(claim_id=fid,entity_id=entity,property=prop,value=json.loads(value),event_role=role,text=text))
            if observation.get('memory_schema_version')==2:
                if not facts:continue
                observation['observation']='Previously sourced candidate claims, not verified facts: '+encode(facts)
                observation['memory_claims']=facts
            observation['stable_id']=ident;observation['memory_reused']=True
            observation['round']=-1;observation.pop('raw',None)
            roles=(requirements or {}).get('roles',[])
            role_score=sum(f['event_role'] in roles for f in facts)
            anchor=entity_ref and observation['clip_id'] in entity_ref.get('anchor_clips',[])
            chronology=-lo if roles==['origin'] else lo if roles==['ending'] else 0
            candidates.append((5*bool(same_entity)+overlap+3*role_score+2*bool(anchor),chronology,ident,observation))
        output=[];seen=set()
        for _,_,_,o in sorted(candidates,key=lambda x:x[:3],reverse=True):
            key=(o.get('source_path'),tuple(o['window']),o.get('media_offset',0))
            if key in seen:continue
            seen.add(key);output.append(o)
            if len(output)>=limit:break
        return output
    def commit(self,session,expected,state,question,result):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT version FROM sessions WHERE id=?',(session,)).fetchone()
            version=row[0] if row else 0
            if version!=expected:raise RuntimeError('Concurrent turn changed session; retry from latest state')
            number=version+1
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(session,number,encode(state)))
            self.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?)',(session,number,question,result['answer']['answer'],encode(state),'unverified',encode(result)))
            for o in result.get('observations',[]):
                if o.get('memory_reused'):continue
                path=pathlib.Path(o['source_path']);sig=f'{path.stat().st_size}:{path.stat().st_mtime_ns}'
                if state.get('schema_version')==2:o['memory_schema_version']=2
                content={k:v for k,v in o.items() if k not in {'raw','evidence_id','round','stable_id'}}
                ident=hashlib.sha256(encode([str(path),sig,content]).encode()).hexdigest()[:24]
                lo=recording_seconds(o['clip_start'])+o['window'][0];hi=recording_seconds(o['clip_start'])+o['window'][1]
                self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',(session,ident,number,state['object'],int(o['date'][3:]),lo,hi,str(path),sig,encode(content)))
                o['stable_id']=ident
            source_map={o['evidence_id']:o.get('stable_id') for o in result.get('observations',[]) if o.get('stable_id')}
            if state.get('schema_version')==2:
                for claim in result['answer'].get('claims',[]):
                    refs=[source_map[x] for x in claim.get('evidence_ids',[]) if x in source_map]
                    if not refs:continue
                    entity=str(claim.get('entity_id') or 'unbound')
                    if entity not in {state.get('entity_ref',{}).get('id'),'unbound'}:entity='unbound'
                    prop=str(claim.get('property','other'));value=claim.get('value',claim.get('text',''));role=str(claim.get('event_role','general'))
                    fid=hashlib.sha256(encode([entity,prop,value,refs]).encode()).hexdigest()[:24]
                    self.db.execute('INSERT OR IGNORE INTO facts VALUES(?,?,?,?,?,?,?,?,?,?)',(session,fid,number,entity,prop,encode(value),role,encode(refs),'candidate',claim.get('text','')))
            # Judge may retract an old answer only with current evidence supporting the correction.
            valid={x['evidence_id'] for x in result.get('observations',[]) if not x.get('memory_reused')}
            revisions=result['answer'].get('revisions',[])[:4] if result.get('mode','memory')=='memory' and state.get('schema_version')!=2 else []
            for revision in revisions:
                old=revision.get('turn'); support=revision.get('evidence_ids',[])
                if not isinstance(old,int) or not 0<old<number or not support or not set(support)<=valid:continue
                self.db.execute('UPDATE turns SET status=? WHERE session=? AND number=?',('superseded',session,old))
                self.db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',(session,number,old,str(revision.get('reason','')),encode(support)))
            for revision in result['answer'].get('claim_revisions',[])[:4] if result.get('mode','memory')=='memory' else []:
                support=revision.get('evidence_ids',[]);fid=revision.get('claim_id')
                if not support or not set(support)<=valid:continue
                old=self.db.execute('SELECT turn FROM facts WHERE session=? AND id=? AND turn<?',(session,fid,number)).fetchone()
                if not old:continue
                self.db.execute('UPDATE facts SET status=? WHERE session=? AND id=?',('superseded',session,fid))
                self.db.execute('INSERT INTO fact_revisions VALUES(?,?,?,?,?)',(session,number,fid,str(revision.get('reason','')),encode(support)))
            self.db.execute('UPDATE turns SET result=? WHERE session=? AND number=?',(encode(result),session,number))
            self.db.commit()
        except BaseException:self.db.rollback();raise
        return number
    def close(self):self.db.close()
    def overview(self,session,allowed_turns):
        allowed=set(allowed_turns);facts=[]
        for ident,n,entity,prop,value,role,support,text in self.db.execute('SELECT id,turn,entity,property,value,role,support,text FROM facts WHERE session=? AND status=? ORDER BY turn DESC',(session,'candidate')):
            if n in allowed:facts.append(dict(claim_id=ident,turn=n,entity_id=entity,property=prop,value=json.loads(value),event_role=role,source_ids=json.loads(support),text=text))
            if len(facts)>=24:break
        return {'purpose':'fallible navigation overview; source IDs here are not current answer evidence IDs','facts':facts}
