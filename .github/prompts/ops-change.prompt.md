---
description: 'CI/CD, container, config, or observability change with rollout and rollback'
agent: 'devops-reliability-engineer'
---
# CI/CD, container, config, or observability change with rollout and rollback

change: ${input:change:What changes, why, which environments}

T2. Never deploy, restart production services, rotate credentials, or touch production data without explicit authorization; never print secrets.
1. Inspect the current pipeline, containers, config, and deploy process.
2. Assess operational impact: startup, migrations, config, resources, new alerts, new failure modes.
3. Define rollout order, feature flags if risky, rollback, and how to verify without touching production.
4. Report with evidence and unverified assumptions (`docs/ai-team/templates/handoff-report.md`).
