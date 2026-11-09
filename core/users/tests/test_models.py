import pytest

from core.users.models import LabManagementEmail, User
from core.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_user_str_is_username():
    user = UserFactory(username="jdoe")
    assert str(user) == "jdoe"


@pytest.mark.django_db
def test_user_default_account_type_is_customer():
    user = UserFactory()
    assert user.account_type == User.ACCOUNT_TYPE_CUSTOMER


@pytest.mark.django_db
def test_user_default_status_is_offline():
    user = UserFactory()
    assert user.status == "OFFLINE"


@pytest.mark.django_db
def test_user_get_absolute_url(db):
    user = UserFactory(username="jdoe")
    assert user.get_absolute_url() == "/users/jdoe/"


@pytest.mark.django_db
def test_urs_group_str_uses_name():
    from core.users.tests.factories import URSGroupFactory
    urs = URSGroupFactory(urs_group_name="admin-group")
    assert str(urs) == "admin-group"


@pytest.mark.django_db
def test_lab_management_email_str_uses_display_name():
    email = LabManagementEmail.objects.create(display_name="Lab Admin", email="lab@example.com")
    assert str(email) == "Lab Admin"


@pytest.mark.django_db
def test_lab_management_email_str_falls_back_to_email():
    email = LabManagementEmail.objects.create(email="lab@example.com")
    assert str(email) == "lab@example.com"
