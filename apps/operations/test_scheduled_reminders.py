import datetime
from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone
from apps.accounts.models import (
    User,
    Notification,
    ScheduledReminderLog,
)
from apps.institutions.models import Institution
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    ReviewTeam,
    ReviewTeamMember,
    ExternalReviewReport,
)
from apps.site_visits.models import SiteVisitSchedule
from apps.decisions.models import (
    CouncilMeeting,
    AccreditationDecision,
    AccreditationCertificate,
)
from apps.surveillance.models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
    CorrectiveActionItem,
)
from apps.operations.deadline_engine import (
    check_site_visit_reminders,
    check_cip_period_opened,
    check_annual_report_reminders,
    check_approaching_report_deadlines,
    check_certificate_expiry_warnings,
    check_followup_report_reminders,
    check_overdue_reporting,
    check_task_deadline_reminders,
    check_overdue_tasks,
    run_all_scheduled_reminders,
)


class ScheduledNotificationsPhase3Tests(TestCase):
    def setUp(self):
        # Base reference date
        self.today = datetime.date(2026, 11, 1)

        # 1. Institutions
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-A",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.univ_b = Institution.objects.create(
            name="جامعة عدن",
            code="UNIV-B",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        # 2. Institution Users
        self.officer_a1 = User.objects.create_user(
            username="officer_a1",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.officer_a2 = User.objects.create_user(
            username="officer_a2",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.officer_a_inactive = User.objects.create_user(
            username="officer_a_inactive",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=False
        )
        self.officer_a_unapproved = User.objects.create_user(
            username="officer_a_unapproved",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL,
            is_active=True
        )
        self.officer_b = User.objects.create_user(
            username="officer_b",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # 3. Council Secretariat & Board
        self.secretariat_user = User.objects.create_user(
            username="sec_officer",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.board_user = User.objects.create_user(
            username="board_member",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # 4. Reviewers
        self.rev_chair = User.objects.create_user(
            username="rev_chair",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.rev_member = User.objects.create_user(
            username="rev_member",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.rev_unassigned = User.objects.create_user(
            username="rev_unassigned",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # 5. Standard Version & Application
        self.standard = StandardVersion.objects.create(
            title="المعايير المؤسسية الوطنية 2026",
            version_number="1.0",
            track=AccreditationTrackType.INSTITUTIONAL
        )
        self.app_a = AccreditationApplication.objects.create(
            application_number="APP-UNIV-A-SCHED",
            institution=self.univ_a,
            applicant_user=self.officer_a1,
            standard_version=self.standard,
            track=AccreditationTrackType.INSTITUTIONAL,
            current_stage=StageChoices.STAGE_4,
            status=ApplicationStatus.SITE_VISIT_SCHEDULED
        )
        self.team_a = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-TEAM-01",
            formation_date=self.today - datetime.timedelta(days=20),
            chairperson=self.rev_chair
        )
        ReviewTeamMember.objects.create(
            team=self.team_a,
            user=self.rev_member,
            role_in_team=ReviewTeamMember.PanelRole.QUALITY_EXPERT
        )

        # 6. Meeting, Decision, and Certificate
        self.meeting = CouncilMeeting.objects.create(
            meeting_number="MEET-2026-01",
            meeting_date=self.today - datetime.timedelta(days=30),
            chairperson_name="أ.د. رئيس المجلس"
        )
        self.decision_a = AccreditationDecision.objects.create(
            meeting=self.meeting,
            application=self.app_a,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="DECREE-2026-100",
            decision_date=self.today - datetime.timedelta(days=10),
            validity_years=5,
            start_date=self.today - datetime.timedelta(days=10),
            expiry_date=self.today + datetime.timedelta(days=150)  # within 180 days
        )
        self.cert_a = AccreditationCertificate.objects.create(
            decision=self.decision_a,
            national_registry_code="CERT-REG-2026-001",
            issue_date=self.today - datetime.timedelta(days=10),
            status=AccreditationCertificate.CertificateStatus.ACTIVE
        )

    def test_scenario_29_site_visit_7_day_reminder(self):
        """Scenario 29: 7-day site visit reminder sent to institution officers and panel reviewers."""
        visit = SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=7),
            end_date=self.today + datetime.timedelta(days=11),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

        res = check_site_visit_reminders(reference_date=self.today)
        self.assertTrue(res['created'] >= 3)

        # Institution officers notified
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="متبقي 7 أيام").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title__contains="متبقي 7 أيام").exists())

        # Reviewers notified
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="متبقي 7 أيام").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_member, title__contains="متبقي 7 أيام").exists())

        # Unassigned reviewer and foreign institution receive 0
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

        # Logged in ScheduledReminderLog
        self.assertTrue(ScheduledReminderLog.is_already_sent('SITE_VISIT_7_DAYS', 'SiteVisitSchedule', visit.pk))

    def test_scenario_29_site_visit_48_hour_reminder(self):
        """Scenario 29: 48-hour reminder sent to institution and panel reviewers."""
        visit = SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=2),
            end_date=self.today + datetime.timedelta(days=6),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

        res = check_site_visit_reminders(reference_date=self.today)
        self.assertTrue(res['created'] >= 3)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="متبقي 48 ساعة").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="48 ساعة").exists())
        self.assertTrue(ScheduledReminderLog.is_already_sent('SITE_VISIT_48_HOURS', 'SiteVisitSchedule', visit.pk))

    def test_scenario_29_cancelled_visit_excluded(self):
        """Scenario 29: Cancelled or postponed visits are strictly excluded."""
        SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=7),
            end_date=self.today + datetime.timedelta(days=11),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.POSTPONED
        )
        res = check_site_visit_reminders(reference_date=self.today)
        self.assertEqual(res['created'], 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_scenario_52_cip_period_opened(self):
        """Scenario 52: Notifies institution officers when CIP submission window opens."""
        res = check_cip_period_opened(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)

        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="بدء فترة إعداد وتقديم خطة التحسين المستمر").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title__contains="بدء فترة إعداد وتقديم خطة التحسين المستمر").exists())
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

        self.assertTrue(ScheduledReminderLog.is_already_sent('CIP_PERIOD_OPENED', 'AccreditationDecision', self.decision_a.pk))

    def test_scenario_59_annual_report_deadline_reminders(self):
        """Scenario 59: Annual report reminder sent 30 days before anniversary."""
        # Set decision date so year 1 anniversary is 20 days ahead
        self.decision_a.decision_date = self.today - datetime.timedelta(days=345)
        self.decision_a.save()

        res = check_annual_report_reminders(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)

        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="تقرير المتابعة السنوي (العام 1)").exists())
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_scenario_59_already_submitted_annual_report_excluded(self):
        """Scenario 59: Already submitted annual report suppresses reminder."""
        self.decision_a.decision_date = self.today - datetime.timedelta(days=345)
        self.decision_a.save()

        # Submit annual report for Year 1
        AnnualMonitoringReport.objects.create(
            decision=self.decision_a,
            year_number=1,
            reporting_period="2026/2027",
            review_status=AnnualMonitoringReport.ReviewStatus.SUBMITTED
        )

        res = check_annual_report_reminders(reference_date=self.today)
        self.assertEqual(res['created'], 0)

    def test_scenario_65_approaching_report_deadline(self):
        """Scenario 65: Approaching deadline reminder for institution right-to-reply."""
        report = ExternalReviewReport.objects.create(
            application=self.app_a,
            response_deadline=self.today + datetime.timedelta(days=3),
            institution_reply_date=None
        )

        res = check_approaching_report_deadlines(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)

        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="اقتراب الموعد النهائي لحق الرد").exists())
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_scenario_66_certificate_expiry_warning(self):
        """Scenario 66: Advance certificate expiration warning (180 days)."""
        # Certificate expires in 150 days (within 180-day window)
        res = check_certificate_expiry_warnings(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)

        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="متبقي 6 أشهر").exists())
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_scenario_66_revoked_certificate_suppresses_warning(self):
        """Scenario 66: Revoked certificates receive no expiry warnings."""
        self.cert_a.is_revoked = True
        self.cert_a.status = AccreditationCertificate.CertificateStatus.REVOKED
        self.cert_a.save()

        res = check_certificate_expiry_warnings(reference_date=self.today)
        self.assertEqual(res['created'], 0)

    def test_scenario_67_followup_report_reminder(self):
        """Scenario 67: Reminder for upcoming surveillance visit and pending CIP revision."""
        SurveillanceVisit.objects.create(
            decision=self.decision_a,
            visit_type=SurveillanceVisit.VisitReason.ROUTINE,
            status=SurveillanceVisit.VisitStatus.ASSIGNED,
            visit_date=self.today + datetime.timedelta(days=5)
        )

        res = check_followup_report_reminders(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="الزيارة الاستطلاعية والمتابعة").exists())

    def test_scenario_68_overdue_reporting_notification(self):
        """Scenario 68: Overdue reporting deadline alerts institution and Secretariat."""
        ExternalReviewReport.objects.create(
            application=self.app_a,
            response_deadline=self.today - datetime.timedelta(days=2),
            institution_reply_date=None
        )

        res = check_overdue_reporting(reference_date=self.today)
        self.assertTrue(res['created'] >= 3)

        # Institution alerted
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="تنبيه فوات المهلة: حق الرد متأخر").exists())

        # Secretariat alerted
        self.assertTrue(Notification.objects.filter(recipient=self.secretariat_user, title__contains="فوات موعد حق الرد").exists())

        # Board member excluded
        self.assertEqual(Notification.objects.filter(recipient=self.board_user).count(), 0)

    def test_scenario_76_task_deadline_reminder(self):
        """Scenario 76: Task deadline reminder dispatched 5 days before due date."""
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة تحسين تجريبية",
            status=ContinuousImprovementPlan.PlanStatus.APPROVED_BY_COUNCIL
        )
        CorrectiveActionItem.objects.create(
            plan=plan,
            deficiency_title="استكمال تجهيز مختبر الحاسوب المتقدم",
            corrective_activity="شراء وتوريد 30 محطة عمل",
            responsible_person="أ. مروان القدسي",
            due_date=self.today + datetime.timedelta(days=5),
            status=CorrectiveActionItem.ActionStatus.IN_PROGRESS
        )

        res = check_task_deadline_reminders(reference_date=self.today)
        self.assertTrue(res['created'] >= 2)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="تذكير باقتراب موعد إنجاز بند تصحيحي").exists())
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_scenario_77_overdue_task_notification(self):
        """Scenario 77: Overdue task status updated and alerts dispatched to institution and Secretariat."""
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة تحسين متأخرة",
            status=ContinuousImprovementPlan.PlanStatus.APPROVED_BY_COUNCIL
        )
        task = CorrectiveActionItem.objects.create(
            plan=plan,
            deficiency_title="تحديث مراجع ومصادر التعلم في المكتبة المركزية",
            corrective_activity="الاشتراك بقواعد البيانات الرقمية",
            responsible_person="د. أمين الصبري",
            due_date=self.today - datetime.timedelta(days=4),
            status=CorrectiveActionItem.ActionStatus.IN_PROGRESS
        )

        res = check_overdue_tasks(reference_date=self.today)
        self.assertTrue(res['created'] >= 3)

        # Status updated to OVERDUE
        task.refresh_from_db()
        self.assertEqual(task.status, CorrectiveActionItem.ActionStatus.OVERDUE)

        # Institution and Secretariat notified
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="إشعار تأخر إنجاز بند تصحيحي").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.secretariat_user, title__contains="بند تصحيحي متأخر").exists())

        # Board member excluded
        self.assertEqual(Notification.objects.filter(recipient=self.board_user).count(), 0)

    def test_idempotency_repeated_scheduler_executions(self):
        """Idempotency: Repeated scheduler runs do not generate duplicate reminders."""
        SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=7),
            end_date=self.today + datetime.timedelta(days=11),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

        # Run 1: generates notifications
        run1 = run_all_scheduled_reminders(reference_date=self.today)
        initial_notif_count = Notification.objects.count()
        self.assertTrue(run1['total_created'] > 0)
        self.assertTrue(initial_notif_count > 0)

        # Run 2: same day -> 0 new notifications, all skipped
        run2 = run_all_scheduled_reminders(reference_date=self.today)
        self.assertEqual(run2['total_created'], 0)
        self.assertTrue(run2['total_skipped'] > 0)
        self.assertEqual(Notification.objects.count(), initial_notif_count)

    def test_dry_run_mode(self):
        """Dry-run mode calculates notifications without writing to database."""
        SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=7),
            end_date=self.today + datetime.timedelta(days=11),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

        results = run_all_scheduled_reminders(reference_date=self.today, dry_run=True)
        self.assertTrue(results['total_created'] > 0)

        # Database remains untouched
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(ScheduledReminderLog.objects.count(), 0)

    def test_inactive_and_unapproved_users_excluded(self):
        """Inactive officers and unapproved accounts receive zero scheduled reminders."""
        SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=self.today + datetime.timedelta(days=7),
            end_date=self.today + datetime.timedelta(days=11),
            visit_location="مقر جامعة صنعاء",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

        run_all_scheduled_reminders(reference_date=self.today)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a_inactive).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a_unapproved).count(), 0)

    def test_management_command_execution(self):
        """Management command runs successfully in dry-run mode."""
        call_command('run_scheduled_reminders', dry_run=True, reference_date=str(self.today))
