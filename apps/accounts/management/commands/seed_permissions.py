from django.core.management.base import BaseCommand
from apps.accounts.permissions import seed_default_permissions

class Command(BaseCommand):
    help = 'Seeds default dynamic permissions and least-privilege role assignments idempotently.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Displays permissions and assignments that would be created without saving to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        if dry_run:
            self.stdout.write(self.style.WARNING("Running permission seeding in DRY-RUN mode..."))
        else:
            self.stdout.write("Running permission seeding...")

        result = seed_default_permissions(stdout=self.stdout, dry_run=dry_run)
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully initialized permissions: {result['permissions_created']} created, "
                    f"{result['assignments_created']} role assignments created."
                )
            )
