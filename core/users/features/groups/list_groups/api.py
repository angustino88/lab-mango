from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Count
from drf_api_contracts import (
    OperationContract,
    ResponseContract,
)
from rest_framework import serializers

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.users.access import IsLabAdminReadWrite


class UserGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    user_count = serializers.IntegerField(read_only=True)
    users_url = serializers.SerializerMethodField()

    def get_users_url(self, group) -> str:
        request = self.context.get("request")
        path = f"/api/user-groups/{group.pk}/users"
        return request.build_absolute_uri(path) if request is not None else path


class UserGroupMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source="username", read_only=True)


class UserGroupMembersQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class ListGroupUserView(AppListAPIView):
    """List user authorization groups with membership counts."""

    schema_tags = ("User Groups",)
    # Group membership shows who holds which role: lab administrators only.
    permission_classes = [IsLabAdminReadWrite]
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("UserGroupList", UserGroupSerializer),
        bad_request=ResponseContract.bad_request(),
        unauthorized=ResponseContract.unauthorized(),
        forbidden=ResponseContract.forbidden(),
    )

    def handle_get(self, request, *args, **kwargs):
        _, error = self.validate_query()
        if error is not None:
            return error
        queryset = Group.objects.annotate(user_count=Count("user")).order_by("name", "pk")
        return self.list_response_sync(queryset)


class ListUsersInGroupView(AppListAPIView):
    """List members belonging to a specific user group."""

    schema_tags = ("User Groups",)
    # Group membership shows who holds which role: lab administrators only.
    permission_classes = [IsLabAdminReadWrite]
    get_contract = OperationContract(
        query=UserGroupMembersQuerySerializer,
        success=ResponseContract.paginated("UserGroupMemberList", UserGroupMemberSerializer),
        bad_request=ResponseContract.bad_request(),
        unauthorized=ResponseContract.unauthorized(),
        forbidden=ResponseContract.forbidden(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request, group_id: int, *args, **kwargs):
        user_model = get_user_model()
        if not Group.objects.filter(pk=group_id).exists():
            return self.respond_problem("not_found")
        users = user_model.objects.filter(groups__id=group_id).only("id", "username").order_by("username", "pk")
        return self.list_response_sync(users)
