"""System checks that keep the stub issuer local (users.E013, E014, E015)."""

from django.test import override_settings

from core.users.checks import check_entra_access_token_configuration, check_entra_stub_issuer

STUB = "00000000-0000-0000-0000-0000000057ab"
REAL = "0ae51e19-07c8-4e4b-bb6d-648ee58410f4"
LOOPBACK_JWKS = f"http://127.0.0.1:8765/{STUB}/discovery/v2.0/keys"


def _ids(errors):
    return {error.id for error in errors}


@override_settings(ENTRA_API_ACCESS_TOKENS_ENABLED=True, AAD_TENANT_ID=STUB, AAD_JWKS_URL=LOOPBACK_JWKS)
def test_loopback_jwks_is_refused_without_the_stub_flag():
    with override_settings(ENTRA_STUB_ISSUER_ENABLED=False):
        assert "users.E013" in _ids(check_entra_access_token_configuration(None))


@override_settings(ENTRA_API_ACCESS_TOKENS_ENABLED=True, AAD_TENANT_ID=STUB, ENTRA_STUB_ISSUER_ENABLED=True)
def test_stub_flag_allows_loopback_jwks_only():
    with override_settings(AAD_JWKS_URL=LOOPBACK_JWKS):
        assert "users.E013" not in _ids(check_entra_access_token_configuration(None))
    with override_settings(AAD_JWKS_URL="http://jwks.example.com/keys"):
        assert "users.E013" in _ids(check_entra_access_token_configuration(None))


@override_settings(ENTRA_STUB_ISSUER_ENABLED=True, ENTRA_SSO_ONLY=False, DEBUG=True, AAD_TENANT_ID=STUB)
def test_stub_flag_is_accepted_only_in_local_debug_for_the_stub_tenant():
    assert check_entra_stub_issuer(None) == []
    with override_settings(DEBUG=False):
        assert "users.E014" in _ids(check_entra_stub_issuer(None))
    with override_settings(ENTRA_SSO_ONLY=True):
        assert "users.E014" in _ids(check_entra_stub_issuer(None))
    with override_settings(AAD_TENANT_ID=REAL):
        assert "users.E014" in _ids(check_entra_stub_issuer(None))


@override_settings(ENTRA_STUB_ISSUER_ENABLED=False, ENTRA_SSO_ONLY=True, AAD_TENANT_ID=REAL)
def test_stub_tenant_is_refused_in_production():
    with override_settings(ROUTING_SYNC_ENTRA_TENANT_IDS=[REAL]):
        assert check_entra_stub_issuer(None) == []
    with override_settings(ROUTING_SYNC_ENTRA_TENANT_IDS=[REAL, STUB]):
        assert "users.E015" in _ids(check_entra_stub_issuer(None))
    with override_settings(AAD_TENANT_ID=STUB):
        assert "users.E015" in _ids(check_entra_stub_issuer(None))


def test_production_settings_force_the_stub_issuer_off():
    source = open("config/settings/production.py", encoding="utf-8").read()
    assert "ENTRA_STUB_ISSUER_ENABLED = False" in source


def test_stub_tenant_constants_agree():
    from django.conf import settings

    from core.users.public import STUB_USERNAME_PREFIX
    from tools.stubs.common import STUB_TENANT_ID, USERNAME_PREFIX

    assert settings.ENTRA_STUB_TENANT_ID == STUB_TENANT_ID == STUB
    assert USERNAME_PREFIX == STUB_USERNAME_PREFIX
