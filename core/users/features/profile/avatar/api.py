from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppAPIView
from core.common.api.permissions import HasAPIKeyAccess
from core.users.features.profile.application import UploadAvatarInput, delete_avatar, upload_avatar
from core.users.features.profile.contracts import ActorContext
from core.users.features.profile.exceptions import AvatarInvalid, AvatarNotFound
from core.users.features.profile.queries import get_avatar_owner
from core.users.features.profile.serializers import UserAvatarReadSerializer, UserAvatarUploadSerializer


class UserAvatarView(AppAPIView):
    """Retrieve, upload, or delete current authenticated user profile avatar image."""

    schema_tags = ("User Profiles",)
    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    parser_classes = [MultiPartParser]
    avatar_response = ResponseContract.success("UserAvatar", UserAvatarReadSerializer)
    bad_request_response = ResponseContract.problem(400)
    not_found_response = ResponseContract.problem(404)
    delete_response = ResponseContract.no_content()

    get_contract = OperationContract(
        success=avatar_response,
        unauthorized=ResponseContract.unauthorized(),
    )

    def handle_get(self, request: Request, *args, **kwargs):
        user = get_avatar_owner(actor=ActorContext(user_id=request.user.pk))
        return self.respond(user)

    post_contract = OperationContract(
        request=UserAvatarUploadSerializer,
        success=avatar_response,
        bad_request=bad_request_response,
        validation_error=ResponseContract.problem(422),
    )

    def handle_post(self, request: Request, *args, **kwargs):
        # Field-level gate (including image verification) stays at the HTTP boundary.
        serializer, error = self.validate_request(serializer_class=UserAvatarUploadSerializer)
        if error is not None:
            codes = {
                detail.get("code")
                for detail in error.data.get("error", {}).get("details", [])
            }
            if "max_size" in codes:
                error.status_code = 413
                error.data["error"]["code"] = "payload_too_large"
                error.data["error"]["message"] = "Uploaded avatar exceeds the maximum size."
            elif "unsupported_media_type" in codes:
                error.status_code = 415
                error.data["error"]["code"] = "unsupported_media_type"
                error.data["error"]["message"] = "Avatar content type is not supported."
            return error

        try:
            user = upload_avatar(
                actor=ActorContext(user_id=request.user.pk),
                data=UploadAvatarInput(image=serializer.validated_data["avatar"]),
            )
        except AvatarInvalid as exc:
            return self.respond_problem("validation_error", errors=exc.errors, code="validation_failed")
        return self.respond(user)

    delete_contract = OperationContract(
        success=delete_response,
        not_found=not_found_response,
    )

    def handle_delete(self, request: Request, *args, **kwargs):
        try:
            delete_avatar(actor=ActorContext(user_id=request.user.pk))
        except AvatarNotFound:
            return self.respond_problem("not_found", code="no_avatar")
        return Response(status=204)
