#!/usr/bin/env python3
"""replay.py: replay a traffic profile (sizes only) against an OpenAI-compatible endpoint and report TTFT/latency.

  python3 replay/replay.py --profile replay/profile_2026-11-13.json --url https://glm-flash.aitist.ai --model glm-zt \
      --phases A,B,C,D,E,F --seconds 180 --out replay-results/glm-zt

Each phase runs closed-loop at its own concurrency (override with --concurrency) for --seconds, drawing the phase's
samples in a fixed random order (--seed), so even a short run follows the phase's overall size distribution. Every request has the sample's input length (synthetic text), thinking on/off
and output length (max_tokens = output, ignore_eos). Prompt reuse follows the original cache behaviour: phase A and C
send a new prompt every time; B, D, E and F build prompts as prefixes of one shared document plus a short unique tail,
so the server's prefix cache hits about as often as it did for the original traffic. A per-run salt keeps runs from
reusing each other's cache. Standard library only (Python >= 3.6). If $BENCH_LEASE is set it is sent as the test-lock lease.
"""
import argparse, json, os, random, statistics, sys, threading, time, urllib.error, urllib.request, uuid
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--profile', required=True); ap.add_argument('--url', default=os.environ.get('URL', 'https://glm-flash.aitist.ai'))
ap.add_argument('--model', default='glm-zt'); ap.add_argument('--phases', default='A,B,C,D,E,F')
ap.add_argument('--seconds', type=float, default=180); ap.add_argument('--warmup', type=float, default=20)
ap.add_argument('--concurrency', type=int, default=0, help='override every phase\'s concurrency (0 = use the profile)')
ap.add_argument('--temperature', type=float, default=0.6); ap.add_argument('--out', default='replay-results/run')
ap.add_argument('--seed', type=int, default=1, help='order in which each phase\'s samples are drawn (a fixed random permutation, so a short run is representative)')
A = ap.parse_args()
PROF = json.load(open(A.profile)); PH = {p['name']: p for p in PROF['phases']}
H = {'Content-Type': 'application/json', 'User-Agent': 'glm-partner-replay/1.0'}
if os.environ.get('BENCH_LEASE'): H['Authorization'] = 'Bearer ' + os.environ['BENCH_LEASE']
SALT = uuid.uuid4().hex[:12]; TPL = 20.2; OVERHEAD = 12
W = ['alpha', 'beta', 'gamma', 'delta', 'omega', 'sigma', 'kappa', 'theta']
_doc_cache = {}
def base_doc(phase, lines):
    key = (phase, lines)
    if key not in _doc_cache:
        r = random.Random('%s-%s' % (SALT, phase))
        _doc_cache[key] = ['Line %d: record %d filed under %s, code %d.' % (i, r.randint(0, 99999), r.choice(W), r.randint(1000, 9999)) for i in range(lines)]
    return _doc_cache[key]
def prompt(phase, n_tokens, k):
    if n_tokens < 60:
        return ' '.join(['ping'] * max(1, int(n_tokens - OVERHEAD)))   # tiny prompts: cache does not matter
    lines = max(1, int((n_tokens - OVERHEAD - 25) / TPL))
    if phase in ('A',):                                   # fresh prompt every time
        r = random.Random('%s-%s-%d' % (SALT, phase, k))
        body = ['Line %d: record %d filed under %s, code %d.' % (i, r.randint(0, 99999), r.choice(W), r.randint(1000, 9999)) for i in range(lines)]
    else:                                                 # prefix of one shared document
        body = base_doc(phase, 8000)[:lines] if lines <= 8000 else base_doc(phase, lines)[:lines]
    return '\n'.join(body) + '\n\nQuestion %d: what is the code on line %d? Answer briefly.' % (k, (k * 7) % max(1, lines))
LOCK = threading.Lock()
def one(phase, k, sample):
    n_in, n_out, think = sample
    body = dict(model=A.model, stream=True, stream_options={'include_usage': True}, temperature=A.temperature, top_p=0.95,
                max_tokens=int(n_out), ignore_eos=True, messages=[{'role': 'user', 'content': prompt(phase, n_in, k)}],
                chat_template_kwargs={'enable_thinking': bool(think)})
    t0 = time.time(); first_any = first_content = None; usage = None; err = None
    try:
        r = urllib.request.urlopen(urllib.request.Request(A.url.rstrip('/') + '/v1/chat/completions', json.dumps(body).encode(), H), timeout=900)
        for line in r:
            line = line.decode('utf8', 'ignore').strip()
            if not line.startswith('data:') or line == 'data: [DONE]': continue
            try: d = json.loads(line[5:])
            except ValueError: continue
            if d.get('usage'): usage = d['usage']
            if d.get('error'): err = str(d['error'])[:200]
            for ch in d.get('choices') or []:
                dl = ch.get('delta') or {}
                if (dl.get('reasoning_content') or dl.get('content')) and first_any is None: first_any = time.time() - t0
                if dl.get('content') and first_content is None: first_content = time.time() - t0
    except urllib.error.HTTPError as e: err = 'HTTP %d %s' % (e.code, e.read()[:120].decode('utf8', 'ignore'))
    except Exception as e: err = repr(e)[:200]
    t = time.time() - t0; u = usage or {}
    out_tok = u.get('completion_tokens') or 0
    return dict(phase=phase, k=k, t0=t0, want_in=n_in, want_out=n_out, think=think, prompt_tokens=u.get('prompt_tokens'),
                cached=(u.get('prompt_tokens_details') or {}).get('cached_tokens'), out=out_tok, ttft=first_any, ttft_content=first_content,
                e2e=t, tps=(out_tok - 1) / (t - first_any) if first_any and out_tok > 1 and t > first_any else None, err=err)
def run_phase(name):
    p = PH[name]; conc = A.concurrency or p['concurrency']; S = list(p['samples']); random.Random('%d-%s' % (A.seed, name)).shuffle(S); nxt = [0]; res = []
    t_start = time.time(); t_meas = t_start + A.warmup; t_end = t_meas + A.seconds
    def worker():
        while time.time() < t_end:
            with LOCK: k = nxt[0]; nxt[0] += 1
            r = one(name, k, S[k % len(S)]); r['measured'] = r['t0'] >= t_meas and r['t0'] + r['e2e'] <= t_end + 600
            with LOCK: res.append(r)
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(conc)]
    for t in ts: t.start()
    for t in ts: t.join()
    return conc, res
def q(xs, f):
    xs = sorted(x for x in xs if x is not None); return round(xs[int(f * (len(xs) - 1))], 3) if xs else None
os.makedirs(A.out, exist_ok=True); summary = {'url': A.url, 'model': A.model, 'salt': SALT, 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phases': []}
for name in A.phases.split(','):
    conc, res = run_phase(name); m = [r for r in res if r['measured']]; ok = [r for r in m if not r['err']]
    win = A.seconds
    s = dict(phase=name, description=PH[name]['description'], concurrency=conc, requests=len(m), errors=len(m) - len(ok),
             rate_per_s=round(len(m) / win, 2), original_rate_per_s=PH[name]['observed_rate_per_s'],
             ttft_p50=q([r['ttft'] for r in ok], .5), ttft_p90=q([r['ttft'] for r in ok], .9), ttft_p99=q([r['ttft'] for r in ok], .99),
             ttft_content_p50=q([r['ttft_content'] for r in ok], .5), e2e_p50=q([r['e2e'] for r in ok], .5), e2e_p90=q([r['e2e'] for r in ok], .9),
             per_request_tok_s_p50=q([r['tps'] for r in ok], .5), output_tok_s=round(sum(r['out'] for r in ok) / win, 1),
             prompt_tokens_p50=q([r['prompt_tokens'] for r in ok], .5), cache_hit=round(sum(r['cached'] or 0 for r in ok) / max(1, sum(r['prompt_tokens'] or 0 for r in ok)), 3),
             error_samples=list({r['err'] for r in m if r['err']})[:3])
    summary['phases'].append(s)
    with open(os.path.join(A.out, 'requests_%s.jsonl' % name), 'w') as f:
        for r in res: f.write(json.dumps(r) + '\n')
    print(json.dumps(s), flush=True)
    json.dump(summary, open(os.path.join(A.out, 'summary.json'), 'w'), indent=1)
print('| Phase | Concurrency | Requests | Errors | TTFT p50 / p90 / p99 (s) | E2E p50 (s) | Per-request tok/s | Cache hit |')
print('|---|---:|---:|---:|---|---:|---:|---:|')
for s in summary['phases']:
    print('| %s | %d | %d | %d | %s / %s / %s | %s | %s | %.0f%% |' % (s['phase'], s['concurrency'], s['requests'], s['errors'], s['ttft_p50'], s['ttft_p90'], s['ttft_p99'], s['e2e_p50'], s['per_request_tok_s_p50'], 100 * s['cache_hit']))
