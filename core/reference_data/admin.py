from django.contrib import admin


class ProtectedReferenceAdmin(admin.ModelAdmin):
    """Admin policy that disables instance and bulk deletion."""

    actions = None
    def has_delete_permission(self, request, obj=None) -> bool:
        return False


__all__ = ["ProtectedReferenceAdmin"]
