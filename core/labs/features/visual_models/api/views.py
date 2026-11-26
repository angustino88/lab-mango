from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.strict_json import StrictObjectJSONParser
from core.labs.features.base.common import FeatureAPIView

from ..application import delete_asset, select_visual_model, update_asset, upload_asset
from ..application.adapters import DjangoModelStorage
from ..contracts import AssetDetails
from ..exceptions import AssetInUse, InvalidModel, ModelConflict, ModelNotFound
from ..queries import get_asset, get_selection, list_assets, list_selections
from ..targets import TARGETS
from .preconditions import VERSION_PRECONDITIONS, expected_version
from .serializers import (
    AssetDetailsSerializer,
    AssetSerializer,
    AssetUploadSerializer,
    SelectionSerializer,
    SelectionWriteSerializer,
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
            return self.respond_problem("conflict", detail=f"{exc} Choose another model for them first.")
        return Response(status=204)


class SelectionListView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Visual Models",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        success=ResponseContract.paginated("VisualModelSelectionList", SelectionSerializer),
    )

    def handle_get(self, request, segment, **kwargs):
        """Resources of one kind with their stored and shown model, e.g. the catalog defaults."""
        if segment not in TARGETS:
            return self.respond_problem("not_found", detail="This resource kind has no 3D model.")
        _, error = self.validate_query()
        return error if error is not None else self.list_response_sync(list_selections(segment))


class SelectionDetailView(FeatureAPIView):
    schema_tags = ("Visual Models",)
    parser_classes = [StrictObjectJSONParser]
    get_contract = OperationContract(
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        success=ResponseContract.success("VisualModelSelection", SelectionSerializer),
    )
    put_contract = OperationContract(
        request=SelectionWriteSerializer,
        bad_request=ResponseContract.bad_request(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
        success=ResponseContract.success("VisualModelSelection", SelectionSerializer),
    )

    def handle_get(self, request, segment, pk, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", detail="This endpoint accepts no query parameters.")
        selection = get_selection(segment, pk) if segment in TARGETS else None
        if selection is None:
            return self.respond_problem("not_found", detail="This resource does not exist.")
        return self.respond(selection)

    def handle_put(self, request, segment, pk, **kwargs):
        """Store which library model this resource shows. Concurrent writes: the last one wins."""
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        try:
            selection = select_visual_model(
                segment, pk, serializer.validated_data["visual_model_id"], actor=request.user
            )
        except ModelNotFound:
            return self.respond_problem("not_found", detail="This resource does not exist.")
        except InvalidModel as exc:
            return self.respond_problem("validation_error", detail=str(exc))
        return self.respond(selection)
