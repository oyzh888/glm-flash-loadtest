#!/usr/bin/env bash
# run_all.sh: the full, fair benchmark of glm-zt vs glm-official in one command, with a results cache.
#
#   bash run_all.sh                         # everything that is not already cached, then one summary table
#   TESTS="mix phases" bash run_all.sh      # a subset: agent | mix | phases | quality
#   FORCE=1 bash run_all.sh                 # ignore the cache
#
# Tests (both backends, same requests, closed loop, at most 64 in flight):
#   agent    coding-agent corpus (120 sessions, ~19K-token prompts), run.py at AGENT_CONC (default 1,16,64), 60 s warm-up + 180 s
#   mix      the customer's request mix (replay/profile_2026-11-13.json, phases weighted by their request counts) at MIX_LEVELS
#   phases   each phase of the customer's test at its own concurrency (phase A capped at 64)
#   quality  GSM8K x2, GSM8K with thinking, HumanEval, tool calls, long output, long-context retrieval (run_quality.sh)
# Cache: a result is reused when the test, its arguments, the scripts, the corpus/profile and the backend's server-config
# fingerprint (config_sha from /api/backends) are all unchanged. Results: $CACHE/<test>/<model>/<key>/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -z "${BENCH_LEASE:-}" ] && [ -z "${NO_BENCH_LOCK:-}" ]; then
  exec python3 "$HERE/bench_lock.py" run --url "${URL:-https://glm-flash.aitist.ai}" --owner "${BENCH_OWNER:-${USER:-anonymous}}" --purpose "${BENCH_PURPOSE:-run_all.sh ${TESTS:-agent mix phases quality}}" -- bash "$0" "$@"
fi
export URL=${URL:-https://glm-flash.aitist.ai}
MODELS=${MODELS:-"glm-official glm-zt"}; TESTS=${TESTS:-"agent mix phases quality"}
AGENT_CONC=${AGENT_CONC:-1,16,64}; MIX_LEVELS=${MIX_LEVELS:-1,4,8,16,32,64}; MIX_SECONDS=${MIX_SECONDS:-120}; PHASE_SECONDS=${PHASE_SECONDS:-90}
CACHE=${CACHE:-$PWD/results-cache}; PROFILE=$HERE/replay/profile_2026-11-13.json
sha() { python3 -c 'import hashlib,sys; h=hashlib.sha256(); [h.update(open(f,"rb").read()) for f in sys.argv[1:]]; print(h.hexdigest()[:12])' "$@"; }
cfg_sha() { python3 - "$URL" "$1" <<'PY'
import json,sys,urllib.request
for b in json.load(urllib.request.urlopen(urllib.request.Request(sys.argv[1].rstrip('/')+'/api/backends',headers={'User-Agent':'run-all/1.0'}),timeout=15)):
    if b['id']==sys.argv[2]: print(b.get('config_sha') or 'unknown'); break
else: print('unknown')
PY
}
for M in $MODELS; do
  C=$(cfg_sha $M); echo "== $M  server config $C"
  for T in $TESTS; do
    case $T in
      agent)   KEY=$(echo "$T $AGENT_CONC $(sha "$HERE/agent/bench/run.py" "$HERE/agent/corpus/coding_v1.jsonl.gz") $C $URL" | sha256sum | cut -c1-12) ;;
      mix)     KEY=$(echo "$T $MIX_LEVELS $MIX_SECONDS $(sha "$HERE/replay/replay.py" "$PROFILE") $C $URL" | sha256sum | cut -c1-12) ;;
      phases)  KEY=$(echo "$T $PHASE_SECONDS $(sha "$HERE/replay/replay.py" "$PROFILE") $C $URL" | sha256sum | cut -c1-12) ;;
      quality) KEY=$(echo "$T $(sha "$HERE"/quality/*.py "$HERE/run_quality.sh") $C $URL" | sha256sum | cut -c1-12) ;;
      *) echo "unknown test $T"; exit 2 ;;
    esac
    D=$CACHE/$T/$M/$KEY
    if [ -s "$D/DONE" ] && [ -z "${FORCE:-}" ]; then echo "   $T: cached ($D)"; continue; fi
    rm -rf "$D"; mkdir -p "$D"; echo "   $T: running -> $D"; date -u +%FT%TZ > "$D/STARTED"
    case $T in
      agent)   python3 "$HERE/agent/bench/run.py" --url "$URL" --model "$M" --label "$M" --out "$D" --concurrency "$AGENT_CONC" --warmup 60 --duration 180 --api-key-env BENCH_LEASE > "$D/log.txt" 2>&1 ;;
      mix)     python3 "$HERE/replay/replay.py" --profile "$PROFILE" --url "$URL" --model "$M" --mix --levels "$MIX_LEVELS" --seconds "$MIX_SECONDS" --warmup 30 --out "$D" > "$D/log.txt" 2>&1 ;;
      phases)  python3 "$HERE/replay/replay.py" --profile "$PROFILE" --url "$URL" --model "$M" --phases A,B,C,D,E,F --seconds "$PHASE_SECONDS" --warmup 15 --out "$D" > "$D/log.txt" 2>&1 ;;
      quality) MODELS=$M OUT="$D" bash "$HERE/run_quality.sh" > "$D/log.txt" 2>&1 ;;
    esac
    echo "{\"test\": \"$T\", \"model\": \"$M\", \"config_sha\": \"$C\", \"key\": \"$KEY\", \"finished\": \"$(date -u +%FT%TZ)\"}" > "$D/DONE"
  done
done
python3 "$HERE/summarize_all.py" "$CACHE" ${SUMMARY_MODELS:-glm-official glm-zt} | tee "$CACHE/summary.md"
