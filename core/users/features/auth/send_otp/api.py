from django.conf import settings
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_api_key.permissions import HasAPIKey

from core.common.api.api_views import AppAPIView
from core.users.features.auth.send_otp.serializer import SendOTPResponseSerializer, SendOTPSerializer
from core.users.features.auth.send_otp.service import OTPDeliveryError, send_otp


class SendUserOTPView(AppAPIView):
    """Deliver a one-time verification password to the requested user."""

    schema_tags = ("User Authentication",)
    permission_classes = [HasAPIKey | IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_otp"

    post_contract = OperationContract(
        request=SendOTPSerializer,
        success=ResponseContract.success("SendOTP", SendOTPResponseSerializer),
        bad_request=ResponseContract.problem(400),
        validation_error=ResponseContract.problem(422),
        forbidden=ResponseContract.forbidden(),
        service_unavailable=ResponseContract.problem(503),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        if settings.ENTRA_SSO_ONLY:
            return self.respond_problem("bad_request", detail="This authentication method is unavailable.")
        serializer, error = self.validate_request()
        if error is not None:
            return error

        username = serializer.validated_data["username"]
        otp = serializer.validated_data["otp"]

        try:
            send_otp(username=username, otp=otp)
        except OTPDeliveryError:
            return self.respond_problem("service_unavailable", detail="OTP delivery failed.")

        return self.respond_data({"message": f"OTP sent successfully to {username}"})
