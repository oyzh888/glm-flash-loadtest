#!/usr/bin/env python3
"""replay.py: replay a traffic profile (sizes only) against an OpenAI-compatible endpoint; report TTFT / TPOT / E2E.

  # each phase of the customer's test at its own concurrency
  python3 replay/replay.py --profile replay/profile_2026-11-13.json --model glm-zt --phases A,B,C,D,E,F --out replay-results/phases
  # the customer's request mix (phases weighted by how many requests each had) at a concurrency ladder
  python3 replay/replay.py --profile replay/profile_2026-11-13.json --model glm-zt --mix --levels 1,4,8,16,32,64 --out replay-results/mix

Closed loop: exactly N requests in flight. Every request has the sample's input length (synthetic text), thinking on/off
and output length (max_tokens = recorded output, ignore_eos, so both sides do the same work). Prompt reuse follows the
original cache behaviour: phases A and C send a new prompt every time; B, D, E and F build prompts as prefixes of one
shared document plus a short unique tail. A per-run salt keeps runs from reusing each other's cache. Samples are drawn in a
fixed random order (--seed), so a short run follows the overall size distribution. Phase A is capped at 64 in flight.
Standard library only (Python >= 3.6). $BENCH_LEASE, if set, is sent as the test-lock lease.
"""
import argparse, json, os, random, sys, threading, time, urllib.error, urllib.request, uuid, hashlib
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--profile', required=True); ap.add_argument('--url', default=os.environ.get('URL', 'https://glm-flash.aitist.ai'))
ap.add_argument('--model', default='glm-zt'); ap.add_argument('--phases', default='A,B,C,D,E,F')
ap.add_argument('--mix', action='store_true', help='pool all phases, weighted by their observed request counts')
ap.add_argument('--levels', default='', help='concurrency ladder, e.g. 1,4,8,16,32,64 (default: each phase\'s own concurrency)')
ap.add_argument('--seconds', type=float, default=120); ap.add_argument('--warmup', type=float, default=20)
ap.add_argument('--concurrency', type=int, default=0, help='override every phase\'s concurrency (0 = profile value)')
ap.add_argument('--max-concurrency', type=int, default=64); ap.add_argument('--temperature', type=float, default=0.6)
ap.add_argument('--seed', type=int, default=1); ap.add_argument('--out', default='replay-results/run')
ap.add_argument('--resummarize', default=None, help='recompute summary.json of an existing result directory from its requests_*.jsonl (no requests sent)')
A = ap.parse_args()
PROF = json.load(open(A.profile)); PH = {p['name']: p for p in PROF['phases']}
H = {'Content-Type': 'application/json', 'User-Agent': 'glm-partner-replay/1.1'}
if os.environ.get('BENCH_LEASE'): H['Authorization'] = 'Bearer ' + os.environ['BENCH_LEASE']
SALT = uuid.uuid4().hex[:12]; TPL = 20.2; OVERHEAD = 12
W = ['alpha', 'beta', 'gamma', 'delta', 'omega', 'sigma', 'kappa', 'theta']
_docs = {}
def doc(phase, lines):
    key = (phase, max(lines, 8000))
    if key not in _docs:
        r = random.Random('%s-%s' % (SALT, phase))
        _docs[key] = ['Line %d: record %d filed under %s, code %d.' % (i, r.randint(0, 99999), r.choice(W), r.randint(1000, 9999)) for i in range(key[1])]
    return _docs[key][:lines]
def prompt(phase, n_tokens, k):
    if n_tokens < 60: return ' '.join(['ping'] * max(1, int(n_tokens - OVERHEAD)))
    lines = max(1, int((n_tokens - OVERHEAD - 25) / TPL))
    if phase == 'A':
        r = random.Random('%s-A-%d' % (SALT, k))
        body = ['Line %d: record %d filed under %s, code %d.' % (i, r.randint(0, 99999), r.choice(W), r.randint(1000, 9999)) for i in range(lines)]
    else: body = doc(phase, lines)
    return '\n'.join(body) + '\n\nQuestion %d: what is the code on line %d? Answer briefly.' % (k, (k * 7) % max(1, lines))
def one(k, sample):
    phase, n_in, n_out, think = sample
    body = dict(model=A.model, stream=True, stream_options={'include_usage': True}, temperature=A.temperature, top_p=0.95,
                max_tokens=int(n_out), ignore_eos=True, messages=[{'role': 'user', 'content': prompt(phase, n_in, k)}],
                chat_template_kwargs={'enable_thinking': bool(think)})
    t0 = time.time(); first = None; usage = None; err = None
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
                if (dl.get('reasoning_content') or dl.get('content')) and first is None: first = time.time() - t0
    except urllib.error.HTTPError as e: err = 'HTTP %d %s' % (e.code, e.read()[:120].decode('utf8', 'ignore'))
    except Exception as e: err = repr(e)[:200]
    t = time.time() - t0; u = usage or {}; out = u.get('completion_tokens') or 0
    return dict(phase=phase, k=k, t0=t0, want_in=n_in, want_out=n_out, think=think, prompt_tokens=u.get('prompt_tokens'),
                cached=(u.get('prompt_tokens_details') or {}).get('cached_tokens'), out=out, ttft=first, e2e=t,
                tpot=(t - first) / (out - 1) if first and out > 1 else None, err=err)
LOCK = threading.Lock()
def run(label, samples, conc):
    conc = min(conc, A.max_concurrency); nxt = [0]; res = []
    t_meas = time.time() + A.warmup; t_end = t_meas + A.seconds
    def worker():
        while time.time() < t_end:
            with LOCK: k = nxt[0]; nxt[0] += 1
            r = one(k, samples[k % len(samples)]); r['measured'] = r['t0'] >= t_meas
            with LOCK: res.append(r)
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(conc)]
    for t in ts: t.start()
    for t in ts: t.join()
    return conc, res, t_meas
def q(xs, f):
    xs = sorted(x for x in xs if x is not None); return round(xs[int(f * (len(xs) - 1))], 4) if xs else None
def tokens_in_window(res, t0w, t1w):
    """Output tokens generated inside [t0w, t1w]: each request's tokens are spread evenly over its decode interval
    (first token -> last token) and only the part inside the window counts. Counting every token of requests that merely
    *started* in the window would inflate throughput (a long request started near the end runs far past it), and more so
    for the slower side."""
    tot = 0.0
    for r in res:
        if r.get('err') or not r.get('ttft') or not r.get('out'): continue
        a, b = r['t0'] + r['ttft'], r['t0'] + r['e2e']
        if b <= a: tot += r['out'] if t0w <= b <= t1w else 0; continue
        tot += r['out'] * max(0.0, min(b, t1w) - max(a, t0w)) / (b - a)
    return tot
def summarize(label, conc, res, t_meas=None):
    if t_meas is None: t_meas = min(r['t0'] for r in res) + A.warmup
    m = [r for r in res if r['measured']]; ok = [r for r in m if not r['err']]
    return dict(label=label, concurrency=conc, requests=len(m), errors=len(m) - len(ok),
                ttft_p50=q([r['ttft'] for r in ok], .5), ttft_p90=q([r['ttft'] for r in ok], .9), ttft_p99=q([r['ttft'] for r in ok], .99),
                tpot_p50_ms=round(1000 * q([r['tpot'] for r in ok], .5), 2) if ok and q([r['tpot'] for r in ok], .5) else None,
                e2e_p50=q([r['e2e'] for r in ok], .5), e2e_p90=q([r['e2e'] for r in ok], .9),
                output_tok_s=round(tokens_in_window(res, t_meas, t_meas + A.seconds) / A.seconds, 1), requests_per_s=round(len([r for r in ok if t_meas <= r['t0'] + r['e2e'] <= t_meas + A.seconds]) / A.seconds, 2),
                exact_output_frac=round(sum(1 for r in ok if r['out'] == r['want_out']) / max(1, len(ok)), 3),
                prompt_tokens_p50=q([r['prompt_tokens'] for r in ok], .5),
                cache_hit=round(sum(r['cached'] or 0 for r in ok) / max(1, sum(r['prompt_tokens'] or 0 for r in ok)), 3),
                error_samples=sorted({r['err'] for r in m if r['err']})[:3])
def backend_config():
    try:
        for b in json.load(urllib.request.urlopen(urllib.request.Request(A.url.rstrip('/') + '/api/backends', headers={'User-Agent': 'glm-partner-replay/1.1'}), timeout=15)):
            if b['id'] == A.model or (b.get('config') or {}).get('served_model_name') == A.model: return {'config_sha': b.get('config_sha'), 'config': b.get('config')}
    except Exception: pass
    return {}
if A.resummarize:
    S = json.load(open(os.path.join(A.resummarize, 'summary.json'))); new = []
    for s0 in S['runs']:
        R = [json.loads(l) for l in open(os.path.join(A.resummarize, 'requests_%s_c%d.jsonl' % (s0['label'], s0['concurrency'])))]
        x = summarize(s0['label'], s0['concurrency'], R)
        if 'description' in s0: x['description'] = s0['description']
        new.append(x)
    S['runs'] = new; S['manifest']['resummarized_with'] = hashlib.sha256(open(__file__, 'rb').read()).hexdigest()
    json.dump(S, open(os.path.join(A.resummarize, 'summary.json'), 'w'), indent=1)
    for x in new: print(x['label'], x['concurrency'], x['output_tok_s'])
    sys.exit(0)
os.makedirs(A.out, exist_ok=True)
manifest = dict(url=A.url, model=A.model, started=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), salt=SALT, seed=A.seed,
                profile_sha256=hashlib.sha256(open(A.profile, 'rb').read()).hexdigest(), script_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(),
                argv=sys.argv[1:], **backend_config())
runs = []
if A.mix:
    pool = []
    for p in PROF['phases']:
        S = [[p['name']] + s for s in p['samples']]
        random.Random('%d-%s' % (A.seed, p['name'])).shuffle(S); pool += S
    random.Random('%d-mix' % A.seed).shuffle(pool)
    manifest['mix_weights'] = {p['name']: round(p['observed_requests'] / sum(x['observed_requests'] for x in PROF['phases']), 3) for p in PROF['phases']}
    for c in [int(x) for x in (A.levels or '1,4,8,16,32,64').split(',')]:
        conc, res, tm = run('mix', pool, c); runs.append(summarize('mix', conc, res, tm)); print(json.dumps(runs[-1]), flush=True)
        with open(os.path.join(A.out, 'requests_mix_c%d.jsonl' % conc), 'w') as f:
            for r in res: f.write(json.dumps(r) + '\n')
else:
    for name in A.phases.split(','):
        S = [[name] + s for s in PH[name]['samples']]; random.Random('%d-%s' % (A.seed, name)).shuffle(S)
        for c in ([int(x) for x in A.levels.split(',')] if A.levels else [A.concurrency or PH[name]['concurrency']]):
            conc, res, tm = run(name, S, c); runs.append(dict(summarize(name, conc, res, tm), description=PH[name]['description'])); print(json.dumps(runs[-1]), flush=True)
            with open(os.path.join(A.out, 'requests_%s_c%d.jsonl' % (name, conc)), 'w') as f:
                for r in res: f.write(json.dumps(r) + '\n')
json.dump(dict(manifest=manifest, runs=runs), open(os.path.join(A.out, 'summary.json'), 'w'), indent=1)
print('| Run | In flight | Requests | Errors | TTFT p50 / p90 / p99 (s) | TPOT p50 (ms) | E2E p50 (s) | Output tok/s | Exact output | Cache hit |')
print('|---|---:|---:|---:|---|---:|---:|---:|---:|---:|')
for s in runs:
    print('| %s | %d | %d | %d | %s / %s / %s | %s | %s | %s | %.0f%% | %.0f%% |' % (s['label'], s['concurrency'], s['requests'], s['errors'], s['ttft_p50'], s['ttft_p90'], s['ttft_p99'], s['tpot_p50_ms'], s['e2e_p50'], s['output_tok_s'], 100 * s['exact_output_frac'], 100 * s['cache_hit']))
