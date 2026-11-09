from django.conf import settings
from django.contrib.auth import login
from django.middleware.csrf import get_token
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from core.users.features.auth.aad_login.serializer import AADLoginSerializer
from core.users.features.auth.aad_login.service import AADAuthError, aad_login, create_login_challenge
from core.users.features.auth.api import AuthAPIView, PublicAuthAutoSchema
from core.users.features.auth.cookies import set_refresh_cookie
from core.users.features.auth.permissions import CookieCSRFPermission

from .serializer import AADChallengeResponseSerializer, AADLoginResponseSerializer


class UserAADChallengeView(AuthAPIView):
    """Generate anti-replay nonce and CSRF challenge cookie for Azure AD SSO."""

    schema_tags = ("User Authentication",)
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"
    post_contract = OperationContract(
        request=None,
        success=ResponseContract.success("AADChallenge", AADChallengeResponseSerializer),
        rate_limited=ResponseContract.problem(429),
        service_unavailable=ResponseContract.problem(503),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        challenge, nonce = create_login_challenge()
        response = self.respond_data({"nonce": nonce, "csrf_token": get_token(request._request)})
        response.set_cookie(
            settings.AAD_LOGIN_CHALLENGE_COOKIE,
            str(challenge.pk),
            max_age=int(settings.AAD_LOGIN_CHALLENGE_LIFETIME.total_seconds()),
            secure=settings.REFRESH_TOKEN_COOKIE_SECURE,
            httponly=True,
            samesite="Lax",
            path="/api",
        )
        response["Cache-Control"] = "no-store"
        return response


class UserAADLoginView(AuthAPIView):
    """Validate a body-supplied Azure AD ID token without a DRF authenticator.

    Requires the anti-replay challenge cookie obtained from the AAD challenge
    endpoint and a valid CSRF cookie/token (normally the X-CSRFToken header).
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

        id_token = serializer.validated_data["id_token"]

        try:
            data, user = aad_login(
                id_token=id_token,
                challenge_id=request.COOKIES.get(settings.AAD_LOGIN_CHALLENGE_COOKIE, ""),
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
        response.delete_cookie(settings.AAD_LOGIN_CHALLENGE_COOKIE, path="/api", samesite="Lax")
        response["Cache-Control"] = "no-store"
        return response
