#!/usr/bin/env bash
# run_quality.sh: the answer-quality tests behind https://reports.aitist.ai/zhongtian/glm-flash-fast-and-correct/
#   bash run_quality.sh                                   # both backends of https://glm-flash.aitist.ai, ~45 min, one table at the end
#   URL=https://<endpoint> MODELS="<model-a> <model-b>" bash run_quality.sh
#   QUICK=1 bash run_quality.sh                           # ~10 min: GSM8K + long-context retrieval only
# Needs Python >= 3.9 and nothing else (standard library). Writes quality-results/<model>/ and quality-results/table.md.
set -euo pipefail
if [ -z "${BENCH_LEASE:-}" ] && [ -z "${NO_BENCH_LOCK:-}" ]; then   # take the endpoint's test lock for the whole run (see bench_lock.py)
  exec python3 "$(cd "$(dirname "$0")" && pwd)/bench_lock.py" run --url "${URL:-https://glm-flash.aitist.ai}" --owner "${BENCH_OWNER:-${USER:-anonymous}}" --purpose "${BENCH_PURPOSE:-run_quality.sh}" -- bash "$0" "$@"
fi
HERE=$(cd "$(dirname "$0")" && pwd); Q=$HERE/quality
export URL=${URL:-https://glm-flash.aitist.ai}
MODELS=${MODELS:-"glm-official glm-zt"}      # glm-zt = optimized build, glm-official = unmodified official SGLang
OUT=${OUT:-$PWD/quality-results}; export DATA_DIR=${DATA_DIR:-$OUT/data}
mkdir -p "$OUT" "$DATA_DIR"
[ -s "$DATA_DIR/test.jsonl" ] && [ -s "$DATA_DIR/HumanEval.jsonl" ] || DATA_DIR=$DATA_DIR bash "$Q/fetch_data.sh"
cd "$Q"
for M in $MODELS; do
  O=$OUT/$M; mkdir -p "$O"; echo "== $M @ $URL"
  for r in 1 2; do python3 gsm8k_ab.py "$M" "$O/gsm8k_run$r.jsonl"; [ -n "${QUICK:-}" ] && break; done
  if [ -z "${QUICK:-}" ]; then
    python3 humaneval.py "$M" "$O/humaneval.jsonl"
    python3 quality_suite.py "$M" "$O" 8
  fi
  python3 longctx_suite.py --model "$M" --conc 1  --sizes 150,300,600,1200,2000,3000,4500 --per 4  --seed 9001 --out "$O/longctx_c1.jsonl"  | tee "$O/longctx_c1.txt"
  python3 longctx_suite.py --model "$M" --conc 16 --sizes 150,300,600,1200,2000,3000      --per 10 --seed 4242 --out "$O/longctx_c16.jsonl" | tee "$O/longctx_c16.txt"
done
python3 "$Q/summarize_quality.py" "$OUT" $MODELS | tee "$OUT/table.md"
