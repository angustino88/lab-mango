from collections.abc import Sequence
from typing import Any

import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from factory import Faker, post_generation
from factory.django import DjangoModelFactory

from core.users.models import URSGroup

User = get_user_model()


class UserFactory(DjangoModelFactory):
    username = Faker("user_name")
    email = Faker("email")
    name = Faker("name")
    display_name = Faker("name")
    is_active = True
    is_urs_managed = True

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)

    @classmethod
    def _after_postgeneration(cls, instance, create, results=None):
        if create and results and not cls._meta.skip_postgeneration_save:
            instance.save()

    class Meta:
        model = User
        django_get_or_create = ["username"]


class GroupFactory(DjangoModelFactory):
    name = Faker("word")

    class Meta:
        model = Group
        django_get_or_create = ["name"]


class URSGroupFactory(DjangoModelFactory):
    group = factory.SubFactory(GroupFactory)
    urs_group_name = Faker("word")
    urs_group_id = Faker("random_int", min=1000, max=9999)
    active = True

    class Meta:
        model = URSGroup
