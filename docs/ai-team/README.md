# Lab Mango backend AI team (GitHub Copilot)

Everything is plain files read by Copilot. Edit them directly; there is nothing to generate.

| Path | What it is |
|---|---|
| `AGENTS.md` | Always-on rules: sources of truth, non-negotiables, risk tiers, definition of done |
| `.github/copilot-instructions.md` | Pointer to `AGENTS.md`; holds no rules |
| `.github/agents/*.agent.md` | 10 roles; pick one in the chat agent dropdown. `engineering-lead` can call the others as subagents |
| `.github/instructions/*.instructions.md` | Standards that load automatically for files matching `applyTo` |
| `.github/prompts/*.prompt.md` | Slash commands: `/feature` `/bug-fix` `/api-change` `/db-migration` `/model-design` `/model-implement` `/integration` `/refactor` `/performance` `/ops-change` `/test-plan` `/adr` `/architecture-review` `/architecture-design` `/architecture-update` `/security-review` `/release-check` `/review` |
| `docs/ai-team/team.md` | Roster, routing by change type, handoff protocol, decision rights |
| `docs/ai-team/quality-gates.md` | Gates to run and how to report them |
| `docs/ai-team/prompt-formats.md` | Fill-in prompt format per kind of work, mapped to slash commands and agents |
| `docs/ai-team/templates/` | Task brief, design doc, ADR, handoff, review report, feature architecture doc, model group doc, model catalog doc |
| `docs/ai-team/documentation-map.md` | Where architecture docs live, by domain, and which model-doc layout each domain uses (with Adopted/Proposed status). The architecture agent follows it; fill in your domains |
| `docs/ai-team/domain-glossary.md` | Domain terms; owner must complete |

## Architecture agent
`architecture` has three modes. Pick it in the dropdown or use the slash commands:
- **Review** (`/architecture-review`): read-only; findings with priority, confirmed vs potential status, evidence.
- **Generate** (`/architecture-design`): proposed design, Mermaid diagrams, ADR; documentation only.
- **Update** (`/architecture-update`): targeted doc edits with an impact scan and consistency check.
It can hand off to `api-designer`, `data-architect`, and `independent-code-reviewer` (handoff buttons need a recent VS Code).

## How to work
1. Start non-trivial work with the `engineering-lead` agent or a slash command.
2. Delegate with a full brief; one writer per file set.
3. Independent review (`/review`) for T1/T2; human approval for T2 merges and all releases.

## Verify in your environment
1. **Model / custom endpoint.** No `model:` is set in the agents, so each uses the model selected
   in the picker. Use your strongest model for lead, architect, data architect, security, reviewer.
   To pin one, add `model: 'Model Name (vendor)'` to that agent's frontmatter.
2. **Tool names.** Agents use `read`, `search`, `edit`, `execute` (the lead also `agent`). Tool names
   change between Copilot versions and unknown names may be ignored silently. Open each agent's
   Configure Tools picker once, especially `independent-code-reviewer` and `security-engineer`,
   which must not edit.
3. **`applyTo` globs** in `.github/instructions/` assume a typical Django layout; adjust to your repo.
4. **Subagents** need support in your VS Code version. Otherwise use the slash commands and switch
   agents manually.
5. A custom endpoint may have a smaller context window or weaker tool use; keep tasks small.
