---
description: 'Behavior-preserving refactor in small reviewable steps'
agent: 'engineering-lead'
---
# Behavior-preserving refactor in small reviewable steps

target: ${input:target:Module or feature, the reason, and files that must not change}

Behavior must stay identical.
1. Add characterization tests first where coverage is missing.
2. Plan small steps; each step leaves all tests green and is reviewable on its own.
3. No unrelated cleanup, no new dependencies, no public contract changes.
4. Run the quality gates (`docs/ai-team/quality-gates.md`) after each step; then hand off to `independent-code-reviewer`.
