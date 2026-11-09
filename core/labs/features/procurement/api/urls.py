from django.urls import path

# Register drf-spectacular serializer schema extensions.
from . import schema as _schema  # noqa: F401
from .views import (
    PurchaseDetailAPIView,
    PurchaseDraftHeaderAPIView,
    PurchaseDraftLineDetailAPIView,
    PurchaseDraftLineListCreateAPIView,
    PurchaseItemListCreateAPIView,
    PurchaseItemResourceListCreateAPIView,
    PurchaseListCreateAPIView,
    PurchasePriorityOptionsAPIView,
    PurchaseTransactionListCreateAPIView,
)

urlpatterns = [
    path("purchase-priorities", PurchasePriorityOptionsAPIView.as_view(), name="purchase-priority-options"),
    path("purchases", PurchaseListCreateAPIView.as_view(), name="purchase-list"),
    path("purchases/<int:purchase_id>", PurchaseDetailAPIView.as_view(), name="purchase-detail"),
    path("purchases/<int:purchase_id>/draft", PurchaseDraftHeaderAPIView.as_view(), name="purchase-draft-header"),
    path(
        "purchases/<int:purchase_id>/items/draft",
        PurchaseDraftLineListCreateAPIView.as_view(),
        name="purchase-draft-line-list",
    ),
    path(
        "purchases/<int:purchase_id>/items/<int:item_id>",
        PurchaseDraftLineDetailAPIView.as_view(),
        name="purchase-draft-line-detail",
    ),
    path(
        "purchases/<int:purchase_id>/items",
        PurchaseItemListCreateAPIView.as_view(),
        name="purchase-item-list",
    ),
    path(
        "purchase-items/<int:purchase_item_id>/resources",
        PurchaseItemResourceListCreateAPIView.as_view(),
        name="purchase-item-resource-list",
    ),
    path(
        "purchases/<int:purchase_id>/transactions",
        PurchaseTransactionListCreateAPIView.as_view(),
        name="purchase-transaction-list",
    ),
]
