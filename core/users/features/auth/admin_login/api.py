from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic.edit import FormView

from core.users.features.auth.login.ldap_service import ldap_auth
from core.users.forms import DjangoAdminSiteLoginForm


class DjangoAdminSiteCustomLoginView(FormView):
    """Production redirects to Entra; non-production retains the LDAP admin form."""

    template_name = "admin/login.html"
    form_class = DjangoAdminSiteLoginForm

    def dispatch(self, request, *args, **kwargs):
        if settings.ENTRA_SSO_ONLY:
            return HttpResponseRedirect(settings.ENTRA_FRONTEND_LOGIN_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        username = form.cleaned_data.get("username")
        password = form.cleaned_data.get("password")

        user = ldap_auth(username=username.lower(), password=password)

        if user is None or not user.is_active or not user.is_staff:
            form.add_error(None, "Incorrect username or password.")  # Bug B2 fix: two args
            return self.form_invalid(form)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return HttpResponseRedirect(reverse("admin:index"))
