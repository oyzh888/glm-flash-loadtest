import json,urllib.request,time
import os
URL=os.environ.get('URL','https://glm-flash.aitist.ai')
H={'Content-Type':'application/json','User-Agent':'zt-gsm8k-consistency/1.0','x-dynamo-meta-policy-class':'batch'}
def chat(model,messages,max_tokens=1024,thinking=False,temperature=0,url=None,**kw):
    b=dict(model=model,temperature=temperature,max_tokens=max_tokens,stream=True,stream_options={"include_usage":True},messages=messages,chat_template_kwargs={"enable_thinking":thinking},**kw)
    err=None
    for att in range(4):
        try:
            t=[];rs=[];tc={};u=None;fin=None;t0=time.time()
            for line in urllib.request.urlopen(urllib.request.Request((url or URL)+'/v1/chat/completions',json.dumps(b).encode(),H),timeout=900):
                line=line.decode().strip()
                if not line.startswith('data:') or line=='data: [DONE]': continue
                d=json.loads(line[5:]); u=d.get('usage') or u
                for ch in d.get('choices',[]):
                    dl=ch.get('delta') or {}; t.append(dl.get('content') or ''); rs.append(dl.get('reasoning_content') or ''); fin=ch.get('finish_reason') or fin
                    for c in dl.get('tool_calls') or []:
                        e=tc.setdefault(c.get('index',0),{'name':'','arguments':''}); f=c.get('function') or {}
                        e['name']+=f.get('name') or ''; e['arguments']+=f.get('arguments') or ''
            return dict(text=''.join(t),reasoning=''.join(rs),tool_calls=[tc[k] for k in sorted(tc)],fin=fin,usage=u,sec=round(time.time()-t0,2))
        except Exception as e: err=repr(e)[:200]; time.sleep(3*(att+1))
    return dict(err=err,text='',reasoning='',tool_calls=[],fin=None,usage=None)
