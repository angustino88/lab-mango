from django.db import migrations, models
from django.db.models import Q

STREAM_TYPES = ("equipment", "agent_keys", "users", "agents")
STREAM_CHOICES = [
    ("equipment", "Equipment"),
    ("agent_keys", "Agent keys"),
    ("users", "Users"),
    ("agents", "Agents"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0011_routing_sync_r0"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="routingchange",
            name="routing_change_stream_valid",
        ),
        migrations.AddConstraint(
            model_name="routingchange",
            constraint=models.CheckConstraint(
                condition=Q(entity_type__in=STREAM_TYPES),
                name="routing_change_stream_valid",
            ),
        ),
        migrations.AlterField(
            model_name="routingchange",
            name="entity_type",
            field=models.CharField(choices=STREAM_CHOICES, max_length=32),
        ),
        migrations.RemoveConstraint(
            model_name="routingentity",
            name="routing_entity_stream_valid",
        ),
        migrations.AddConstraint(
            model_name="routingentity",
            constraint=models.CheckConstraint(
                condition=Q(entity_type__in=STREAM_TYPES),
                name="routing_entity_stream_valid",
            ),
        ),
        migrations.AlterField(
            model_name="routingentity",
            name="entity_type",
            field=models.CharField(choices=STREAM_CHOICES, max_length=32),
        ),
        migrations.RemoveConstraint(
            model_name="syncstate",
            name="routing_sync_stream_valid",
        ),
        migrations.AddConstraint(
            model_name="syncstate",
            constraint=models.CheckConstraint(
                condition=Q(entity_type__in=STREAM_TYPES),
                name="routing_sync_stream_valid",
            ),
        ),
        migrations.AlterField(
            model_name="syncstate",
            name="entity_type",
            field=models.CharField(
                choices=STREAM_CHOICES,
                max_length=32,
                primary_key=True,
                serialize=False,
            ),
        ),
    ]
