# humaneval.py <model> <out.jsonl> : HumanEval 164 题，temperature 0，关思考；生成后在隔离子进程里跑官方单元测试
import json,sys,re,os,subprocess,tempfile,concurrent.futures as cf
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from common import chat
model,out=sys.argv[1],sys.argv[2]
P=[json.loads(l) for l in open(os.path.join(os.environ.get('DATA_DIR','.'),'HumanEval.jsonl'))]
def gen(p):
    r=chat(model,[{"role":"user","content":"Complete the following Python function. Return the complete function (signature, docstring and body) in a single ```python code block, with no explanation.\n\n```python\n"+p['prompt']+"\n```"}],max_tokens=1024)
    m=re.findall(r"```(?:python)?\n(.*?)```",r['text'],flags=re.S); code=max(m,key=len) if m else r['text']
    return dict(task_id=p['task_id'],code=code,raw=r['text'],fin=r['fin'],err=r.get('err'))
def run(g,p):
    prog=g['code']+"\n\n"+p['test']+f"\n\ncheck({p['entry_point']})\n"
    with tempfile.TemporaryDirectory() as d:
        f=os.path.join(d,'t.py'); open(f,'w').write(prog)
        try:
            pr=subprocess.run(['bash','-c',f'ulimit -v 2000000 -t 20; exec {sys.executable} -I t.py'],cwd=d,capture_output=True,timeout=30,env={'PATH':'/usr/bin:/bin','HOME':d})
            return pr.returncode==0,pr.stderr.decode()[-200:]
        except subprocess.TimeoutExpired: return False,'timeout'
with cf.ThreadPoolExecutor(8) as ex: G=list(ex.map(gen,P))
res=[]
for g,p in zip(G,P):
    ok,e=run(g,p); g['passed']=ok; g['stderr']=e; res.append(g)
open(out,'w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in res)+'\n')
print(model,'humaneval pass@1',sum(r['passed'] for r in res),'/',len(res),'gen errs',sum(bool(r['err']) for r in res))
