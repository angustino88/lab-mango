from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from core.labs.admin import EquipmentCategoryAdmin, EquipmentKindAdmin
from core.labs.models import EquipmentCategory, EquipmentKind
from core.reference_data.admin import ProtectedReferenceAdmin


class EquipmentKindAdminTests(SimpleTestCase):
    def test_category_relation_uses_label_visible_foreign_key_chooser(self):
        model_admin = admin.site._registry[EquipmentKind]
        category_field = EquipmentKind._meta.get_field("category")

        self.assertIsInstance(model_admin, EquipmentKindAdmin)
        self.assertNotIn("category", model_admin.autocomplete_fields)
        self.assertNotIn("category", model_admin.raw_id_fields)
        self.assertEqual(category_field.remote_field.model, EquipmentCategory)

    def test_category_field_uses_readable_foreign_key_widget(self):
        model_admin = admin.site._registry[EquipmentKind]

        request = RequestFactory().get("/admin/")
        request.user = AnonymousUser()
        form = model_admin.get_form(request)()
        self.assertNotEqual(form.fields["category"].widget.__class__.__name__, "ForeignKeyRawIdWidget")
        self.assertEqual(str(EquipmentCategory(name="Debugging")), "Debugging")

    def test_category_admin_uses_default_string_representation(self):
        category_admin = admin.site._registry[EquipmentCategory]

        self.assertIsInstance(category_admin, EquipmentCategoryAdmin)
        self.assertEqual(str(EquipmentCategory(name="Computing")), "Computing")

    def test_category_cannot_be_deleted_through_admin(self):
        model_admin = admin.site._registry[EquipmentCategory]

        request = HttpRequest()
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertIsInstance(model_admin, ProtectedReferenceAdmin)
        self.assertIsNone(model_admin.actions)

    def test_category_cannot_be_added_or_changed_through_admin(self):
        model_admin = admin.site._registry[EquipmentCategory]

        request = HttpRequest()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, EquipmentCategory(name="Computing")))
        self.assertIsNone(model_admin.actions)
