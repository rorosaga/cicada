"""Stored answers judged N times through the harness's own judge call (providers.resolve_llm_fn, stage=judge); majority of N.
python rejudge3.py LABEL N OUT RUN[,RUN...] PATH ; cwd=checkout. No new answers (ROR bench-1107)."""
import json,glob,os,sys,concurrent.futures as cf,time
sys.path.insert(0,os.getcwd())
os.environ.update(CICADA_CAPTURE="off",CICADA_RECALL="off",CICADA_TELEMETRY="off")
from benchmarks.public import judges as J
from api.config import Settings
from api.services import providers
label,N,out,runs,path=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4].split(','),sys.argv[5]
B=os.path.expanduser('~/cicada-bench-public/runs/')
fn=providers.resolve_llm_fn(Settings(_env_file=None,llm_mode='agent',agent_model='haiku'),stage='judge',is_async=False)
items=[]
for r in runs:
    for u in sorted(glob.glob(B+r+'/units/*')):
        un=json.load(open(u+'/unit.json'));Q={q['qid']:q for q in un['questions']}
        V={}
        for l in open(u+'/judgments.jsonl'):
            x=json.loads(l);V[x['key']]=x
        for l in open(u+'/answers.jsonl'):
            a=json.loads(l)
            if a['path']!=path or a.get('error') or not a.get('answer'):continue
            q=Q[a['qid']]
            if un['dataset']=='locomo':
                items.append((r+'|'+a['key'],q,a['answer'],bool(V[a['key']]['correct'])));continue
            items.append((r+'|'+a['key'],q,a['answer'],bool(V[a['key']]['correct'])))
def one(it):
    k,q,ans,st=it;vs=[]
    p=J.mem0_prompt(q['question'],q['answer'],ans) if q.get('category_id') is not None else J.personal_prompt(q['question'],q['answer'],ans)
    for _ in range(N):
        t=''
        for _t in range(3):
            try:
                t=fn(messages=[{'role':'user','content':p}]).choices[0].message.content or ''
                if t.strip():break
            except Exception:pass
        vs.append((J.parse_mem0(t) if q.get('category_id') is not None else J.parse_lme(t)) if t.strip() else None)
    return dict(key=k,stored=st,votes=vs)
t0=time.time()
with cf.ThreadPoolExecutor(5) as ex: rows=list(ex.map(one,items))
json.dump(rows,open(out,'w'))
maj=sum(sum(bool(v) for v in r['votes'])*2>len([v for v in r['votes'] if v is not None]) for r in rows)
print(label,'n',len(rows),'stored',sum(r['stored'] for r in rows),'per rep',[sum(bool(r['votes'][i]) for r in rows) for i in range(N)],'majority',maj,'unjudged',sum(v is None for r in rows for v in r['votes']),'secs',int(time.time()-t0),flush=True)
