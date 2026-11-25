"""Seed a development database with demo data: users and roles, a room with stations, benches with a computer
and samples, lab projects and bench bookings.

Everything goes through the features' application commands (``create_room``, ``create_bench``,
``create_equipment``, ``assign_equipment``, ``create_bench_booking`` ...), so the data respects the same rules as
data entered in the app. Re-running is safe: rows found by their SKU / username / code are reused, and bookings
are only added for users that have no seeded booking yet.

Examples::

    python manage.py seed_demo_data
    python manage.py seed_demo_data --benches 10 --users 5 --password Demo@12345
    python manage.py seed_demo_data --entra-tenant 0ae51e19-07c8-4e4b-bb6d-648ee58410f4   # also publish users
    python manage.py seed_demo_data --no-bookings

Refuses to run with ``DEBUG`` off unless ``--i-know-this-is-not-production`` is passed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group as AuthGroup
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.common.domain.errors import DomainError
from core.labs.features.bench_bookings.public import CreateBenchBookingInput, create_bench_booking
from core.labs.features.benches.public import create_bench
from core.labs.features.equipment.public import (
    AssignEquipmentInput,
    CreateEquipmentInput,
    assign_equipment,
    create_equipment,
)
from core.labs.features.locations.public import create_room, create_station
from core.labs.models import Bench, BenchBooking, Equipment, LabProject, Room, Station
from core.labs.models.activity.computing_activity import ComputingActivity
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.users.models import EntraIdentity, URSGroup
from core.users.public import BindEntraIdentityInput, bind_entra_identity_from_operator

User = get_user_model()

SEED_REASON = "Seed demo booking"
#: Fixed URS group ids of the seeded role groups (far from real URS ids).
ROLE_GROUPS = (
    ("seed-labs-admin", 990_000_001, "admin"),
    ("seed-labs-coordinator", 990_000_002, "coord"),
    ("seed-labs-user", 990_000_003, "member"),
)
PROJECTS = (
    ("SEED-P001", "Powertrain Validation"),
    ("SEED-P002", "ECU Software Testing"),
    ("SEED-P003", "Sensor Calibration"),
)
#: Demo activity of the computers, cycled over the benches (dashboard / chatbot "lab status").
ACTIVITY_CYCLE = ("free", "active", "free", "offline", "free", "maintaining")
#: Namespace for the deterministic fake Entra object ids of seeded users.
ENTRA_NAMESPACE = uuid.UUID("5b4c1f3e-7a2d-4e0b-9c1a-6f2e8d3b7a10")


@dataclass
class Summary:
    created: dict[str, int] = field(default_factory=dict)
    reused: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, created: bool) -> None:
        bucket = self.created if created else self.reused
        bucket[kind] = bucket.get(kind, 0) + 1


class Command(BaseCommand):
    help = "Seed demo users, room, stations, benches with computers and samples, projects and bookings (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--prefix", default="SEED", help="SKU / username prefix (default: SEED).")
        parser.add_argument("--benches", type=int, default=6, help="Number of benches (default: 6).")
        parser.add_argument("--stations", type=int, default=2, help="Number of stations (default: 2).")
        parser.add_argument("--users", type=int, default=3, help="Number of normal users (default: 3).")
        parser.add_argument("--password", default="Demo@12345", help="Password of the seeded users.")
        parser.add_argument("--no-bookings", action="store_true", help="Do not create bookings.")
        parser.add_argument(
            "--entra-tenant",
            type=uuid.UUID,
            default=None,
            help="Bind each seeded user to a fake Entra identity of this tenant, which publishes them to the "
            "routing 'users' stream (tenant resolver). Object ids are derived from the username.",
        )
        parser.add_argument(
            "--i-know-this-is-not-production",
            action="store_true",
            dest="force",
            help="Allow running with DEBUG off.",
        )

    def handle(self, *args, **options):
        if not (settings.DEBUG or options["force"]):
            raise CommandError("Refusing to seed demo data with DEBUG off. This is a development command.")
        for name in ("benches", "stations", "users"):
            if options[name] < 1:
                raise CommandError(f"--{name} must be at least 1.")

        prefix = options["prefix"].strip().upper() or "SEED"
        self.summary = Summary()

        # Equipment categories (Computing, Sample ...) are baseline reference data.
        call_command("provision_reference_data", verbosity=0)

        with transaction.atomic():
            users = self._seed_users(prefix, options["users"], options["password"])
            actor = users["admin"]
            projects = self._seed_projects(actor)
            benches = self._seed_locations_and_benches(prefix, options["stations"], options["benches"], actor)
            if not options["no_bookings"]:
                self._seed_bookings(users, benches, projects)
            if options["entra_tenant"] is not None:
                self._bind_entra(users, options["entra_tenant"])

        self._report(prefix, users, options)

    # ------------------------------------------------------------------ users and roles

    def _seed_users(self, prefix: str, count: int, password: str) -> dict:
        groups = {}
        for name, urs_group_id, role in ROLE_GROUPS:
            group, created_group = AuthGroup.objects.get_or_create(name=name)
            urs, created_urs = URSGroup.objects.get_or_create(
                urs_group_id=urs_group_id,
                defaults={"group": group, "urs_group_name": name, "labs_role": role, "active": True},
            )
            if urs.group_id != group.pk or urs.labs_role != role:
                urs.group, urs.labs_role, urs.active = group, role, True
                urs.save(update_fields=["group", "labs_role", "active"])
            groups[role] = group
            self.summary.add("role groups", created_group or created_urs)

        base = prefix.lower()
        specs = [(f"{base}_admin", "Demo Admin", "admin"), (f"{base}_coord", "Demo Coordinator", "coord")]
        specs += [(f"{base}_user{i}", f"Demo User {i}", "member") for i in range(1, count + 1)]

        users: dict = {"normal": []}
        for username, display_name, role in specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.com",
                    "display_name": display_name,
                    "name": display_name,
                    "is_active": True,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            user.groups.add(groups[role])
            self.summary.add("users", created)
            if role == "member":
                users["normal"].append(user)
            else:
                users[role] = user
        return users

    def _bind_entra(self, users: dict, tenant_id: uuid.UUID) -> None:
        for user in [users["admin"], users["coord"], *users["normal"]]:
            if EntraIdentity.objects.filter(user=user).exists():
                self.summary.add("entra identities", False)
                continue
            result = bind_entra_identity_from_operator(
                data=BindEntraIdentityInput(
                    user_id=user.pk,
                    tenant_id=tenant_id,
                    object_id=uuid.uuid5(ENTRA_NAMESPACE, f"{tenant_id}:{user.username}"),
                )
            )
            self.summary.add("entra identities", result.changed)

    # ------------------------------------------------------------------ projects

    def _seed_projects(self, actor) -> list[LabProject]:
        projects = []
        today = timezone.localdate()
        for code, name in PROJECTS:
            project = LabProject.objects.filter(code=code).first()
            created = project is None
            if created:
                project = LabProject(
                    code=code,
                    project_name=name,
                    active=True,
                    starts_on=today - timedelta(days=30),
                    ends_on=today + timedelta(days=365),
                )
                project.save(actor=actor)
            projects.append(project)
            self.summary.add("projects", created)
        return projects

    # ------------------------------------------------------------------ room, stations, benches, equipment

    def _seed_locations_and_benches(self, prefix: str, station_count: int, bench_count: int, actor) -> list[Bench]:
        room = Room.objects.filter(sku=f"{prefix}-ROOM-01").first()
        room_created = room is None
        if room_created:
            room = create_room(actor=actor, sku=f"{prefix}-ROOM-01", name="Demo Lab Room", label="Demo Lab")
        self.summary.add("rooms", room_created)

        stations = []
        for i in range(1, station_count + 1):
            sku = f"{prefix}-ST-{i:02d}"
            station = Station.objects.filter(sku=sku).first()
            created = station is None
            if created:
                station = create_station(actor=actor, sku=sku, name=f"Demo Station {i}", room_id=room.pk)
            stations.append(station)
            self.summary.add("stations", created)

        computing_kind = self._kind("computing", "Computing", "Test PC")
        sample_kind = self._kind("sample", "Sample", "Demo Sample")

        benches = []
        for i in range(1, bench_count + 1):
            sku = f"{prefix}-BENCH-{i:02d}"
            bench = Bench.objects.filter(sku=sku).first()
            created = bench is None
            if created:
                bench = create_bench(
                    actor=actor,
                    sku=sku,
                    name=f"RLAB_{i:02d}",
                    description="Demo bench created by seed_demo_data.",
                    setup_location_id=stations[(i - 1) % len(stations)].pk,
                )
            benches.append(bench)
            self.summary.add("benches", created)

            computer_name = f"{prefix}-PC-{i:03d}"
            computer = self._equipment(
                sku=computer_name,
                name=computer_name,
                kind=computing_kind,
                actor=actor,
                computing={"hostname": computer_name.lower()},
            )
            self._assign(computer, bench, position=0, actor=actor)
            self._set_activity(computer, ACTIVITY_CYCLE[(i - 1) % len(ACTIVITY_CYCLE)])

            for s in (1, 2):
                sample_sku = f"{prefix}-SMP-{i:02d}-{s}"
                sample = self._equipment(sku=sample_sku, name=f"Sample {i}.{s}", kind=sample_kind, actor=actor)
                self._assign(sample, bench, position=s, actor=actor)
        return benches

    def _kind(self, key: str, category_name: str, kind_name: str) -> EquipmentKind:
        category = (
            EquipmentCategory.objects.filter(key=key).first()
            or EquipmentCategory.objects.filter(name__iexact=category_name).first()
        )
        if category is None:
            raise CommandError(f"Equipment category {category_name!r} is missing; run provision_reference_data.")
        kind, created = EquipmentKind.objects.get_or_create(
            category=category, name=kind_name, defaults={"active": True}
        )
        self.summary.add("equipment kinds", created)
        return kind

    def _equipment(self, *, sku: str, name: str, kind: EquipmentKind, actor, computing=None) -> Equipment:
        equipment = Equipment.objects.filter(sku=sku).first()
        created = equipment is None
        if created:
            fields = {"kind": kind, "sku": sku, "name": name}
            if computing is not None:
                fields["computing"] = computing
            equipment = create_equipment(CreateEquipmentInput(fields=tuple(fields.items())), actor=actor)
        self.summary.add("computers" if computing is not None else "samples", created)
        return equipment

    def _assign(self, equipment: Equipment, bench: Bench, *, position: int, actor) -> None:
        assign_equipment(
            AssignEquipmentInput(equipment_id=equipment.pk, bench_id=bench.pk, position=position), actor=actor
        )

    def _set_activity(self, computer: Equipment, status: str) -> None:
        """Demo activity so the dashboard shows a mix; normally the agent's heartbeat sets it."""
        reported_at = timezone.now() if status != "offline" else None
        ComputingActivity.objects.filter(computing=computer).update(status=status, last_agent_report_at=reported_at)

    # ------------------------------------------------------------------ bookings

    def _seed_bookings(self, users: dict, benches: list[Bench], projects: list[LabProject]) -> None:
        """Per normal user: two approved 2-hour bookings on the coming days, plus one 5-hour booking that waits
        for approval (bookings over four hours need a coordinator).

        Each booking takes the next (bench, day) cell; a cell that is already taken (for example by bookings of
        an earlier run) is skipped, so a re-run never stops on a conflict.
        """
        tomorrow = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        max_cells = len(benches) * 30
        cell = 0
        for index, user in enumerate(users["normal"]):
            if BenchBooking.objects.filter(creator=user, reason__startswith=SEED_REASON).exists():
                self.summary.add("bookings", False)
                continue
            for start_hour, hours in ((9, 2), (14, 2), (8, 5)):
                while cell < max_cells:
                    bench = benches[cell % len(benches)]
                    starts_at = (tomorrow + timedelta(days=cell // len(benches))).replace(hour=start_hour)
                    cell += 1
                    try:
                        with transaction.atomic():
                            create_bench_booking(
                                actor=user,
                                data=CreateBenchBookingInput(
                                    bench_id=bench.pk,
                                    starts_at=starts_at,
                                    ends_at=starts_at + timedelta(hours=hours),
                                    reason=f"{SEED_REASON} ({hours}h)",
                                    project_id=projects[(index + cell) % len(projects)].pk,
                                ),
                            )
                    except (DomainError, ValidationError):
                        continue  # cell taken or bench blocked (downtime); try the next one
                    self.summary.add("bookings", True)
                    break

    # ------------------------------------------------------------------ report

    def _report(self, prefix: str, users: dict, options) -> None:
        self.stdout.write(self.style.SUCCESS("Demo data is seeded."))
        kinds = sorted(set(self.summary.created) | set(self.summary.reused))
        for kind in kinds:
            self.stdout.write(
                f"  {kind:<18} created {self.summary.created.get(kind, 0):>3}, "
                f"already there {self.summary.reused.get(kind, 0):>3}"
            )
        names = ", ".join(u.username for u in [users["admin"], users["coord"], *users["normal"]])
        self.stdout.write(f"  users: {names} (password for new users: {options['password']})")
        if options["entra_tenant"] is None:
            self.stdout.write(
                "  users are not bound to Entra: pass --entra-tenant <uuid> to publish them to the routing stream."
            )
