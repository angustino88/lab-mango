from django.conf import settings


if not settings.configured:
    settings.configure(
        DEFAULT_CHARSET="utf-8",
        REST_FRAMEWORK={},
    )
