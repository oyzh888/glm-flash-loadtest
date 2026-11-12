# Quality tests: does the optimized backend give the same answers as the official one?

The speed test in this repo ([`agent/`](../agent), `run_agent_c64.sh`) measures how fast. These scripts measure whether the answers are as good. They produced the quality half of
<https://reports.aitist.ai/zhongtian/glm-flash-fast-and-correct/>. Every test has an answer that a program can check, and both backends get byte-identical requests at temperature 0.

**One command, from the repository root:** `bash run_quality.sh` runs everything below on both backends and prints one table (≈ 45 min; `QUICK=1` for a ≈ 10 min version with GSM8K and long-context retrieval only). The rest of this page explains each test and how to run it alone.

Needs Python ≥ 3.9 and nothing else (standard library only). Defaults point at `https://glm-flash.aitist.ai`; pin a backend with the model name `glm-zt` (optimized) or `glm-official` (unmodified official SGLang). To use another OpenAI-compatible endpoint set `URL=https://host` (and use its own model names). Please use one test at a time, and stream (the scripts already do).

```bash
cd quality
./fetch_data.sh                                   # GSM8K test set + HumanEval into $DATA_DIR (default .)
for M in glm-zt glm-official; do
  python3 gsm8k_ab.py $M gsm8k_$M.jsonl           # 1) GSM8K, all 1,319 questions            ~1 min
  python3 humaneval.py $M humaneval_$M.jsonl      # 2) HumanEval, 164 problems, tests executed  ~4 min
  python3 quality_suite.py $M out_$M 8            # 3) tool calls, long output, GSM8K with thinking  ~15 min
  python3 longctx_suite.py --model $M --conc 1  --sizes 150,300,600,1200,2000,3000,4500 --per 4 --seed 9001 --out lc1_$M.jsonl   # 4) long context, serial
  python3 longctx_suite.py --model $M --conc 16 --sizes 150,300,600,1200,2000,3000      --per 10 --seed 4242 --out lc16_$M.jsonl # 5) long context, 16 concurrent
done
python3 parity.py parity.json                     # 6) same prompt-token count on 6 request shapes
```

| Script | What it checks | How it is graded |
|---|---|---|
| `gsm8k_ab.py` | Grade-school math, thinking off, concurrency via `GSM_CONC` (default 32) | last number after `####` equals the gold answer |
| `humaneval.py` | Code generation | the generated function is run against the official HumanEval unit tests in a sandboxed subprocess (`python -I`, memory and time limits); pass@1 |
| `quality_suite.py` | (a) **tool calls**: 120 prompts over 4 tool schemas; (b) **long output**: "integers 1..N one per line", N = 300–1000; (c) **GSM8K with thinking on**, first 300 | (a) exactly one call, right function name, arguments JSON equal to the expected object; (b) line-by-line equality; (c) as above |
| `longctx_suite.py` | **Long-context retrieval**: a fresh random document per question (never cached), 150–4,500 lines ≈ 2.8K–90K tokens, "what is the code on Line k?" | exact match on the 4-digit code |
| `parity.py` | The server renders the same prompt to the same number of tokens on both backends (chat, thinking on, multi-turn, tool call, tool result, ~27K-token context) | prompt-token counts equal; outputs compared |

`longctx_suite.py` is the one to run on **every new server configuration**. A configuration of the optimized build that passed GSM8K and short canary checks returned wrong answers for every uncached prompt above ~10K tokens; only this test caught it.

## Results the report was built from (2026-11-12, public endpoint, temperature 0)

| Dimension | Optimized | Official |
|---|---|---|
| GSM8K 1,319 q, two runs | 96.4% / 95.8% | 95.8% / 95.8% |
| GSM8K with thinking, first 300 | 295 | 295 |
| HumanEval pass@1 (164) | 155 | 154 |
| Tool calls (120) | 120 | 120 |
| Long output (24) | 24 | 24 |
| Long context, serial (28) | 28 | 28 |
| Long context, 16 concurrent (60) | 58 | 57 |

Final-answer agreement on GSM8K between the two backends is 98.7%, the same level as the official backend against its own rerun (99.1%). Text is **not** byte-identical at temperature 0 under concurrent load (batching changes floating-point summation order), so compare final answers and accuracy, not text.

Notes: the scripts send `User-Agent: zt-gsm8k-consistency/1.0` and `x-dynamo-meta-policy-class: batch` (marks the traffic as batch/evaluation on our gateway; harmless elsewhere). Raw per-request outputs from the report run are published with the report under its `data/` folder.
