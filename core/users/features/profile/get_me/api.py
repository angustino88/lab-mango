from django.contrib.auth import get_user_model
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from core.common.api.api_views import AppAPIView
from core.common.api.permissions import HasAPIKeyAccess
from core.users.features.profile.serializers import UserWithPermissionSerializer

User = get_user_model()


class GetMeView(AppAPIView):
    """Retrieve current authenticated user profile and permissions."""

    schema_tags = ("User Profiles",)
    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    current_user_response = ResponseContract.success("CurrentUser", UserWithPermissionSerializer)

    get_contract = OperationContract(
        success=current_user_response,
        unauthorized=ResponseContract.unauthorized(),
    )

    def handle_get(self, request: Request, *args, **kwargs):
        def _get_user():
            return User.objects.prefetch_related("groups").get(pk=request.user.pk)

        return self.respond(_get_user())
