from django.db import models


class LabManagementEmail(models.Model):
    display_name = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.display_name if self.display_name else self.email
