# quality_suite.py <model> <outdir> [conc=16] : 工具调用 / 长输出 / 开思考 GSM8K 三项，答案都可程序判定
import json,sys,re,random,os,concurrent.futures as cf
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from common import chat
model,out=sys.argv[1],sys.argv[2]; conc=int(sys.argv[3]) if len(sys.argv)>3 else 16; os.makedirs(out,exist_ok=True)
R=random.Random(20261112)
TOOLS=[{"type":"function","function":{"name":"get_weather","description":"Get current weather for a city","parameters":{"type":"object","properties":{"city":{"type":"string"},"unit":{"type":"string","enum":["celsius","fahrenheit"]}},"required":["city","unit"]}}},
 {"type":"function","function":{"name":"read_file","description":"Read a file from the repository","parameters":{"type":"object","properties":{"path":{"type":"string"},"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["path","start_line","end_line"]}}},
 {"type":"function","function":{"name":"run_command","description":"Run a shell command","parameters":{"type":"object","properties":{"command":{"type":"string"},"timeout_s":{"type":"integer"}},"required":["command","timeout_s"]}}},
 {"type":"function","function":{"name":"add_numbers","description":"Add two integers","parameters":{"type":"object","properties":{"a":{"type":"integer"},"b":{"type":"integer"}},"required":["a","b"]}}}]
cities=['Paris','Tokyo','Nairobi','Lima','Oslo','Cairo','Hanoi','Quito','Dhaka','Perth']
def tool_cases():
    cs=[]
    for i in range(120):
        k=i%4
        if k==0: c=R.choice(cities);u=R.choice(['celsius','fahrenheit']); cs.append((f"What's the weather in {c} right now, in {u}? Use the tool.",'get_weather',{"city":c,"unit":u}))
        elif k==1: p=f"src/{R.choice(['auth','db','api','utils'])}/{R.choice(['main','handler','models','config'])}_{R.randint(1,99)}.py";a=R.randint(1,400);b=a+R.randint(5,80); cs.append((f"Show me lines {a} to {b} of {p}.",'read_file',{"path":p,"start_line":a,"end_line":b}))
        elif k==2: n=R.randint(2,30);t=R.choice([30,60,120,300]); cs.append((f"Run exactly this command with a {t} second timeout: pytest -x -k test_case_{n} tests/",'run_command',{"command":f"pytest -x -k test_case_{n} tests/","timeout_s":t}))
        else: a=R.randint(-9999,9999);b=R.randint(-9999,9999); cs.append((f"Use the add_numbers tool to add {a} and {b}.",'add_numbers',{"a":a,"b":b}))
    return cs
def run_tool(c):
    q,name,args=c; r=chat(model,[{"role":"user","content":q}],max_tokens=256,tools=TOOLS)
    tc=r['tool_calls']; ok=False; parsed=None
    if len(tc)==1 and tc[0]['name']==name:
        try: parsed=json.loads(tc[0]['arguments']); ok=parsed==args
        except Exception: pass
    return dict(q=q,want=[name,args],got=tc,ok=ok,fin=r['fin'],err=r.get('err'))
def run_count(n):
    r=chat(model,[{"role":"user","content":f"Output the integers from 1 to {n}, one per line, with nothing else."}],max_tokens=n*5+50)
    got=[x for x in r['text'].split('\n') if x.strip()]
    return dict(n=n,ok=got==[str(i) for i in range(1,n+1)],fin=r['fin'],out_tokens=(r['usage'] or {}).get('completion_tokens'),head=r['text'][:60],tail=r['text'][-60:],err=r.get('err'))
qs=[json.loads(l) for l in open(os.path.join(os.environ.get('DATA_DIR','.'),'test.jsonl'))][:300]
def run_think(i):
    q=qs[i]; r=chat(model,[{"role":"user","content":q['question']+"\nGive the final answer on the last line as: #### <number>"}],max_tokens=4096,thinking=True)
    gold=q['answer'].split('####')[-1].strip().replace(',',''); t=r['text']
    nums=re.findall(r'-?\d[\d,]*\.?\d*',t.split('####')[-1]); pred=nums[-1].replace(',','').rstrip('.') if nums else None
    return dict(i=i,gold=gold,pred=pred,ok=pred==gold,fin=r['fin'],reasoning_chars=len(r['reasoning']),text=t[-300:],err=r.get('err'))
S={}
with cf.ThreadPoolExecutor(conc) as ex:
    for name,fn,items in [('tool_calls',run_tool,tool_cases()),('long_output',run_count,[300,400,500,600,800,1000]*4),('gsm8k_thinking',run_think,list(range(300)))]:
        res=list(ex.map(fn,items)); open(f'{out}/{name}.jsonl','w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in res)+'\n')
        S[name]=dict(n=len(res),ok=sum(r['ok'] for r in res),errs=sum(bool(r.get('err')) for r in res)); print(model,name,S[name],flush=True)
json.dump(S,open(f'{out}/summary.json','w'),indent=1)
