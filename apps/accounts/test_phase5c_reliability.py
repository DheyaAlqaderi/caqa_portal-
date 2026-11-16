import datetime
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.db import transaction, IntegrityError

from apps.accounts.models import (
    User,
    Notification,
    send_notification,
    notify_institution,
    ScheduledReminderLog,
)
from apps.institutions.models import Institution
from apps.operations.deadline_engine import (
    calculate_calendar_anniversary,
    check_site_visit_reminders,
)
from apps.standards.models import (
    StandardVersion,
    AccreditationTrackType,
)
from apps.accreditation.models import (
    AccreditationApplication,
)
from apps.site_visits.models import SiteVisitSchedule


class NotificationDeduplicationAndReliabilityTests(TestCase):
    """
    Tests for Fix A: Deduplication window behavior and distinct event preservation.
    """
    def setUp(self):
        self.institution = Institution.objects.create(
            name="جامعة عدن",
            code="UNIV-ADEN",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.officer1 = User.objects.create_user(
            username="aden_officer1",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED,
            institution=self.institution,
            is_active=True
        )
        self.officer2 = User.objects.create_user(
            username="aden_officer2",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED,
            institution=self.institution,
            is_active=True
        )

    def test_old_unread_notification_does_not_block_new_legitimate_event(self):
        """
        Regression test for Fix A:
        An old unread notification (e.g. from 30 days ago) must NOT block
        a new legitimate business event sharing the same title and URL.
        """
        old_time = timezone.now() - datetime.timedelta(days=30)
        old_notif = Notification.objects.create(
            recipient=self.officer1,
            title="صدور مطالبة مالية",
            message="المطالبة القديمة رقم 101",
            url="/operations/invoices/101/",
            is_read=False
        )
        # Manually force created_at to 30 days ago
        Notification.objects.filter(pk=old_notif.pk).update(created_at=old_time)

        # Trigger new legitimate event with same title and URL
        new_notif = send_notification(
            user=self.officer1,
            title="صدور مطالبة مالية",
            message="المطالبة الجديدة رقم 202",
            url="/operations/invoices/101/",
            prevent_duplicates=True
        )
        self.assertIsNotNone(new_notif, "New legitimate event should NOT be blocked by old unread notification.")
        self.assertEqual(Notification.objects.filter(recipient=self.officer1, title="صدور مطالبة مالية").count(), 2)

    def test_genuine_duplicate_inside_window_is_suppressed(self):
        """
        Fix A: A genuine duplicate inside the configured deduplication window (e.g. 10 minutes)
        with identical title, message, and URL is suppressed.
        """
        notif1 = send_notification(
            user=self.officer1,
            title="تنبيه تجديد الاعتماد",
            message="يرجى البدء في مراجعة الشروط",
            url="/accreditation/renew/",
            prevent_duplicates=True,
            deduplicate_window_minutes=10
        )
        self.assertIsNotNone(notif1)

        # Immediate repeated call (e.g. double click or duplicate request)
        notif2 = send_notification(
            user=self.officer1,
            title="تنبيه تجديد الاعتماد",
            message="يرجى البدء في مراجعة الشروط",
            url="/accreditation/renew/",
            prevent_duplicates=True,
            deduplicate_window_minutes=10
        )
        self.assertIsNone(notif2, "Duplicate inside 10-minute window must be suppressed.")
        self.assertEqual(Notification.objects.filter(recipient=self.officer1, title="تنبيه تجديد الاعتماد").count(), 1)

    def test_distinct_events_inside_window_are_not_suppressed(self):
        """
        Fix A: Distinct events with different messages occurring within the window
        are BOTH delivered, even if they share title and URL.
        """
        notif1 = send_notification(
            user=self.officer1,
            title="تحديث مرحلة الطلب",
            message="انتقل الطلب إلى مرحلة الفحص المالي",
            url="/accreditation/app/1/",
            prevent_duplicates=True
        )
        notif2 = send_notification(
            user=self.officer1,
            title="تحديث مرحلة الطلب",
            message="انتقل الطلب إلى مرحلة التقييم الذاتي",
            url="/accreditation/app/1/",
            prevent_duplicates=True
        )
        self.assertIsNotNone(notif1)
        self.assertIsNotNone(notif2)
        self.assertEqual(Notification.objects.filter(recipient=self.officer1, title="تحديث مرحلة الطلب").count(), 2)

    def test_notifications_for_different_recipients_remain_isolated(self):
        """
        Fix A: Sending to user 1 does not suppress dispatching to user 2.
        """
        notif_u1 = send_notification(
            user=self.officer1,
            title="جلسة اعتماد قادمة",
            message="تفاصيل الجلسة",
            url="/meetings/1/",
            prevent_duplicates=True
        )
        notif_u2 = send_notification(
            user=self.officer2,
            title="جلسة اعتماد قادمة",
            message="تفاصيل الجلسة",
            url="/meetings/1/",
            prevent_duplicates=True
        )
        self.assertIsNotNone(notif_u1)
        self.assertIsNotNone(notif_u2)
        self.assertEqual(Notification.objects.filter(recipient=self.officer1).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.officer2).count(), 1)


class PersistentScheduledReminderIdempotencyTests(TestCase):
    """
    Tests for Fix B: Scheduled reminder persistent idempotency and uniqueness constraints.
    """
    def setUp(self):
        self.institution = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-SANA",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

    def test_database_level_uniqueness_constraint(self):
        """
        Fix B: ScheduledReminderLog enforces unique constraint on
        (reminder_type, target_content_type, target_id) at DB level.
        """
        ScheduledReminderLog.objects.create(
            reminder_type="SITE_VISIT_7_DAYS",
            target_content_type="SiteVisitSchedule",
            target_id="100",
            details="First dispatch"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ScheduledReminderLog.objects.create(
                    reminder_type="SITE_VISIT_7_DAYS",
                    target_content_type="SiteVisitSchedule",
                    target_id="100",
                    details="Second duplicate dispatch"
                )

    def test_separate_milestones_for_same_target_allowed(self):
        """
        Fix B: Distinct milestone keys (e.g. 7_DAYS and 48_HOURS) on the same target
        do not conflict and are both stored.
        """
        r1 = ScheduledReminderLog.record_sent("SITE_VISIT_7_DAYS", "SiteVisitSchedule", "200")
        r2 = ScheduledReminderLog.record_sent("SITE_VISIT_48_HOURS", "SiteVisitSchedule", "200")
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertEqual(
            ScheduledReminderLog.objects.filter(target_content_type="SiteVisitSchedule", target_id="200").count(),
            2
        )

    def test_record_sent_handles_concurrency_race_safely(self):
        """
        Fix B: record_sent catches IntegrityError gracefully when concurrent threads attempt duplicate dispatch.
        """
        r1 = ScheduledReminderLog.record_sent("CERT_EXPIRY_180D", "AccreditationCertificate", "50")
        # Second call simulating concurrent worker that bypassed application check
        r2 = ScheduledReminderLog.record_sent("CERT_EXPIRY_180D", "AccreditationCertificate", "50")
        self.assertIsNotNone(r2)
        self.assertEqual(r1.pk, r2.pk)

    def test_failed_notification_creation_does_not_mark_reminder_as_sent(self):
        """
        Fix B: When an institution has no eligible recipients and 0 notifications are created,
        the reminder is not marked as sent in ScheduledReminderLog, allowing safe retry.
        """
        empty_inst = Institution.objects.create(
            name="جامعة فارغة بلا مسؤولين",
            code="UNIV-EMPTY"
        )
        std_ver = StandardVersion.objects.create(
            title="معايير تجريبية",
            track=AccreditationTrackType.INSTITUTIONAL
        )
        inactive_user = User.objects.create_user(
            username="inactive_applicant",
            password="Password123!",
            is_active=False,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL,
            institution=empty_inst
        )
        app = AccreditationApplication.objects.create(
            application_number="CAQA-INST-2026-EMPTY",
            track=AccreditationTrackType.INSTITUTIONAL,
            institution=empty_inst,
            standard_version=std_ver,
            applicant_user=inactive_user
        )
        today = timezone.now().date()
        visit = SiteVisitSchedule.objects.create(
            application=app,
            start_date=today + datetime.timedelta(days=5),
            end_date=today + datetime.timedelta(days=8),
            status=SiteVisitSchedule.VisitStatus.SCHEDULED,
            visit_location="مقر الجامعة"
        )

        stats = check_site_visit_reminders(reference_date=today, dry_run=False)
        self.assertEqual(stats['created'], 0)
        # Verify it was NOT recorded as sent
        self.assertFalse(
            ScheduledReminderLog.is_already_sent('SITE_VISIT_7_DAYS', 'SiteVisitSchedule', visit.pk),
            "Reminder must not be marked sent when 0 notifications were created."
        )


class TransactionSafetyTests(TransactionTestCase):
    """
    Tests for Fix C: Transaction safety and on_commit behavior.
    """
    def setUp(self):
        self.institution = Institution.objects.create(
            name="جامعة إب",
            code="UNIV-IBB"
        )
        self.officer = User.objects.create_user(
            username="ibb_officer",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED,
            institution=self.institution,
            is_active=True
        )

    def test_rolled_back_transaction_leaves_no_orphaned_notification(self):
        """
        Fix C: When a business transaction rolls back, notifications with on_commit=True
        are never created.
        """
        init_count = Notification.objects.filter(recipient=self.officer).count()

        try:
            with transaction.atomic():
                send_notification(
                    user=self.officer,
                    title="إشعار معاملة فاشلة",
                    message="تفاصيل",
                    on_commit=True
                )
                notify_institution(
                    institution=self.institution,
                    title="إشعار مؤسسي فاشل",
                    message="تفاصيل",
                    on_commit=True
                )
                # Simulate business exception triggering rollback
                raise RuntimeError("Simulated transaction failure")
        except RuntimeError:
            pass

        final_count = Notification.objects.filter(recipient=self.officer).count()
        self.assertEqual(final_count, init_count, "Rolled back transaction must leave zero notifications.")

    def test_committed_transaction_dispatches_notification(self):
        """
        Fix C: When a business transaction commits, on_commit notifications are created.
        """
        init_count = Notification.objects.filter(recipient=self.officer).count()

        with transaction.atomic():
            send_notification(
                user=self.officer,
                title="إشعار معاملة ناجحة",
                message="تفاصيل النجاح",
                on_commit=True
            )

        final_count = Notification.objects.filter(recipient=self.officer).count()
        self.assertEqual(final_count, init_count + 1)
        self.assertTrue(Notification.objects.filter(recipient=self.officer, title="إشعار معاملة ناجحة").exists())


class CalendarAnniversaryAndLeapYearTests(TestCase):
    """
    Tests for Fix D: Calendar anniversary calculations and leap-year edge cases.
    """
    def test_february_29_leap_year_to_non_leap_year(self):
        """
        Fix D: Feb 29 (leap year 2024) anniversary in non-leap year (2025) resolves to Feb 28.
        """
        base_leap = datetime.date(2024, 2, 29)
        anniversary_y1 = calculate_calendar_anniversary(base_leap, 1)
        self.assertEqual(anniversary_y1, datetime.date(2025, 2, 28))

        anniversary_y2 = calculate_calendar_anniversary(base_leap, 2)
        self.assertEqual(anniversary_y2, datetime.date(2026, 2, 28))

    def test_february_29_leap_year_to_next_leap_year(self):
        """
        Fix D: Feb 29 (leap year 2024) anniversary in next leap year (2028) resolves to Feb 29.
        """
        base_leap = datetime.date(2024, 2, 29)
        anniversary_y4 = calculate_calendar_anniversary(base_leap, 4)
        self.assertEqual(anniversary_y4, datetime.date(2028, 2, 29))

    def test_standard_dates_have_zero_drift_across_leap_years(self):
        """
        Fix D: Normal dates (e.g. May 15) preserve the exact calendar date each year,
        unlike timedelta(days=365) which drifts by 1 day when passing through a leap year.
        """
        base_date = datetime.date(2023, 5, 15)
        # Year 1 passes through leap year 2024 (which has 366 days)
        anniversary_y1 = calculate_calendar_anniversary(base_date, 1)
        self.assertEqual(anniversary_y1, datetime.date(2024, 5, 15))

        anniversary_y5 = calculate_calendar_anniversary(base_date, 5)
        self.assertEqual(anniversary_y5, datetime.date(2028, 5, 15))
