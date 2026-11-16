from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Notification
from apps.institutions.models import Institution
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    ReviewTeam,
    ReviewTeamMember,
    ConflictOfInterestDeclaration
)
from apps.site_visits.models import SiteVisitSchedule
from apps.site_visits.services import (
    get_panel_reviewers,
    notify_reviewer_team_assigned,
    notify_reviewer_invitation,
    notify_reviewer_accepted,
    notify_reviewer_declined,
    notify_conflict_of_interest_declared,
    notify_site_visit_plan_published,
    notify_site_visit_schedule_changed,
    notify_site_visit_reminder,
    notify_site_visit_cancelled,
    notify_site_visit_completed,
    notify_assignment_or_visit_requires_correction,
)


class SiteVisitsAndReviewerNotificationsPhase2BTests(TestCase):
    def setUp(self):
        self.client = Client()

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

        # 2. Institution Officers
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

        # 3. Council Secretariat and Board Members
        self.secretariat_user = User.objects.create_user(
            username="sec_user",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.admin_user = User.objects.create_user(
            username="admin_user",
            password="password123",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True,
            is_staff=True
        )
        self.board_user = User.objects.create_user(
            username="board_user",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # 4. Reviewers
        self.rev_chair = User.objects.create_user(
            username="rev_chair",
            password="password123",
            first_name="د. أحمد",
            last_name="المتوكل",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.rev_member = User.objects.create_user(
            username="rev_member",
            password="password123",
            first_name="د. منى",
            last_name="الحكيمي",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.rev_unassigned = User.objects.create_user(
            username="rev_unassigned",
            password="password123",
            first_name="د. طارق",
            last_name="الزبيدي",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.rev_inactive = User.objects.create_user(
            username="rev_inactive",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=False
        )

        # 5. Standards and Application
        self.standard = StandardVersion.objects.create(
            title="معايير الاعتماد المؤسسي الوطني 2026",
            version_number="1.0",
            track=AccreditationTrackType.INSTITUTIONAL
        )

        self.app_a = AccreditationApplication.objects.create(
            application_number="APP-UNIV-A-001",
            institution=self.univ_a,
            applicant_user=self.officer_a1,
            standard_version=self.standard,
            track=AccreditationTrackType.INSTITUTIONAL,
            current_stage=StageChoices.STAGE_4,
            status=ApplicationStatus.PANEL_ASSIGNED
        )

        # 6. Review Team Setup
        self.team_a = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-2026-99",
            formation_date=timezone.now().date(),
            chairperson=self.rev_chair
        )
        self.member_entry = ReviewTeamMember.objects.create(
            team=self.team_a,
            user=self.rev_member,
            role_in_team=ReviewTeamMember.PanelRole.QUALITY_EXPERT
        )

        # 7. Site Visit Schedule
        self.visit_a = SiteVisitSchedule.objects.create(
            application=self.app_a,
            start_date=timezone.now().date() + timezone.timedelta(days=10),
            end_date=timezone.now().date() + timezone.timedelta(days=14),
            visit_location="المقر الرئيسي لجامعة صنعاء",
            agenda_details="برنامج الزيارة الميدانية التفصيلي",
            logistics_coordinator="أ. منسق الزيارة",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )

    def test_scenario_22_and_23_reviewer_team_assigned(self):
        """Scenario 22 & 23: Review team assigned notifies Secretariat and sends individual reviewer invitations."""
        notifs = notify_reviewer_team_assigned(self.team_a)
        self.assertTrue(len(notifs) >= 3)

        # Secretariat and Admin receive assignment notice
        sec_notifs = Notification.objects.filter(recipient=self.secretariat_user)
        self.assertTrue(sec_notifs.filter(title__contains="اعتماد تشكيل فريق التقييم الخارجي").exists())

        admin_notifs = Notification.objects.filter(recipient=self.admin_user)
        self.assertTrue(admin_notifs.filter(title__contains="اعتماد تشكيل فريق التقييم الخارجي").exists())

        # Reviewers receive individual invitation (Scenario 23)
        chair_notifs = Notification.objects.filter(recipient=self.rev_chair)
        self.assertTrue(chair_notifs.filter(title__contains="تكليف بمهمة تحكيم خارجي").exists())
        self.assertIn("DEC-2026-99", chair_notifs.first().message)

        member_notifs = Notification.objects.filter(recipient=self.rev_member)
        self.assertTrue(member_notifs.filter(title__contains="تكليف بمهمة تحكيم خارجي").exists())

        # Reviewer not on this panel receives 0 notifications
        unassigned_notifs = Notification.objects.filter(recipient=self.rev_unassigned)
        self.assertEqual(unassigned_notifs.count(), 0)

        # Board members do NOT receive operational notifications
        board_notifs = Notification.objects.filter(recipient=self.board_user)
        self.assertEqual(board_notifs.count(), 0)

    def test_scenario_23_inactive_reviewer_not_notified(self):
        """Scenario 23: Inactive reviewer is excluded from invitations."""
        notif = notify_reviewer_invitation(self.rev_inactive, self.app_a, "DEC-2026-99")
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.filter(recipient=self.rev_inactive).count(), 0)

    def test_scenario_24_reviewer_accepted(self):
        """Scenario 24: Reviewer accepts assignment and signs clean COI -> Secretariat is notified."""
        notifs = notify_reviewer_accepted(self.rev_member, self.app_a)
        self.assertTrue(len(notifs) >= 1)

        sec_notifs = Notification.objects.filter(recipient=self.secretariat_user)
        self.assertTrue(sec_notifs.filter(title__contains="قبول تكليف التحكيم الخارجي").exists())

        # Institution officers do NOT receive internal reviewer acceptance
        inst_notifs = Notification.objects.filter(recipient=self.officer_a1)
        self.assertEqual(inst_notifs.count(), 0)

    def test_scenario_25_reviewer_declined(self):
        """Scenario 25: Reviewer declines assignment -> Secretariat notified, confidential reason preserved."""
        notifs = notify_reviewer_declined(self.rev_member, self.app_a, reason="ظروف سفر طارئة")
        self.assertTrue(len(notifs) >= 1)

        sec_notifs = Notification.objects.filter(recipient=self.secretariat_user)
        notif = sec_notifs.filter(title__contains="اعتذار محكّم عن التكليف").first()
        self.assertIsNotNone(notif)
        self.assertIn("ظروف سفر طارئة", notif.message)

        # Confidentiality: Institution and unassigned reviewers receive nothing
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a1).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)

    def test_scenario_26_conflict_of_interest_confidentiality(self):
        """Scenario 26: Conflict of interest declared -> Confidential to Secretariat only, zero leakage to institution."""
        notifs = notify_conflict_of_interest_declared(self.rev_member, self.app_a, has_conflict=True)
        self.assertTrue(len(notifs) >= 1)

        sec_notifs = Notification.objects.filter(recipient=self.secretariat_user)
        notif = sec_notifs.filter(title__contains="إفادة بوجود تعارض مصالح").first()
        self.assertIsNotNone(notif)
        self.assertIn("استبدال المحكّم", notif.message)

        # STRICT DATA CONFIDENTIALITY: Institution officers MUST NOT receive any COI disclosure
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a1).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a2).count(), 0)

    def test_scenario_27_site_visit_plan_published(self):
        """Scenario 27: Site visit plan published -> Institution officers and assigned reviewers notified."""
        notifs = notify_site_visit_plan_published(self.visit_a)
        self.assertTrue(len(notifs) >= 3)

        # Institution A officers receive notification
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="اعتماد خطة الزيارة الميدانية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title__contains="اعتماد خطة الزيارة الميدانية").exists())

        # Assigned reviewers receive notification
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="برنامج الزيارة الميدانية المعتمد").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_member, title__contains="برنامج الزيارة الميدانية المعتمد").exists())

        # Unassigned reviewer does NOT receive notification
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)

        # Institution B officer does NOT receive notification
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_scenario_28_site_visit_schedule_changed(self):
        """Scenario 28: Site visit schedule changed -> Institution officers and assigned reviewers notified with old/new dates."""
        old_dates = "2026-11-10 إلى 2026-11-14"
        self.visit_a.start_date = timezone.now().date() + timezone.timedelta(days=20)
        self.visit_a.end_date = timezone.now().date() + timezone.timedelta(days=24)
        self.visit_a.save()

        notifs = notify_site_visit_schedule_changed(self.visit_a, old_dates=old_dates)
        self.assertTrue(len(notifs) >= 3)

        inst_notif = Notification.objects.filter(recipient=self.officer_a1, title__contains="تعديل مواعيد الزيارة الميدانية").first()
        self.assertIsNotNone(inst_notif)
        self.assertIn(old_dates, inst_notif.message)

        rev_notif = Notification.objects.filter(recipient=self.rev_chair, title__contains="تحديث مواعيد الزيارة الميدانية").first()
        self.assertIsNotNone(rev_notif)
        self.assertIn(old_dates, rev_notif.message)

        # Isolation
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)

    def test_scenario_29_site_visit_reminder_helper(self):
        """Scenario 29: Site visit reminder helper dispatches reminders to institution and panel reviewers."""
        notifs = notify_site_visit_reminder(self.visit_a)
        self.assertTrue(len(notifs) >= 3)

        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="تذكير باقتراب موعد الزيارة الميدانية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="تذكير بموعد الزيارة الميدانية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_member, title__contains="تذكير بموعد الزيارة الميدانية").exists())

    def test_scenario_30_site_visit_cancelled_or_postponed(self):
        """Scenario 30: Site visit cancelled or postponed -> Institution, reviewers, and Secretariat notified."""
        notifs = notify_site_visit_cancelled(self.visit_a, reason="طلب تأجيل من إدارة الجامعة للتجهيزات الفنية")
        self.assertTrue(len(notifs) >= 4)

        inst_notif = Notification.objects.filter(recipient=self.officer_a1, title__contains="تأجيل / إلغاء الزيارة الميدانية").first()
        self.assertIsNotNone(inst_notif)
        self.assertIn("طلب تأجيل من إدارة الجامعة", inst_notif.message)

        rev_notif = Notification.objects.filter(recipient=self.rev_chair, title__contains="إشعار تأجيل الزيارة الميدانية").first()
        self.assertIsNotNone(rev_notif)

        sec_notif = Notification.objects.filter(recipient=self.secretariat_user, title__contains="تسجيل تأجيل الزيارة الميدانية").first()
        self.assertIsNotNone(sec_notif)

        # Isolation
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)

    def test_scenario_31_site_visit_completed(self):
        """Scenario 31: Site visit completed -> Secretariat and assigned reviewers notified."""
        notifs = notify_site_visit_completed(self.visit_a)
        self.assertTrue(len(notifs) >= 3)

        self.assertTrue(Notification.objects.filter(recipient=self.secretariat_user, title__contains="اختتام الزيارة الميدانية رسمياً").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="اكتمال الزيارة الميدانية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_member, title__contains="اكتمال الزيارة الميدانية").exists())

        # Unassigned reviewer receives nothing
        self.assertEqual(Notification.objects.filter(recipient=self.rev_unassigned).count(), 0)

    def test_scenario_32_correction_requested(self):
        """Scenario 32: Correction requested -> Secretariat and targeted reviewer notified."""
        notifs = notify_assignment_or_visit_requires_correction(
            self.app_a,
            target_reviewer=self.rev_member,
            reason="يرجى إعادة استيفاء إقرار النزاهة بدقة وتحديد مقر العمل الحالي"
        )
        self.assertTrue(len(notifs) >= 2)

        sec_notif = Notification.objects.filter(recipient=self.secretariat_user, title__contains="طلب تصحيح في ملف التقييم / الزيارة").first()
        self.assertIsNotNone(sec_notif)

        target_notif = Notification.objects.filter(recipient=self.rev_member, title__contains="توجيه إداري بشأن مهمة التقييم").first()
        self.assertIsNotNone(target_notif)
        self.assertIn("إعادة استيفاء إقرار النزاهة", target_notif.message)

        # Non-targeted reviewer does NOT receive individual correction notice
        self.assertEqual(Notification.objects.filter(recipient=self.rev_chair).count(), 0)

    def test_reviewer_assignment_isolation(self):
        """Reviewers only receive notifications for panels they are explicitly assigned to."""
        # Create second application for Univ B with Reviewer Unassigned as chair
        app_b = AccreditationApplication.objects.create(
            application_number="APP-UNIV-B-001",
            institution=self.univ_b,
            applicant_user=self.officer_b,
            standard_version=self.standard,
            track=AccreditationTrackType.INSTITUTIONAL,
            current_stage=StageChoices.STAGE_4,
            status=ApplicationStatus.PANEL_ASSIGNED
        )
        visit_b = SiteVisitSchedule.objects.create(
            application=app_b,
            start_date=timezone.now().date() + timezone.timedelta(days=15),
            end_date=timezone.now().date() + timezone.timedelta(days=18),
            visit_location="المقر الرئيسي لجامعة عدن",
            agenda_details="برنامج الزيارة",
            status=SiteVisitSchedule.VisitStatus.SCHEDULED
        )
        team_b = ReviewTeam.objects.create(
            application=app_b,
            decree_number="DEC-2026-100",
            formation_date=timezone.now().date(),
            chairperson=self.rev_unassigned
        )

        # Action on Visit B
        notify_site_visit_plan_published(visit_b)

        # Reviewer Unassigned (chair of Panel B) receives notification
        self.assertTrue(Notification.objects.filter(recipient=self.rev_unassigned, title__contains="برنامج الزيارة الميدانية المعتمد").exists())

        # Reviewers of Panel A (Chair and Member) MUST NOT receive notification for Visit B
        self.assertEqual(Notification.objects.filter(recipient=self.rev_chair).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.rev_member).count(), 0)

    def test_institution_isolation(self):
        """Institution officers only receive notifications for their own institution."""
        notify_site_visit_plan_published(self.visit_a)

        # Univ A officers received notifications
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a1).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a2).count(), 1)

        # Univ B officers received ZERO notifications
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b).count(), 0)

    def test_inactive_and_unapproved_users_excluded(self):
        """Inactive officers and unapproved officers are strictly excluded from notifications."""
        notify_site_visit_plan_published(self.visit_a)

        self.assertEqual(Notification.objects.filter(recipient=self.officer_a_inactive).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a_unapproved).count(), 0)

    def test_board_members_excluded(self):
        """Board members (COUNCIL_BOARD) are excluded from operational visit notifications."""
        notify_site_visit_plan_published(self.visit_a)
        notify_site_visit_schedule_changed(self.visit_a, old_dates="old")
        notify_site_visit_completed(self.visit_a)
        notify_site_visit_cancelled(self.visit_a, reason="test")

        self.assertEqual(Notification.objects.filter(recipient=self.board_user).count(), 0)

    def test_site_visit_console_view_integration(self):
        """Integration test: Updating visit schedule in site_visit_console triggers notifications."""
        self.client.login(username="sec_user", password="password123")
        url = reverse('site_visits:console', kwargs={'app_pk': self.app_a.pk})

        new_start = str(timezone.now().date() + timezone.timedelta(days=25))
        new_end = str(timezone.now().date() + timezone.timedelta(days=29))

        response = self.client.post(url, {
            'action': 'update_schedule',
            'start_date': new_start,
            'end_date': new_end,
            'visit_location': 'المقر الرئيسي المحدث',
            'agenda_details': 'أجندة محدثة',
            'status': SiteVisitSchedule.VisitStatus.SCHEDULED,
        })
        self.assertEqual(response.status_code, 302)

        # Check notifications triggered for schedule change (Scenario 28)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="تعديل مواعيد الزيارة الميدانية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.rev_chair, title__contains="تحديث مواعيد الزيارة الميدانية").exists())

    def test_site_visit_console_access_control(self):
        """Access control: Unassigned reviewer and foreign institution officer are blocked."""
        url = reverse('site_visits:console', kwargs={'app_pk': self.app_a.pk})

        # Foreign institution officer blocked
        self.client.login(username="officer_b", password="password123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Unassigned reviewer blocked
        self.client.login(username="rev_unassigned", password="password123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
