from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.infrastructure.storage.urls import get_media_url
from core.users.access import LabsRole, effective_labs_roles

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "codename"]


class GroupPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "name"]


class UserGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "name"]


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar_url"]

    def get_avatar_url(self, obj) -> str | None:
        return get_media_url(obj.avatar, request=self.context.get("request"))


class EffectiveRolesSerializer(serializers.Serializer):
    labs = serializers.ListField(child=serializers.CharField(), read_only=True)


class UserWithPermissionSerializer(UserSerializer):
    groups = GroupPermissionSerializer(many=True, read_only=True)
    effective_roles = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["groups", "effective_roles"]

    @extend_schema_field(EffectiveRolesSerializer)
    def get_effective_roles(self, obj) -> dict[str, list[str]]:
        roles = effective_labs_roles(obj)
        return {"labs": [role.value for role in LabsRole if role in roles]}


class UserAvatarReadSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["avatar_url"]

    def get_avatar_url(self, obj) -> str | None:
        return get_media_url(obj.avatar, request=self.context.get("request"))


class UserAvatarUploadSerializer(serializers.Serializer):
    avatar = serializers.ImageField(required=True, allow_null=False)

    def validate_avatar(self, value):
        max_size = 5 * 1024 * 1024  # 5 MB
        if value.size > max_size:
            raise serializers.ValidationError("Avatar file size must not exceed 5 MB.", code="max_size")
        allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if hasattr(value, "content_type") and value.content_type not in allowed_types:
            raise serializers.ValidationError("Unsupported image type.", code="unsupported_media_type")
        return value


UserAvatarSerializer = UserAvatarReadSerializer
