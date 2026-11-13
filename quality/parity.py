# parity.py: 同一请求分别发给 glm-zt / glm-official（串行、单请求），比 prompt_tokens 和 temperature 0 的输出
import json,urllib.request,sys
import os
URL=os.environ.get('URL','https://glm-flash.aitist.ai')+'/v1/chat/completions'
H={'Content-Type':'application/json','User-Agent':'zt-gsm8k-consistency/1.0','x-dynamo-meta-policy-class':'batch'}
if os.environ.get('BENCH_LEASE'): H['Authorization']='Bearer '+os.environ['BENCH_LEASE']   # test lock lease (bench_lock.py)
tools=[{"type":"function","function":{"name":"get_weather","description":"Get current weather for a city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]
long_doc=" ".join(f"Line {i}: the quick brown fox jumps over the lazy dog, item {i*7%1000}." for i in range(1400))
cases={
 'chat, thinking off':dict(messages=[{"role":"user","content":"Explain what a hash map is in two sentences."}],chat_template_kwargs={"enable_thinking":False}),
 'chat, thinking on':dict(messages=[{"role":"user","content":"What is 17*23? Answer with the number only."}],chat_template_kwargs={"enable_thinking":True}),
 'multi-turn':dict(messages=[{"role":"system","content":"You are a concise assistant."},{"role":"user","content":"Name a prime number."},{"role":"assistant","content":"7"},{"role":"user","content":"Name a bigger one."}],chat_template_kwargs={"enable_thinking":False}),
 'tool call':dict(messages=[{"role":"user","content":"What's the weather in Paris?"}],tools=tools,chat_template_kwargs={"enable_thinking":False}),
 'tool result':dict(messages=[{"role":"user","content":"What's the weather in Paris?"},{"role":"assistant","content":"","tool_calls":[{"id":"call_1","type":"function","function":{"name":"get_weather","arguments":"{\"city\": \"Paris\"}"}}]},{"role":"tool","tool_call_id":"call_1","content":"{\"temp_c\": 18, \"sky\": \"cloudy\"}"}],tools=tools,chat_template_kwargs={"enable_thinking":False}),
 '~20K-token context':dict(messages=[{"role":"user","content":long_doc+"\n\nWhat item number is on Line 1234? Answer with the number only."}],chat_template_kwargs={"enable_thinking":False}),
}
def call(model,c):
    b=dict(model=model,temperature=0,max_tokens=256,stream=True,stream_options={"include_usage":True},**c)
    txt=[];tc=[];usage=None
    for line in urllib.request.urlopen(urllib.request.Request(URL,json.dumps(b).encode(),H),timeout=600):
        line=line.decode().strip()
        if not line.startswith('data:') or line=='data: [DONE]': continue
        d=json.loads(line[5:]); usage=d.get('usage') or usage
        for ch in d.get('choices',[]):
            dl=ch.get('delta') or {}; txt.append(dl.get('content') or ''); txt.append(dl.get('reasoning_content') or '')
            for t in dl.get('tool_calls') or []: tc.append(json.dumps(t.get('function',{}),sort_keys=True))
    return dict(prompt_tokens=(usage or {}).get('prompt_tokens'),text=''.join(txt),tool=''.join(tc))
out=[]
for name,c in cases.items():
    a=call('glm-zt',c); o=call('glm-official',c)
    out.append(dict(case=name,prompt_tokens_zt=a['prompt_tokens'],prompt_tokens_official=o['prompt_tokens'],same_prompt=a['prompt_tokens']==o['prompt_tokens'],same_output=(a['text'],a['tool'])==(o['text'],o['tool']),zt=a,official=o))
    print(name,a['prompt_tokens'],o['prompt_tokens'],out[-1]['same_output'],repr((a['text']+a['tool'])[:80]))
json.dump(out,open(sys.argv[1],'w'),ensure_ascii=False,indent=1)
