from django.contrib.auth import get_user_model
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_api_key.permissions import KeyParser

from core.common.api.api_views import AppDetailAPIView, AppListAPIView
from core.common.api.pagination import with_page_query
from core.common.api.permissions import HasAPIKeyAccess, api_key_access_enabled
from core.users.features.profile.application import UpdateUserInput, update_user
from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import UserNotFound
from core.users.features.profile.queries import get_visible_user, visible_users_for
from core.users.features.profile.serializers import UserSerializer

User = get_user_model()


def _is_api_client(request) -> bool:
    """True when the caller presents an API key and is not a logged-in user.

    HasAPIKeyAccess does not attach the key object to the request, so the key header is checked directly.
    A JWT-authenticated user is always scoped as a normal user, even if a key header is also sent.
    """
    if request.user and request.user.is_authenticated:
        return False
    return api_key_access_enabled() and bool(KeyParser().get(request))


def _actor(request) -> ActorContext:
    return ActorContext(user_id=getattr(request.user, "pk", 0) or 0)


class UsersListQuerySerializer(drf_serializers.Serializer):
    username = drf_serializers.CharField(required=False, allow_blank=False)


class ListUsersView(AppListAPIView):
    """List visible system users with optional username filtering."""

    schema_tags = ("User Profiles",)
    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    get_contract = OperationContract(
        query=with_page_query(UsersListQuerySerializer),
        success=ResponseContract.paginated("Users", UserSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request, *args, **kwargs):
        filters, error = self.validate_query()
        if error is not None:
            return error
        queryset = visible_users_for(
            actor=_actor(request),
            is_staff=getattr(request.user, "is_staff", False),
            is_api_client=_is_api_client(request),
        )
        if username := filters.get("username"):
            queryset = queryset.filter(username=username)
        return self.list_response_sync(queryset)


class _UpdateUserSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["display_name", "name", "department"]
        extra_kwargs = {f: {"required": False} for f in ["display_name", "name", "department"]}


class RetrieveUserView(AppDetailAPIView):
    """Retrieve or partially update a specific user profile."""

    schema_tags = ("User Profiles",)
    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    success_response = ResponseContract.success("User", UserSerializer)
    not_found_response = ResponseContract.problem(status.HTTP_404_NOT_FOUND)
    get_contract = OperationContract(
        success=success_response,
        not_found=not_found_response,
        bad_request=ResponseContract.bad_request(),
    )
    patch_contract = OperationContract(
        request=_UpdateUserSerializer,
        success=success_response,
        bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
        not_found=not_found_response,
    )

    def handle_get(self, request, pk: int, *args, **kwargs):
        user = get_visible_user(
            actor=_actor(request),
            is_staff=getattr(request.user, "is_staff", False),
            pk=pk,
            is_api_client=_is_api_client(request),
        )
        if user is None:
            return self.respond_problem("not_found", code="user_not_found")
        return self.respond(user)

    def handle_patch(self, request, pk: int, *args, **kwargs):
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        try:
            user = update_user(
                actor=_actor(request),
                target_pk=pk,
                data=UpdateUserInput(values=serializer.validated_data),
                is_staff=getattr(request.user, "is_staff", False),
                is_api_client=_is_api_client(request),
            )
        except UserNotFound:
            return self.respond_problem("not_found", code="user_not_found")
        return self.respond(user)
