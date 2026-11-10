---
applyTo: '**/permissions*.py,**/policies*.py,**/auth*/**,**/api/**,**/settings*/**,**/settings*.py'
---
# Security rules

HTTP-facing security rules (SEC-1 to SEC-16, ERR-5, FIL-1 to FIL-7) are owned by
`docs/api/response-standard.md`. This file owns how authorization is implemented and tested here.

## Authorization (checkable)
- Every view sets `permission_classes` explicitly; never rely on the DRF default.
- Visibility is applied in the query (actor-scoped queryset); eligibility in a policy (`can_*` / `ensure_*`,
  `docs/architecture/feature-template.md` section 4). A view never decides access by inspecting `request.user` fields itself.
- A mutation loads its target through the actor-scoped query, so an object the caller cannot see is `404`
  (ERR-5, SEC-15), not `403`.
- Commands take an explicit `actor`. A system or API-key actor is scoped; `actor=None` is never a bypass.
- Changing who may do what (roles, permission classes, policy outcomes) is an access-control change:
  T2 and human authorization (AGENTS.md rule 9).

## Required authorization test matrix (every new or changed endpoint)
Role × action × object relationship (own / same group / other / anonymous). Assert allowed and denied outcomes,
and that denied responses reveal nothing (`404` body identical to a missing object).
Example row: `lab_member | PATCH /api/labs/benches/{id} | other group's bench | 404`.

## Secrets and config
Secrets come only from SOPS-managed env files (`scripts/sops/`). Never print, log, commit, or echo a decrypted
value. Settings changes run `check --deploy` with `DJANGO_SETTINGS_MODULE=config.settings.production`
(`docs/ai-team/quality-gates.md`).
