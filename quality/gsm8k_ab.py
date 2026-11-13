# gsm8k_ab.py <model> <out.jsonl> : GSM8K test 全量，经公网入口，流式，temperature 0，关思考
import json,sys,re,os,urllib.request,concurrent.futures as cf,time
model,out=sys.argv[1],sys.argv[2]
qs=[json.loads(l) for l in open(os.path.join(os.environ.get('DATA_DIR','.'),'test.jsonl'))]
import os
URL=os.environ.get('URL','https://glm-flash.aitist.ai')+'/v1/chat/completions'
H={'Content-Type':'application/json','User-Agent':'zt-gsm8k-consistency/1.0','x-dynamo-meta-policy-class':'batch'}
if os.environ.get('BENCH_LEASE'): H['Authorization']='Bearer '+os.environ['BENCH_LEASE']   # test lock lease (bench_lock.py)
def ask(i):
    q=qs[i]
    body={"model":model,"stream":True,"messages":[{"role":"user","content":q['question']+"\nSolve step by step, then give the final answer on the last line as: #### <number>"}],
          "temperature":0,"max_tokens":1024,"chat_template_kwargs":{"enable_thinking":False}}
    for att in range(4):
        try:
            t0=time.time(); txt=[]; fin=None
            r=urllib.request.urlopen(urllib.request.Request(URL,json.dumps(body).encode(),H),timeout=600)
            for line in r:
                line=line.decode().strip()
                if not line.startswith('data:') or line=='data: [DONE]': continue
                d=json.loads(line[5:])
                for c in d.get('choices',[]):
                    txt.append((c.get('delta') or {}).get('content') or ''); fin=c.get('finish_reason') or fin
            t=''.join(txt); break
        except Exception as e:
            t=None; err=repr(e); time.sleep(3*(att+1))
    if t is None: return dict(i=i,err=err)
    gold=q['answer'].split('####')[-1].strip().replace(',','')
    nums=re.findall(r'-?\d[\d,]*\.?\d*',t.split('####')[-1]); pred=nums[-1].replace(',','').rstrip('.') if nums else None
    return dict(i=i,gold=gold,pred=pred,ok=pred==gold,fin=fin,sec=round(time.time()-t0,2),text=t)
t0=time.time()
with cf.ThreadPoolExecutor(int(os.environ.get("GSM_CONC","32"))) as ex, open(out,'w') as f:
    for r in ex.map(ask,range(len(qs))): f.write(json.dumps(r,ensure_ascii=False)+'\n')
print(model,'done',round(time.time()-t0),'s')
