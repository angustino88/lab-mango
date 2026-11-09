"""
Non-production LDAP authentication adapter.

Flow:
- Whitelist users (admin, adminlab) → fall back to Django's authenticate()
  so their stored Django password hash is used (no LDAP required).
- All other users → certificate-validated LDAPS bind → search → update an existing
  user record (email, name, display_name, department) → return User.
- Expected LDAP failures return None; unexpected programming/database errors surface.

Config is read from django.conf.settings:
    LDAP_AUTH_URL          (default: ldaps://de.bosch.com:3269)
  LDAP_AUTH_SEARCH_BASE  (default: dc=bosch,dc=com)
  LDAP_AUTH_WHITELIST    (default: ["admin", "adminlab"])
"""

import logging
import ssl
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from ldap3 import SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

logger = logging.getLogger(__name__)

User = get_user_model()

# LDAP field → Django User field mapping (matches old backend)
_FIELD_MAP = {
    "first_name": "givenName",
    "last_name": "sn",
    "email": "mail",
    "display_name": "displayName",
    "department": "department",
}


def ldap_auth(username: str, password: str):
    """Authenticate a user via LDAP (or Django authenticate for whitelist).

    Returns a User instance on success, None on failure.
    Never raises — all LDAP errors are logged and swallowed.
    """
    if settings.ENTRA_SSO_ONLY or not username or not password:
        return None
    whitelist: list[str] = getattr(settings, "LDAP_AUTH_WHITELIST", ["admin", "adminlab"])
    if username.lower() in {w.lower() for w in whitelist}:
        return authenticate(username=username, password=password)

    user = User.objects.filter(username=username, is_active=True, is_superuser=True).first()
    if user is not None:
        auth_user = authenticate(username=username, password=password)
        if auth_user is not None:
            return auth_user

    ldap_url: str = getattr(settings, "LDAP_AUTH_URL", "ldaps://de.bosch.com:3269")
    search_base: str = getattr(settings, "LDAP_AUTH_SEARCH_BASE", "dc=bosch,dc=com")

    conn = None
    try:
        parsed = urlsplit(ldap_url)
        if parsed.scheme != "ldaps" or not parsed.hostname:
            logger.error("LDAP requires an explicitly configured LDAPS endpoint")
            return None
        server = Server(
            parsed.hostname,
            port=parsed.port or 636,
            use_ssl=True,
            tls=Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.LDAP_AUTH_CA_CERT_FILE),
            connect_timeout=settings.LDAP_AUTH_CONNECT_TIMEOUT,
        )
        conn = Connection(
            server=server,
            user=f"{username}@bosch.com",
            password=password,
            auto_bind=True,
            receive_timeout=settings.LDAP_AUTH_RECEIVE_TIMEOUT,
        )
        conn.search(
            search_base=search_base,
            search_scope=SUBTREE,
            search_filter=f"(&(objectclass=person)(sAMAccountName={escape_filter_chars(username)}))",
            attributes=list(_FIELD_MAP.values()),
        )

        if len(conn.entries) != 1:
            return None

        attrs = conn.entries[0].entry_attributes_as_dict

        def _first(ldap_attr: str) -> str:
            values = attrs.get(ldap_attr, [])
            return values[0] if values else ""

        # Authentication never provisions an account or changes permissions.
        user = User.objects.filter(username=username, is_active=True).first()
        if user is None:
            return None
        fields = {
            "email": _first(_FIELD_MAP["email"]),
            "first_name": _first(_FIELD_MAP["first_name"]),
            "last_name": _first(_FIELD_MAP["last_name"]),
            "display_name": _first(_FIELD_MAP["display_name"]),
            "department": _first(_FIELD_MAP["department"]),
        }
        for field, value in fields.items():
            setattr(user, field, value)
        user.save(update_fields=list(fields))
        return user

    except (LDAPException, OSError, ValueError):
        logger.warning("LDAP authentication failed")
        return None
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except (LDAPException, OSError):
                logger.warning("LDAP connection cleanup failed")
