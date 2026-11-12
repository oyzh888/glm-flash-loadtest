# summarize_quality.py <results_dir> <model> [<model> ...] : one Markdown table of the quality tests
import json,os,sys
d=sys.argv[1]; models=sys.argv[2:]
J=lambda p:[json.loads(l) for l in open(p) if l.strip()]
def gs(m,r):
    p=f'{d}/{m}/gsm8k_run{r}.jsonl'
    if not os.path.exists(p): return None
    x=J(p); return f"{100*sum(q.get('ok',False) for q in x)/len(x):.1f}%"
def cnt(m,name,key='ok'):
    p=f'{d}/{m}/{name}.jsonl'
    if not os.path.exists(p): return '—'
    x=J(p); return f"{sum(bool(q.get(key)) for q in x)} / {len(x)}"
def he(m):
    p=f'{d}/{m}/humaneval.jsonl'
    if not os.path.exists(p): return '—'
    x=J(p); return f"{sum(q['passed'] for q in x)} / {len(x)}"
def lc(m,c):
    p=f'{d}/{m}/longctx_c{c}.jsonl'
    if not os.path.exists(p): return '—'
    x=J(p); return f"{sum(q['ok'] for q in x)} / {len(x)}"
rows=[('GSM8K, 1,319 questions (run 1 / run 2)',lambda m:' / '.join(v for v in (gs(m,1),gs(m,2)) if v)),
 ('GSM8K with thinking, first 300',lambda m:cnt(m,'gsm8k_thinking')),
 ('HumanEval, 164 problems, tests executed (pass@1)',he),
 ('Tool calls, right function + exact arguments',lambda m:cnt(m,'tool_calls')),
 ('Long output, 300-1000 lines checked line by line',lambda m:cnt(m,'long_output')),
 ('Long-context retrieval, serial, 2.8K-90K tokens',lambda m:lc(m,1)),
 ('Long-context retrieval, 16 concurrent, 2.8K-59K tokens',lambda m:lc(m,16))]
print('| Dimension | '+' | '.join(models)+' |'); print('|---|'+'---|'*len(models))
for n,f in rows: print(f'| {n} | '+' | '.join(f(m) for m in models)+' |')
