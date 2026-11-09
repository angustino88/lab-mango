"""Management command to rebuild the routing entity projection from domain data."""

from django.core.management.base import BaseCommand, CommandError

from core.routing.application.publish import rebuild_routing_projection
from core.routing.exceptions import RoutingPublishError


class Command(BaseCommand):
    help = "Rebuild RoutingEntity claims from live domain models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--entity",
            choices=["users", "agents"],
            default=None,
            help="Stream entity type to rebuild (default: all streams).",
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            default=False,
            help="Verify projection against domain without mutating database.",
        )

    def handle(self, *args, **options):
        entity = options.get("entity")
        verify = options.get("verify", False)
        try:
            results = rebuild_routing_projection(entity, verify=verify)
            if verify:
                all_match = True
                for stream, data in results.items():
                    if data.get("matches"):
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Stream '{stream}' matches domain projection (unchanged: {data['unchanged']})"
                            )
                        )
                    else:
                        all_match = False
                        self.stdout.write(
                            self.style.WARNING(
                                f"Stream '{stream}' diff: to_upsert={len(data['to_upsert'])}, "
                                f"to_delete={len(data['to_delete'])}, unchanged={data['unchanged']}"
                            )
                        )
                if not all_match:
                    self.stdout.write(
                        self.style.NOTICE("Verification found mismatches. Run without --verify to reconcile.")
                    )
            else:
                for stream, data in results.items():
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Rebuilt stream '{stream}': upserted={data['upserted']}, "
                            f"deleted={data['deleted']}, unchanged={data['unchanged']}, "
                            f"head_version={data['head_version']}"
                        )
                    )
        except RoutingPublishError as exc:
            raise CommandError(str(exc)) from exc
