# longctx_suite.py --url U --model M --conc C --sizes 100,300,... --per N --out f.jsonl
# 长上下文检索：每题一份全新随机文档（不命中缓存），问第 k 行的 code（答案可算）。并发 C。
import json,urllib.request,sys,random,time,argparse,os,concurrent.futures as cf
ap=argparse.ArgumentParser();ap.add_argument('--url',default=os.environ.get('URL','https://glm-flash.aitist.ai'));ap.add_argument('--model');ap.add_argument('--conc',type=int,default=1)
ap.add_argument('--sizes',default='200,600,1200,2000,3000');ap.add_argument('--per',type=int,default=4);ap.add_argument('--out');ap.add_argument('--seed',type=int,default=0)
A=ap.parse_args()
H={'Content-Type':'application/json','User-Agent':'zt-gsm8k-consistency/1.0','x-dynamo-meta-policy-class':'batch'}
W=['alpha','beta','gamma','delta','omega','sigma']
def mk(n,seed):
    r=random.Random(seed); codes=[r.randint(1000,9999) for _ in range(n)]; k=r.randint(n//10,n-1-n//10)
    doc="\n".join(f"Line {i}: record {r.randint(0,99999)} filed under {r.choice(W)}, code {codes[i]}." for i in range(n))
    return doc+f"\n\nWhat is the code on Line {k}? Answer with the number only.",str(codes[k])
def ask(job):
    n,seed=job; c,g=mk(n,seed)
    b=dict(model=A.model,temperature=0,max_tokens=24,stream=True,stream_options={"include_usage":True},messages=[{"role":"user","content":c}],chat_template_kwargs={"enable_thinking":False})
    try:
        t=[];u=None;t0=time.time()
        for line in urllib.request.urlopen(urllib.request.Request(A.url+'/v1/chat/completions',json.dumps(b).encode(),H),timeout=900):
            line=line.decode().strip()
            if line.startswith('data:') and line!='data: [DONE]':
                d=json.loads(line[5:]); u=d.get('usage') or u
                for ch in d.get('choices',[]): t.append((ch.get('delta') or {}).get('content') or '')
        t=''.join(t).strip()
        return dict(lines=n,seed=seed,ptok=(u or {}).get('prompt_tokens'),gold=g,out=t[:80],ok=t==g,sec=round(time.time()-t0,2))
    except Exception as e: return dict(lines=n,seed=seed,gold=g,err=repr(e)[:200],ok=False)
base=A.seed or int(time.time())
jobs=[(n,base+i*1000+n) for i in range(A.per) for n in map(int,A.sizes.split(','))]
random.Random(base).shuffle(jobs)
with cf.ThreadPoolExecutor(A.conc) as ex: res=list(ex.map(ask,jobs))
if A.out: open(A.out,'w').write('\n'.join(json.dumps(r) for r in res)+'\n')
by={}
for r in res: by.setdefault(r['lines'],[]).append(r)
print(f"{A.model} conc={A.conc}: {sum(r['ok'] for r in res)}/{len(res)} correct, errs={sum('err' in r for r in res)}")
for n in sorted(by): x=by[n]; print(f"  {n:5d} lines ~{(x[0].get('ptok') or 0):6d} tok: {sum(r['ok'] for r in x)}/{len(x)}", [r.get('out',r.get('err'))[:20] for r in x if not r['ok']][:3])
