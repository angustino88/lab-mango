"""Server-rendered profile-page route facade."""

from django.urls import path
from django.views.generic import RedirectView

urlpatterns = [
    path("<str:username>/", RedirectView.as_view(url="/"), name="detail"),
]
