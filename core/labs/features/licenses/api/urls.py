from django.urls import path

from . import views
from .reference_data import urlpatterns as reference_urlpatterns
from .views import (
    LicenseAgreementListCreateAPIView,
    LicenseAssignActionAPIView,
    LicenseCategorySummaryAPIView,
    LicenseFiltersAPIView,
    LicenseHistoryAPIView,
    LicenseListAPIView,
    LicenseRetrieveAPIView,
    LicenseStatusAPIView,
    LicenseStatusSummaryAPIView,
    LicenseUnassignActionAPIView,
)

urlpatterns = [
    path("licenses/status-summary", LicenseStatusSummaryAPIView.as_view(), name="license-status-summary"),
    path("licenses/categories/summary", LicenseCategorySummaryAPIView.as_view(), name="license-category-summary"),
    path("licenses", LicenseListAPIView.as_view(), name="license-list"),
    path("licenses/filters", LicenseFiltersAPIView.as_view(), name="license-filters"),
    path("licenses/<int:license_id>", LicenseRetrieveAPIView.as_view(), name="license-detail"),
    path("licenses/<int:license_id>/image", views.LicenseImageAPIView.as_view(), name="license-image"),
    path("licenses/<int:license_id>/actions/change-status", LicenseStatusAPIView.as_view(), name="license-change-status"),
    path("licenses/<int:license_id>/history", LicenseHistoryAPIView.as_view(), name="license-history"),
    path("licenses/<int:license_id>/actions/assign", LicenseAssignActionAPIView.as_view(), name="license-action-assign"),
    path("licenses/<int:license_id>/actions/unassign", LicenseUnassignActionAPIView.as_view(), name="license-action-unassign"),
    path("licenses/<int:license_id>/agreements", LicenseAgreementListCreateAPIView.as_view(), name="license-agreements"),

    # License lookup catalogs and options
    path("license-vendors", views.LicenseVendorListAPIView.as_view(), name="license-vendor-list"),
    path("license-vendors/options", views.LicenseVendorOptionsAPIView.as_view(), name="license-vendor-options"),
    path("license-vendors/<int:vendor_id>", views.LicenseVendorDetailAPIView.as_view(), name="license-vendor-detail"),

    path("license-products", views.LicenseProductListAPIView.as_view(), name="license-product-list"),
    path("license-products/options", views.LicenseProductOptionsAPIView.as_view(), name="license-product-options"),
    path("license-products/<int:product_id>", views.LicenseProductDetailAPIView.as_view(), name="license-product-detail"),

    path("license-types", views.LicenseTypeListAPIView.as_view(), name="license-type-list"),
    path("license-types/options", views.LicenseTypeOptionsAPIView.as_view(), name="license-type-options"),
    path("license-types/<int:type_id>", views.LicenseTypeDetailAPIView.as_view(), name="license-type-detail"),

    path("license-categories", views.LicenseCategoryListAPIView.as_view(), name="license-category-list"),
    path("license-categories/options", views.LicenseCategoryOptionsAPIView.as_view(), name="license-category-options"),
    path("license-categories/<int:category_id>", views.LicenseCategoryDetailAPIView.as_view(), name="license-category-detail"),

    path("license-restrictions", views.LicenseRestrictionListAPIView.as_view(), name="license-restriction-list"),
    path("license-restrictions/options", views.LicenseRestrictionOptionsAPIView.as_view(), name="license-restriction-options"),
    path("license-restrictions/<int:restriction_id>", views.LicenseRestrictionDetailAPIView.as_view(), name="license-restriction-detail"),
]
urlpatterns += reference_urlpatterns
