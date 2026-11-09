import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_email(
    subject: str,
    context: dict,
    template: str,
    receivers: list[str],
    *,
    log_failure_details: bool = True,
) -> bool:
    """Send an HTML email. Returns True on success, False on failure."""
    try:
        html_content = render_to_string(template, context)
        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=receivers,
        )
        email.content_subtype = "html"
        return bool(email.send(fail_silently=False))
    except Exception:
        if log_failure_details:
            logger.exception("Failed to send email to %s", receivers)
        else:
            logger.error("Failed to send HTML email")
        return False
