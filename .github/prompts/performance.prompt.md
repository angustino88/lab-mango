---
description: 'Investigate a performance problem with measurements before changing anything'
agent: 'engineering-lead'
---
# Investigate a performance problem with measurements before changing anything

symptom: ${input:symptom:What is slow, how slow, target, measurements so far}

Measure first; make no optimization without evidence.
1. Reproduce and measure (timings, query counts, `EXPLAIN (ANALYZE)`, traces) on representative data; record the baseline.
2. Find the cause (N+1, unbounded query, missing or wrong index, lock contention, serialization cost). Involve `data-architect` for query and index design.
3. Make the smallest fix; no behavior change; migrations follow expand, migrate, contract.
4. Report before and after numbers and any residual risk.
