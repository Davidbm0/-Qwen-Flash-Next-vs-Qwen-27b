# extreme-llm-bench — Qwen3.8-Flash-Next vs Qwen3.8-27B on one RTX 5080

Benchmark of two local models on a 4-problem "extreme" coding/engineering suite, with **real execution-based verification** (generated code is extracted, run against reference asserts, self-repair retries within a time budget).

## Hardware / setup

- GPU: RTX 5080 16 GB (both models run on it, one at a time — 14 GB + 13 GB don't fit together)
- Flash-Next: served by the Strata engine on port 8080 (MoE, experts offloaded to 96 GB DDR5)
- Qwen3.8-27B dense: llama.cpp `llama-server` Q3_K_XL, port 8083, ctx 16k, full GPU offload
- 2-phase runs: Flash first, then Fable with the **same per-problem time budget** Flash used
- `max_tokens=8000`, temperature 0.3, verifier reads both `content` and `reasoning_content`

## Problems

1. **P1 — parity/turn/color-constrained Dijkstra** (state-space search, not plain Dijkstra)
2. **P2 — microstrip width inverse solver** (Hammerstad-Jensen + Wheeler conductor correction, bisection to 1e-7)
3. **P3 — transactional key-value store** (exclusive locks, wait-for-graph deadlock detection, savepoints, FIFO lock queues)
4. **P4 — PDN impedance sweep** (parallel caps with ESR/ESL, log sweep, anti-resonance peak detection)

Reference asserts were **verified independently** before benchmarking (`extreme_ref.py`): the original suite document contained three broken asserts (P2 width inconsistent with its own formulas, P3 output length inconsistent with its own semantics, P4 minimum below the smallest ESR — physically impossible). Corrected reference values are used here.

## Results (timeboxed, self-repair max 4 attempts)

| Problem | Flash-Next | Qwen3.8-27B Q3 |
|---|---|---|
| P1 Dijkstra | OK — 211.9 s, 2 attempts | OK — 148.2 s, **1 attempt** |
| P2 microstrip | FAIL — 373.3 s, 4 attempts | FAIL — 442.1 s, 3 attempts |
| P3 TX engine | FAIL — 408.9 s, 4 attempts | FAIL — 439.9 s, 3 attempts |
| P4 PDN | OK — 190.7 s, 2 attempts | OK — 146.6 s, **1 attempt** |
| **Score** | **2/4** | **2/4** |

## Findings

- **Reasoning quality: 27B wins.** It solves both solvable problems **pass@1**; Flash-Next needed 2 attempts on each (with stderr feedback injected between attempts).
- **Speed: Flash-Next wins.** MoE + expert offload keeps generation fast; the dense 27B Q3 at 16 GB VRAM drops to ~5–10 tok/s once reasoning chains fill the 16k context — on P2/P3 it was cut off by the time budget *before emitting code*, not by lack of knowledge (a correct P2 solver appeared in an untimed replay).
- **Flash-Next's real weakness is self-repair depth**: on P2/P3 it repeats the same wrong premise (formula / queue semantics) across all 4 attempts even with exact error messages.
- P3 (deadlock-aware TX engine) was solved by neither model under any tested condition — hardest problem of the suite.

## Files

- `bench_extreme.py` — harness (2-phase, preflight health checks, execution verification, timeboxed self-repair)
- `extreme_ref.py` — independent reference implementations used to audit the suite asserts
- `results_flash.json`, `results_fable.json` — raw per-problem results

## Reproduce

```
python bench_extreme.py flash   # Flash-Next on :8080
python bench_extreme.py fable   # 27B on :8083, budgets loaded from results_flash.json
```
