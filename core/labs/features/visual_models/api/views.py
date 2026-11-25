from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.strict_json import StrictObjectJSONParser
from core.labs.features.base.common import FeatureAPIView

from ..application import assign_model, delete_asset, unassign_model, update_asset, upload_asset
from ..application.adapters import DjangoModelStorage
from ..contracts import AssetDetails, AssignmentFit
from ..exceptions import AssetInUse, InvalidModel, ModelConflict, ModelNotFound
from ..queries import get_asset, list_assets, list_assignments
from .preconditions import CREATE_OR_VERSION_PRECONDITIONS, VERSION_PRECONDITIONS, expected_version
from .serializers import (
    AssetDetailsSerializer,
    AssetSerializer,
    AssetUploadSerializer,
    AssignmentSerializer,
    AssignmentWriteSerializer,
    multipart_model_data,
)
from .uploads import ModelSizeLimit

STALE = "This model changed. Reload the library and try again."


def _with_etag(response: Response, version: int) -> Response:
    response["ETag"] = f'"{version}"'
    return response


class AssetListView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Visual Models",)
    parser_classes = [MultiPartParser]
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.paginated("VisualModelAssetList", AssetSerializer),
    )
    post_contract = OperationContract(
        request=AssetUploadSerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.created("VisualModelAsset", AssetSerializer),
        existing=ResponseContract.success("VisualModelAssetExisting", AssetSerializer),
        validation_error=ResponseContract.problem(422),
        payload_too_large=ResponseContract.problem(413),
    )

    def initialize_request(self, request, *args, **kwargs):
        if request.method == "POST":
            request.upload_handlers.insert(0, ModelSizeLimit(request))
        return super().initialize_request(request, *args, **kwargs)

    def handle_get(self, request, **kwargs):
        _, error = self.validate_query()
        return error if error is not None else self.list_response_sync(list_assets())

    def handle_post(self, request, **kwargs):
        """Add a GLB to the library. Uploading bytes already in the library returns that asset with 200."""
        try:
            values = multipart_model_data(request.data)
        except ValidationError as exc:
            return self.respond_problem("validation_error", code="validation_failed", errors=exc.detail)
        serializer, error = self.validate_request(serializer_class=AssetUploadSerializer, data=values)
        if error is not None:
            return error
        assert serializer is not None
        values = dict(serializer.validated_data)
        file = values.pop("file")
        try:
            asset, created = upload_asset(
                file.read(), AssetDetails(**values), actor=request.user, storage=DjangoModelStorage()
            )
        except InvalidModel as exc:
            return self.respond_problem("validation_error", detail=str(exc))
        asset = get_asset(asset.pk)
        if created:
            return _with_etag(self.respond(asset), asset.version)
        existing = self.operation().responses.get("existing")
        return _with_etag(existing.serialize(asset, context={"request": request}), asset.version)


class AssetDetailView(FeatureAPIView):
    schema_tags = ("Visual Models",)
    parser_classes = [StrictObjectJSONParser]
    put_contract = OperationContract(
        request=AssetDetailsSerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.success("VisualModelAsset", AssetSerializer),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=VERSION_PRECONDITIONS,
    )
    delete_contract = OperationContract(
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=VERSION_PRECONDITIONS,
    )

    def handle_put(self, request, asset_id, **kwargs):
        version = expected_version(request)
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        try:
            update_asset(
                asset_id, AssetDetails(**serializer.validated_data), expected_version=version, actor=request.user
            )
        except ModelNotFound:
            return self.respond_problem("not_found", detail="This model is not in the library.")
        except InvalidModel as exc:
            return self.respond_problem("validation_error", detail=str(exc))
        except ModelConflict:
            return self.respond_problem("precondition_failed", detail=STALE)
        asset = get_asset(asset_id)
        return _with_etag(self.respond(asset), asset.version)

    def handle_delete(self, request, asset_id, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", detail="This endpoint accepts no query parameters.")
        version = expected_version(request)
        try:
            delete_asset(asset_id, expected_version=version, actor=request.user, storage=DjangoModelStorage())
        except ModelNotFound:
            return self.respond_problem("not_found", detail="This model is not in the library.")
        except ModelConflict:
            return self.respond_problem("precondition_failed", detail=STALE)
        except AssetInUse as exc:
            return self.respond_problem("conflict", detail=f"{exc} Remove those assignments first.")
        return Response(status=204)


class AssignmentListView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Visual Models",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.paginated("VisualModelAssignmentList", AssignmentSerializer),
    )

    def handle_get(self, request, **kwargs):
        _, error = self.validate_query()
        return error if error is not None else self.list_response_sync(list_assignments())


class AssignmentDetailView(FeatureAPIView):
    schema_tags = ("Visual Models",)
    parser_classes = [StrictObjectJSONParser]
    put_contract = OperationContract(
        request=AssignmentWriteSerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.success("VisualModelAssignment", AssignmentSerializer),
        validation_error=ResponseContract.problem(422),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=CREATE_OR_VERSION_PRECONDITIONS,
    )
    delete_contract = OperationContract(
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=VERSION_PRECONDITIONS,
    )

    def handle_put(self, request, scope, target_key, **kwargs):
        """Assign a library model to a target. Send If-None-Match: * to create, If-Match to update."""
        version = expected_version(request, allow_create=True)
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        try:
            assignment = assign_model(
                scope,
                target_key,
                AssignmentFit(**serializer.validated_data),
                expected_version=version,
                actor=request.user,
            )
        except InvalidModel as exc:
            return self.respond_problem("validation_error", detail=str(exc))
        except ModelConflict:
            return self.respond_problem("precondition_failed", detail=STALE)
        return _with_etag(self.respond(assignment), assignment.version)

    def handle_delete(self, request, scope, target_key, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", detail="This endpoint accepts no query parameters.")
        version = expected_version(request)
        try:
            unassign_model(scope, target_key, expected_version=version, actor=request.user)
        except ModelNotFound:
            return self.respond_problem("not_found", detail="This resource has no model assigned.")
        except ModelConflict:
            return self.respond_problem("precondition_failed", detail=STALE)
        return Response(status=204)
