#!/usr/bin/env bash
# Download the two public datasets the quality tests need into $DATA_DIR (default: current directory).
set -euo pipefail
D=${DATA_DIR:-.}; mkdir -p "$D"
curl -fsSL -o "$D/test.jsonl" https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl
curl -fsSL -o "$D/HumanEval.jsonl.gz" https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz
gunzip -f "$D/HumanEval.jsonl.gz"
wc -l "$D/test.jsonl" "$D/HumanEval.jsonl"   # expect 1319 and 164
