#!/usr/bin/env python3
"""summarize_all.py <cache dir> <baseline model> <candidate model>: one Markdown summary of run_all.sh results.
For each test it takes the newest finished result per model and prints the candidate next to the baseline with ratios."""
import json, os, sys, glob
cache, models = sys.argv[1], sys.argv[2:]
base, cand = (models + [None, None])[:2]
def newest(test, m):
    ds = [d for d in glob.glob(os.path.join(cache, test, m, '*')) if os.path.exists(os.path.join(d, 'DONE'))]
    return max(ds, key=lambda d: os.path.getmtime(os.path.join(d, 'DONE'))) if ds else None
def done(d): return json.load(open(os.path.join(d, 'DONE')))
def r(x, y, inv=False):
    if not x or not y: return ''
    v = (x / y) if not inv else (y / x)
    return ' (%.2f×)' % v
f = lambda v, n=0: ('{:,.%df}' % n).format(v) if isinstance(v, (int, float)) else '—'
out = ['# Benchmark summary: %s vs %s' % (cand, base), '']
for m in models:
    for t in ('agent', 'mix', 'phases', 'quality'):
        d = newest(t, m)
        if d: out.append('- `%s` / `%s`: server config `%s`, finished %s' % (t, m, done(d)['config_sha'], done(d)['finished']))
out.append('')
# agent (run.py summary)
db, dc = newest('agent', base), newest('agent', cand)
if db and dc:
    B = {l['concurrency']: l for l in json.load(open(os.path.join(db, 'summary.json')))['levels']}
    Cc = {l['concurrency']: l for l in json.load(open(os.path.join(dc, 'summary.json')))['levels']}
    out += ['## Coding-agent corpus (run.py)', '', '| In flight | Output tok/s %s → %s | TTFT p50 (ms) | TPOT p50 (ms) | E2E p50 (s) | Failed |' % (base, cand), '|---:|---|---|---|---|---|']
    for c in sorted(set(B) & set(Cc)):
        b, x = B[c], Cc[c]
        out.append('| %d | %s → **%s**%s | %s → %s | %s → %s | %.2f → %.2f | %d / %d |' % (c, f(b['output_tokens_per_s']), f(x['output_tokens_per_s']), r(x['output_tokens_per_s'], b['output_tokens_per_s']),
                   f(b['ttft_ms']['p50']), f(x['ttft_ms']['p50']), f(b['tpot_ms']['p50'], 1), f(x['tpot_ms']['p50'], 1), b['e2e_ms']['p50'] / 1000, x['e2e_ms']['p50'] / 1000, b['failed'], x['failed']))
    out.append('')
for t, title in (('mix', "Customer request mix (replay.py --mix)"), ('phases', "Customer phases at their own concurrency (replay.py)")):
    db, dc = newest(t, base), newest(t, cand)
    if not (db and dc): continue
    B = {(s['label'], s['concurrency']): s for s in json.load(open(os.path.join(db, 'summary.json')))['runs']}
    Cc = {(s['label'], s['concurrency']): s for s in json.load(open(os.path.join(dc, 'summary.json')))['runs']}
    out += ['## ' + title, '', '| Run | In flight | Output tok/s %s → %s | TTFT p50 / p99 (s) | TPOT p50 (ms) | E2E p50 (s) | Errors | Exact output |' % (base, cand), '|---|---:|---|---|---|---|---|---|']
    for k in sorted(set(B) & set(Cc), key=lambda k: (k[0], k[1])):
        b, x = B[k], Cc[k]
        out.append('| %s | %d | %s → **%s**%s | %s / %s → %s / %s | %s → %s | %s → %s%s | %d / %d | %.0f%% / %.0f%% |' % (k[0], k[1], f(b['output_tok_s']), f(x['output_tok_s']), r(x['output_tok_s'], b['output_tok_s']),
                   b['ttft_p50'], b['ttft_p99'], x['ttft_p50'], x['ttft_p99'], b['tpot_p50_ms'], x['tpot_p50_ms'], b['e2e_p50'], x['e2e_p50'], r(x['e2e_p50'], b['e2e_p50'], inv=True),
                   b['errors'], x['errors'], 100 * b['exact_output_frac'], 100 * x['exact_output_frac']))
    out.append('')
db, dc = newest('quality', base), newest('quality', cand)
if db and dc:
    import subprocess
    tmp = os.path.join(cache, 'quality', '_combined'); os.makedirs(tmp, exist_ok=True)
    for m, d in ((base, db), (cand, dc)):
        link = os.path.join(tmp, m)
        if os.path.islink(link): os.unlink(link)
        os.symlink(os.path.join(d, m), link)
    q = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quality', 'summarize_quality.py'), tmp, base, cand], capture_output=True, text=True).stdout
    out += ['## Quality (same requests to both, temperature 0)', '', q]
print('\n'.join(out))
