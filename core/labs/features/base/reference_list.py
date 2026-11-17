"""Reusable list API endpoint template for reference data."""

from drf_api_contracts import OperationContract, ResponseContract

from core.common.api.api_views import AppListAPIView

from .common import FeatureAPIView


class ReferenceDataListAPIView(AppListAPIView, FeatureAPIView):
    """Base endpoint for active, non-deleted reference-data lists."""

    model = None
    serializer_class = None
    entity_name = None
    openapi_list_response = True
    required_attributes = ("model", "serializer_class", "entity_name")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        serializer_class = getattr(cls, "serializer_class", None)
        if serializer_class is None:
            return
        cls.get_contract = OperationContract(
            success=ResponseContract.paginated(cls.__name__, serializer_class),
        )

    def get_queryset(self):
        queryset = self.model.objects.all()
        field_names = {field.name for field in self.model._meta.get_fields()}
        if "deleted_at" in field_names:
            queryset = queryset.filter(deleted_at__isnull=True)
        elif "is_delete" in field_names:
            queryset = queryset.filter(is_delete=False)
        if "active" in field_names:
            queryset = queryset.filter(active=True)
        return queryset

    def handle_get(self, request, *args, **kwargs):
        self.validate_configuration()
        return self.list_response_sync(self.get_queryset())
