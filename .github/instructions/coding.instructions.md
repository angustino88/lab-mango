---
applyTo: '**/*.py'
---
# Python code rules

Owns code-level rules that apply to every Python file. Layering is in
`django-conventions.instructions.md`; import boundaries are in `architecture.instructions.md`.

- **Exceptions.** No bare `except:`. `except Exception:` only at a process boundary (task entry point,
  exception handler) and it must log and re-raise or record a failed state. Never return a success-shaped
  value from a failure path.
  Bad: `except Bench.DoesNotExist: return []` in a query. Good: raise `BenchNotFound` from `exceptions.py`.
- **Types.** Type-hint every function in `public.py`, `contracts.py`, `application`, and `queries`.
  Check with `uv run mypy <changed paths>`.
- **Time.** Use `django.utils.timezone.now()`; never `datetime.now()` or `datetime.utcnow()`. Tests control
  time with `freezegun` or a fixture (e.g. `core/labs/features/bench_bookings/tests/conftest.py`), not sleeps.
- **Names.** No new modules named `helpers`, `misc`, `shared`, or `utils`; name the capability
  (`docs/feature-template.md` section 5).
- **Commits.** Never stage `.env*`, decrypted SOPS files, `media/`, `build/`, or real personal data.
