from django.urls import path

from .api import SendUserOTPView

urlpatterns = [
    path("send-otp", SendUserOTPView.as_view(), name="send-otp"),
]
