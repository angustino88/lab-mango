"""Initial Support Desk schema: one migration (ADR 005, consolidated 2026-11-12; no deployed database).

Hand-written: pg_trgm for the label search index (first); the ticket number sequence and the
insert-only TicketActivity trigger (last).
"""

import django.contrib.postgres.indexes
import django.core.validators
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def create_ticket_number_sequence(apps, schema_editor):
    """PostgreSQL-only: native sequence backing ``SupportTicket.number`` (SQLite uses a MAX()+1 fallback)."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE SEQUENCE IF NOT EXISTS support_ticket_number_seq START WITH 1;")


def drop_ticket_number_sequence(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP SEQUENCE IF EXISTS support_ticket_number_seq;")


def create_activity_immutability_trigger(apps, schema_editor):
    """TicketActivity rows are insert-only."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            CREATE OR REPLACE FUNCTION prevent_ticket_activity_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'TicketActivity records are immutable and cannot be updated or deleted.';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_update ON support_desk_ticketactivity;
            CREATE TRIGGER trg_prevent_ticket_activity_update
            BEFORE UPDATE ON support_desk_ticketactivity
            FOR EACH ROW EXECUTE FUNCTION prevent_ticket_activity_modification();

            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_delete ON support_desk_ticketactivity;
            CREATE TRIGGER trg_prevent_ticket_activity_delete
            BEFORE DELETE ON support_desk_ticketactivity
            FOR EACH ROW EXECUTE FUNCTION prevent_ticket_activity_modification();
        """)


def drop_activity_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_update ON support_desk_ticketactivity;
            DROP TRIGGER IF EXISTS trg_prevent_ticket_activity_delete ON support_desk_ticketactivity;
            DROP FUNCTION IF EXISTS prevent_ticket_activity_modification();
        """)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm;", reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name="SupportStatus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50, unique=True)),
                (
                    "system_state",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("active", "Active"),
                            ("waiting", "Waiting"),
                            ("done", "Done"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=20,
                    ),
                ),
                (
                    "color_hex",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional '#RRGGBB' badge colour.",
                        max_length=7,
                    ),
                ),
                ("is_initial", models.BooleanField(default=False)),
                (
                    "is_final",
                    models.BooleanField(
                        default=False,
                        help_text="Terminal status (e.g. Closed). Entering it stamps closed_at; auto-close moves tickets here.",
                    ),
                ),
                (
                    "pauses_sla",
                    models.BooleanField(
                        default=False,
                        help_text="While a ticket is in this status (e.g. Waiting for Customer) SLA clocks are paused.",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Support Status",
                "verbose_name_plural": "Support Statuses",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="SupportLabel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50)),
                (
                    "color_hex",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional '#RRGGBB' badge colour.",
                        max_length=7,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Support Label",
                "verbose_name_plural": "Support Labels",
                "ordering": ["name", "id"],
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["name"],
                        name="support_label_name_trgm_idx",
                        opclasses=["gin_trgm_ops"],
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        name="unique_support_label_name_ci",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SupportPriority",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50)),
                (
                    "code",
                    models.SlugField(
                        blank=True,
                        default="",
                        help_text="Stable machine-readable identifier.",
                    ),
                ),
                (
                    "color_hex",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional '#RRGGBB' badge colour.",
                        max_length=7,
                    ),
                ),
                (
                    "rank",
                    models.PositiveIntegerField(help_text="Lower rank indicates higher urgency (1=Critical)"),
                ),
                (
                    "response_target_minutes",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="SLA: minutes allowed until the first agent response (empty = no target).",
                        null=True,
                    ),
                ),
                (
                    "resolution_target_minutes",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="SLA: minutes allowed until the ticket is resolved (empty = no target).",
                        null=True,
                    ),
                ),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Support Priority",
                "verbose_name_plural": "Support Priorities",
                "ordering": ["rank", "name", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("is_active", True)),
                        fields=("name",),
                        name="unique_active_support_priority_name",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SupportSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "reopen_window_days",
                    models.PositiveIntegerField(
                        default=14,
                        help_text="Days after resolution during which a requester may reopen a ticket.",
                    ),
                ),
                (
                    "auto_close_days",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Days after resolution before auto-closing a ticket (0 to disable).",
                    ),
                ),
                (
                    "max_attachment_size_bytes",
                    models.PositiveBigIntegerField(
                        default=26214400,
                        help_text="Maximum allowed attachment size in bytes (default 25 MB).",
                    ),
                ),
                (
                    "allowed_attachment_extensions",
                    models.JSONField(
                        default=list,
                        help_text="List of permitted file extensions with dots, e.g. ['.png', '.pdf'].",
                    ),
                ),
                (
                    "max_attachments_per_ticket",
                    models.PositiveIntegerField(
                        default=10,
                        help_text="Maximum number of attachments allowed on a single ticket.",
                    ),
                ),
                (
                    "comment_edit_window_minutes",
                    models.PositiveIntegerField(
                        default=15,
                        help_text="Minutes after creation during which an author may edit/delete their comment.",
                    ),
                ),
                (
                    "requesters_can_set_priority",
                    models.BooleanField(
                        default=True,
                        help_text="If disabled, requesters describe impact/urgency and the priority is derived (agents still set it).",
                    ),
                ),
                (
                    "sla_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Compute SLA deadlines and flag breaches from the priority targets.",
                    ),
                ),
                (
                    "sla_at_risk_percent",
                    models.PositiveSmallIntegerField(
                        default=80,
                        help_text="A ticket is 'at risk' once this percentage of its SLA window has elapsed.",
                    ),
                ),
                (
                    "csat_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Allow requesters to rate resolved tickets (1-5).",
                    ),
                ),
                (
                    "csat_window_days",
                    models.PositiveIntegerField(
                        default=14,
                        help_text="Days after resolution during which the requester can submit a satisfaction rating.",
                    ),
                ),
                (
                    "default_ticket_type",
                    models.CharField(
                        choices=[
                            ("incident", "Incident"),
                            ("service_request", "Service Request"),
                            ("problem", "Problem"),
                            ("change", "Change"),
                            ("question", "Question"),
                        ],
                        default="incident",
                        help_text="Type applied when a ticket is created without one.",
                        max_length=20,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Support Desk Settings",
                "verbose_name_plural": "Support Desk Settings",
            },
        ),
        migrations.CreateModel(
            name="SupportTeam",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "code",
                    models.SlugField(help_text="Stable machine-readable identifier used by the options API."),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "lead",
                    models.ForeignKey(
                        blank=True,
                        help_text="Receives SLA breach escalations for tickets owned by this team.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="led_support_teams",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "members",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Agents who work this team's queue and are notified about new tickets.",
                        related_name="support_teams",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Support Team",
                "verbose_name_plural": "Support Teams",
                "ordering": ["name", "id"],
            },
        ),
        migrations.CreateModel(
            name="SupportCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "code",
                    models.SlugField(
                        blank=True,
                        default="",
                        help_text="Stable machine-readable identifier (exposed as 'sku' by the options API).",
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "default_team",
                    models.ForeignKey(
                        blank=True,
                        help_text="Tickets created in this category are routed to this team unless one is specified.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="default_categories",
                        to="support_desk.supportteam",
                    ),
                ),
            ],
            options={
                "verbose_name": "Support Category",
                "verbose_name_plural": "Support Categories",
                "ordering": ["sort_order", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="CannedResponse",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=120)),
                ("body", models.TextField()),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        help_text="Restrict to one team's agents; empty means available to every agent.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="canned_responses",
                        to="support_desk.supportteam",
                    ),
                ),
            ],
            options={
                "verbose_name": "Canned Response",
                "verbose_name_plural": "Canned Responses",
                "ordering": ["title", "id"],
            },
        ),
        migrations.CreateModel(
            name="SupportTicket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(editable=False, max_length=32, unique=True)),
                ("number", models.BigIntegerField(editable=False, unique=True)),
                ("subject", models.CharField(max_length=200)),
                ("description", models.TextField()),
                (
                    "ticket_type",
                    models.CharField(
                        choices=[
                            ("incident", "Incident"),
                            ("service_request", "Service Request"),
                            ("problem", "Problem"),
                            ("change", "Change"),
                            ("question", "Question"),
                        ],
                        db_index=True,
                        default="incident",
                        max_length=20,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("web", "Web"),
                            ("email", "Email"),
                            ("phone", "Phone"),
                            ("walk_in", "Walk In"),
                            ("api", "Api"),
                            ("system", "System"),
                        ],
                        default="web",
                        max_length=20,
                    ),
                ),
                (
                    "impact",
                    models.CharField(
                        blank=True,
                        choices=[("1", "High"), ("2", "Medium"), ("3", "Low")],
                        default="",
                        max_length=1,
                    ),
                ),
                (
                    "urgency",
                    models.CharField(
                        blank=True,
                        choices=[("1", "High"), ("2", "Medium"), ("3", "Low")],
                        default="",
                        max_length=1,
                    ),
                ),
                (
                    "external_reference",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Reference in an external system (vendor RMA / case number, legacy Jira key...).",
                        max_length=128,
                    ),
                ),
                (
                    "due_date",
                    models.DateField(
                        blank=True,
                        help_text="Requester/agent-set target date, independent of the SLA.",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "last_activity_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("first_response_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("response_due_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_due_at", models.DateTimeField(blank=True, null=True)),
                (
                    "sla_paused_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Set while the ticket sits in a status that pauses SLA clocks.",
                        null=True,
                    ),
                ),
                (
                    "sla_paused_seconds",
                    models.PositiveBigIntegerField(
                        default=0,
                        help_text="Total seconds the SLA clocks have been paused (already added to the due dates).",
                    ),
                ),
                ("response_breached_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_breached_at", models.DateTimeField(blank=True, null=True)),
                ("reopen_count", models.PositiveIntegerField(default=0)),
                (
                    "resolution_code",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("fixed", "Fixed"),
                            ("workaround", "Workaround"),
                            ("cannot_reproduce", "Cannot Reproduce"),
                            ("duplicate", "Duplicate"),
                            ("wont_fix", "Wont Fix"),
                            ("user_error", "User Error"),
                            ("vendor", "Vendor"),
                        ],
                        default="",
                        max_length=20,
                    ),
                ),
                ("resolution_summary", models.TextField(blank=True, default="")),
                ("root_cause", models.TextField(blank=True, default="")),
                (
                    "csat_score",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ],
                    ),
                ),
                ("csat_comment", models.TextField(blank=True, default="")),
                ("csat_submitted_at", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "idempotency_key",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=128,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to="support_desk.supportcategory",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "labels",
                    models.ManyToManyField(
                        blank=True,
                        related_name="tickets",
                        to="support_desk.supportlabel",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        help_text="Parent ticket (one level of sub-tickets only).",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="support_desk.supportticket",
                    ),
                ),
                (
                    "priority",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to="support_desk.supportpriority",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requested_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to="support_desk.supportstatus",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tickets",
                        to="support_desk.supportteam",
                    ),
                ),
            ],
            options={
                "verbose_name": "Support Ticket",
                "verbose_name_plural": "Support Tickets",
                "ordering": ["priority__rank", "created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketActivity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("updated", "Updated"),
                            ("assigned", "Assigned"),
                            ("unassigned", "Unassigned"),
                            ("status_changed", "Status Changed"),
                            ("priority_changed", "Priority Changed"),
                            ("category_changed", "Category Changed"),
                            ("comment_added", "Comment Added"),
                            ("comment_edited", "Comment Edited"),
                            ("comment_deleted", "Comment Deleted"),
                            ("attachment_added", "Attachment Added"),
                            ("attachment_removed", "Attachment Removed"),
                            ("resource_linked", "Resource Linked"),
                            ("resource_unlinked", "Resource Unlinked"),
                            ("resolved", "Resolved"),
                            ("reopened", "Reopened"),
                            ("watcher_added", "Watcher Added"),
                            ("watcher_removed", "Watcher Removed"),
                            ("ticket_linked", "Ticket Linked"),
                            ("ticket_unlinked", "Ticket Unlinked"),
                            ("sla_breached", "Sla Breached"),
                            ("sla_paused", "Sla Paused"),
                            ("sla_resumed", "Sla Resumed"),
                            ("csat_submitted", "Csat Submitted"),
                        ],
                        db_index=True,
                        max_length=64,
                    ),
                ),
                ("actor_name", models.CharField(max_length=255)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("payload", models.JSONField(default=dict)),
                (
                    "correlation_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activities",
                        to="support_desk.supportticket",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Activity",
                "verbose_name_plural": "Ticket Activities",
                "ordering": ["occurred_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketComment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("body", models.TextField()),
                (
                    "visibility",
                    models.CharField(
                        choices=[("public", "Public"), ("internal", "Internal")],
                        default="public",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("edited_at", models.DateTimeField(blank=True, null=True)),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="support_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="support_desk.supportticket",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Comment",
                "verbose_name_plural": "Ticket Comments",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketAttachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("storage_key", models.CharField(max_length=255, unique=True)),
                (
                    "file",
                    models.FileField(
                        blank=True,
                        max_length=500,
                        upload_to="support_desk/attachments/%Y/%m/%d/",
                    ),
                ),
                ("filename", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                (
                    "scan_status",
                    models.CharField(
                        choices=[
                            ("clean", "Clean"),
                            ("pending", "Pending"),
                            ("infected", "Infected"),
                        ],
                        default="clean",
                        max_length=20,
                    ),
                ),
                (
                    "is_restricted",
                    models.BooleanField(
                        default=False,
                        help_text="Restricted attachments are visible only to support agents and administrators.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="support_desk.supportticket",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="support_attachments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "comment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="attachments",
                        to="support_desk.ticketcomment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Attachment",
                "verbose_name_plural": "Ticket Attachments",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketLink",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "link_type",
                    models.CharField(
                        choices=[
                            ("relates_to", "Relates To"),
                            ("duplicates", "Duplicates"),
                            ("blocks", "Blocks"),
                            ("caused_by", "Caused By"),
                        ],
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outgoing_links",
                        to="support_desk.supportticket",
                    ),
                ),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="incoming_links",
                        to="support_desk.supportticket",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Link",
                "verbose_name_plural": "Ticket Links",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketResourceLink",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "resource_type",
                    models.CharField(
                        choices=[
                            ("room", "Room"),
                            ("station", "Station"),
                            ("bench", "Bench"),
                            ("equipment", "Equipment"),
                            ("license", "License"),
                        ],
                        db_index=True,
                        max_length=50,
                    ),
                ),
                ("resource_id", models.CharField(db_index=True, max_length=64)),
                (
                    "snapshot",
                    models.JSONField(
                        default=dict,
                        help_text="Immutable snapshot of resource name, code, parent context at link time.",
                    ),
                ),
                ("linked_at", models.DateTimeField(auto_now_add=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("unlinked_at", models.DateTimeField(blank=True, null=True)),
                ("unlink_reason", models.TextField(blank=True, default="")),
                (
                    "linked_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resource_links",
                        to="support_desk.supportticket",
                    ),
                ),
                (
                    "unlinked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Resource Link",
                "verbose_name_plural": "Ticket Resource Links",
                "ordering": ["-linked_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TicketWatcher",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "added_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watchers",
                        to="support_desk.supportticket",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watched_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Ticket Watcher",
                "verbose_name_plural": "Ticket Watchers",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="NotificationOutbox",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_id", models.CharField(db_index=True, max_length=64)),
                (
                    "channel",
                    models.CharField(
                        choices=[("email", "Email"), ("in_app", "In_App")],
                        max_length=20,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "next_attempt_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification Outbox Entry",
                "verbose_name_plural": "Notification Outbox Entries",
                "ordering": ["created_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["status", "next_attempt_at"],
                        name="idx_outbox_status_attempt",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event_id", "recipient", "channel"),
                        name="unique_outbox_event_recipient_channel",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SupportStatusTransition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "allowed_roles",
                    models.JSONField(
                        default=list,
                        help_text="List of roles allowed to trigger this transition, e.g. ['agent', 'admin'].",
                    ),
                ),
                (
                    "requires_reason",
                    models.BooleanField(
                        default=False,
                        help_text="Whether this transition requires a reason from the actor.",
                    ),
                ),
                (
                    "requires_resolution",
                    models.BooleanField(
                        default=False,
                        help_text="Whether this transition requires a resolution summary.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "from_status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outgoing_transitions",
                        to="support_desk.supportstatus",
                    ),
                ),
                (
                    "to_status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="incoming_transitions",
                        to="support_desk.supportstatus",
                    ),
                ),
            ],
            options={
                "verbose_name": "Support Status Transition",
                "verbose_name_plural": "Support Status Transitions",
                "ordering": ["from_status__sort_order", "to_status__sort_order", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("from_status", "to_status"),
                        name="unique_support_status_transition",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="supportteam",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("code",),
                name="unique_active_support_team_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="supportteam",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("name",),
                name="unique_active_support_team_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="supportcategory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("name",),
                name="unique_active_support_category_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="cannedresponse",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("title", "team"),
                name="unique_active_canned_response_title_team",
            ),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["status", "priority", "created_at"], name="idx_ticket_queue"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["assignee", "status"], name="idx_ticket_assignee_status"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["requester", "created_at"], name="idx_ticket_req_created"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["category"], name="idx_ticket_category"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["team", "status"], name="idx_ticket_team_status"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["resolution_due_at"], name="idx_ticket_resolution_due"),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(fields=["response_due_at"], name="idx_ticket_response_due"),
        ),
        migrations.AddConstraint(
            model_name="supportticket",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("csat_score__isnull", True),
                    models.Q(("csat_score__gte", 1), ("csat_score__lte", 5)),
                    _connector="OR",
                ),
                name="ticket_csat_score_1_to_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="supportticket",
            constraint=models.CheckConstraint(
                condition=models.Q(("parent", models.F("pk")), _negated=True),
                name="ticket_parent_not_self",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketactivity",
            index=models.Index(fields=["ticket", "occurred_at"], name="idx_activity_ticket_occurred"),
        ),
        migrations.AddIndex(
            model_name="ticketcomment",
            index=models.Index(fields=["ticket", "created_at"], name="idx_comment_ticket_created"),
        ),
        migrations.AddIndex(
            model_name="ticketattachment",
            index=models.Index(fields=["ticket", "created_at"], name="idx_att_ticket_created"),
        ),
        migrations.AddIndex(
            model_name="ticketlink",
            index=models.Index(fields=["target", "link_type"], name="idx_ticket_link_target"),
        ),
        migrations.AddConstraint(
            model_name="ticketlink",
            constraint=models.UniqueConstraint(fields=("source", "target", "link_type"), name="unique_ticket_link"),
        ),
        migrations.AddConstraint(
            model_name="ticketlink",
            constraint=models.CheckConstraint(
                condition=models.Q(("source", models.F("target")), _negated=True),
                name="ticket_link_no_self_reference",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketresourcelink",
            index=models.Index(
                fields=["resource_type", "resource_id", "ticket"],
                name="idx_res_link_lookup",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketresourcelink",
            index=models.Index(fields=["ticket", "is_active"], name="idx_res_link_ticket_active"),
        ),
        migrations.AddConstraint(
            model_name="ticketresourcelink",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("ticket", "resource_type", "resource_id"),
                name="unique_active_ticket_resource_link",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketwatcher",
            index=models.Index(fields=["user", "ticket"], name="idx_watcher_user_ticket"),
        ),
        migrations.AddConstraint(
            model_name="ticketwatcher",
            constraint=models.UniqueConstraint(fields=("ticket", "user"), name="unique_ticket_watcher"),
        ),
        migrations.RunPython(create_ticket_number_sequence, drop_ticket_number_sequence),
        migrations.RunPython(create_activity_immutability_trigger, drop_activity_immutability_trigger),
    ]
