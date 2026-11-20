"""End-to-end scenarios against a running local backend, with PASS/FAIL per step.

Prerequisites (see tools/stubs/README.md): ``entra init`` and its .env block, ``entra serve`` running,
the backend running with that .env (``manage.py runserver``). The scenarios seed what they need through the
other stubs. Exit code 1 when any step fails.

    python -m tools.stubs scenario setup                 # identities, lab, agents for pc-1 / pc-2 / pc-loose
    python -m tools.stubs scenario booking-happy-path
    python -m tools.stubs scenario all                   # every scenario, in order
    python -m tools.stubs scenario book --as @alice --bench bench-1 --minutes 60   # print a booking code
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from tools.stubs import agent as agent_stub
from tools.stubs.common import DEFAULT_BASE_URL, HttpResult, read_json
from tools.stubs.entra import Faults, StubIssuer, call_as, login

AGENT_PROFILES = {"pc-1": "pc-1", "pc-2": "pc-2", "pc-loose": "pc-loose"}


@dataclass
class Report:
    name: str
    passed: int = 0
    failed: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        print(f"  {'PASS' if condition else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")
        if condition:
            self.passed += 1
        else:
            self.failed.append(label)
        return condition

    def expect(self, label: str, result: HttpResult, statuses: set[int], flag: bool | None = None) -> bool:
        data = result.data if isinstance(result.data, dict) else {}
        actual_flag = agent_stub._flag(result)
        ok = result.status in statuses and (flag is None or actual_flag is flag)
        detail = f"got {result.status}" + (f" {actual_flag=}" if actual_flag is not None else "")
        if not ok:
            detail += f"; expected {sorted(statuses)}" + (f" flag={flag}" if flag is not None else "")
            error = result.body.get("error") if isinstance(result.body, dict) else None
            if error or not data:
                detail += f"; body={json.dumps(error or result.body, default=str)[:300]}"
        return self.check(label, ok, detail)


@dataclass
class Context:
    base_url: str
    issuer: StubIssuer

    def as_(self, persona: str, method: str, path: str, body: Any = None) -> HttpResult:
        return call_as(
            self.issuer.manifest.get(persona), method, path, body=body, base_url=self.base_url, issuer=self.issuer
        )

    def agent(self, computer: str) -> agent_stub.StubAgent:
        agent = agent_stub.StubAgent.load(agent_stub.profile_path(AGENT_PROFILES[computer]))
        agent.base_url = self.base_url
        return agent


def _lab() -> dict[str, Any]:
    from tools.stubs.identities import setup_django
    from tools.stubs.lab import rows

    setup_django()
    return {f"{row.kind}:{row.key}": row for row in rows()}


def book(
    ctx: Context,
    *,
    persona: str = "alice",
    bench: str = "bench-1",
    project: str = "proj-1",
    start_in: timedelta = timedelta(0),
    minutes: int = 60,
    approver: str = "carol",
) -> tuple[HttpResult, str | None]:
    """Create a booking as ``persona`` through the user API; approve it as ``approver`` if it needs approval."""
    lab = _lab()
    starts_at = (datetime.now(UTC) + start_in).replace(microsecond=0)
    payload = {
        "bench_id": lab[f"bench:{bench}"].id,
        "project_id": lab[f"project:{project}"].id,
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(minutes=minutes)).isoformat(),
        "reason": "stub scenario",
    }
    created = ctx.as_(persona, "POST", "/api/labs/bench-bookings", payload)
    if not created.ok:
        return created, None
    booking = created.data
    if booking.get("approval_status") == "pending":
        approved = ctx.as_(approver, "POST", f"/api/labs/bench-bookings/{booking['id']}/actions/approve", {})
        if not approved.ok:
            return approved, None
    return created, booking.get("booking_code")


def _clear_bookings() -> None:
    from tools.stubs.identities import setup_django
    from tools.stubs.lab import clear_bookings

    setup_django()
    clear_bookings()


# Scenarios -----------------------------------------------------------------------------------------------------


def scenario_setup(ctx: Context, report: Report) -> None:
    from tools.stubs import identities, lab

    identities.setup_django()
    outcomes = identities.seed()
    report.check("identities seeded", bool(outcomes), f"{len(outcomes)} personas")
    report.check("second seed changes nothing", not any(o.changed for o in identities.seed()))
    lab.seed()
    report.check("lab seeded", {"bench:bench-1", "computing:pc-1", "project:proj-1"} <= set(_lab()))
    lab.clear_bookings()
    for computer, profile in AGENT_PROFILES.items():
        existing = read_json(agent_stub.profile_path(profile))
        if existing is not None:
            heartbeat = ctx.agent(computer).heartbeat()
            if heartbeat.ok:
                report.check(f"agent {computer} already enrolled", True)
                continue
        result, enrolled = agent_stub.provision(
            persona="carol", equipment=computer, profile=profile, base_url=ctx.base_url
        )
        report.expect(f"provision agent for {computer}", result, {200, 201})
        if enrolled:
            report.expect(f"{computer} heartbeat", enrolled.heartbeat(), {200})


def scenario_booking_happy_path(ctx: Context, report: Report) -> None:
    _clear_bookings()
    created, code = book(ctx, persona="alice", bench="bench-1", minutes=30)
    if not report.expect("alice books bench-1 now for 30 min", created, {200, 201}) or not code:
        return
    pc1 = ctx.agent("pc-1")
    report.expect("validate", pc1.booking("validate", code), {200}, flag=True)
    report.expect("check-in", pc1.booking("check-in", code), {200}, flag=True)
    report.expect(
        "activity active as alice", pc1.activity(status="active", remote_user="@alice", booking_code=code), {200}
    )
    report.expect("heartbeat", pc1.heartbeat(), {200})
    report.expect("extend by 15 min", pc1.extend_by(code, timedelta(minutes=15)), {200}, flag=True)
    report.expect("session log", pc1.session_log(remote_user="@alice", minutes=5, booking_code=code), {200, 201})
    report.expect("complete", pc1.booking("complete", code), {200}, flag=True)
    report.expect("activity free", pc1.activity(status="free", remote_user="", booking_code=""), {200})
    detail = ctx.as_("alice", "GET", f"/api/labs/bench-bookings/code/{code}")
    status = (detail.data or {}).get("status") if detail.ok else None
    status = status.get("value") if isinstance(status, dict) else status  # {"value", "label"} choice shape
    report.check("alice sees the booking completed", status == "completed", f"status={status}")


def scenario_booking_wrong_bench(ctx: Context, report: Report) -> None:
    _clear_bookings()
    created, code = book(ctx, persona="alice", bench="bench-1", minutes=30)
    if not report.expect("alice books bench-1", created, {200, 201}) or not code:
        return
    pc2 = ctx.agent("pc-2")
    report.expect("pc-2 (bench-2) validate is not eligible", pc2.booking("validate", code), {200}, flag=False)
    report.expect("pc-2 check-in is refused", pc2.booking("check-in", code), {200}, flag=False)


def scenario_booking_unassigned_agent(ctx: Context, report: Report) -> None:
    _clear_bookings()
    created, code = book(ctx, persona="alice", bench="bench-1", minutes=30)
    if not report.expect("alice books bench-1", created, {200, 201}) or not code:
        return
    loose = ctx.agent("pc-loose")
    report.expect("pc-loose (no bench) validate is not eligible", loose.booking("validate", code), {200}, flag=False)
    report.expect(
        "unknown code is not eligible", ctx.agent("pc-1").booking("validate", "NO-SUCH-CODE"), {200}, flag=False
    )


def scenario_booking_early(ctx: Context, report: Report) -> None:
    _clear_bookings()
    created, code = book(ctx, persona="alice", bench="bench-1", start_in=timedelta(hours=2), minutes=30)
    if not report.expect("alice books bench-1 in 2 h", created, {200, 201}) or not code:
        return
    report.expect(
        "validate before start is not eligible", ctx.agent("pc-1").booking("validate", code), {200}, flag=False
    )


def scenario_booking_extend_conflict(ctx: Context, report: Report) -> None:
    _clear_bookings()
    first, code = book(ctx, persona="alice", bench="bench-1", minutes=30)
    if not report.expect("alice books bench-1 now for 30 min", first, {200, 201}) or not code:
        return
    second, _ = book(ctx, persona="carol", bench="bench-1", start_in=timedelta(minutes=30), minutes=30)
    report.expect("carol books bench-1 right after", second, {200, 201})
    pc1 = ctx.agent("pc-1")
    report.expect("check-in", pc1.booking("check-in", code), {200}, flag=True)
    report.expect("extend into carol's booking is refused", pc1.extend_by(code, timedelta(minutes=15)), {409})


def scenario_booking_idempotent(ctx: Context, report: Report) -> None:
    _clear_bookings()
    created, code = book(ctx, persona="alice", bench="bench-1", minutes=30)
    if not report.expect("alice books bench-1", created, {200, 201}) or not code:
        return
    pc1 = ctx.agent("pc-1")
    report.expect("check-in", pc1.booking("check-in", code), {200}, flag=True)
    report.expect("check-in again is safe", pc1.booking("check-in", code), {200}, flag=True)
    event_key = str(uuid.uuid4())
    first = pc1.session_log(remote_user="@alice", minutes=3, booking_code=code, event_key=event_key)
    report.expect("session log", first, {200, 201})
    again = pc1.session_log(remote_user="@alice", minutes=3, booking_code=code, event_key=event_key)
    report.expect("same session log again is accepted", again, {200, 201})
    first_id = (first.data or {}).get("id")
    report.check(
        "no duplicate session log",
        first_id is not None and first_id == (again.data or {}).get("id"),
        f"ids {first_id} / {(again.data or {}).get('id')}",
    )
    report.expect("complete", pc1.booking("complete", code), {200}, flag=True)
    second = pc1.booking("complete", code)
    report.check(
        "complete again does not fail", second.status < 500, f"got {second.status} {agent_stub.flag_text(second)}"
    )


def scenario_signing_faults(ctx: Context, report: Report) -> None:
    pc1 = ctx.agent("pc-1")
    report.expect("valid heartbeat", pc1.heartbeat(), {200})
    for name, faults in (
        ("clock skew 15 min", agent_stub.SigningFaults(skew=900)),
        ("replayed nonce", agent_stub.SigningFaults(replay=True)),
        ("tampered body", agent_stub.SigningFaults(tamper_body=True)),
        ("wrong key", agent_stub.SigningFaults(wrong_key=True)),
        ("signed another path", agent_stub.SigningFaults(path_mismatch=True)),
    ):
        report.expect(f"{name} is refused", pc1.heartbeat(faults), {401})


def scenario_operator_authz(ctx: Context, report: Report) -> None:
    report.expect("carol (coord) lists agents", ctx.as_("carol", "GET", "/api/agents"), {200})
    report.expect("adam (admin) lists agents", ctx.as_("adam", "GET", "/api/agents"), {200})
    # IsLabCoordinator: any Labs role may read; only coordinators and admins may write.
    report.expect("alice (user) cannot read agents", ctx.as_("alice", "GET", "/api/agents"), {403})
    pc1 = ctx.agent("pc-1")
    grant = {"equipment_uid": pc1.equipment_uid, "ttl_minutes": 5}
    report.expect(
        "alice (user) cannot create an enrollment grant", ctx.as_("alice", "POST", "/api/agents", grant), {403}
    )
    report.expect("nora (no role) cannot read agents", ctx.as_("nora", "GET", "/api/agents"), {403})
    report.expect(
        "alice (user) cannot approve bookings",
        ctx.as_("alice", "POST", "/api/labs/bench-bookings/0/actions/approve", {}),
        {403, 404},
    )


def scenario_entra_faults(ctx: Context, report: Report) -> None:
    manifest = ctx.issuer.manifest
    alice = manifest.get("alice")
    report.expect("alice logs in", login(ctx.issuer, alice, base_url=ctx.base_url), {200})
    for name, faults in (
        ("expired", Faults(expired=True)),
        ("not yet valid", Faults(not_yet_valid=True)),
        ("issued too long ago", Faults(stale_iat=True)),
        ("wrong audience", Faults(audience="someone-else")),
        ("wrong tenant", Faults(tenant="11111111-2222-4333-8444-555555555555")),
        ("unknown signing key", Faults(unknown_kid=True)),
        ("HS256", Faults(hs256=True)),
    ):
        report.expect(
            f"login with {name} token is refused",
            login(ctx.issuer, alice, base_url=ctx.base_url, faults=faults),
            {401},
        )
    report.expect(
        "guest (#EXT#) token is refused",
        login(ctx.issuer, manifest.get("dave"), base_url=ctx.base_url, faults=Faults(guest=True)),
        {401},
    )
    report.expect("ivy (inactive) cannot log in", login(ctx.issuer, manifest.get("ivy"), base_url=ctx.base_url), {401})
    # dave is unbound: first login binds by username (allowed domain), once per account. Recreate him so the
    # check is repeatable (an account that was ever bound is never re-bound automatically).
    from tools.stubs import identities

    identities.setup_django()
    from core.users.public import list_stub_users

    dave = manifest.get("dave")
    if any(state.username == dave.username for state in list_stub_users()):
        identities.delete(dave)
    identities.seed(keys=["dave"])
    report.expect("dave (unbound) binds on first login", login(ctx.issuer, dave, base_url=ctx.base_url), {200})
    report.check(
        "dave is now bound to his object ID",
        any(line.startswith(dave.username) and manifest.user_key(dave) in line for line in identities.describe()),
    )
    router = _router(ctx)
    report.check("sync API accepts the stub app token", router(ctx.issuer.app_token()).status == 200)
    for name, faults, statuses in (
        ("app token without role", Faults(no_role=True), {403}),
        ("app token with scp", Faults(with_scp=True), {403}),
        ("expired app token", Faults(expired=True), {401}),
        ("wrong audience app token", Faults(audience="api://labmango-other"), {401}),
        ("unknown signing key", Faults(unknown_kid=True), {401}),
    ):
        report.expect(f"sync API refuses {name}", router(ctx.issuer.app_token(faults=faults)), statuses)
    user_token = ctx.issuer.access_token(alice)
    report.expect("sync API refuses a delegated user token", router(user_token), {401, 403})


def _router(ctx: Context) -> Callable[[str], HttpResult]:
    from tools.stubs.common import http

    def call(token: str) -> HttpResult:
        return http(ctx.base_url, "GET", "/internal/info", headers={"Authorization": f"Bearer {token}"})

    return call


def scenario_routing_users(ctx: Context, report: Report) -> None:
    from tools.stubs import identities
    from tools.stubs.router import StubRouter

    identities.setup_django()
    identities.seed()
    manifest = ctx.issuer.manifest
    router = StubRouter(ctx.base_url, ctx.issuer.app_token())
    try:
        keys = {claim["key"] for claim in router.snapshot("users")}
    except RuntimeError as exc:
        report.check("users snapshot", False, str(exc)[:300])
        return
    for key in ("alice", "carol", "adam", "nora"):
        report.check(f"{key} is routed", manifest.user_key(manifest.get(key)) in keys)
    for key, why in (("ivy", "inactive"), ("dave", "unbound"), ("bob", "other backend")):
        report.check(f"{key} is not routed ({why})", manifest.user_key(manifest.get(key)) not in keys)
    alice = manifest.get("alice")
    old_key = manifest.user_key(alice)
    identities.unlink(alice)
    changes = router.changes("users").get("changes", [])
    report.check("unlink publishes a delete", any(c["op"] == "delete" and c["key"] == old_key for c in changes))
    identities.seed(keys=["alice"])
    changes = router.changes("users").get("changes", [])
    report.check("seed publishes the upsert again", any(c["op"] == "upsert" and c["key"] == old_key for c in changes))
    old, new = identities.replace(manifest, alice)
    changes = router.changes("users").get("changes", [])
    report.check(
        "replace tombstones the old key and publishes the new one",
        any(c["op"] == "delete" and c["key"] == old for c in changes)
        and any(c["op"] == "upsert" and c["key"] == new for c in changes),
    )
    report.expect("alice can log in with the new object ID", login(ctx.issuer, alice, base_url=ctx.base_url), {200})


def scenario_agent_lifecycle(ctx: Context, report: Report) -> None:
    """Revoke pc-2's agent, check it is refused and leaves routing, then provision it again."""
    from tools.stubs.router import StubRouter

    pc2 = ctx.agent("pc-2")
    listed = ctx.as_("carol", "GET", f"/api/agents?equipment_uid={pc2.equipment_uid}")
    agents = [a for a in (listed.data or []) if a.get("agent_uid") == pc2.agent_uid]
    if not report.check("find pc-2's agent", bool(agents), f"status {listed.status}"):
        return
    router = StubRouter(ctx.base_url, ctx.issuer.app_token())
    try:
        before = {claim["key"] for claim in router.snapshot("agents")}
        report.check("pc-2's agent is routed", pc2.agent_uid in before)
    except RuntimeError as exc:
        report.check("agents snapshot", False, str(exc)[:300])
        return
    report.expect(
        "carol revokes it", ctx.as_("carol", "POST", f"/api/agents/{agents[0]['id']}/actions/revoke", {}), {200}
    )
    report.expect("revoked agent heartbeat is refused", pc2.heartbeat(), {401, 403})
    changes = router.changes("agents").get("changes", [])
    report.check("routing publishes a delete", any(c["op"] == "delete" and c["key"] == pc2.agent_uid for c in changes))
    result, enrolled = agent_stub.provision(persona="carol", equipment="pc-2", profile="pc-2", base_url=ctx.base_url)
    report.expect("pc-2 provisioned again", result, {200, 201})


SCENARIOS: dict[str, Callable[[Context, Report], None]] = {
    "setup": scenario_setup,
    "booking-happy-path": scenario_booking_happy_path,
    "booking-wrong-bench": scenario_booking_wrong_bench,
    "booking-unassigned-agent": scenario_booking_unassigned_agent,
    "booking-early": scenario_booking_early,
    "booking-extend-conflict": scenario_booking_extend_conflict,
    "booking-idempotent": scenario_booking_idempotent,
    "signing-faults": scenario_signing_faults,
    "operator-authz": scenario_operator_authz,
    "entra-faults": scenario_entra_faults,
    "routing-users": scenario_routing_users,
    "agent-lifecycle": scenario_agent_lifecycle,
}


def run(names: list[str], ctx: Context) -> list[Report]:
    reports = []
    for name in names:
        print(f"== {name}")
        report = Report(name)
        try:
            SCENARIOS[name](ctx, report)
        except Exception as exc:  # report and continue with the next scenario
            report.check("scenario ran without an exception", False, f"{type(exc).__name__}: {exc}")
        reports.append(report)
    _clear_bookings()
    print("\nSummary")
    for report in reports:
        print(
            f"  {'PASS' if not report.failed else 'FAIL'}  {report.name:<26} {report.passed} passed, "
            f"{len(report.failed)} failed"
        )
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.stubs scenario",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("names", nargs="*", help=f"scenario names, 'all', or 'book'; known: {', '.join(SCENARIOS)}")
    parser.add_argument("--as", dest="persona", default="@alice", help="book: persona")
    parser.add_argument("--bench", default="bench-1", help="book: stub bench key")
    parser.add_argument("--start-in", type=agent_stub.parse_duration, default=timedelta(0), help="book: e.g. 10m")
    parser.add_argument("--minutes", type=int, default=60, help="book: duration")
    args = parser.parse_args(argv)
    ctx = Context(base_url=args.base_url, issuer=StubIssuer.load())

    if args.names == ["book"]:
        result, code = book(
            ctx, persona=args.persona.removeprefix("@"), bench=args.bench, start_in=args.start_in, minutes=args.minutes
        )
        print(
            json.dumps({"status": result.status, "booking_code": code, "booking": result.body}, indent=2, default=str)
        )
        return 0 if code else 1
    names = list(SCENARIOS) if args.names in ([], ["all"]) else args.names
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(unknown)}")
    reports = run(names, ctx)
    return 1 if any(report.failed for report in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
