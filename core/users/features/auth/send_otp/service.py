import logging

from django.conf import settings

from core.infrastructure.email.service import send_email
from core.infrastructure.teams.service import send_ms_teams_notification

logger = logging.getLogger(__name__)


class OTPDeliveryError(Exception):
    pass


def send_otp(*, username: str, otp: str) -> None:
    """Deliver an OTP to the user via email and MS Teams webhook.

    Raises OTPDeliveryError if both delivery channels fail.
    Internal delivery state (email_sent, ms_teams_sent) is never
    exposed to callers — fixes old backend security leak.
    """
    email_sent = send_email(
        subject="[Lab Mango] One-Time Login Code",
        context={"username": username, "otp": otp},
        template="emails/send_otp.html",
        receivers=[f"{username}@bosch.com"],
    )

    ms_teams_sent = send_ms_teams_notification(
        url=settings.OTP_PA_API,
        payload={"username": username, "otp": otp},
    )

    if not email_sent and not ms_teams_sent:
        logger.error("OTP delivery failed for user '%s' on all channels.", username)
        raise OTPDeliveryError("OTP delivery failed.")
