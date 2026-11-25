from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base.common import FeatureAPIView

from ..application import remove_model, save_model
from ..application.adapters import DjangoModelStorage
from ..contracts import SaveModelInput
from ..exceptions import InvalidModel, ModelConflict
from ..queries import list_models
from .preconditions import MODEL_PRECONDITIONS, expected_version
from .serializers import ModelSerializer, ModelWriteSerializer, multipart_model_data
from .uploads import ModelSizeLimit


class ModelListView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Visual Models",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.paginated("VisualModelList", ModelSerializer),
    )

    def handle_get(self, request, **kwargs):
        _, error = self.validate_query()
        return error if error is not None else self.list_response_sync(list_models())


class ModelDetailView(FeatureAPIView):
    schema_tags = ("Visual Models",)
    parser_classes = [MultiPartParser]
    put_contract = OperationContract(
        request=ModelWriteSerializer,
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.success("VisualModel", ModelSerializer),
        validation_error=ResponseContract.problem(422),
        payload_too_large=ResponseContract.problem(413),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=MODEL_PRECONDITIONS,
    )
    delete_contract = OperationContract(
        bad_request=ResponseContract.bad_request(),
        success=ResponseContract.no_content(),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=MODEL_PRECONDITIONS,
    )

    def initialize_request(self, request, *args, **kwargs):
        if request.method == "PUT":
            request.upload_handlers.insert(0, ModelSizeLimit(request))
        return super().initialize_request(request, *args, **kwargs)

    def handle_put(self, request, scope, target_key, **kwargs):
        version = expected_version(request, allow_create=True)
        try:
            values = multipart_model_data(request.data)
        except ValidationError as exc:
            return self.respond_problem("validation_error", code="validation_failed", errors=exc.detail)
        serializer, error = self.validate_request(serializer_class=ModelWriteSerializer, data=values)
        if error is not None:
            return error
        assert serializer is not None
        values = dict(serializer.validated_data)
        file = values.pop("file", None)
        if len(request.FILES.getlist("file")) > 1:
            return self.respond_problem("validation_error", detail="Attach exactly one GLB file.")
        try:
            model = save_model(
                SaveModelInput(
                    scope=scope,
                    target_key=target_key,
                    content=file.read() if file else None,
                    expected_version=version,
                    **values,
                ),
                actor=request.user,
                storage=DjangoModelStorage(),
            )
        except InvalidModel as exc:
            return self.respond_problem("validation_error", detail=str(exc))
        except ModelConflict:
            return self.respond_problem(
                "precondition_failed", detail="This model changed. Reload the library before saving."
            )
        response = self.respond(model)
        response["ETag"] = f'"{model.version}"'
        return response

    def handle_delete(self, request, scope, target_key, **kwargs):
        if request.query_params:
            return self.respond_problem("bad_request", detail="This endpoint accepts no query parameters.")
        version = expected_version(request)
        try:
            remove_model(
                scope=scope,
                target_key=target_key,
                actor=request.user,
                storage=DjangoModelStorage(),
                expected_version=version,
            )
        except ModelConflict:
            return self.respond_problem(
                "precondition_failed", detail="This model changed. Reload the library before removing."
            )
        return Response(status=204)
