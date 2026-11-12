# Results behind https://reports.aitist.ai/zhongtian/glm-flash-fast-and-correct/ (2026-11-12)

| Folder | Backend | Client | Levels (in flight) |
|---|---|---|---|
| `official-public` | unmodified official SGLang (`glm-official`) | public internet → HTTPS endpoint | 1 4 8 16 32 64, one run |
| `optimized-public` | optimized build (`glm-zt`), prefill chunks 8,192, 4 decode rounds between prefill batches | same | 1 4 8 16 32 64, each level its own invocation (`CONC=<n>`), merged into one `summary.json`; the server log showed no other traffic at any level |
| `official-node` | `glm-official` | on the server node, inside a container from the server image | 1 4 8 16 32 64 |
| `optimized-node` | `glm-zt` (same configuration as above) | on the server node | 1 4 8 16 32 64 |

Each folder: `summary.json` (manifest with script and corpus hashes, per-level metrics and integrity checks), `requests_c<N>.jsonl` (every request), `canaries_c<N>.jsonl`, `SHA256SUMS`. Hostnames and local paths in the metadata were replaced with placeholders.

```bash
python3 agent/bench/compare.py agent/results/2026-11-12-final/official-public agent/results/2026-11-12-final/optimized-public
python3 agent/bench/compare.py agent/results/2026-11-12-final/official-node   agent/results/2026-11-12-final/optimized-node
```
