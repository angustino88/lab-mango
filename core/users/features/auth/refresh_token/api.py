from django.conf import settings
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError

from core.users.features.auth.api import AuthAPIView, PublicAuthAutoSchema
from core.users.features.auth.cookies import set_refresh_cookie
from core.users.features.auth.permissions import CookieCSRFPermission
from core.users.features.auth.tokens import rotate_refresh

from .serializer import RefreshTokenResponseSerializer


class UserRefreshTokenView(AuthAPIView):
    """Rotate the HttpOnly refresh cookie and issue a renewed access token.

    No DRF authenticator or Bearer token is required. The refresh token is read
    only from its cookie, never the request body. A valid CSRF cookie/token
    (normally the X-CSRFToken header) and Django CSRF origin/referer checks apply.
    Missing or invalid refresh cookies return 401 after CSRF verification.
    """

    schema = PublicAuthAutoSchema()
    schema_tags = ("User Authentication",)
    permission_classes = [CookieCSRFPermission]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_refresh"
    authentication_classes = []

    post_contract = OperationContract(
        request=None,
        success=ResponseContract.success("RefreshToken", RefreshTokenResponseSerializer),
        unauthorized=ResponseContract.unauthorized(),
        forbidden=ResponseContract.problem(403),
        service_unavailable=ResponseContract.problem(503),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        # Read refresh token from HttpOnly cookie — never from request body.
        refresh_token = request.COOKIES.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        if not refresh_token:
            return self.respond_problem("unauthorized", code="invalid_refresh_token")

        try:
            data = rotate_refresh(raw_token=refresh_token)
        except TokenError:
            return self.respond_problem("unauthorized", code="invalid_refresh_token")

        # Pop new refresh token from data — set it as an HttpOnly cookie.
        new_refresh = data.pop("refresh", None)
        response = self.respond_data(data)
        if new_refresh:
            set_refresh_cookie(response, new_refresh)
        response["Cache-Control"] = "no-store"
        return response
