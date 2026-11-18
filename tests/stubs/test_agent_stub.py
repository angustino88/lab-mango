"""The agent stub against a live server: signing contract, provisioning, booking session, faults."""

from datetime import timedelta

import pytest
from django.test import override_settings

from core.agents.application import agent_request_message
from tools.stubs import agent as agent_stub
from tools.stubs import identities, lab, scenario
from tools.stubs.entra import call_as


def test_stub_signs_the_exact_bytes_the_backend_verifies(stub_home):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    agent = agent_stub.StubAgent(
        key_file=stub_home / "a.json",
        base_url="http://unused",
        backend_id="dept_a",
        agent_uid="3b05d37c-7c89-4506-adcd-d44c3bb58e68",
        key=Ed25519PrivateKey.generate(),
    )
    body = b'{"status":"free"}'
    headers = agent.signed_headers("PATCH", "/agent/equipment/activity", body)
    with override_settings(BACKEND_ID="dept_a"):
        message = agent_request_message(
            agent_uid=agent.agent_uid,
            method="PATCH",
            path="/agent/equipment/activity",
            timestamp=headers["X-Agent-Timestamp"],
            nonce=headers["X-Agent-Nonce"],
            body=body,
        )
    agent.key.public_key().verify(agent_stub.b64url_decode(headers["X-Agent-Signature"]), message)


@pytest.fixture()
def live_stub(stub_env, live_server, monkeypatch):
    """Seeded personas and lab, agents provisioned for pc-1 and pc-loose, all over real HTTP."""
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    identities.seed()
    lab.seed()
    agents = {}
    for computer in ("pc-1", "pc-loose"):
        result, enrolled = agent_stub.provision(
            persona="carol", equipment=computer, profile=computer, base_url=live_server.url
        )
        assert result.status == 201, result.body
        agents[computer] = enrolled
    return scenario.Context(base_url=live_server.url, issuer=stub_env), agents


@pytest.mark.django_db(transaction=True)
def test_full_booking_session_through_the_stubs(live_stub):
    ctx, agents = live_stub
    created, code = scenario.book(ctx, persona="alice", bench="bench-1", minutes=30)
    assert created.status == 201 and code, created.body

    lines = []
    assert agent_stub.run_session(
        agents["pc-1"], user="@alice", code=code, minutes=2, extend_by=timedelta(minutes=15), log=lines.append
    ), lines
    detail = ctx.as_("alice", "GET", f"/api/labs/bench-bookings/code/{code}")
    assert detail.data["status"]["value"] == "completed"

    # The computer that is not on the booking's bench may not use the code.
    assert agent_stub._flag(agents["pc-loose"].booking("validate", code)) is False


@pytest.mark.django_db(transaction=True)
def test_signing_faults_and_operator_authorization(live_stub):
    ctx, agents = live_stub
    pc1 = agents["pc-1"]
    assert pc1.heartbeat().status == 200
    for faults in (
        agent_stub.SigningFaults(skew=900),
        agent_stub.SigningFaults(replay=True),
        agent_stub.SigningFaults(tamper_body=True),
        agent_stub.SigningFaults(wrong_key=True),
        agent_stub.SigningFaults(path_mismatch=True),
    ):
        assert pc1.heartbeat(faults).status == 401, faults

    manifest = ctx.issuer.manifest
    grant = {"equipment_uid": pc1.equipment_uid, "ttl_minutes": 5}
    assert call_as(manifest.get("alice"), "POST", "/api/agents", body=grant, base_url=ctx.base_url).status == 403
    assert call_as(manifest.get("nora"), "GET", "/api/agents", base_url=ctx.base_url).status == 403
