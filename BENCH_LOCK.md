# The test lock: one benchmark at a time

`https://glm-flash.aitist.ai` serves one benchmark at a time, so that numbers from two testers never contaminate each other.

| Endpoint | What it does |
|---|---|
| `POST /api/bench/lock` `{"owner": "...", "purpose": "...", "duration_s": 3600}` | take the lock → `{"lease": "...", ...}`; `409` with the holder and expiry if someone else has it |
| `POST /api/bench/renew` `{"lease": "..."}` | keep it alive (any request carrying the lease also counts) |
| `POST /api/bench/release` `{"lease": "..."}` | give it back |
| `GET /api/bench/status` | who holds it, until when, and the last 20 leases |

- Send the lease on every request as `Authorization: Bearer <lease>` or `X-Bench-Lease: <lease>`.
- While a lease is held, other requests get HTTP 429 with `Retry-After` and the holder's name and expected end.
- Without a lease, one address may keep up to 4 requests in flight (casual use). More than that counts as a benchmark and needs the lock. The holder may use up to 128 in flight from a single address.
- A lease is released automatically after 10 minutes without traffic or renewal, and after 2 hours at the latest.

You normally never call these yourself: `run_agent_c64.sh`, `run_quality.sh` and `bench_lock.py run -- <command>` take the
lock (waiting in line if needed), renew it, pass it on as `$BENCH_LEASE`, and release it when the command exits.
Set `BENCH_OWNER` to say who you are. `NO_BENCH_LOCK=1` skips the lock (for endpoints without one).

Requests sent under a lease are recorded in full at the gateway so a benchmark can be replayed exactly; see [TESTING.md §5](TESTING.md#5-what-we-record-and-why). Step-by-step examples (curl, OpenAI SDK, our scripts): [TESTING.md](TESTING.md).
