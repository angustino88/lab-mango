from django.urls import path

from . import views

urlpatterns = [
    path(
        "workbook-imports/template",
        views.WorkbookImportTemplateAPIView.as_view(),
        name="workbook-import-template",
    ),
    path(
        "workbook-imports/export",
        views.WorkbookExportAPIView.as_view(),
        name="workbook-import-export",
    ),
    path(
        "workbook-imports/actions/check",
        views.WorkbookImportCheckAPIView.as_view(),
        name="workbook-import-action-check",
    ),
    path(
        "workbook-imports/actions/apply",
        views.WorkbookImportApplyAPIView.as_view(),
        name="workbook-import-action-apply",
    ),
]
