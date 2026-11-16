from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Notification
from apps.institutions.models import Institution
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus
from apps.decisions.models import CouncilMeeting, AccreditationDecision, AccreditationCertificate


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DecisionAndNotificationRoutingTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="SNA-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.univ_b = Institution.objects.create(
            name="جامعة تعز",
            code="TAIZ-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        self.officer_a = User.objects.create_user(
            username="officer_a",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.officer_b = User.objects.create_user(
            username="officer_b",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.board_member = User.objects.create_user(
            username="board_dr_ali",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.meeting = CouncilMeeting.objects.create(
            meeting_number="COUNCIL-2026-M04",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="مداولات طلبات الاعتماد",
            minutes_summary="محضر اعتماد البرامج"
        )

        self.std_ver = StandardVersion.objects.create(
            title="المعايير المؤسسية",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="1.0"
        )

        self.app_a = AccreditationApplication.objects.create(
            application_number="APP-ACCRED-2026-001",
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            standard_version=self.std_ver,
            applicant_user=self.officer_a,
            current_stage=StageChoices.STAGE_6,
            status=ApplicationStatus.IN_COUNCIL_REVIEW
        )

    def test_certificate_issuance_notifies_institution_officer_exclusively(self):
        """
        Issuing accreditation certificate notifies authorized officers of the applicant institution,
        and does NOT leak or broadcast notifications to officers of other institutions.
        """
        self.client.login(username="board_dr_ali", password="password123")

        response = self.client.post(reverse('decisions:issue_decision', args=[self.app_a.pk]), {
            'meeting': self.meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': 'قرار مجلس الاعتماد رقم (44) لسنة 2026',
            'validity_years': 5,
            'conditions': 'الحفاظ على جودة البرامج الأكاديمية'
        })
        self.assertEqual(response.status_code, 302)

        cert = AccreditationCertificate.objects.filter(decision__application=self.app_a).first()
        self.assertIsNotNone(cert)

        # Officer A should have received notification
        notifs_a = Notification.objects.filter(recipient=self.officer_a)
        self.assertEqual(notifs_a.count(), 1)
        notif_a = notifs_a.first()
        self.assertIn("شهادة الاعتماد", notif_a.title)
        self.assertEqual(notif_a.url, f"/decisions/certificate/{cert.pk}/")

        # Officer B of University B should NOT receive any notification
        notifs_b = Notification.objects.filter(recipient=self.officer_b)
        self.assertEqual(notifs_b.count(), 0)

    def test_certificate_view_tenant_isolation(self):
        """Officer B cannot view Certificate belonging to University A."""
        decision = AccreditationDecision.objects.create(
            application=self.app_a,
            meeting=self.meeting,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decision_date=timezone.now().date(),
            decree_number='قرار تجريبي (55)'
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code='YEM-TEST-55',
            issue_date=timezone.now().date()
        )

        # Officer A can view
        self.client.login(username="officer_a", password="password123")
        res_a = self.client.get(reverse('decisions:certificate_detail', args=[cert.pk]))
        self.assertEqual(res_a.status_code, 200)

        # Officer B is redirected with error
        self.client.login(username="officer_b", password="password123")
        res_b = self.client.get(reverse('decisions:certificate_detail', args=[cert.pk]))
        self.assertEqual(res_b.status_code, 302)

    def test_official_certificate_pdf_export(self):
        """Official certificate can be exported and streamed as landscape A4 PDF with security metadata."""
        decision = AccreditationDecision.objects.create(
            application=self.app_a,
            meeting=self.meeting,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decision_date=timezone.now().date(),
            decree_number='قرار مجلس الاعتماد (99) لسنة 2026'
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code='YEM-TEST-PDF-99',
            issue_date=timezone.now().date()
        )

        # 1. Internal PDF export by authorized officer
        self.client.login(username="officer_a", password="password123")
        resp_pdf = self.client.get(reverse('decisions:certificate_pdf_export', args=[cert.pk]))
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(resp_pdf.content.startswith(b'%PDF'))
        self.assertIn(f'CAQA_Certificate_{cert.national_registry_code}.pdf', resp_pdf['Content-Disposition'])

        # 2. Public UUID PDF export (unauthenticated)
        self.client.logout()
        resp_pub_pdf = self.client.get(reverse('decisions:verify_certificate_pdf_public', args=[cert.certificate_uuid]))
        self.assertEqual(resp_pub_pdf.status_code, 200)
        self.assertEqual(resp_pub_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(resp_pub_pdf.content.startswith(b'%PDF'))

    def test_minister_dashboard_access_and_role_protection(self):
        """H.E. Minister of Higher Education has exclusive access to the Ministerial Dashboard."""
        minister = User.objects.create_user(
            username="minister_test",
            password="password123",
            role=User.Roles.MINISTER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # 1. Minister access granted
        self.client.login(username="minister_test", password="password123")
        res_min = self.client.get(reverse('decisions:minister_dashboard'))
        self.assertEqual(res_min.status_code, 200)
        self.assertContains(res_min, "ديوان معالي وزير التعليم العالي والبحث العلمي")

        # 2. Unauthorized institution officer redirected
        self.client.login(username="officer_a", password="password123")
        res_unauth = self.client.get(reverse('decisions:minister_dashboard'))
        self.assertEqual(res_unauth.status_code, 302)

    def test_minister_board_nomination_and_decree_flow(self):
        """Minister can register nominations for CAQA leadership and record Republican decrees."""
        from apps.decisions.models import BoardNomination
        minister = User.objects.create_user(
            username="minister_nom",
            password="password123",
            role=User.Roles.MINISTER,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.client.login(username="minister_nom", password="password123")

        # Create Nomination
        res_create = self.client.post(reverse('decisions:minister_nomination_create'), {
            'nominee_name': 'أ.د. حسام الدين الصنعاني',
            'academic_rank': 'أستاذ دكتور (بروفيسور)',
            'proposed_position': BoardNomination.ProposedPosition.CHAIRMAN,
            'specialization': 'إدارة الجودة الأكاديمية والاعتماد الدولي',
            'current_institution': 'جامعة صنعاء',
            'cv_summary': 'عميد سابق لمركز التطوير الأكاديمي وخبير تقييم مؤسسي.',
            'nomination_letter_ref': 'و ت ع / 2026 / 99',
            'status': BoardNomination.NominationStatus.SUBMITTED_TO_PM,
        })
        self.assertEqual(res_create.status_code, 302)
        nom = BoardNomination.objects.filter(nominee_name='أ.د. حسام الدين الصنعاني').first()
        self.assertIsNotNone(nom)
        self.assertEqual(nom.status, BoardNomination.NominationStatus.SUBMITTED_TO_PM)

        # Update with Republican Decree
        res_update = self.client.post(reverse('decisions:minister_nomination_update', args=[nom.pk]), {
            'status': BoardNomination.NominationStatus.DECREE_ISSUED,
            'republican_decree_number': 'قرار جمهوري رقم (21) لسنة 2026',
            'minister_notes': 'صدر القرار الجمهوري بموافقة رئيس مجلس الوزراء ورئيس الجمهورية.',
        })
        self.assertEqual(res_update.status_code, 302)
        nom.refresh_from_db()
        self.assertEqual(nom.status, BoardNomination.NominationStatus.DECREE_ISSUED)
        self.assertEqual(nom.republican_decree_number, 'قرار جمهوري رقم (21) لسنة 2026')

    def test_minister_policy_ratification_and_notifications(self):
        """Minister ratifies Council policies with Ministerial Decrees and notifies stakeholders."""
        from apps.decisions.models import CouncilPolicy
        minister = User.objects.create_user(
            username="minister_pol",
            password="password123",
            role=User.Roles.MINISTER,
            approval_status=User.ApprovalStatus.APPROVED
        )
        sec_user = User.objects.create_user(
            username="sec_notif_target",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED
        )
        policy = CouncilPolicy.objects.create(
            title='لائحة معايير اعتماد المستشفيات الجامعية والمراكز الطبية التدريبية',
            policy_type=CouncilPolicy.PolicyType.EXECUTIVE_REGULATION,
            council_session_ref='محضر جلسة المجلس (06) لسنة 2026',
            submission_date=timezone.now().date(),
            summary='تنظيم اعتماد مراكز تدريب كليات الطب بالجامعات.',
            status=CouncilPolicy.RatificationStatus.PENDING_RATIFICATION
        )

        self.client.login(username="minister_pol", password="password123")

        # Minister ratifies and issues decree
        res_ratify = self.client.post(reverse('decisions:minister_policy_ratify', args=[policy.pk]), {
            'action_decision': 'RATIFY',
            'ministerial_decree_number': 'قرار وزاري رقم (55) لسنة 2026 بالمصادقة والنفاذ',
            'minister_directive': 'التعميم على كافة الجامعات للعمل بموجبها ابتداءً من تاريخه.',
        })
        self.assertEqual(res_ratify.status_code, 302)
        policy.refresh_from_db()
        self.assertEqual(policy.status, CouncilPolicy.RatificationStatus.RATIFIED)
        self.assertEqual(policy.ministerial_decree_number, 'قرار وزاري رقم (55) لسنة 2026 بالمصادقة والنفاذ')

        # Council Secretary receives notification
        notifs = Notification.objects.filter(recipient=sec_user)
        self.assertTrue(notifs.exists())
        self.assertIn("المصادقة الوزارية", notifs.first().title)

