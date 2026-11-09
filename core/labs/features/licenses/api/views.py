from typing import Any

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import OptionsAPIView, OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base import FeatureAPIView
from core.labs.features.licenses import public
from core.labs.features.licenses.api.serializers import (
    LicenseAgreementSerializer,
    LicenseAgreementWriteSerializer,
    LicenseAssignmentRequestSerializer,
    LicenseAssignmentResultSerializer,
    LicenseCategorySerializer,
    LicenseCategorySummarySerializer,
    LicenseListQuerySerializer,
    LicenseProductOptionsQuerySerializer,
    LicenseProductSerializer,
    LicenseRestrictionSerializer,
    LicenseSerializer,
    LicenseStatusSerializer,
    LicenseStatusSummarySerializer,
    LicenseTypeSerializer,
    LicenseVendorSerializer,
)
from core.labs.features.licenses.public import (
    AssignLicenseInput,
    ChangeLicenseStatusInput,
    CreateLicenseAgreementInput,
    UnassignLicenseInput,
)

from ..queries.reference_data import (
    get_license_category,
    get_license_product,
    get_license_restriction,
    get_license_type,
    get_license_vendor,
    list_license_categories,
    list_license_category_options,
    list_license_product_options,
    list_license_products,
    list_license_restriction_options,
    list_license_restrictions,
    list_license_type_options,
    list_license_types,
    list_license_vendor_options,
    list_license_vendors,
)
from ..queries.summaries import get_license_status_summary, list_license_category_summary
from .filters import LICENSE_FILTERS


class LicenseStatusSummaryAPIView(FeatureAPIView):
    """Non-deleted licenses by latest recorded state; no expiry/assignment inference."""

    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseStatusSummaryData", LicenseStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem("bad_request", code="invalid_query", detail="This endpoint accepts no query parameters.")
        return self.respond(get_license_status_summary())


class LicenseCategorySummaryAPIView(AppListAPIView, FeatureAPIView):
    """Inventory counts by category, ordered by name/ID; page and page_size only."""

    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseCategorySummaryList", LicenseCategorySummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        return error if error is not None else self.list_response_sync(list_license_category_summary())


class LicenseListAPIView(AppListAPIView, FeatureAPIView):
    """List non-deleted license inventory with acquisition information."""

    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=LicenseListQuerySerializer,
        success=ResponseContract.paginated("LicenseList", LicenseSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        filters = dict(filters)
        search = filters.pop("search", None) or filters.pop("q", None)
        return self.list_response_sync(LICENSE_FILTERS.apply(public.list_licenses(search=search), filters))


class LicenseFiltersAPIView(FilterMetadataMixin, FeatureAPIView):
    filter_spec = LICENSE_FILTERS
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.success("LicenseFilters", FilterMetadataSerializer),
    )


class LicenseRetrieveAPIView(FeatureAPIView):
    """Retrieve a license's inventory and acquisition information."""

    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseDetail", LicenseSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        license = public.get_license(license_id=license_id)
        if license is None:
            return self.respond_problem("not_found")
        return self.respond(license)


class LicenseAssignmentAPIView(FeatureAPIView):
    """Assign or release a license for equipment (nested route)."""

    schema_tags = ("Licenses",)
    post_contract = OperationContract(
        success=ResponseContract.success("LicenseAssignment", LicenseAssignmentResultSerializer),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, license_id: int, equipment_id: int, *args, **kwargs) -> Response:
        assignment = public.assign_license(
            AssignLicenseInput(equipment_id=equipment_id, license_id=license_id),
            actor=request.user,
        )
        return self.respond(assignment)

    def handle_delete(self, request: Request, license_id: int, equipment_id: int, *args, **kwargs) -> Response:
        assignment = public.unassign_license(
            UnassignLicenseInput(equipment_id=equipment_id, license_id=license_id),
            actor=request.user,
        )
        if assignment is None:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


class LicenseAssignActionAPIView(FeatureAPIView):
    """Assign a license to an equipment via action endpoint (or DELETE to unassign)."""

    schema_tags = ("Licenses",)
    post_contract = OperationContract(
        request=LicenseAssignmentRequestSerializer,
        success=ResponseContract.success("LicenseAssignAction", LicenseAssignmentResultSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    delete_contract = OperationContract(
        request=LicenseAssignmentRequestSerializer,
        success=ResponseContract.no_content(),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assignment = public.assign_license(
            AssignLicenseInput(equipment_id=serializer.validated_data["equipment_id"], license_id=license_id),
            actor=request.user,
        )
        return self.respond(assignment)

    def handle_delete(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assignment = public.unassign_license(
            UnassignLicenseInput(equipment_id=serializer.validated_data["equipment_id"], license_id=license_id),
            actor=request.user,
        )
        if assignment is None:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(
        deprecated=True,
        description="Deprecated alias. Use DELETE /api/labs/licenses/{license_id}/actions/assign instead.",
    ),
)
class LicenseUnassignActionAPIView(FeatureAPIView):
    """Release a license from an equipment via action endpoint."""

    schema_tags = ("Licenses",)
    post_contract = OperationContract(
        request=LicenseAssignmentRequestSerializer,
        success=ResponseContract.no_content(),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        license_id = kwargs.get("license_id")
        if license_id:
            response["Link"] = f'</api/labs/licenses/{license_id}/actions/assign>; rel="successor-version"'
        return response

    def handle_post(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assignment = public.unassign_license(
            UnassignLicenseInput(equipment_id=serializer.validated_data["equipment_id"], license_id=license_id),
            actor=request.user,
        )
        if assignment is None:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


class LicenseStatusAPIView(FeatureAPIView):
    """Record a new status for a license record."""

    schema_tags = ("Licenses",)
    post_contract = OperationContract(
        request=LicenseStatusSerializer,
        success=ResponseContract.success("LicenseDetail", LicenseSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        status_record = public.change_license_status(
            ChangeLicenseStatusInput(license_id=license_id, **serializer.validated_data),
            actor=request.user,
        )
        license_record = public.get_license(license_id=status_record.license_id)
        return self.respond(license_record)


class LicenseAgreementListCreateAPIView(AppListAPIView, FeatureAPIView):
    """List and create commercial agreements for a license."""

    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseAgreementList", LicenseAgreementSerializer),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=LicenseAgreementWriteSerializer,
        success=ResponseContract.created("LicenseAgreement", LicenseAgreementSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        if public.get_active_license(license_id=license_id) is None:
            return self.respond_problem("not_found")
        return self.list_response_sync(public.list_license_agreements(license_id=license_id))

    def handle_post(self, request: Request, license_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        agreement = public.create_license_agreement(
            CreateLicenseAgreementInput(license_id=license_id, **serializer.validated_data),
            actor=request.user,
        )
        return self.respond(agreement)


# Vendors
class LicenseVendorListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseVendorCatalogList", LicenseVendorSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_license_vendors())


class LicenseVendorDetailAPIView(FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseVendorCatalogDetail", LicenseVendorSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, vendor_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_license_vendor(vendor_id=vendor_id))


class LicenseVendorOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.LARGE
    owner = "licenses"
    schema_tags = ("Licenses",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_license_vendor_options(actor=actor, **filters)


# Products
class LicenseProductListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=LicenseProductOptionsQuerySerializer,
        success=ResponseContract.paginated("LicenseProductCatalogList", LicenseProductSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_license_products(vendor_id=query.get("vendor_id") if query else None))


class LicenseProductDetailAPIView(FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseProductCatalogDetail", LicenseProductSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, product_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_license_product(product_id=product_id))


class LicenseProductOptionsAPIView(OptionsAPIView):
    query_serializer = LicenseProductOptionsQuerySerializer
    size_class = SizeClass.LARGE
    owner = "licenses"
    schema_tags = ("Licenses",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_license_product_options(actor=actor, **filters)


# Types
class LicenseTypeListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseTypeCatalogList", LicenseTypeSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_license_types())


class LicenseTypeDetailAPIView(FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseTypeCatalogDetail", LicenseTypeSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, type_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_license_type(type_id=type_id))


class LicenseTypeOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "licenses"
    schema_tags = ("Licenses",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_license_type_options(actor=actor, **filters)


# Categories
class LicenseCategoryListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseCategoryCatalogList", LicenseCategorySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_license_categories())


class LicenseCategoryDetailAPIView(FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseCategoryCatalogDetail", LicenseCategorySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, category_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_license_category(category_id=category_id))


class LicenseCategoryOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "licenses"
    schema_tags = ("Licenses",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_license_category_options(actor=actor, **filters)


# Restrictions
class LicenseRestrictionListAPIView(AppListAPIView, FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("LicenseRestrictionCatalogList", LicenseRestrictionSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_license_restrictions())


class LicenseRestrictionDetailAPIView(FeatureAPIView):
    schema_tags = ("Licenses",)
    get_contract = OperationContract(
        success=ResponseContract.success("LicenseRestrictionCatalogDetail", LicenseRestrictionSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, restriction_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_license_restriction(restriction_id=restriction_id))


class LicenseRestrictionOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "licenses"
    schema_tags = ("Licenses",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_license_restriction_options(actor=actor, **filters)


__all__ = (
    "LicenseAgreementListCreateAPIView",
    "LicenseAssignActionAPIView",
    "LicenseAssignmentAPIView",
    "LicenseCategoryDetailAPIView",
    "LicenseCategoryListAPIView",
    "LicenseCategoryOptionsAPIView",
    "LicenseListAPIView",
    "LicenseProductDetailAPIView",
    "LicenseProductListAPIView",
    "LicenseProductOptionsAPIView",
    "LicenseRestrictionDetailAPIView",
    "LicenseRestrictionListAPIView",
    "LicenseRestrictionOptionsAPIView",
    "LicenseRetrieveAPIView",
    "LicenseStatusAPIView",
    "LicenseTypeDetailAPIView",
    "LicenseTypeListAPIView",
    "LicenseTypeOptionsAPIView",
    "LicenseUnassignActionAPIView",
    "LicenseVendorDetailAPIView",
    "LicenseVendorListAPIView",
    "LicenseVendorOptionsAPIView",
)
