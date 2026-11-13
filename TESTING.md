# How to test https://glm-flash.aitist.ai fairly

The endpoint serves **one benchmark at a time**. Take the test lock before a load test, send the lease with every
request, release it when you are done. While you hold it nobody else's traffic reaches the servers, so your numbers
are not mixed with anyone else's, and ours are not mixed with yours.

## Checklist for your official test

1. **Take the test lock** (`POST /api/bench/lock`, section 1). Without it, more than 4 parallel requests from one address are rejected with HTTP 429.
2. **Use the lease as your API key**: base URL `https://glm-flash.aitist.ai/v1`, API key = lease, model `glm-zt` (optimized) or `glm-official` (unmodified official SGLang). Any OpenAI-compatible client or benchmark tool works (section 2).
3. **Stream** (`"stream": true`).
4. **Thinking is on by default.** Reasoning arrives in `delta.reasoning_content`, the answer in `delta.content`. With a small `max_tokens` the whole budget can go to reasoning and `content` stays empty. To test without thinking send `"chat_template_kwargs": {"enable_thinking": false}` (OpenAI SDK: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`).
5. **Keep concurrency at or below 64** for now (above 64, requests queue on the server; we will announce when 128 is supported).
6. **Client timeout ≥ 600 s**: with thinking on, a single long answer can take several minutes.
7. **Release the lock when done** (`POST /api/bench/release`); it also expires 10 minutes after your last request. `GET /api/bench/status` shows who is testing.

The gateway runs in Singapore next to the GPUs: from Southeast Asia a cached prompt reaches its first token in about 0.1–0.15 s.

## 1. Quick start with curl

```bash
BASE=https://glm-flash.aitist.ai

# take the lock (409 + holder + expected end if someone else is testing; try again later)
LEASE=$(curl -s -X POST $BASE/api/bench/lock -H 'Content-Type: application/json' \
  -d '{"owner": "your-team", "purpose": "TTFT test", "duration_s": 3600}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["lease"])')

# every request carries the lease (OpenAI or Anthropic format)
curl -sN $BASE/v1/chat/completions -H "Authorization: Bearer $LEASE" -H 'Content-Type: application/json' \
  -d '{"model": "glm-zt", "stream": true, "max_tokens": 64, "chat_template_kwargs": {"enable_thinking": false}, "messages": [{"role": "user", "content": "Hello"}]}'

# done: give it back (otherwise it expires 10 minutes after your last request)
curl -s -X POST $BASE/api/bench/release -H 'Content-Type: application/json' -d "{\"lease\": \"$LEASE\"}"

# who is testing right now, until when, and the last 20 tests
curl -s $BASE/api/bench/status
```

## 2. With any OpenAI-compatible client

Use the lease as the API key: base URL `https://glm-flash.aitist.ai/v1`, API key `<lease>`, model `glm-zt`
(optimized) or `glm-official` (unmodified official SGLang, for comparison). For example:

```python
from openai import OpenAI
client = OpenAI(base_url="https://glm-flash.aitist.ai/v1", api_key=LEASE)
stream = client.chat.completions.create(model="glm-zt", stream=True, max_tokens=64,
                                        messages=[{"role": "user", "content": "Hello"}],
                                        extra_body={"chat_template_kwargs": {"enable_thinking": False}})  # thinking is on by default
```

Most load-test tools accept an API key or extra headers, so this works without code changes: vLLM `benchmark_serving`,
`evalscope perf`, `llmperf`, `genai-perf`, Claude Code / OpenCode (Anthropic endpoint at the same base URL).

## 3. Or let our scripts do it

`bench_lock.py run -- <your command>` takes the lock (waits in line if someone else holds it), exports the lease as
`$BENCH_LEASE`, renews it while your command runs and releases it at the end, also on Ctrl-C:

```bash
git clone https://github.com/oyzh888/glm-flash-loadtest && cd glm-flash-loadtest
export BENCH_OWNER="your-team"
python3 bench_lock.py run --purpose "my benchmark" -- python3 my_benchmark.py      # your own tool, reading $BENCH_LEASE
bash run_agent_c64.sh        # our coding-agent speed test (takes the lock itself)
bash run_quality.sh          # our quality tests (takes the lock itself)
python3 bench_lock.py run --purpose "TTFT replay" -- \
  python3 replay/replay.py --profile replay/profile_2026-11-13.json --model glm-zt --phases A,B,C,D,E,F --seconds 180
```

`replay/` re-creates the shape of a TTFT-focused test (six phases from ~16-token pings to 148K-token prompts); see
[`replay/README.md`](replay/README.md).

## 3b. The full benchmark in one command: `run_all.sh`

```bash
export BENCH_OWNER="your-team"
bash run_all.sh                       # glm-official vs glm-zt: agent + mix + phases + quality, then one summary table
TESTS="mix phases" bash run_all.sh    # a subset
```

| Test | What it measures |
|---|---|
| `agent` | coding-agent corpus (120 sessions, ~19K-token prompts), closed loop at 1 / 16 / 64 in flight (`AGENT_CONC`) |
| `mix` | the real request mix of a TTFT-focused evaluation (six request shapes, weighted by how often each occurred), closed loop at 1 / 4 / 8 / 16 / 32 / 64 (`MIX_LEVELS`) |
| `phases` | each of those six request shapes at its own concurrency (TTFT p50 / p99 per shape) |
| `quality` | GSM8K ×2, GSM8K with thinking, HumanEval (unit tests executed), tool calls, long output, long-context retrieval |

All tests send identical requests to both backends, at most 64 in flight, and check that every response has exactly the
requested length. The whole run holds the test lock.

**Results cache.** `GET /api/backends` publishes each backend's server-configuration fingerprint (`config_sha` plus the
settings that affect speed or answers). A result is reused when the test, its arguments, the scripts, the corpus /
profile and that fingerprint are all unchanged, so re-running `run_all.sh` after a server change only measures what
changed (`FORCE=1` re-measures everything). Results are in `results-cache/<test>/<model>/<key>/`, the table in
`results-cache/summary.md`.

## 4. Rules

| Rule | Value |
|---|---|
| Requests in flight without a lease | up to 4 per client address (casual use) — more needs the lock |
| Requests in flight with the lease | **please stay at or below 64 for now** (128 is technically allowed, but above 64 requests queue on the server and some fail; we will announce when 128 is supported) |
| Lease expiry | 10 minutes after your last request or renewal; 2 hours at the latest |
| Requests from others while you hold it | rejected with HTTP 429 and `Retry-After`, with your owner name and expected end |
| Long requests | use streaming; Cloudflare closes non-streaming responses that send nothing for ~100 s. With thinking on, single requests can run several minutes: set client timeouts to ≥ 600 s |
| Thinking | **on by default**. The reasoning streams in `delta.reasoning_content`, the answer in `delta.content`; with a small `max_tokens` the whole budget can go to reasoning and `content` stays empty. To turn it off send `"chat_template_kwargs": {"enable_thinking": false}` (OpenAI SDK: `extra_body={...}`) |

## 5. What we record, and why

- **Every request**: arrival time, client address, user agent, model, parameters (max_tokens, temperature, thinking on/off,
  number of messages and tools), sizes, prompt fingerprints (hashes that show prompt reuse, not text), token counts and a
  timing breakdown (time to reach the server, time to first token, total). No content.
- **Requests sent under your lease**: additionally the full request body, so that a benchmark can be replayed exactly
  (`replay/replay_capture.py`) when we investigate a result together. Kept on our gateway only, never published. If you do
  not want this, tell us before testing and use synthetic prompts.
- **On the GPU servers**: per-request queue time, compute time, cached vs new prompt tokens, sampling parameters. No content.

## 6. Reading TTFT correctly

TTFT measured at your client = your network path to the endpoint + gateway + server queueing + prefill. Since
13 Nov 2026 the gateway runs next to the GPUs in Singapore (Cloudflare's Singapore edge), so from Southeast Asia a
cached prompt reaches its first token in about 0.1–0.15 s (measured from Singapore), and from Europe in about 0.4–0.7 s.
When you compare providers, compare from the same client location, with the same prompts, thinking setting and
streaming mode.
