import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.accounts.models import record_audit_log
from apps.operations.deadline_engine import run_all_scheduled_reminders


class Command(BaseCommand):
    help = "Executes the CAQA scheduled notifications and deadline management engine (Phase 3)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Simulate execution and display which notifications would be generated without saving to DB.'
        )
        parser.add_argument(
            '--date',
            type=str,
            dest='reference_date',
            help='Override reference execution date (format: YYYY-MM-DD). Defaults to today.'
        )
        parser.add_argument(
            '--scenario',
            type=str,
            dest='scenario',
            help='Run only a specific notification scenario (e.g., 29, 52, 59, 65, 66, 67, 68, 76, 77).'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        date_str = options.get('reference_date')
        scenario_filter = options.get('scenario')

        ref_date = None
        if date_str:
            try:
                ref_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Expected YYYY-MM-DD."))
                return

        effective_date = ref_date or timezone.now().date()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Running CAQA Deadline Management Engine [Date: {effective_date}] [Dry-Run: {dry_run}] ==="
        ))

        results = run_all_scheduled_reminders(
            reference_date=effective_date,
            dry_run=dry_run,
            scenario_filter=scenario_filter
        )

        self.stdout.write("-" * 80)
        self.stdout.write(f"{'Scenario':<10} | {'Name':<45} | {'Created':<8} | {'Skipped':<8} | {'Errors':<6}")
        self.stdout.write("-" * 80)

        for code, data in results['scenarios'].items():
            name = data['name'][:43]
            created = data['created']
            skipped = data['skipped']
            errors = data['errors']
            line = f"{code:<10} | {name:<45} | {created:<8} | {skipped:<8} | {errors:<6}"
            if errors > 0:
                self.stdout.write(self.style.ERROR(line))
            elif created > 0:
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(line)

        self.stdout.write("-" * 80)
        self.stdout.write(self.style.SUCCESS(
            f"Total Notifications Created: {results['total_created']} | "
            f"Skipped (Already Dispatched): {results['total_skipped']} | "
            f"Errors: {results['total_errors']}"
        ))

        if not dry_run and results['total_created'] > 0:
            record_audit_log(
                user=None,
                action='SCHEDULED_ENGINE_EXECUTED',
                target_model='ScheduledReminderLog',
                target_id='BATCH',
                details=(
                    f"Scheduled engine executed for date {effective_date}: "
                    f"{results['total_created']} notifications created, "
                    f"{results['total_skipped']} skipped, {results['total_errors']} errors."
                )
            )
