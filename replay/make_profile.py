#!/usr/bin/env python3
"""make_profile.py <gateway requests.jsonl> <out.json>: turn a gateway trace into a replay profile.

Keeps only sizes, never content: for each phase a list of (input_tokens, output_tokens, thinking) samples in arrival
order, plus the phase's concurrency. Identical input sizes inside a phase are treated as the same prompt (repeated
prompts are how a test exercises the prefix cache)."""
import json, sys, datetime as dt
src, out = sys.argv[1], sys.argv[2]
PH = [  # name, start UTC, end UTC, closed-loop concurrency seen on the server, description
    ('A', '00:20', '01:30', 128, 'high concurrency, ~100-token prompts, thinking on, long outputs'),
    ('B', '01:40', '02:00', 4,   'fixed 5K / 14.5K-token prompts repeated, ~16-token outputs, thinking on'),
    ('C', '02:00', '02:20', 1,   '16-token prompt, 2-3 token output (minimum latency)'),
    ('D', '02:40', '03:10', 2,   'one 31.6K-token prompt repeated, ~700-token outputs'),
    ('E', '03:20', '03:40', 8,   '~3.4K-token prompts, ~15-token outputs, ~13 requests/s'),
    ('F', '03:40', '04:00', 4,   'long context: 44K-148K-token prompts, ~90-token outputs'),
]
R = [json.loads(l) for l in open(src)]
R = [r for r in R if r.get('kind') == 'api' and not r.get('error') and r.get('in') and r.get('out')]
def ts(hm): h, m = map(int, hm.split(':')); return dt.datetime(2026, 11, 13, h, m, tzinfo=dt.timezone.utc).timestamp()
prof = {'source': 'gateway trace 2026-11-13 00:20-04:00 UTC (sizes only, no content)', 'phases': []}
for name, a, b, conc, desc in PH:
    x = sorted((r for r in R if ts(a) <= r['at'] < ts(b)), key=lambda r: r['at'])
    prof['phases'].append({'name': name, 'description': desc, 'concurrency': conc, 'observed_requests': len(x),
                           'observed_rate_per_s': round(len(x) / (ts(b) - ts(a)), 2),
                           'samples': [[r['in'], r['out'], 1 if r.get('think_tok') else 0] for r in x]})
json.dump(prof, open(out, 'w'))
for p in prof['phases']: print(p['name'], p['observed_requests'], 'samples, concurrency', p['concurrency'])
