from django.conf import settings
from django.contrib.auth import login
from django.middleware.csrf import get_token
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from core.users.features.auth.aad_login.serializer import AADLoginSerializer
from core.users.features.auth.aad_login.service import AADAuthError, aad_login
from core.users.features.auth.api import AuthAPIView, PublicAuthAutoSchema
from core.users.features.auth.cookies import set_refresh_cookie
from core.users.features.auth.permissions import CookieCSRFPermission

from .serializer import AADLoginResponseSerializer, CSRFTokenResponseSerializer


class CSRFTokenView(AuthAPIView):
    """Issue the CSRF cookie and token that login, refresh and logout require. Writes nothing."""

    schema = PublicAuthAutoSchema()
    schema_tags = ("User Authentication",)
    permission_classes = [AllowAny]
    authentication_classes = []
    get_contract = OperationContract(
        success=ResponseContract.success("CSRFToken", CSRFTokenResponseSerializer),
    )

    def handle_get(self, request: Request, *args, **kwargs):
        response = self.respond_data({"csrf_token": get_token(request._request)})
        response["Cache-Control"] = "no-store"
        return response


class UserAADLoginView(AuthAPIView):
    """Validate a body-supplied Azure AD ID token without a DRF authenticator.

    The body carries the ID token and the browser's ``nonce_secret``; the token's ``nonce`` must equal
    base64url(SHA-256(nonce_secret)), the token must be recent, and each nonce is accepted once.
    Requires a valid CSRF cookie/token (``GET /api/csrf-token``; normally the X-CSRFToken header).
    Django CSRF origin/referer checks apply. Success issues an HttpOnly refresh cookie.
    Explicit public OpenAPI security does not exempt this operation from CSRF.
    """

    schema = PublicAuthAutoSchema()
    schema_tags = ("User Authentication",)
    permission_classes = [CookieCSRFPermission]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    post_contract = OperationContract(
        request=AADLoginSerializer,
        success=ResponseContract.success("AADLogin", AADLoginResponseSerializer),
        unauthorized=ResponseContract.unauthorized(),
        validation_error=ResponseContract.problem(422),
        forbidden=ResponseContract.problem(403),
        service_unavailable=ResponseContract.problem(503),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error

        try:
            data, user = aad_login(
                id_token=serializer.validated_data["id_token"],
                nonce_secret=serializer.validated_data["nonce_secret"],
            )
        except AADAuthError:
            return self.respond_problem(
                "unauthorized",
                code="invalid_sso_token",
                detail="Microsoft Token is invalid or expired",
            )

        refresh_token = data.pop("refresh")
        if settings.ENTRA_SSO_ONLY and user.is_staff:
            login(request._request, user, backend="core.users.backends.EntraSessionBackend")
            data["csrf_token"] = get_token(request._request)
        response = self.respond_data(data)
        set_refresh_cookie(response, refresh_token)
        response["Cache-Control"] = "no-store"
        return response
