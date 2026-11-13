# Replay a real traffic shape: the TTFT-focused test

`replay.py` re-creates the *shape* of a real test run against the endpoint: request sizes, output lengths, thinking
on/off, prompt reuse and concurrency. It does not contain or need anyone's prompts. Use it to measure what a
TTFT-sensitive evaluation sees, and to compare two endpoints or two configurations under exactly that shape.

```bash
pip install aiohttp                       # not needed by replay.py itself (stdlib only), only by the other tests
export BENCH_OWNER="your-team"            # who is testing (shown to others while you hold the test lock)
python3 bench_lock.py run --purpose "replay A-F" -- \
  python3 replay/replay.py --profile replay/profile_2026-11-13.json --model glm-zt --phases A,B,C,D,E,F --seconds 180 --out replay-results/glm-zt
```

## The profile: six phases

`profile_2026-11-13.json` was derived from a test run seen at our gateway on 13 Nov 2026 (08:20–12:00 MYT). It keeps
only sizes, never content: one `[input_tokens, output_tokens, thinking]` triple per request, in arrival order.

| Phase | Concurrency | What each request looks like | What it measures |
|---|---:|---|---|
| A | 128 | ~100-token prompt, thinking on, output p50 ~280 tokens (p90 ~1,600) | throughput and queueing under heavy load |
| B | 4 | a few fixed prompts of ~5K / ~14.5K tokens, each repeated, ~16-token outputs, thinking on | TTFT with a warm prefix cache |
| C | 1 | 16-token prompt, 2–3 output tokens | minimum latency (network + server) |
| D | 2 | one ~31.6K-token prompt repeated, ~700-token outputs | long prompt, cached, then decoding |
| E | 8 | ~3.4K-token prompts, ~15-token outputs, ~13 requests/s | TTFT at a high request rate |
| F | 4 | 44K–148K-token prompts, ~90-token outputs | long-context TTFT |

Every request is sent with the sample's input length (synthetic text), `enable_thinking` as recorded, and
`max_tokens` = recorded output length with `ignore_eos`, so both sides do the same amount of work. Prompts in B, D, E and
F share a long common prefix (as the original traffic did: 97–100% of their prompt tokens were served from the prefix
cache); A and C send fresh prompts. A random per-run salt keeps one run from reusing another run's cache.

Options: `--phases A,C` (subset), `--seconds` per phase (after `--warmup`), `--concurrency N` (override every phase),
`--url` / `--model` for other endpoints. One IP address may keep at most 64 requests in flight unless it holds the
test lock, so phase A at 128 needs `bench_lock.py`.

## Output

`replay-results/<name>/summary.json` and one `requests_<phase>.jsonl` per phase. The table printed at the end:

| Column | Meaning |
|---|---|
| TTFT p50 / p90 / p99 | time to the first streamed token of any kind (reasoning or answer), measured at the client |
| E2E p50 | whole request |
| Per-request tok/s | output tokens after the first one ÷ time after the first token |
| Cache hit | prompt tokens the server reported as cached ÷ all prompt tokens |

TTFT measured from your client includes your network path to the endpoint. To see the server's own share, run the same
phases on the server node (`--url http://127.0.0.1:30000 --model zai-org/GLM-5.3-Flash`) if you have access.
