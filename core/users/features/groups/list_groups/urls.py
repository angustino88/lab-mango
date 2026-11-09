from django.urls import path

from .api import ListGroupUserView, ListUsersInGroupView

urlpatterns = [
    path("user-groups/<int:group_id>/users", ListUsersInGroupView.as_view(), name="user-group-users"),
    path("user-groups", ListGroupUserView.as_view(), name="user-groups"),
]
