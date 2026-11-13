#!/usr/bin/env python3
"""replay_capture.py: replay a captured benchmark exactly (the same request bodies, at the same relative times).

  python3 replay/replay_capture.py <lease_id>.jsonl.gz --url https://glm-flash.aitist.ai [--speed 1.0] [--model glm-zt] --out replay-results/capture

The gateway records the full body of every request sent under a test-lock lease (see BENCH_LOCK.md). This tool
sends those bodies again, open loop, each at its original offset from the first request (scaled by 1/--speed), and
reports TTFT / E2E per request and as percentiles. `--model` overrides the model name (e.g. to replay a run recorded
against glm-zt on glm-official). Standard library only. $BENCH_LEASE, if set, is sent as the lease.
"""
import argparse, gzip, json, os, threading, time, urllib.error, urllib.request
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('capture'); ap.add_argument('--url', default=os.environ.get('URL', 'https://glm-flash.aitist.ai'))
ap.add_argument('--speed', type=float, default=1.0); ap.add_argument('--model', default=None); ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--out', default='replay-results/capture')
A = ap.parse_args()
rows = [json.loads(l) for l in gzip.open(A.capture, 'rt')]
rows.sort(key=lambda r: r['at']); rows = rows[:A.limit] if A.limit else rows
H = {'Content-Type': 'application/json', 'User-Agent': 'glm-capture-replay/1.0'}
if os.environ.get('BENCH_LEASE'): H['Authorization'] = 'Bearer ' + os.environ['BENCH_LEASE']
res = []; L = threading.Lock(); T0 = rows[0]['at']; start = time.time()
def send(r):
    b = dict(r['body'])
    if A.model: b['model'] = A.model
    path = '/v1/messages' if 'system' in b and 'messages' in b and b.get('max_tokens') and 'anthropic_version' in b else '/v1/chat/completions'
    t0 = time.time(); first = None; usage = None; err = None
    try:
        resp = urllib.request.urlopen(urllib.request.Request(A.url.rstrip('/') + path, json.dumps(b).encode(), H), timeout=1800)
        if b.get('stream'):
            for line in resp:
                line = line.decode('utf8', 'ignore').strip()
                if not line.startswith('data:') or line == 'data: [DONE]': continue
                try: d = json.loads(line[5:])
                except ValueError: continue
                usage = d.get('usage') or usage
                for ch in d.get('choices') or []:
                    dl = ch.get('delta') or {}
                    if (dl.get('content') or dl.get('reasoning_content')) and first is None: first = time.time() - t0
        else:
            d = json.loads(resp.read()); usage = d.get('usage'); first = time.time() - t0
    except urllib.error.HTTPError as e: err = 'HTTP %d' % e.code
    except Exception as e: err = repr(e)[:160]
    with L: res.append(dict(rid=r['rid'], offset=r['at'] - T0, ttft=first, e2e=time.time() - t0, usage=usage, err=err))
ts = []
for r in rows:
    wait = (r['at'] - T0) / A.speed - (time.time() - start)
    if wait > 0: time.sleep(wait)
    t = threading.Thread(target=send, args=(r,), daemon=True); t.start(); ts.append(t)
for t in ts: t.join()
os.makedirs(A.out, exist_ok=True)
with open(os.path.join(A.out, 'requests.jsonl'), 'w') as f:
    for r in sorted(res, key=lambda r: r['offset']): f.write(json.dumps(r) + '\n')
ok = sorted(x['ttft'] for x in res if x['ttft'] is not None and not x['err']); e2e = sorted(x['e2e'] for x in res if not x['err'])
q = lambda v, f: round(v[int(f * (len(v) - 1))], 3) if v else None
s = dict(requests=len(res), errors=sum(1 for x in res if x['err']), ttft_p50=q(ok, .5), ttft_p90=q(ok, .9), ttft_p99=q(ok, .99), e2e_p50=q(e2e, .5), e2e_p90=q(e2e, .9))
json.dump(s, open(os.path.join(A.out, 'summary.json'), 'w'), indent=1); print(json.dumps(s))
