from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic.edit import FormView

from core.users.features.auth.login.ldap_service import ldap_auth
from core.users.forms import DjangoAdminSiteLoginForm


class DjangoAdminSiteCustomLoginView(FormView):
    """Custom admin login that authenticates via LDAP (or Django auth for whitelist users).

    Fixes old backend bug B2: form.add_error() requires (field, error) — old code
    passed only one argument, causing a TypeError on failed login.
    """

    template_name = "admin/login.html"
    form_class = DjangoAdminSiteLoginForm

    def form_valid(self, form):
        username = form.cleaned_data.get("username")
        password = form.cleaned_data.get("password")

        user = ldap_auth(username=username.lower(), password=password)

        if user is None or not user.is_active or not user.is_staff:
            form.add_error(None, "Incorrect username or password.")  # Bug B2 fix: two args
            return self.form_invalid(form)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return HttpResponseRedirect(reverse("admin:index"))
