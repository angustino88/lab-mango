"""Shared Django admin building blocks (technical only; imports no business app)."""

from django.contrib import admin

from core.common.models.user_stamped import UserStampedModel

_AUDIT_FIELDS = ("created", "creator", "modified", "last_modified_by")


class UserStampedAdminMixin:
    """Record the admin user on ``UserStampedModel`` rows and show who/when on the change form.

    ``ModelAdmin.save_model`` calls ``obj.save()`` without an actor, so rows written in the admin never
    had ``creator`` / ``last_modified_by`` set. This passes ``actor=request.user`` for the object and
    for inline rows. Models that are not user-stamped are saved exactly as before.
    """

    def save_model(self, request, obj, form, change):
        if isinstance(obj, UserStampedModel):
            obj.save(actor=request.user)
        else:
            super().save_model(request, obj, form, change)  # type: ignore[misc]

    def save_formset(self, request, form, formset, change):
        if not issubclass(formset.model, UserStampedModel):
            super().save_formset(request, form, formset, change)  # type: ignore[misc]
            return
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            obj.save(actor=request.user)
        formset.save_m2m()

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))  # type: ignore[misc]
        if obj is None:
            return fields
        present = {f.name for f in self.model._meta.concrete_fields}  # type: ignore[attr-defined]
        return fields + tuple(name for name in _AUDIT_FIELDS if name in present and name not in fields)


class LabMangoModelAdmin(UserStampedAdminMixin, admin.ModelAdmin):
    """Default base for Lab Mango model admins: stamped saves and a sensible page size."""

    list_per_page = 50
    show_full_result_count = False  # Avoid an extra unfiltered COUNT(*) on large tables.

    #: Relations that ``__str__`` reads, selected for every queryset of this admin (changelist,
    #: autocomplete results, change form). Merged with ``list_select_related`` because Django's
    #: changelist ignores ``list_select_related`` once the queryset already selects related rows.
    label_select_related: tuple[str, ...] = ()

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not self.label_select_related:
            return queryset
        listed = self.list_select_related if isinstance(self.list_select_related, (list, tuple)) else ()
        return queryset.select_related(*self.label_select_related, *listed)


class ReadOnlyModelAdmin(LabMangoModelAdmin):
    """View-only admin for rows that only application code writes: logs, audit trails, telemetry, snapshots.

    Editing such a row by hand would falsify history or reported data, so the admin cannot add, change or
    delete them, even for superusers. ``actions = None`` also removes bulk "delete selected".
    """

    actions = None

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


__all__ = ["LabMangoModelAdmin", "ReadOnlyModelAdmin", "UserStampedAdminMixin"]
