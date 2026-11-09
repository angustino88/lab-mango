from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from core.users.features.auth.api import AuthAPIView, PublicAuthAutoSchema
from core.users.features.auth.cookies import set_refresh_cookie
from core.users.features.auth.login.serializer import LoginResponseSerializer, LoginSerializer
from core.users.features.auth.login.service import AuthenticationError
from core.users.features.auth.login.service import login as do_login


class UserLoginView(AuthAPIView):
    """Authenticate credentials from the request body without a DRF authenticator.

    No cookie or CSRF token is required by this view. On success, issue an access
    token and an HttpOnly refresh cookie; cookie-backed refresh/logout require CSRF.
    """

    schema = PublicAuthAutoSchema()
    schema_tags = ("User Authentication",)
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    post_contract = OperationContract(
        request=LoginSerializer,
        success=ResponseContract.success("Login", LoginResponseSerializer),
        unauthorized=ResponseContract.unauthorized(),
        validation_error=ResponseContract.problem(422),
        service_unavailable=ResponseContract.problem(503),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        try:
            data = do_login(username=username, password=password)
        except AuthenticationError:
            return self.respond_problem("unauthorized", code="invalid_credentials")

        refresh_token = data.pop("refresh")
        response = self.respond_data(data)
        set_refresh_cookie(response, refresh_token)
        response["Cache-Control"] = "no-store"
        return response
