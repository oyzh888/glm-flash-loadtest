#!/usr/bin/env bash
# compare_external.sh: the same customer-shaped requests sent to two OpenAI-compatible endpoints, back to back per shape.
# Reproduces the 11-14 and 11-16 "ours vs ILMU" comparisons (https://reports.aitist.ai/zhongtian/).
#
#   A_URL=https://api.ilmu.ai       A_MODEL=glm-5.3-flash-ryt A_KEY_ENV=ILMU_API_KEY \
#   B_URL=https://glm-flash.aitist.ai B_MODEL=glm-zt \
#   bash compare_external.sh results-compare
#
# Keys are read from the environment variable NAMED in A_KEY_ENV / B_KEY_ENV (values are never printed).
# If an endpoint is https://glm-flash.aitist.ai, its runs go through bench_lock.py (the test lock; >4 in flight needs it).
# Shapes (from replay/profile_2026-11-13.json, the customer's 11-13 gateway traffic, sizes only):
#   C 16-token ping c1 | B 14.5K cached prompt, short output c1 | E 3.4K prompts c2 | D 31.6K prompt + ~700-token output c1
#   F 44K-120K long context c1 (45 s) | A ~100-token prompts, long outputs c4 and c16 | customer mix c1
# Every run: fixed salt + seed (identical bytes on both endpoints), thinking on, output length fixed with ignore_eos,
# 10 s warm-up + 60 s measured, prompts capped at 120K tokens, client-side cap of 3M prompt tokens/min (stay below provider limits).
set -uo pipefail
OUT=${1:-results-compare}; HERE=$(cd "$(dirname "$0")" && pwd); mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
SHAPES=${SHAPES:-"B-1 C-1 D-1 E-2 F-1 A-4 A-16 MIX-1"}
run_one(){ # side shape
  local side=$1 sh=$2 url model keyenv ph c secs
  eval url=\${${side}_URL} model=\${${side}_MODEL} keyenv=\${${side}_KEY_ENV:-}
  ph=${sh%-*}; c=${sh#*-}; secs=60; [ "$ph" = F ] && secs=45
  local args=(--profile profile_2026-11-13.json --warmup 10 --max-input 120000 --tpm-limit 3000000 --seed 7 --url "$url" --model "$model" --salt "cmp-$ph-$c" --out "$OUT/$side-$sh")
  [ -n "$keyenv" ] && args+=(--api-key-env "$keyenv")
  if [ "$ph" = MIX ]; then args+=(--mix --levels 1 --seconds 60); else args+=(--phases "$ph" --concurrency "$c" --seconds "$secs"); fi
  local cmd=(python3 replay.py "${args[@]}")
  case "$url" in https://glm-flash.aitist.ai*) [ -z "$keyenv" ] && cmd=(python3 "$HERE/bench_lock.py" run --url "$url" --owner "${BENCH_OWNER:-${USER:-anonymous}}" --purpose "compare_external.sh $sh" -- "${cmd[@]}");; esac
  (cd "$HERE/replay" && "${cmd[@]}" > "$OUT/$side-$sh.log" 2>&1); echo "[$(date -u +%T)] $side $sh exit $?"
}
for sh in $SHAPES; do run_one A "$sh"; run_one B "$sh"; done
python3 - "$OUT" <<'PY'
import json, glob, os, sys
out = sys.argv[1]
print('| shape | side | requests | errors | TTFT p50 (s) | TPOT p50 (ms) | E2E p50 (s) | output tok/s |')
print('|---|---|---|---|---|---|---|---|')
for d in sorted(glob.glob(out + '/*/summary.json')):
    r = json.load(open(d))['runs'][0]; side, sh = os.path.basename(os.path.dirname(d)).split('-', 1)
    print(f"| {sh} | {side} | {r['requests']} | {r['errors']} | {r['ttft_p50']:.2f} | {r['tpot_p50_ms']:.1f} | {r['e2e_p50']:.2f} | {r['output_tok_s']:.0f} |")
PY
