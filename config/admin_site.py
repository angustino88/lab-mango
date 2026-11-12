"""Lab Mango admin site: branded header and an index grouped by what an operator is doing.

Django groups the admin index by app label, which puts reference catalogs, live resources, bookings and
telemetry into one long "Labs" list. This site regroups the index and sidebar into functional sections
(``ADMIN_SECTIONS``). Only navigation changes: every model keeps its ``/admin/<app_label>/<model>/`` URL,
its permissions and its app index page. Models not listed in a section keep their original app group after
the sections, so a newly registered model is never hidden.

Entries are ``"app_label.ModelName"`` strings so this module imports no business app.

The default ``admin.site`` is this class (``LabMangoAdminConfig`` in ``INSTALLED_APPS``), so every
``admin.register`` call keeps working unchanged.
"""

from dataclasses import dataclass

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import path, reverse


@dataclass(frozen=True)
class AdminSection:
    slug: str
    name: str
    models: tuple[str, ...]


ADMIN_SECTIONS: tuple[AdminSection, ...] = (
    AdminSection(
        "people-and-access",
        "People and access",
        (
            "users.User",
            "users.URSGroup",
            "users.PrivilegedUser",
            "users.RoleAuditEvent",
            "users.EntraIdentity",
            "auth.Group",
            "account.EmailAddress",
            "socialaccount.SocialAccount",
        ),
    ),
    AdminSection(
        "reference-locations",
        "Reference data · Locations",
        ("labs.Country", "labs.City", "labs.Building", "labs.StationType"),
    ),
    AdminSection(
        "reference-equipment",
        "Reference data · Equipment catalog",
        (
            "labs.EquipmentCategory",
            "labs.EquipmentKind",
            "labs.EquipmentType",
            "labs.EquipmentManufacturer",
            "labs.EquipmentProductModel",
            "labs.SpecificationDefinition",
            "labs.EquipmentInterface",
            "labs.Material",
            "labs.NetworkingProtocol",
            "labs.DisplaySize",
            "labs.DisplayResolution",
            "labs.SampleCustomer",
            "labs.SampleCharacteristic",
        ),
    ),
    AdminSection(
        "reference-licenses",
        "Reference data · License catalog",
        (
            "labs.LicenseVendor",
            "labs.LicenseProduct",
            "labs.LicenseType",
            "labs.LicenseCategory",
            "labs.LicenseRestriction",
        ),
    ),
    AdminSection(
        "reference-organisation",
        "Reference data · Departments, teams, benches and projects",
        (
            "labs.Department",
            "labs.Team",
            "labs.BenchGroup",
            "labs.BenchType",
            "labs.LabProject",
            "labs.PurchasePriority",
            "labs.TechnicalUser",
        ),
    ),
    AdminSection(
        "lab-resources",
        "Lab resources",
        (
            "labs.Room",
            "labs.RoomSlot",
            "labs.Station",
            "labs.StationSlot",
            "labs.Bench",
            "labs.Equipment",
            "labs.ComputingProfile",
        ),
    ),
    AdminSection(
        "bookings",
        "Bookings",
        ("labs.BenchBooking", "labs.EquipmentBooking", "labs.BenchFavorite"),
    ),
    AdminSection(
        "monitoring",
        "Monitoring and activity",
        (
            "labs.ComputingActivity",
            "labs.LabSessionLog",
            "labs.MonitoringEvent",
            "labs.LaboratoryVisitEvent",
            "labs.StorageQuotaMeasurement",
        ),
    ),
    AdminSection(
        "analytics",
        "Analytics observations",
        (
            "labs.ActiveUserObservation",
            "labs.ActiveLaboratoryObservation",
            "labs.BookingVolumeObservation",
            "labs.BookingOutcomeObservation",
            "labs.VisitorVolumeObservation",
            "labs.ResourceUtilizationObservation",
            "labs.LaboratoryAvailabilityObservation",
            "labs.ProjectUsageObservation",
        ),
    ),
    AdminSection(
        "status-history-and-audit",
        "Status history and audit",
        (
            "labs.RoomStatusRecord",
            "labs.StationStatusRecord",
            "labs.EquipmentEvent",
            "labs.ResourceAudit",
            "labs.ResourceChangeLog",
        ),
    ),
    AdminSection(
        "configuration",
        "Configuration and notifications",
        (
            "users.LabManagementEmail",
            "websocket.Notification",
            "sites.Site",
            "socialaccount.SocialApp",
        ),
    ),
    AdminSection(
        "scheduled-tasks",
        "Scheduled tasks",
        (
            "django_celery_beat.PeriodicTask",
            "django_celery_beat.CrontabSchedule",
            "django_celery_beat.IntervalSchedule",
            "django_celery_beat.ClockedSchedule",
            "django_celery_beat.SolarSchedule",
        ),
    ),
    AdminSection(
        "api-access-and-tokens",
        "API access and tokens",
        (
            "rest_framework_api_key.APIKey",
            "socialaccount.SocialToken",
            "token_blacklist.OutstandingToken",
            "token_blacklist.BlacklistedToken",
        ),
    ),
)


class LabMangoAdminSite(AdminSite):
    site_header = "Lab Mango administration"
    site_title = "Lab Mango admin"
    index_title = "Administration"

    sections: tuple[AdminSection, ...] = ADMIN_SECTIONS

    def get_urls(self):
        # Before the default patterns so the final catch-all view never shadows section pages.
        section_urls = [
            path("sections/<slug:slug>/", self.admin_view(self.section_index), name="section"),
        ]
        return section_urls + super().get_urls()

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        if app_label is not None:
            # The per-app page (/admin/<app_label>/) keeps Django's grouping.
            return apps
        return self._group_into_sections(apps)

    def _group_into_sections(self, apps):
        by_key = {}
        for app in apps:
            for model in app["models"]:
                by_key[f"{app['app_label']}.{model['object_name']}"] = model

        grouped = []
        placed: set[str] = set()
        for section in self.sections:
            models = [by_key[key] for key in section.models if key in by_key]
            if not models:
                continue  # The user may see nothing in this section.
            placed.update(key for key in section.models if key in by_key)
            grouped.append(
                {
                    "name": section.name,
                    "app_label": section.slug,
                    "app_url": reverse(f"{self.name}:section", kwargs={"slug": section.slug}),
                    "has_module_perms": True,
                    "models": models,
                }
            )

        for app in apps:
            rest = [m for m in app["models"] if f"{app['app_label']}.{m['object_name']}" not in placed]
            if rest:
                grouped.append({**app, "models": rest})
        return grouped

    def section_index(self, request, slug):
        section_list = [app for app in self.get_app_list(request) if app["app_label"] == slug]
        if not any(section.slug == slug for section in self.sections) or not section_list:
            raise Http404("The requested admin page does not exist.")
        context = {
            **self.each_context(request),
            "title": section_list[0]["name"],
            "subtitle": None,
            "app_list": section_list,
            "app_label": slug,
        }
        request.current_app = self.name
        return TemplateResponse(request, "admin/app_index.html", context)


class LabMangoAdminConfig(AdminConfig):
    default_site = "config.admin_site.LabMangoAdminSite"
