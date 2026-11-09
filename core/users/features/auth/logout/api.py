from django.conf import settings
from django.contrib.auth import logout
from drf_api_contracts import EmptyPayloadSerializer, OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework_simplejwt.exceptions import TokenError

from core.users.features.auth.api import AuthAPIView, PublicAuthAutoSchema
from core.users.features.auth.permissions import CookieCSRFPermission
from core.users.features.auth.tokens import revoke_refresh


class UserLogoutView(AuthAPIView):
    """Revoke the refresh cookie, when present, and invalidate the Django session.

    No DRF authenticator or Bearer token is required. A valid CSRF cookie/token
    (normally the X-CSRFToken header) is required even without a refresh cookie.
    Django CSRF origin/referer checks apply. Success deletes the refresh cookie.
    """

    schema = PublicAuthAutoSchema()
    schema_tags = ("User Authentication",)
    permission_classes = [CookieCSRFPermission]
    authentication_classes = []

    post_contract = OperationContract(
        request=None,
        success=ResponseContract.success("Logout", EmptyPayloadSerializer),
        forbidden=ResponseContract.problem(403),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        refresh_token = request.COOKIES.get(settings.REFRESH_TOKEN_COOKIE_NAME)

        if refresh_token:

            def _blacklist_response():
                try:
                    revoke_refresh(raw_token=refresh_token)
                except TokenError:
                    pass

            _blacklist_response()

        logout(request._request)
        response = self.respond_data({})
        response.delete_cookie(
            key=settings.REFRESH_TOKEN_COOKIE_NAME,
            path="/api",
            samesite=settings.REFRESH_TOKEN_COOKIE_SAMESITE,
        )
        response["Cache-Control"] = "no-store"
        return response
