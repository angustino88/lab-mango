"""Read-only procurement collection queries."""

from django.db.models import Count, QuerySet

from core.labs.models import Purchase, PurchaseItem, PurchaseItemResource, PurchasePriority, PurchaseTransaction


def get_purchase(*, purchase_id: int) -> Purchase:
    return (
        Purchase.objects.annotate(item_count=Count("items"))
        .filter(pk=purchase_id)
        .get()
    )


def get_purchase_item(*, purchase_id: int, item_id: int) -> PurchaseItem:
    return (
        PurchaseItem.objects.select_related("priority", "purchase")
        .filter(purchase_id=purchase_id, pk=item_id)
        .get()
    )


def list_purchase_priorities(*, include_inactive: bool = False) -> QuerySet[PurchasePriority]:
    priorities = PurchasePriority.objects.all()
    if not include_inactive:
        priorities = priorities.filter(is_active=True)
    return priorities.order_by("-rank", "id")


def list_purchases() -> QuerySet[Purchase]:
    return (
        Purchase.objects.annotate(item_count=Count("items"))
        .prefetch_related("items")
        .order_by("-purchase_date", "-pk")
    )


def list_purchase_items(*, purchase_id: int) -> QuerySet[PurchaseItem]:
    # Raises Purchase.DoesNotExist (mapped to 404) when the parent purchase is missing.
    Purchase.objects.get(pk=purchase_id)
    return PurchaseItem.objects.filter(purchase_id=purchase_id).select_related("priority").order_by("pk")


def list_purchase_item_resources(*, purchase_item_id: int) -> QuerySet[PurchaseItemResource]:
    PurchaseItem.objects.get(pk=purchase_item_id)
    return (
        PurchaseItemResource.objects.filter(purchase_item_id=purchase_item_id)
        .select_related("resource_type", "purchase_item__purchase")
        .prefetch_related("resource")
        .order_by("pk")
    )


def list_purchase_transactions(*, purchase_id: int) -> QuerySet[PurchaseTransaction]:
    Purchase.objects.get(pk=purchase_id)
    return PurchaseTransaction.objects.filter(purchase_id=purchase_id).order_by("-settled_at", "-pk")


__all__ = [
    "get_purchase",
    "get_purchase_item",
    "list_purchase_priorities",
    "list_purchase_item_resources",
    "list_purchase_items",
    "list_purchase_transactions",
    "list_purchases",
]
