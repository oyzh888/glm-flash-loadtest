# Superseded: optimized runs in this folder

The optimized runs here (`glm-zt`) were taken with prefill chunks of 16,384 tokens. In that configuration the fused MoE kernel returned wrong results, silently, whenever one forward pass carried more than 8,192 tokens, so uncached prompts of about 10K tokens or more were answered wrongly. The load test checks lengths and short canaries, so it did not show it.

Use `../2026-11-12-final/` instead. The official-SGLang runs here (`official-sglang`, `official-l20x-https`) are unaffected and still valid.
