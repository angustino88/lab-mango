"""Lab Mango admin site: branded header and an index that starts with people and access.

The default ``admin.site`` is this class (``LabMangoAdminConfig`` in ``INSTALLED_APPS``), so every
``admin.register`` call keeps working unchanged.
"""

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig

# Apps shown first on the admin index, in this order; every other app follows alphabetically.
ADMIN_APP_ORDER = ("users", "auth", "labs", "support_desk")


class LabMangoAdminSite(AdminSite):
    site_header = "Lab Mango administration"
    site_title = "Lab Mango admin"
    index_title = "Administration"

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        rank = {label: index for index, label in enumerate(ADMIN_APP_ORDER)}
        return sorted(apps, key=lambda app: (rank.get(app["app_label"], len(rank)), app["name"].lower()))


class LabMangoAdminConfig(AdminConfig):
    default_site = "config.admin_site.LabMangoAdminSite"
