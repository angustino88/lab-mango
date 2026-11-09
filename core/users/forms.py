from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import forms as admin_forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class DjangoAdminSiteLoginForm(AdminAuthenticationForm):
    """Admin login form — only validates presence of username/password.
    Actual authentication is done by DjangoAdminSiteCustomLoginView via LDAP."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if not username or not password:
            raise admin_forms.ValidationError("Username and password are required.")
        return self.cleaned_data


class UserAdminChangeForm(admin_forms.UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "is_urs_managed" in self.fields:
            self.fields["is_urs_managed"].help_text = (
                "Designates whether this user should be managed by the URS Group system."
            )

    class Meta(admin_forms.UserChangeForm.Meta):
        model = User


class UserAdminCreationForm(admin_forms.UserCreationForm):
    """User creation form for admin. Password is optional — LDAP users have no Django password."""

    password1 = forms.CharField(
        label="Password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Password confirmation",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
        help_text=_("Enter the same password as before, for verification."),
    )

    class Meta(admin_forms.UserCreationForm.Meta):
        model = User
        error_messages = {
            "username": {"unique": _("This username has already been taken.")},
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # LDAP users don't have a Django password
        if commit:
            user.save()
        return user
