import os
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User, Notification, AuditLog, UserDocument
from apps.institutions.models import Institution, College, AcademicProgram
from apps.standards.models import (
    StandardVersion,
    StandardCategory,
    StandardIndicator,
    AccreditationTrackType,
    RubricEvaluationLevel,
)
from apps.accreditation.models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    ApplicationStatusHistory,
    SelfStudyReport,
    SelfStudyIndicatorResponse,
    EvidenceDocument,
    DeskReviewEvaluation,
    ReviewTeam,
    ReviewTeamMember,
    ConflictOfInterestDeclaration,
    IndicatorEvaluationScore,
    ExternalReviewReport,
    SecretariatAssessmentComparisonReport,
    GrievanceAppeal,
)
from apps.operations.models import FeeSchedule, Invoice
from apps.site_visits.models import SiteVisitSchedule, FacilityInspection, StakeholderInterview
from apps.decisions.models import (
    CouncilMeeting,
    CouncilMeetingAttendance,
    CouncilAgendaItem,
    CouncilAgendaDiscussion,
    CouncilMeetingAttachment,
    CouncilBallot,
    CouncilPublicVote,
    CouncilSecretVote,
    CouncilBallotVoterRecord,
    CouncilMeetingMinutes,
    CouncilResolution,
    AccreditationDecision,
    AccreditationCertificate,
    SovereignTransaction,
)
from apps.surveillance.models import (
    ContinuousImprovementPlan,
    CorrectiveActionItem,
    AnnualMonitoringReport,
    SurveillanceVisit,
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class FullAccreditationAndCouncilLifecycle54Tests(TestCase):
    """
    Comprehensive 54-Test End-to-End Verification Suite covering:
    - Part A: Accreditation Workflow Tests (Tests 01 to 30)
    - Part B: Council Meeting & Governance Tests (Tests 31 to 54)
    """

    def setUp(self):
        self.client = Client()

        # Institutions
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-SNA-54",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY,
            decree_number="قرار جمهوري رقم (1) لسنة 1970",
            quality_center_dean="أ.د. عميد الجودة بصنعاء",
        )
        self.univ_b = Institution.objects.create(
            name="جامعة عدن",
            code="UNIV-ADN-54",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY,
            decree_number="قرار جمهوري رقم (2) لسنة 1975",
        )
        self.college_a = College.objects.create(
            institution=self.univ_a,
            name="كلية الطب والعلوم الصحية",
        )
        self.program_a = AcademicProgram.objects.create(
            college=self.college_a,
            name="بكالوريوس الطب والجراحة",
            degree_level=AcademicProgram.DegreeLevel.BACHELOR,
        )

        # Standards & Indicators
        self.std_version = StandardVersion.objects.create(
            title="معايير الاعتماد المؤسسي الوطنية 2026",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="2.0",
            status=StandardVersion.VersionStatus.ACTIVE,
        )
        self.cat_1 = StandardCategory.objects.create(
            version=self.std_version,
            track=AccreditationTrackType.INSTITUTIONAL,
            code="STD-1",
            title="الرسالة والحوكمة المؤسسية",
            weight_percentage=50,
            order=1,
            is_active=True,
        )
        self.ind_1 = StandardIndicator.objects.create(
            category=self.cat_1,
            code="IND-1.1",
            title="وضوح الرسالة والأهداف الاستراتيجية",
            explanation="تتوفر وثيقة رسمية للرسالة والأهداف الاستراتيجية معتمدة من مجلس الجامعة.",
            order=1,
        )
        self.ind_2 = StandardIndicator.objects.create(
            category=self.cat_1,
            code="IND-1.2",
            title="كفاءة الهياكل التنظيمية ومجالس الحوكمة",
            explanation="تتوفر لوائح حوكمة واضحة ومفعلة.",
            order=2,
        )

        # Different track category/indicator for track mismatch validation test
        self.cat_prog = StandardCategory.objects.create(
            version=self.std_version,
            track=AccreditationTrackType.PROGRAMMATIC,
            code="PROG-STD-1",
            title="معيار برامجي",
            weight_percentage=50,
            order=1,
            is_active=True,
        )
        self.ind_prog = StandardIndicator.objects.create(
            category=self.cat_prog,
            code="PROG-IND-1.1",
            title="مؤشر برامجي خاص",
            explanation="وصف المؤشر البرامجي",
            order=1,
        )

        # Fee Schedule
        self.fee_schedule = FeeSchedule.objects.create(
            service_name="رسوم الاعتماد المؤسسي الشامل",
            track=AccreditationTrackType.INSTITUTIONAL,
            regulatory_reference="لائحة الرسوم المالية المعتمدة 2026",
            amount_yer=1500000,
            is_active=True,
        )

        # Users across all required roles
        self.officer_a = User.objects.create_user(
            username="officer_univ_a",
            password="password123",
            first_name="خالد",
            last_name="العمري",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.president_a = User.objects.create_user(
            username="president_univ_a",
            password="password123",
            first_name="القاسم",
            last_name="عباس",
            role=User.Roles.UNIVERSITY_PRESIDENT,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.officer_b = User.objects.create_user(
            username="officer_univ_b",
            password="password123",
            first_name="سالم",
            last_name="العدني",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.president_b = User.objects.create_user(
            username="president_univ_b",
            password="password123",
            first_name="الخضر",
            last_name="لصور",
            role=User.Roles.UNIVERSITY_PRESIDENT,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.dg_accreditation = User.objects.create_user(
            username="dg_accred_user",
            password="password123",
            first_name="عبدالرحمن",
            last_name="الصعفاني",
            role=User.Roles.DG_ACCREDITATION,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.dg_evaluation = User.objects.create_user(
            username="dg_eval_user",
            password="password123",
            first_name="نبيل",
            last_name="الشامي",
            role=User.Roles.DG_EVALUATION,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.dg_finance = User.objects.create_user(
            username="dg_finance_user",
            password="password123",
            first_name="فؤاد",
            last_name="المقطري",
            role=User.Roles.DG_FINANCE_ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.sec_general = User.objects.create_user(
            username="sec_gen_user",
            password="password123",
            first_name="محمد",
            last_name="ضحيان",
            role=User.Roles.COUNCIL_SECRETARY_GENERAL,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.council_sec = User.objects.create_user(
            username="council_sec_user",
            password="password123",
            first_name="عادل",
            last_name="الأغبري",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.reviewer_chair = User.objects.create_user(
            username="rev_chair",
            password="password123",
            first_name="منصور",
            last_name="الزنداني",
            role=User.Roles.EXTERNAL_REVIEWER,
            is_certified_evaluator=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.reviewer_member = User.objects.create_user(
            username="rev_member",
            password="password123",
            first_name="هدى",
            last_name="العماد",
            role=User.Roles.EXTERNAL_REVIEWER,
            is_certified_evaluator=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.reviewer_conflicted = User.objects.create_user(
            username="rev_conflicted",
            password="password123",
            first_name="ياسر",
            last_name="الحوري",
            role=User.Roles.EXTERNAL_REVIEWER,
            is_certified_evaluator=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.chairman = User.objects.create_user(
            username="council_chair",
            password="password123",
            first_name="أحمد",
            last_name="الحبوبي",
            role=User.Roles.COUNCIL_CHAIRMAN,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.vice_chairman = User.objects.create_user(
            username="council_vice",
            password="password123",
            first_name="عزيز",
            last_name="الشيباني",
            role=User.Roles.COUNCIL_VICE_CHAIRMAN,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.board_1 = User.objects.create_user(
            username="board_mem_1",
            password="password123",
            first_name="سوسن",
            last_name="باخبيرة",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.board_2 = User.objects.create_user(
            username="board_mem_2",
            password="password123",
            first_name="فضل",
            last_name="باذيب",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.board_conflicted = User.objects.create_user(
            username="board_conflicted",
            password="password123",
            first_name="طارق",
            last_name="الصنعاني",
            role=User.Roles.BOARD_MEMBER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.invited_expert = User.objects.create_user(
            username="invited_expert",
            password="password123",
            first_name="خبير",
            last_name="مستشار",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.legal_director = User.objects.create_user(
            username="legal_dir",
            password="password123",
            first_name="جمال",
            last_name="الشرعبي",
            role=User.Roles.LEGAL_DIRECTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.grievance_judge = User.objects.create_user(
            username="grievance_judge_1",
            password="password123",
            first_name="القاضي",
            last_name="المستقل",
            role=User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.surveillance_auditor = User.objects.create_user(
            username="surv_auditor",
            password="password123",
            first_name="مفتش",
            last_name="المتابعة",
            role=User.Roles.SURVEILLANCE_AUDITOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.minister = User.objects.create_user(
            username="minister_mohe",
            password="password123",
            first_name="وزير",
            last_name="التعليم العالي",
            role=User.Roles.MINISTER,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def _create_base_application(self, status=ApplicationStatus.DRAFT):
        app = AccreditationApplication.objects.create(
            application_number=f"CAQA-INST-2026-{AccreditationApplication.objects.count()+100:04d}",
            track=AccreditationTrackType.INSTITUTIONAL,
            institution=self.univ_a,
            standard_version=self.std_version,
            applicant_user=self.officer_a,
            status=status,
            current_stage=StageChoices.STAGE_1,
        )
        SelfStudyReport.objects.get_or_create(
            application=app,
            defaults={
                'executive_summary': 'ملخص تنفيذي للدراسة الذاتية',
                'internal_committee_names': 'لجنة الجودة بجامعة صنعاء',
            }
        )
        return app

    # =========================================================================
    # PART A: ACCREDITATION WORKFLOW TESTS (TESTS 01 TO 30)
    # =========================================================================

    def test_01_institution_officer_creates_draft_application(self):
        """1. Institution officer creates draft application."""
        self.client.login(username="officer_univ_a", password="password123")
        resp = self.client.post(reverse('accreditation:application_create'), {
            'track': AccreditationTrackType.INSTITUTIONAL,
            'academic_year': '2025/2026',
            'contact_person_name': 'د. خالد العمري',
            'contact_phone': '777111222',
            'contact_email': 'quality@su.edu.ye',
            'notes': 'مسودة طلب اعتماد مؤسسي أولي',
        })
        self.assertEqual(resp.status_code, 302)
        app = AccreditationApplication.objects.filter(institution=self.univ_a).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.status, ApplicationStatus.DRAFT)
        self.assertTrue(hasattr(app, 'self_study_report'))

    def test_02_institution_officer_submits_application(self):
        """2. Institution officer submits application."""
        app = self._create_base_application(status=ApplicationStatus.DRAFT)
        self.client.login(username="officer_univ_a", password="password123")
        resp = self.client.post(reverse('accreditation:application_submit_draft', args=[app.pk]))
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PENDING_REVIEW)
        self.assertTrue(Notification.objects.filter(recipient=self.dg_accreditation).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.president_a).exists())

    def test_03_university_president_endorses_application(self):
        """3. University President endorses the application."""
        app = self._create_base_application(status=ApplicationStatus.PENDING_REVIEW)
        self.client.login(username="president_univ_a", password="password123")
        resp = self.client.post(reverse('accreditation:university_president_endorse', args=[app.pk]), {
            'president_decree_ref': 'قرار رئيس الجامعة رقم (45) لسنة 2026',
            'president_notes': 'نصادق على بيانات الطلب ونفوض عميد الجودة بالمتابعة.',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertTrue(app.president_endorsed)
        self.assertEqual(app.president_endorsed_by, self.president_a)
        self.assertEqual(app.president_decree_ref, 'قرار رئيس الجامعة رقم (45) لسنة 2026')
        self.assertTrue(SovereignTransaction.objects.filter(
            application=app,
            transaction_type=SovereignTransaction.TransactionType.PRESIDENT_ENDORSEMENT
        ).exists())

    def test_04_unauthorized_users_cannot_endorse(self):
        """4. Unauthorized users cannot endorse the application."""
        app = self._create_base_application(status=ApplicationStatus.PENDING_REVIEW)
        # Institution officer cannot endorse as University President
        self.client.login(username="officer_univ_a", password="password123")
        resp_off = self.client.post(reverse('accreditation:university_president_endorse', args=[app.pk]), {
            'president_decree_ref': 'محاولة توقيع غير مصرحة',
        })
        self.assertEqual(resp_off.status_code, 403)
        app.refresh_from_db()
        self.assertFalse(app.president_endorsed)

        # President of University B cannot endorse University A's application
        self.client.login(username="president_univ_b", password="password123")
        resp_pres_b = self.client.post(reverse('accreditation:university_president_endorse', args=[app.pk]), {
            'president_decree_ref': 'محاولة من جامعة أخرى',
        })
        self.assertEqual(resp_pres_b.status_code, 403)
        app.refresh_from_db()
        self.assertFalse(app.president_endorsed)

    def test_05_director_general_approves_application_and_sets_fee(self):
        """5. Director General approves application and sets fee."""
        app = self._create_base_application(status=ApplicationStatus.PENDING_REVIEW)
        app.president_endorsed = True
        app.president_endorsed_by = self.president_a
        app.save()

        self.client.login(username="dg_accred_user", password="password123")
        resp = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'accept_application',
            'cost_amount': '1500000',
            'cost_currency': 'YER',
            'cost_breakdown_notes': 'رسوم دراسة التقييم والزيارة الميدانية',
            'council_approval_notes': 'الموافقة والبدء بإعداد التقييم الذاتي',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        self.assertEqual(float(app.cost_amount), 1500000.0)
        self.assertTrue(Invoice.objects.filter(application=app, total_amount=1500000).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.president_a, title__contains="الموافقة على طلب الاعتماد").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a, title__contains="الموافقة على طلب الاعتماد").exists())

    def test_06_director_general_rejects_and_institution_resubmits(self):
        """6. Director General rejects/returns application with reason and institution resubmits."""
        app = self._create_base_application(status=ApplicationStatus.PENDING_REVIEW)
        self.client.login(username="dg_accred_user", password="password123")
        resp_rej = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'reject_application',
            'rejection_reason': 'يرجى إرفاق قرار الإنشاء المحدث وبيانات التواصل الرسمية.',
        })
        self.assertEqual(resp_rej.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.REJECTED)
        self.assertIn('قرار الإنشاء', app.rejection_reason)

        # Institution modifies and resubmits
        self.client.login(username="officer_univ_a", password="password123")
        resp_resub = self.client.post(reverse('accreditation:application_resubmit', args=[app.pk]), {
            'notes': 'تم إرفاق قرار الإنشاء المحدث واستيفاء الملاحظات.',
            'contact_person_name': 'د. خالد العمري',
        })
        self.assertEqual(resp_resub.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PENDING_REVIEW)
        self.assertGreaterEqual(app.status_history.count(), 2)

    def test_07_institution_completes_self_evaluation_and_uploads_evidence(self):
        """7. Institution completes self-evaluation across indicators and uploads evidence."""
        app = self._create_base_application(status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        self.client.login(username="officer_univ_a", password="password123")

        # Upload valid PDF evidence linked to indicator 1
        pdf_file = SimpleUploadedFile("evidence_1.pdf", b"%PDF-1.4 valid evidence content", content_type="application/pdf")
        resp_ev = self.client.post(reverse('accreditation:evidence_manage', args=[app.pk]), {
            'indicator': self.ind_1.pk,
            'code': 'EV-001',
            'title': 'وثيقة الخطة الاستراتيجية المعتمدة',
            'description': 'نسخة مصدقة من مجلس الجامعة',
            'document_file': pdf_file,
        })
        self.assertEqual(resp_ev.status_code, 302)
        self.assertEqual(app.evidences.count(), 1)

        # Attempt to link evidence to an unrelated track indicator -> rejected
        bad_pdf = SimpleUploadedFile("bad_track.pdf", b"%PDF-1.4 content", content_type="application/pdf")
        self.client.post(reverse('accreditation:evidence_manage', args=[app.pk]), {
            'indicator': self.ind_prog.pk,
            'code': 'EV-BAD',
            'title': 'شاهد برامجي على طلب مؤسسي',
            'document_file': bad_pdf,
        })
        self.assertFalse(app.evidences.filter(code='EV-BAD').exists())

        # Save indicator responses
        resp_ind = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[app.pk]), {
            f'compliance_{self.ind_1.id}': SelfStudyIndicatorResponse.ComplianceLevel.MET,
            f'justification_{self.ind_1.id}': 'تم اعتماد الرسالة ونشرها.',
            f'strengths_{self.ind_1.id}': 'مشاركة مجتمعية واسعة',
            f'compliance_{self.ind_2.id}': SelfStudyIndicatorResponse.ComplianceLevel.PARTIALLY_MET,
            f'justification_{self.ind_2.id}': 'الهيكل معتمد وجارٍ تحديث دليل الصلاحيات.',
            f'gaps_{self.ind_2.id}': 'تحديث توصيف بعض الوحدات',
            f'corrective_{self.ind_2.id}': 'إصدار الدليل المحدث',
        })
        self.assertEqual(resp_ind.status_code, 302)
        self.assertEqual(SelfStudyIndicatorResponse.objects.filter(report=app.self_study_report).count(), 2)

    def test_08_submitting_ssr_locks_it_and_notifies_secretariat(self):
        """8. Submitting SSR locks it and sends required notifications."""
        app = self._create_base_application(status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        EvidenceDocument.objects.create(
            application=app,
            indicator=self.ind_1,
            code="EV-101",
            title="شاهد الرسالة",
        )
        self.client.login(username="officer_univ_a", password="password123")
        resp = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[app.pk]), {
            f'compliance_{self.ind_1.id}': SelfStudyIndicatorResponse.ComplianceLevel.MET,
            f'justification_{self.ind_1.id}': 'مستوفى بالكامل',
            f'compliance_{self.ind_2.id}': SelfStudyIndicatorResponse.ComplianceLevel.MET,
            f'justification_{self.ind_2.id}': 'مستوفى بالكامل',
            'submit_self_study_official': '1',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        app.self_study_report.refresh_from_db()
        self.assertTrue(app.self_study_report.is_locked)
        self.assertEqual(app.status, ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        self.assertTrue(AuditLog.objects.filter(action='SELF_EVALUATION_SUBMITTED', target_id=str(app.self_study_report.pk)).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.dg_accreditation,
            title="تم استلام تقرير التقييم الذاتي"
        ).exists())

        # Attempt to edit locked SSR by institution officer -> blocked
        resp_locked = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[app.pk]), {
            'executive_summary': 'محاولة تعديل بعد القفل',
        })
        app.self_study_report.refresh_from_db()
        self.assertNotEqual(app.self_study_report.executive_summary, 'محاولة تعديل بعد القفل')

    def test_09_desk_review_deficiency_reopens_submission_and_preserves_history(self):
        """9. Desk review deficiency reopens submission and preserves history."""
        app = self._create_base_application(status=ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        app.self_study_report.is_locked = True
        app.self_study_report.save()

        self.client.login(username="dg_accred_user", password="password123")
        resp = self.client.post(reverse('accreditation:desk_review_process', args=[app.pk]), {
            'decision': DeskReviewEvaluation.DeskDecision.NEEDS_COMPLETION,
            'completeness_percentage': 65,
            'technical_remarks': 'نقص في مرفقات المعيار الثاني',
            'deficiencies_requested': 'إرفاق قوائم أعضاء هيئة التدريس المحدثة',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        app.self_study_report.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.DESK_DEFICIENCY)
        self.assertFalse(app.self_study_report.is_locked)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a, title__contains="نواقص").exists())
        self.assertTrue(app.status_history.filter(to_status=ApplicationStatus.DESK_DEFICIENCY).exists())

    def test_10_desk_review_acceptance_transitions_application(self):
        """10. Desk review acceptance transitions application to next stage."""
        app = self._create_base_application(status=ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        self.client.login(username="dg_accred_user", password="password123")
        resp = self.client.post(reverse('accreditation:desk_review_process', args=[app.pk]), {
            'decision': DeskReviewEvaluation.DeskDecision.ACCEPTED,
            'completeness_percentage': 100,
            'formal_criteria_met': 'on',
            'technical_remarks': 'الملف مكتمل شكلياً وفنياً.',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.DESK_ACCEPTED)
        self.assertTrue(Notification.objects.filter(recipient=self.dg_finance).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.dg_evaluation).exists())

    def test_11_invoice_created_proof_uploaded_and_finance_clears(self):
        """11. Invoice is created, payment proof uploaded, and finance officer clears payment."""
        app = self._create_base_application(status=ApplicationStatus.DESK_ACCEPTED)
        invoice = Invoice.objects.create(
            invoice_number="INV-2026-9001",
            application=app,
            fee_schedule=self.fee_schedule,
            total_amount=1500000,
            status=Invoice.PaymentStatus.UNPAID,
        )
        # Institution uploads payment proof
        self.client.login(username="officer_univ_a", password="password123")
        receipt_file = SimpleUploadedFile("bank_receipt.pdf", b"%PDF-1.4 receipt", content_type="application/pdf")
        resp_up = self.client.post(reverse('operations:invoice_detail', args=[invoice.pk]), {
            'upload_proof': '1',
            'payment_reference': 'BNK-2026-778899',
            'proof_of_payment': receipt_file,
        })
        self.assertEqual(resp_up.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_reference, 'BNK-2026-778899')
        self.assertEqual(invoice.status, Invoice.PaymentStatus.UNPAID)

        # DG Finance confirms payment and issues financial clearance
        self.client.login(username="dg_finance_user", password="password123")
        resp_conf = self.client.post(reverse('operations:invoice_detail', args=[invoice.pk]), {
            'confirm_payment': '1',
        })
        self.assertEqual(resp_conf.status_code, 302)
        invoice.refresh_from_db()
        app.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.PaymentStatus.PAID)
        self.assertEqual(invoice.verified_by, self.dg_finance)
        self.assertEqual(app.status, ApplicationStatus.FINANCIAL_CLEARED)
        self.assertTrue(Notification.objects.filter(recipient=self.dg_evaluation, title__contains="اكتمال السداد المالي").exists())

    def test_12_institution_cannot_clear_own_payment(self):
        """12. Institution cannot clear its own payment."""
        app = self._create_base_application(status=ApplicationStatus.DESK_ACCEPTED)
        invoice = Invoice.objects.create(
            invoice_number="INV-2026-9002",
            application=app,
            fee_schedule=self.fee_schedule,
            total_amount=1500000,
            status=Invoice.PaymentStatus.UNPAID,
        )
        self.client.login(username="officer_univ_a", password="password123")
        self.client.post(reverse('operations:invoice_detail', args=[invoice.pk]), {
            'confirm_payment': '1',
        })
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.PaymentStatus.UNPAID)

    def test_13_external_review_team_assigned_with_chair_and_members(self):
        """13. External review team is assigned with chair and members."""
        app = self._create_base_application(status=ApplicationStatus.FINANCIAL_CLEARED)
        self.client.login(username="dg_eval_user", password="password123")
        resp = self.client.post(reverse('accreditation:assign_review_team', args=[app.pk]), {
            'decree_number': 'قرار تشكيل رقم (77/2026)',
            'chairperson': self.reviewer_chair.pk,
            'member_ids': [self.reviewer_member.pk, self.reviewer_conflicted.pk],
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PANEL_ASSIGNED)
        self.assertEqual(app.review_team.chairperson, self.reviewer_chair)
        self.assertEqual(app.review_team.members.count(), 2)

    def test_14_reviewer_cannot_access_dossier_or_score_before_coi(self):
        """14. Reviewer cannot access dossier or score before signing COI."""
        app = self._create_base_application(status=ApplicationStatus.PANEL_ASSIGNED)
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (88)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ReviewTeamMember.objects.create(team=team, user=self.reviewer_member, role_in_team=ReviewTeamMember.PanelRole.QUALITY_EXPERT)

        self.client.login(username="rev_member", password="password123")
        # Attempt to view SSR before signing COI -> redirected to coi_declare
        resp_ssr = self.client.get(reverse('accreditation:self_study_report_view', args=[app.pk]))
        self.assertEqual(resp_ssr.status_code, 302)
        self.assertIn('coi', resp_ssr.url)

        # Attempt to access rubrics evaluation before signing COI -> redirected to coi_declare
        resp_rub = self.client.get(reverse('accreditation:external_rubrics_evaluation', args=[app.pk]))
        self.assertEqual(resp_rub.status_code, 302)
        self.assertIn('coi', resp_rub.url)

    def test_15_reviewer_with_conflict_blocked_and_secretariat_notified(self):
        """15. Reviewer with conflict is blocked and Secretariat is notified."""
        app = self._create_base_application(status=ApplicationStatus.PANEL_ASSIGNED)
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (89)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ReviewTeamMember.objects.create(team=team, user=self.reviewer_conflicted, role_in_team=ReviewTeamMember.PanelRole.QUALITY_EXPERT)

        self.client.login(username="rev_conflicted", password="password123")
        resp = self.client.post(reverse('accreditation:coi_declare', args=[app.pk]), {
            'has_taught': 'on',
            'is_conflict_acknowledged': 'on',
            'other_conflict_details': 'عملت سابقاً في نفس الكلية.',
        })
        self.assertEqual(resp.status_code, 302)

        # Conflicted reviewer is blocked from viewing SSR dossier and rubrics
        resp_ssr = self.client.get(reverse('accreditation:self_study_report_view', args=[app.pk]))
        self.assertEqual(resp_ssr.status_code, 302)
        resp_rub = self.client.get(reverse('accreditation:external_rubrics_evaluation', args=[app.pk]))
        self.assertEqual(resp_rub.status_code, 302)
        self.assertTrue(Notification.objects.filter(recipient=self.council_sec).exists())

    def test_16_reviewer_with_clean_coi_accesses_ssr_and_evidence(self):
        """16. Reviewer with clean COI accesses SSR and evidence."""
        app = self._create_base_application(status=ApplicationStatus.PANEL_ASSIGNED)
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (90)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ReviewTeamMember.objects.create(team=team, user=self.reviewer_member, role_in_team=ReviewTeamMember.PanelRole.QUALITY_EXPERT)

        self.client.login(username="rev_member", password="password123")
        resp_coi = self.client.post(reverse('accreditation:coi_declare', args=[app.pk]), {})
        self.assertEqual(resp_coi.status_code, 302)

        coi = ConflictOfInterestDeclaration.objects.get(application=app, reviewer=self.reviewer_member)
        self.assertFalse(coi.is_conflict_acknowledged)

        # Now reviewer can view SSR and access is audited
        resp_ssr = self.client.get(reverse('accreditation:self_study_report_view', args=[app.pk]))
        self.assertEqual(resp_ssr.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='SSR_DOSSIER_ACCESSED', user=self.reviewer_member).exists())

    def test_17_site_visit_scheduled_and_completed_with_records(self):
        """17. Site visit is scheduled and completed with inspection/interview records."""
        app = self._create_base_application(status=ApplicationStatus.PANEL_ASSIGNED)
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (91)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ConflictOfInterestDeclaration.objects.create(
            application=app,
            reviewer=self.reviewer_chair,
            is_conflict_acknowledged=False,
        )

        self.client.login(username="rev_chair", password="password123")
        # Add facility inspection
        self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'add_facility',
            'category': FacilityInspection.FacilityCategory.LABS,
            'facility_name': 'المختبر المركزي السريري',
            'capacity_students': 45,
            'adequacy_rating': FacilityInspection.AdequacyLevel.EXCELLENT,
            'safety_compliance': 'on',
            'detailed_observations': 'مجهز بأحدث الأجهزة ومطابق لمعايير السلامة.',
        })
        # Add stakeholder interview
        self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'add_interview',
            'target_group': StakeholderInterview.StakeholderGroup.FACULTY,
            'attendees_count': 15,
            'key_themes_discussed': 'العبء التدريسي والبحث العلمي',
            'feedback_summary': 'رضا عالٍ عن بيئة البحث العلمي',
            'satisfaction_level': 'عالٍ',
        })
        # Complete site visit
        app.status = ApplicationStatus.SITE_VISIT_SCHEDULED
        app.save()
        resp_comp = self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'update_schedule',
            'start_date': timezone.now().date().isoformat(),
            'end_date': (timezone.now().date() + timedelta(days=3)).isoformat(),
            'visit_location': 'الحرم الجامعي الرئيسي',
            'agenda_details': 'جدول الزيارة الميدانية المكتمل',
            'status': SiteVisitSchedule.VisitStatus.COMPLETED,
            'final_exit_meeting_notes': 'تم عقد اللقاء الختامي بحضور قيادة الجامعة.',
        })
        self.assertEqual(resp_comp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.SITE_VISIT_COMPLETED)
        self.assertEqual(app.site_visit.facility_inspections.count(), 1)
        self.assertEqual(app.site_visit.interviews.count(), 1)

    def test_18_reviewers_score_indicators_and_save_rubrics(self):
        """18. Reviewers score indicators and save rubrics evaluations."""
        app = self._create_base_application(status=ApplicationStatus.SITE_VISIT_COMPLETED)
        ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (92)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ConflictOfInterestDeclaration.objects.create(
            application=app,
            reviewer=self.reviewer_chair,
            is_conflict_acknowledged=False,
        )

        self.client.login(username="rev_chair", password="password123")
        resp = self.client.post(reverse('accreditation:external_rubrics_evaluation', args=[app.pk]), {
            f'score_{self.ind_1.id}': RubricEvaluationLevel.FULLY_MET,
            f'strengths_{self.ind_1.id}': 'رسالة واضحة ومعتمدة',
            f'verif_{self.ind_1.id}': 'تم التحقق من محاضر مجلس الجامعة',
            f'score_{self.ind_2.id}': RubricEvaluationLevel.SUBSTANTIALLY_MET,
            f'weaknesses_{self.ind_2.id}': 'تحتاج بعض اللوائح لتحديث دوري',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(IndicatorEvaluationScore.objects.filter(application=app, evaluator=self.reviewer_chair).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action='RUBRICS_SCORED', user=self.reviewer_chair).exists())

    def test_19_draft_external_report_sent_to_institution_for_reply(self):
        """19. Draft external report is sent to institution for right of reply."""
        app = self._create_base_application(status=ApplicationStatus.SITE_VISIT_COMPLETED)
        ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (93)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        self.client.login(username="rev_chair", password="password123")
        resp = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'save_draft',
            'draft_executive_summary': 'خلاصة مسودة التقييم الخارجي',
            'draft_findings_per_standard': 'تفاصيل نتائج المعايير الأولية',
            'response_deadline_days': '14',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.WAITING_INSTITUTION_RESPONSE)
        self.assertIsNotNone(app.external_report.response_deadline)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a, title__contains="حق الرد").exists())

    def test_20_institution_submits_formal_response_within_window(self):
        """20. Institution submits formal response within the reply window."""
        app = self._create_base_application(status=ApplicationStatus.WAITING_INSTITUTION_RESPONSE)
        ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (94)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ExternalReviewReport.objects.create(
            application=app,
            draft_executive_summary="مسودة التقرير",
            draft_findings_per_standard="النتائج",
        )
        self.client.login(username="officer_univ_a", password="password123")
        reply_doc = SimpleUploadedFile("inst_reply.pdf", b"%PDF-1.4 reply doc", content_type="application/pdf")
        resp = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'submit_institution_reply',
            'institution_reply_text': 'مذكرة رد المؤسسة وتصويب الملاحظات المادية بالمعيار الثاني.',
            'institution_reply_file': reply_doc,
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.RESPONSE_SUBMITTED)
        self.assertIn('تصويب الملاحظات', app.external_report.institution_reply_text)
        self.assertTrue(Notification.objects.filter(recipient=self.reviewer_chair, title__contains="رد المؤسسة").exists())

    def test_21_finalized_external_report_locked_and_does_not_bypass_council(self):
        """21. Finalized external report is locked and does not bypass Council decision."""
        app = self._create_base_application(status=ApplicationStatus.RESPONSE_SUBMITTED)
        ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (95)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        ExternalReviewReport.objects.create(
            application=app,
            draft_executive_summary="مسودة التقرير",
            draft_findings_per_standard="النتائج",
            institution_reply_text="رد المؤسسة",
        )
        self.client.login(username="rev_chair", password="password123")
        resp = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'finalize_report',
            'team_response_to_reply': 'تمت دراسة رد المؤسسة وقبول التوضيح.',
            'final_report_text': 'التقرير الفني النهائي المعتمد من فريق المراجعة الخارجية.',
            'final_recommendation': ExternalReviewReport.FinalRecommendation.FULL_ACCREDITATION,
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        # Status is FINAL_REPORT_READY, NOT FULL_ACCREDITATION (does not bypass Council decision)
        self.assertEqual(app.status, ApplicationStatus.FINAL_REPORT_READY)
        self.assertFalse(hasattr(app, 'council_decision'))
        self.assertTrue(Notification.objects.filter(recipient=self.dg_evaluation).exists())

        # Attempt to overwrite locked finalized report -> 403 Forbidden
        resp_edit = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'finalize_report',
            'final_report_text': 'تعديل غير مصرح بعد القفل',
        })
        self.assertEqual(resp_edit.status_code, 403)

    def test_22_comparative_report_compares_self_and_external_scores(self):
        """22. Comparative report compares self-evaluation and external evaluation scores."""
        app = self._create_base_application(status=ApplicationStatus.FINAL_REPORT_READY)
        SelfStudyIndicatorResponse.objects.create(
            report=app.self_study_report,
            indicator=self.ind_1,
            compliance_level=SelfStudyIndicatorResponse.ComplianceLevel.MET,
            justification="تقييم ذاتي مستوفى",
        )
        IndicatorEvaluationScore.objects.create(
            application=app,
            indicator=self.ind_1,
            evaluator=self.reviewer_chair,
            score_level=RubricEvaluationLevel.SUBSTANTIALLY_MET,
            strengths="تقييم خارجي جوهري",
        )
        self.client.login(username="dg_eval_user", password="password123")
        resp = self.client.post(reverse('accreditation:secretariat_comparison_dashboard', args=[app.pk]), {
            'save_comparison_report': '1',
            'comparison_title': 'التقرير المقارن الشامل - جامعة صنعاء',
            'secretariat_analytical_summary': 'تطابق بنسبة 85% بين التقييم الذاتي والخارجي.',
        })
        self.assertEqual(resp.status_code, 302)
        comp = SecretariatAssessmentComparisonReport.objects.filter(application=app).first()
        self.assertIsNotNone(comp)
        self.assertTrue(comp.attached_to_council_briefing)
        self.assertIn('category_summary', comp.comparison_data_json)
        self.assertTrue(Notification.objects.filter(recipient=self.board_1).exists())

    def test_23_council_decision_requires_valid_meeting_and_vote(self):
        """23. Council decision issuance requires a valid meeting and quorum/vote."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting_no_quorum = CouncilMeeting.objects.create(
            meeting_number="M-NO-QUORUM-23",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول الأعمال",
            quorum_required=3,
        )
        # Invite 3 voting members, only 1 confirms -> no quorum
        for m in [self.chairman, self.board_1, self.board_2]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting_no_quorum,
                member=m,
                attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
                status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED if m == self.chairman else CouncilMeetingAttendance.RSVPStatus.INVITED,
            )

        self.client.login(username="council_chair", password="password123")
        resp = self.client.post(reverse('decisions:issue_decision', args=[app.pk]), {
            'meeting_id': meeting_no_quorum.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': 'قرار غير مكتمل النصاب',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AccreditationDecision.objects.filter(application=app).exists())

    def test_24_full_or_conditional_accreditation_generates_certificate_and_qr(self):
        """24. Full or conditional accreditation generates certificate and QR verification record."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-VALID-24",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول الأعمال",
            quorum_required=2,
        )
        for m in [self.chairman, self.board_1, self.board_2]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=m,
                attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
                status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            )

        self.client.login(username="council_chair", password="password123")
        resp = self.client.post(reverse('decisions:issue_decision', args=[app.pk]), {
            'meeting_id': meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': 'قرار مجلس الاعتماد رقم (2026/24)',
            'validity_years': 5,
            'legal_justifications': 'استيفاء كافة معايير الاعتماد المؤسسي.',
        })
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.FULL_ACCREDITATION)
        cert = AccreditationCertificate.objects.filter(decision__application=app).first()
        self.assertIsNotNone(cert)
        self.assertIsNotNone(cert.certificate_uuid)
        self.assertTrue(Notification.objects.filter(recipient=self.president_a).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.minister).exists())

    def test_25_public_certificate_verification_returns_only_public_fields(self):
        """25. Public certificate verification returns only public fields."""
        app = self._create_base_application(status=ApplicationStatus.FULL_ACCREDITATION)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-PUB-25",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        decision = AccreditationDecision.objects.create(
            meeting=meeting,
            application=app,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار رقم (25/2026)",
            decision_date=timezone.now().date(),
            validity_years=5,
            legal_justifications="حيثيات سرية داخلية لا تظهر للعامة",
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code="YEM-CAQA-2026-0025",
            issue_date=timezone.now().date(),
        )
        self.client.logout()
        resp = self.client.get(reverse('decisions:verify_certificate_public', args=[cert.certificate_uuid]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, cert.national_registry_code)
        self.assertContains(resp, self.univ_a.name)
        self.assertNotContains(resp, "حيثيات سرية داخلية لا تظهر للعامة")

    def test_26_institution_submits_grievance_with_grounds_and_attachment(self):
        """26. Institution submits grievance with grounds and attachment."""
        app = self._create_base_application(status=ApplicationStatus.DENIED)
        self.client.login(username="officer_univ_a", password="password123")
        appeal_doc = SimpleUploadedFile("appeal_memo.pdf", b"%PDF-1.4 legal appeal", content_type="application/pdf")
        resp = self.client.post(reverse('accreditation:grievance_create', args=[app.pk]), {
            'grounds_of_appeal': 'تظلم رسمي بسبب عدم احتساب شواهد المعيار الثالث المحدثة.',
            'supporting_document': appeal_doc,
        })
        self.assertEqual(resp.status_code, 302)
        appeal = GrievanceAppeal.objects.filter(application=app).first()
        self.assertIsNotNone(appeal)
        self.assertEqual(appeal.status, GrievanceAppeal.AppealStatus.SUBMITTED)
        self.assertTrue(Notification.objects.filter(recipient=self.legal_director).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.grievance_judge).exists())

    def test_27_grievance_committee_reviews_and_board_resolves_with_independence(self):
        """27. Grievance committee reviews appeal and Board resolves it (enforcing reviewer independence)."""
        app = self._create_base_application(status=ApplicationStatus.DENIED)
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="قرار (27)",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_chair,
        )
        appeal = GrievanceAppeal.objects.create(
            application=app,
            appellant_user=self.officer_a,
            appeal_number="GRV-2026-027",
            grounds_of_appeal="أسباب التظلم القانونية",
        )

        # Reviewer who participated in original evaluation cannot adjudicate grievance even if given legal role
        self.reviewer_chair.role = User.Roles.GRIEVANCE_COMMITTEE_MEMBER
        self.reviewer_chair.save()
        self.client.login(username="rev_chair", password="password123")
        resp_blocked = self.client.post(reverse('accreditation:grievance_review', args=[appeal.pk]), {
            'action': 'save_legal_report',
            'committee_report': 'تقرير غير محايد',
        })
        self.assertEqual(resp_blocked.status_code, 403)
        self.reviewer_chair.role = User.Roles.EXTERNAL_REVIEWER
        self.reviewer_chair.save()

        # Independent Grievance Committee member submits legal report
        self.client.login(username="grievance_judge_1", password="password123")
        resp_leg = self.client.post(reverse('accreditation:grievance_review', args=[appeal.pk]), {
            'action': 'save_legal_report',
            'committee_report': 'توصي اللجنة المستقلة بقبول التظلم شكلاً وموضوعاً وإعادة النظر.',
        })
        self.assertEqual(resp_leg.status_code, 302)
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW)

        # Council Chairman resolves appeal
        self.client.login(username="council_chair", password="password123")
        resp_res = self.client.post(reverse('accreditation:grievance_review', args=[appeal.pk]), {
            'action': 'resolve_board',
            'final_resolution': 'accept',
            'final_resolution_notes': 'قبول التظلم وإعادة النظر في تقييم المعيار الثالث.',
        })
        self.assertEqual(resp_res.status_code, 302)
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION)
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a, title__contains=appeal.appeal_number).exists())

    def test_28_surveillance_plan_and_annual_report_workflow(self):
        """28. Surveillance plan and annual report workflow works after accreditation."""
        app = self._create_base_application(status=ApplicationStatus.CONDITIONAL_ACCREDITATION)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-SURV-28",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        decision = AccreditationDecision.objects.create(
            meeting=meeting,
            application=app,
            decision_type=AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
            decree_number="قرار مشروط (28/2026)",
            decision_date=timezone.now().date(),
            validity_years=2,
            legal_justifications="استيفاء مشروط",
            corrective_requirements="استكمال تجهيز المختبرات خلال عام",
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code="YEM-CAQA-2026-0028",
            issue_date=timezone.now().date(),
            status=AccreditationCertificate.CertificateStatus.ACTIVE,
        )

        self.client.login(username="officer_univ_a", password="password123")
        # Institution accesses surveillance management & submits annual monitoring report
        resp = self.client.post(reverse('surveillance:manage', args=[decision.pk]), {
            'action': 'submit_annual_report',
            'year_number': 1,
            'reporting_period': 'العام الأكاديمي الأول 2026/2027',
            'progress_summary': 'تم إنجاز 90% من تجهيز المختبرات.',
            'quality_improvements_achieved': 'شراء وتركيب 15 جهازاً مخبرياً حديثاً.',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(decision.annual_reports.count(), 1)
        # Certificate is NOT automatically renewed on annual report submission
        cert.refresh_from_db()
        self.assertEqual(cert.status, AccreditationCertificate.CertificateStatus.ACTIVE)

    def test_29_cross_institution_access_blocked_everywhere(self):
        """29. Cross-institution access is blocked across all endpoints."""
        app_a = self._create_base_application(status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        invoice_a = Invoice.objects.create(
            invoice_number="INV-ISO-29",
            application=app_a,
            fee_schedule=self.fee_schedule,
            total_amount=1500000,
        )
        self.client.login(username="officer_univ_b", password="password123")

        # Officer B cannot view University A's application detail, SSR, or invoice
        resp_app = self.client.get(reverse('accreditation:application_detail', args=[app_a.pk]))
        self.assertEqual(resp_app.status_code, 302)
        resp_ssr = self.client.get(reverse('accreditation:self_study_report_view', args=[app_a.pk]))
        self.assertEqual(resp_ssr.status_code, 302)
        resp_inv = self.client.get(reverse('operations:invoice_detail', args=[invoice_a.pk]))
        self.assertEqual(resp_inv.status_code, 302)

    def test_30_all_major_documents_sync_to_my_library(self):
        """30. All major documents sync to My Library for authorized owners/recipients."""
        app = self._create_base_application(status=ApplicationStatus.FULL_ACCREDITATION)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-LIB-30",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        decision = AccreditationDecision.objects.create(
            meeting=meeting,
            application=app,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار مكتبتي (30/2026)",
            decision_date=timezone.now().date(),
            validity_years=5,
            legal_justifications="حيثيات الاعتماد",
        )
        AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code="YEM-CAQA-2026-0030",
            issue_date=timezone.now().date(),
        )
        from apps.accounts.library_service import sync_system_assets_to_library
        sync_system_assets_to_library()

        self.assertTrue(UserDocument.objects.filter(application=app).exists())

    # =========================================================================
    # PART B: COUNCIL MEETING & GOVERNANCE TESTS (TESTS 31 TO 54)
    # =========================================================================

    def test_31_authorized_user_creates_ordinary_or_extraordinary_meeting(self):
        """31. Authorized user creates an ordinary or extraordinary Council meeting."""
        self.client.login(username="council_chair", password="password123")
        resp = self.client.post(reverse('decisions:meeting_create'), {
            'meeting_number': 'جلسة استثنائية (31/2026)',
            'meeting_type': CouncilMeeting.MeetingType.EXTRAORDINARY,
            'meeting_date': timezone.now().date().isoformat(),
            'meeting_time': '10:00',
            'location': 'القاعة الكبرى بالمجلس - صنعاء',
            'chairperson_name': 'أ.د. أحمد الحبوبي',
            'quorum_required': 3,
            'meeting_agenda': 'مناقشة ملفات الاعتماد المؤسسي الطارئة',
        })
        self.assertEqual(resp.status_code, 302)
        m = CouncilMeeting.objects.filter(meeting_number='جلسة استثنائية (31/2026)').first()
        self.assertIsNotNone(m)
        self.assertEqual(m.meeting_type, CouncilMeeting.MeetingType.EXTRAORDINARY)

    def test_32_unauthorized_user_cannot_create_or_modify_meeting(self):
        """32. Unauthorized user cannot create or modify a Council meeting."""
        self.client.login(username="officer_univ_a", password="password123")
        resp = self.client.post(reverse('decisions:meeting_create'), {
            'meeting_number': 'جلسة غير مصرحة',
            'meeting_date': timezone.now().date().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CouncilMeeting.objects.filter(meeting_number='جلسة غير مصرحة').exists())

    def test_33_agenda_items_created_ordered_and_linked_to_applications(self):
        """33. Agenda items are created, ordered, and linked to accreditation applications."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-AGENDA-33",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        self.client.login(username="sec_gen_user", password="password123")
        resp = self.client.post(reverse('decisions:agenda_item_create', args=[meeting.pk]), {
            'item_number': 'البند الأول',
            'position': 1,
            'title': 'البت في طلب الاعتماد المؤسسي لجامعة صنعاء',
            'item_category': CouncilAgendaItem.ItemCategory.INSTITUTIONAL_ACCREDITATION,
            'required_action': CouncilAgendaItem.RequiredAction.APPROVAL,
            'application_id': app.pk,
            'referring_entity': 'الإدارة العامة للتقييم والمراجعة الخارجية',
            'description': 'عرض ملف الاعتماد المؤسسي لجامعة صنعاء',
            'initial_recommendation': 'منح الاعتماد المؤسسي الكامل لمدة 5 سنوات',
        })
        self.assertEqual(resp.status_code, 302)
        item = meeting.agenda_items.first()
        self.assertIsNotNone(item)
        self.assertEqual(item.application, app)
        self.assertEqual(item.position, 1)

    def test_34_invitations_sent_to_council_members_with_notifications(self):
        """34. Invitations are sent to Council members with notifications."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-INV-34",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            status=CouncilMeeting.MeetingStatus.DRAFT,
        )
        self.client.login(username="council_chair", password="password123")
        resp = self.client.post(reverse('decisions:meeting_send_invitations', args=[meeting.pk]))
        self.assertEqual(resp.status_code, 302)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.INVITATIONS_SENT)
        self.assertTrue(CouncilMeetingAttendance.objects.filter(meeting=meeting, member=self.board_1).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.board_1).exists())

    def test_35_members_confirm_attendance_or_submit_apology_with_reason(self):
        """35. Members confirm attendance or submit apology with reason."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-RSVP-35",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        CouncilMeetingAttendance.objects.create(meeting=meeting, member=self.board_1)
        CouncilMeetingAttendance.objects.create(meeting=meeting, member=self.board_2)

        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {'status': 'CONFIRMED'})
        att_1 = CouncilMeetingAttendance.objects.get(meeting=meeting, member=self.board_1)
        self.assertEqual(att_1.status, CouncilMeetingAttendance.RSVPStatus.CONFIRMED)

        self.client.login(username="board_mem_2", password="password123")
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {
            'status': 'APOLOGIZED',
            'remarks': 'مهمة علمية رسمية خارج البلاد',
        })
        att_2 = CouncilMeetingAttendance.objects.get(meeting=meeting, member=self.board_2)
        self.assertEqual(att_2.status, CouncilMeetingAttendance.RSVPStatus.APOLOGIZED)
        self.assertEqual(att_2.remarks, 'مهمة علمية رسمية خارج البلاد')

    def test_36_quorum_calculated_correctly_from_active_voting_members(self):
        """36. Quorum is calculated correctly from active voting members (Article 6 majority)."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-QUORUM-36",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            use_dynamic_quorum=True,
        )
        # 4 voting members invited -> majority required is (4 // 2) + 1 = 3
        for m in [self.chairman, self.vice_chairman, self.board_1, self.board_2]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=m,
                attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
                status=CouncilMeetingAttendance.RSVPStatus.INVITED,
            )
        self.assertEqual(meeting.effective_quorum_required(), 3)
        self.assertFalse(meeting.is_quorum_met())

        CouncilMeetingAttendance.objects.filter(
            meeting=meeting, member__in=[self.chairman, self.vice_chairman, self.board_1]
        ).update(status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED)
        self.assertTrue(meeting.is_quorum_met())

    def test_37_invited_experts_do_not_count_toward_quorum_or_vote(self):
        """37. Invited experts do not count toward quorum and cannot vote."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-EXPERT-37",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=2,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.chairman,
            attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.invited_expert,
            attendee_category=CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        # Only 1 voting member present + 1 expert -> confirmed_attendance_count is 1 -> quorum (2) NOT met!
        self.assertEqual(meeting.confirmed_attendance_count(), 1)
        self.assertFalse(meeting.is_quorum_met())

    def test_38_meeting_cannot_issue_decisions_without_quorum(self):
        """38. Meeting cannot start session or open voting without quorum."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-NOQ-38",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            status=CouncilMeeting.MeetingStatus.INVITATIONS_SENT,
            quorum_required=3,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.chairman,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:meeting_status_transition', args=[meeting.pk]), {
            'status': CouncilMeeting.MeetingStatus.IN_SESSION,
        })
        meeting.refresh_from_db()
        self.assertNotEqual(meeting.status, CouncilMeeting.MeetingStatus.IN_SESSION)

    def test_39_council_member_views_complete_17_part_accreditation_dossier(self):
        """39. Council member views the complete 17-part accreditation dossier from the agenda item."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-DOSSIER-39",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        item = CouncilAgendaItem.objects.create(
            meeting=meeting,
            item_number="بند 1",
            position=1,
            title="ملف اعتماد جامعة صنعاء",
            description="تفاصيل ملف الاعتماد",
            application=app,
        )
        self.client.login(username="board_mem_1", password="password123")
        resp = self.client.get(reverse('decisions:agenda_item_detail', args=[item.pk]))
        self.assertEqual(resp.status_code, 200)
        dossier = resp.context['dossier']
        for part_num in range(1, 18):
            self.assertTrue(any(k.startswith(f"part_{part_num}_") for k in dossier.keys()))

    def test_40_member_interventions_and_reservations_recorded(self):
        """40. Member interventions, questions, and reservations are recorded on agenda items."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-DISC-40",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
        )
        item = CouncilAgendaItem.objects.create(
            meeting=meeting,
            item_number="بند 1",
            position=1,
            title="مناقشة معايير الاعتماد",
            description="تفاصيل المعايير",
        )
        self.client.login(username="board_mem_1", password="password123")
        resp = self.client.post(reverse('decisions:agenda_item_add_discussion', args=[item.pk]), {
            'intervention_type': CouncilAgendaDiscussion.InterventionType.RESERVATION,
            'content': 'أتحفظ رسمياً على تقليص مهلة الخطة التصحيحية إلى أقل من سنة.',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(item.discussions.filter(
            intervention_type=CouncilAgendaDiscussion.InterventionType.RESERVATION
        ).exists())

    def test_41_public_voting_records_votes_and_calculates_majority(self):
        """41. Public voting records member votes and calculates majority result."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-PUBVOTE-41",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            chairperson_user=self.chairman,
            meeting_agenda="جدول",
            quorum_required=2,
            use_dynamic_quorum=False,
        )
        for m in [self.chairman, self.board_1, self.board_2]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=m,
                status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="تصويت علني على لائحة داخلية",
            voting_mode=CouncilBallot.VotingMode.PUBLIC,
        )
        for user_obj, choice in [
            (self.chairman, CouncilSecretVote.VoteChoice.FULL),
            (self.board_1, CouncilSecretVote.VoteChoice.FULL),
            (self.board_2, CouncilSecretVote.VoteChoice.DENIED),
        ]:
            self.client.login(username=user_obj.username, password="password123")
            self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {'vote_choice': choice})

        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot.pk]))
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, CouncilBallot.BallotStatus.CLOSED)
        self.assertEqual(ballot.votes_full_count, 2)
        self.assertEqual(ballot.votes_denied_count, 1)
        self.assertTrue(ballot.majority_achieved)
        self.assertEqual(ballot.final_result, 'APPROVED')

    def test_42_secret_voting_preserves_ballot_confidentiality(self):
        """42. Secret voting records voter participation while preserving ballot confidentiality."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-SECVOTE-42",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=1,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.board_1,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="اقتراع سري على منح الاعتماد",
            voting_mode=CouncilBallot.VotingMode.SECRET,
        )
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.CONDITIONAL,
        })
        self.assertTrue(CouncilBallotVoterRecord.objects.filter(ballot=ballot, voter=self.board_1).exists())
        secret_vote = CouncilSecretVote.objects.filter(ballot=ballot).first()
        self.assertIsNotNone(secret_vote)
        self.assertFalse(hasattr(secret_vote, 'voter'))

    def test_43_member_cannot_vote_twice_on_same_ballot(self):
        """43. Member cannot vote twice on the same ballot."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-DBL-43",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=1,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.board_1,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="اقتراع",
            voting_mode=CouncilBallot.VotingMode.SECRET,
        )
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL,
        })
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.DENIED,
        })
        self.assertEqual(CouncilSecretVote.objects.filter(ballot=ballot).count(), 1)

    def test_44_member_cannot_vote_when_ballot_closed(self):
        """44. Member cannot vote when ballot is closed."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-CLSD-44",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=1,
            use_dynamic_quorum=False,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="اقتراع مغلق",
            status=CouncilBallot.BallotStatus.CLOSED,
        )
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL,
        })
        self.assertEqual(CouncilSecretVote.objects.filter(ballot=ballot).count(), 0)

    def test_45_member_with_conflict_blocked_from_voting(self):
        """45. Member with conflict of interest is blocked from voting on the conflicted item."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-COI-45",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=1,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.board_conflicted,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            application=app,
            title="اقتراع على جامعة صنعاء",
            voting_mode=CouncilBallot.VotingMode.SECRET,
        )
        # board_conflicted belongs to univ_a (same as app.institution) -> blocked!
        self.client.login(username="board_conflicted", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL,
        })
        self.assertEqual(CouncilSecretVote.objects.filter(ballot=ballot).count(), 0)

    def test_46_tie_vote_follows_chairperson_side_in_public_voting(self):
        """46. Tie vote follows the Chairperson's side in public voting when applicable."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-TIE-46",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            chairperson_user=self.chairman,
            meeting_agenda="جدول",
            quorum_required=2,
            use_dynamic_quorum=False,
        )
        for m in [self.chairman, self.board_1]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=m,
                status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="تصويت علني متعادل الأصوات",
            voting_mode=CouncilBallot.VotingMode.PUBLIC,
        )
        # Chairman votes FULL, Board Member 1 votes DENIED -> 1 vs 1 tie!
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL,
        })
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.DENIED,
        })
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot.pk]))
        ballot.refresh_from_db()
        self.assertTrue(ballot.tie_occurred)
        self.assertTrue(ballot.tie_broken_by_chairperson)
        self.assertEqual(ballot.final_result, 'APPROVED_BY_CHAIR_TIEBREAK')

    def test_47_votes_cannot_be_altered_after_ballot_closure(self):
        """47. Votes cannot be altered after ballot closure."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-IMMUT-47",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جدول",
            quorum_required=1,
            use_dynamic_quorum=False,
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.board_1,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            title="تصويت علني",
            voting_mode=CouncilBallot.VotingMode.PUBLIC,
        )
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL,
        })
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot.pk]))

        pub_vote = CouncilPublicVote.objects.get(ballot=ballot, voter=self.board_1)
        with self.assertRaises(Exception):
            pub_vote.vote_choice = CouncilSecretVote.VoteChoice.DENIED
            pub_vote.save()

    def test_48_official_meeting_minutes_generated_with_all_sections(self):
        """48. Official meeting minutes are generated with attendance, agenda, discussions, voting results, reservations, and decisions."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-MIN-48",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول الأعمال الرسمي",
        )
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.chairman,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        item = CouncilAgendaItem.objects.create(
            meeting=meeting,
            item_number="بند 1",
            position=1,
            title="اعتماد برنامج الطب",
            description="تفاصيل البرنامج",
        )
        CouncilAgendaDiscussion.objects.create(
            agenda_item=item,
            speaker=self.board_1,
            speaker_name="أ.د. سوسن",
            intervention_type=CouncilAgendaDiscussion.InterventionType.RESERVATION,
            content="تحفظ رسمي مثبت في المحضر",
        )
        self.client.login(username="sec_gen_user", password="password123")
        resp = self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'opening_statement': 'افتتحت الجلسة برئاسة رئيس المجلس.',
            'closing_statement': 'أغلقت الجلسة في تمام الساعة الثانية ظهراً.',
        })
        self.assertEqual(resp.status_code, 302)
        minutes = meeting.official_minutes
        self.assertIn("اعتماد برنامج الطب", minutes.discussions_record)
        self.assertIn("تحفظ رسمي مثبت في المحضر", minutes.discussions_record)

    def test_49_approved_minutes_locked_against_unauthorized_edits(self):
        """49. Approved minutes are locked against unauthorized edits."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-LOCKMIN-49",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول",
        )
        minutes = CouncilMeetingMinutes.objects.create(
            meeting=meeting,
            minutes_number="MIN-49",
            opening_statement="نص المحضر الأصلي",
            status=CouncilMeetingMinutes.MinutesStatus.APPROVED,
        )
        self.client.login(username="sec_gen_user", password="password123")
        self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'opening_statement': 'محاولة تعديل بعد المصادقة والقفل',
        })
        minutes.refresh_from_db()
        self.assertEqual(minutes.opening_statement, "نص المحضر الأصلي")

    def test_50_decisions_and_recommendations_generated_with_unique_numbers(self):
        """50. Decisions and recommendations are generated with unique numbers."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-RES-50",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول",
        )
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:resolution_create', args=[meeting.pk]), {
            'resolution_type': CouncilResolution.ResolutionType.FINAL_DECISION,
            'title': 'قرار تنظيمي أول',
            'decision_text': 'نص القرار الأول',
            'responsible_entity': 'الأمانة العامة',
        })
        self.client.post(reverse('decisions:resolution_create', args=[meeting.pk]), {
            'resolution_type': CouncilResolution.ResolutionType.RECOMMENDATION,
            'title': 'توصية فنية ثانية',
            'decision_text': 'نص التوصية الثانية',
            'responsible_entity': 'الإدارة العامة للجودة',
        })
        resolutions = list(meeting.resolutions.all())
        self.assertEqual(len(resolutions), 2)
        self.assertNotEqual(resolutions[0].resolution_number, resolutions[1].resolution_number)

    def test_51_execution_assignments_track_responsible_entity_and_status(self):
        """51. Execution assignments track responsible entity, deadline, and completion status."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-EXEC-51",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول",
        )
        res = CouncilResolution.objects.create(
            meeting=meeting,
            resolution_number="RES-2026-051",
            resolution_type=CouncilResolution.ResolutionType.ASSIGNMENT,
            title="تكليف بإعداد دليل محدث",
            decision_text="تكليف الإدارة العامة للاعتماد بإعداد الدليل.",
            responsible_entity="الإدارة العامة للاعتماد والتراخيص",
            responsible_user=self.dg_accreditation,
            deadline_date=timezone.now().date() + timedelta(days=30),
        )
        self.client.login(username="dg_accred_user", password="password123")
        resp = self.client.post(reverse('decisions:resolution_update_status', args=[res.pk]), {
            'implementation_status': CouncilResolution.ImplementationStatus.COMPLETED,
            'followup_notes': 'تم إنجاز الدليل المحدث ورفعه للأمانة العامة.',
        })
        self.assertEqual(resp.status_code, 302)
        res.refresh_from_db()
        self.assertEqual(res.implementation_status, CouncilResolution.ImplementationStatus.COMPLETED)
        self.assertIsNotNone(res.completion_date)

    def test_52_postponed_or_incomplete_items_carried_over_to_next_meeting(self):
        """52. Postponed or incomplete agenda items can be carried over to a subsequent meeting."""
        m1 = CouncilMeeting.objects.create(
            meeting_number="M-52-A",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول 1",
        )
        m2 = CouncilMeeting.objects.create(
            meeting_number="M-52-B",
            meeting_date=timezone.now().date() + timedelta(days=14),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول 2",
        )
        item = CouncilAgendaItem.objects.create(
            meeting=m1,
            item_number="بند مؤجل",
            position=1,
            title="موضوع مؤجل للجلسة القادمة",
            description="تفاصيل البند المؤجل",
            status=CouncilAgendaItem.ItemStatus.POSTPONED,
        )
        self.client.login(username="sec_gen_user", password="password123")
        resp = self.client.post(reverse('decisions:agenda_item_carry_over', args=[item.pk]), {
            'target_meeting_id': m2.pk,
        })
        self.assertEqual(resp.status_code, 302)
        carried = m2.agenda_items.filter(title=item.title).first()
        self.assertIsNotNone(carried)
        self.assertEqual(carried.title, item.title)

    def test_53_confidential_attachments_restricted_to_authorized_members(self):
        """53. Confidential meeting attachments are restricted to authorized Council members."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-CONF-53",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول",
        )
        item = CouncilAgendaItem.objects.create(
            meeting=meeting,
            item_number="بند 1",
            position=1,
            title="بند سري",
            description="تفاصيل البند",
        )
        item.authorized_experts.add(self.invited_expert)
        CouncilMeetingAttendance.objects.create(
            meeting=meeting,
            member=self.invited_expert,
            attendee_category=CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT,
            status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
        )
        CouncilMeetingAttachment.objects.create(
            meeting=meeting,
            agenda_item=item,
            title="مرفق سري خاص بأعضاء المجلس فقط",
            file=SimpleUploadedFile("secret.pdf", b"%PDF-1.4 secret", content_type="application/pdf"),
            is_confidential=True,
        )
        CouncilMeetingAttachment.objects.create(
            meeting=meeting,
            agenda_item=item,
            title="مرفق فني عام للخبير",
            file=SimpleUploadedFile("public.pdf", b"%PDF-1.4 public", content_type="application/pdf"),
            is_confidential=False,
        )
        # Invited expert views agenda item -> sees non-confidential attachment only, NOT confidential one
        self.client.login(username="invited_expert", password="password123")
        resp_exp = self.client.get(reverse('decisions:agenda_item_detail', args=[item.pk]))
        self.assertEqual(resp_exp.status_code, 200)
        self.assertEqual(resp_exp.context['attachments'].count(), 1)
        self.assertFalse(resp_exp.context['attachments'].first().is_confidential)

        # Board member views agenda item -> sees both attachments
        self.client.login(username="board_mem_1", password="password123")
        resp_bm = self.client.get(reverse('decisions:agenda_item_detail', args=[item.pk]))
        self.assertEqual(resp_bm.status_code, 200)
        self.assertEqual(resp_bm.context['attachments'].count(), 2)

    def test_54_final_accreditation_decision_linked_to_meeting_vote_and_resolution(self):
        """54. Final accreditation decision is linked to meeting, vote, and resolution."""
        app = self._create_base_application(status=ApplicationStatus.IN_COUNCIL_REVIEW)
        meeting = CouncilMeeting.objects.create(
            meeting_number="M-LINK-54",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. أحمد الحبوبي",
            meeting_agenda="جدول",
            quorum_required=2,
            use_dynamic_quorum=False,
        )
        for m in [self.chairman, self.board_1, self.board_2]:
            CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=m,
                status=CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            )
        item = CouncilAgendaItem.objects.create(
            meeting=meeting,
            item_number="بند 1",
            position=1,
            title="البت في اعتماد جامعة صنعاء",
            description="تفاصيل البند",
            application=app,
        )
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            agenda_item=item,
            application=app,
            title="اقتراع سري على اعتماد جامعة صنعاء",
            voting_mode=CouncilBallot.VotingMode.SECRET,
            status=CouncilBallot.BallotStatus.CLOSED,
            votes_full_count=3,
            votes_approve_count=3,
            votes_conditional_count=0,
            votes_denied_count=0,
            votes_reject_count=0,
            majority_achieved=True,
            final_result='APPROVED',
        )

        self.client.login(username="council_chair", password="password123")
        resp = self.client.post(reverse('decisions:issue_decision', args=[app.pk]), {
            'meeting_id': meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': 'قرار مجلس الاعتماد رقم (54/2026)',
            'validity_years': 5,
            'legal_justifications': 'بناءً على نتيجة الاقتراع السري بالإجماع.',
        })
        self.assertEqual(resp.status_code, 302)
        decision = AccreditationDecision.objects.get(application=app)
        self.assertEqual(decision.meeting, meeting)
        self.assertEqual(decision.votes_in_favor, 3)
        item.refresh_from_db()
        self.assertEqual(item.status, CouncilAgendaItem.ItemStatus.DECIDED)
        self.assertTrue(CouncilResolution.objects.filter(meeting=meeting, agenda_item=item).exists())

    def test_55_phase1_targeted_repairs_full_flow(self):
        """
        55. Phase 1 Targeted Repairs End-to-End Verification:
        - Point 1: Application submission sends notification + Application Report link (/accreditation/<pk>/report/) + My Library copy to University President & DG Accreditation.
        - Point 2: Rejection/modification sends notification with direct URL (/accreditation/<pk>/resubmit/) to Institution & University President, allowing modification & resubmission to DG Accreditation.
        - Point 3: Initial approval sends notification with direct URL (/accreditation/<pk>/#approved-paths) and exposes 2 direct paths: Invoice Payment (/operations/invoices/<inv_pk>/) & Self-Study Preparation (/accreditation/<pk>/self-study/).
        - Point 4: Self-Study submission sends notification to DG Accreditation with direct URL (/accreditation/<pk>/self-study/report/).
        - Point 5:
          * External Reviewer sends modification report -> preserves Original SSR in My Library, unlocks SSR for Institution, notifies Institution.
          * Institution modifies SSR & submits reply -> saves Modified SSR in My Library alongside Original SSR, notifies External Reviewer & DG Evaluation.
          * External Reviewer finalizes & sends External Report to DG Evaluation -> notifies DG Evaluation with direct URL (/accreditation/<pk>/external-report/) and saves External Report + Original SSR + Modified SSR in DG Evaluation's My Library.
          * DG Evaluation generates Comparison Report with Evidences & sends to Council -> transitions to IN_COUNCIL_REVIEW, includes evidences in comparison_data_json, and notifies Council Board.
        """
        from apps.accounts.models import UserDocument, DocumentShare
        from apps.accreditation.models import EvidenceDocument

        # --- POINT 1: Submit Application -> Notification + Report Copy to President & DG Accreditation ---
        self.client.login(username="officer_univ_a", password="password123")
        resp_create = self.client.post(reverse('accreditation:application_create'), {
            'track': AccreditationTrackType.INSTITUTIONAL,
            'institution_id': self.univ_a.pk,
            'academic_year': '2026-2027',
            'establishment_decree_number': 'DEC-2026-P1',
            'contact_person_name': 'د. مسؤول الجودة',
            'contact_phone': '777123456',
            'contact_email': 'qa@sanaa.edu.ye',
            'notes': 'طلب اعتماد مؤسسي جديد - المرحلة الأولى',
            'submit_official': '1',
        })
        self.assertEqual(resp_create.status_code, 302)
        app = AccreditationApplication.objects.filter(institution=self.univ_a).order_by('-id').first()
        self.assertIsNotNone(app)

        # Verify notifications to President and DG Accreditation point directly to /accreditation/<pk>/report/
        pres_notif = Notification.objects.filter(recipient=self.president_a, url=f"/accreditation/{app.pk}/report/").first()
        dg_notif = Notification.objects.filter(recipient=self.dg_accreditation, url=f"/accreditation/{app.pk}/report/").first()
        self.assertIsNotNone(pres_notif)
        self.assertIsNotNone(dg_notif)

        # Verify Application Report copy in My Library (UserDocument + DocumentShare)
        app_doc = UserDocument.objects.filter(application=app, doc_type=UserDocument.DocumentType.APPLICATION_DOSSIER).first()
        self.assertIsNotNone(app_doc)
        self.assertEqual(app_doc.system_source_url, f"/accreditation/{app.pk}/report/")
        self.assertTrue(DocumentShare.objects.filter(document=app_doc, recipient=self.president_a).exists())
        self.assertTrue(DocumentShare.objects.filter(document=app_doc, recipient=self.dg_accreditation).exists())

        # --- POINT 2: DG Rejects / Requests Modification -> Direct Notification to /resubmit/ -> Modify & Resend ---
        self.client.login(username="dg_accred_user", password="password123")
        resp_rej = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'reject_application',
            'rejection_reason': 'يرجى استيفاء رقم قرار الإنشاء المحدث وتعديل بيانات الاتصال.',
        })
        self.assertEqual(resp_rej.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.REJECTED)

        # Check notification URL points directly to /accreditation/<pk>/resubmit/
        resub_notif_inst = Notification.objects.filter(recipient=self.officer_a, url=f"/accreditation/{app.pk}/resubmit/").first()
        resub_notif_pres = Notification.objects.filter(recipient=self.president_a, url=f"/accreditation/{app.pk}/resubmit/").first()
        self.assertIsNotNone(resub_notif_inst)
        self.assertIsNotNone(resub_notif_pres)

        # Institution navigates to /resubmit/, modifies application, and resends to DG Accreditation
        self.client.login(username="officer_univ_a", password="password123")
        resp_resub = self.client.post(reverse('accreditation:application_resubmit', args=[app.pk]), {
            'establishment_decree_number': 'DEC-2026-P1-MODIFIED',
            'academic_year': '2026-2027',
            'contact_person_name': 'د. مسؤول الجودة المحدث',
            'contact_phone': '777999888',
            'contact_email': 'qa_updated@sanaa.edu.ye',
            'notes': 'تم استيفاء وتعديل قرار الإنشاء وبيانات الاتصال وإعادة الإرسال.',
        })
        self.assertEqual(resp_resub.status_code, 302)
        app.refresh_from_db()
        self.univ_a.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PENDING_REVIEW)
        self.assertEqual(self.univ_a.decree_number, 'DEC-2026-P1-MODIFIED')
        self.assertTrue(Notification.objects.filter(recipient=self.dg_accreditation, url=f"/accreditation/board-review/{app.pk}/").exists())

        # --- POINT 3: Initial Approval + Cost -> Notification -> Two Direct Paths (Payment & Self-Study) ---
        self.client.login(username="dg_accred_user", password="password123")
        resp_acc = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'accept_application',
            'cost_amount': '3500000',
            'cost_currency': 'YER',
            'cost_breakdown_notes': 'رسوم دراسة الاعتماد والفحص المكتبي',
            'council_approval_notes': 'الموافقة المبدئية وفتح التقييم الذاتي',
        })
        self.assertEqual(resp_acc.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        inv = Invoice.objects.filter(application=app).first()
        self.assertIsNotNone(inv)

        # Check notification URL points to /accreditation/<pk>/#approved-paths and page contains both direct paths
        app_notif = Notification.objects.filter(recipient=self.officer_a, url=f"/accreditation/{app.pk}/#approved-paths").first()
        self.assertIsNotNone(app_notif)
        self.client.login(username="officer_univ_a", password="password123")
        resp_detail = self.client.get(reverse('accreditation:application_detail', args=[app.pk]))
        self.assertEqual(resp_detail.status_code, 200)
        self.assertContains(resp_detail, reverse('operations:invoice_detail', args=[inv.pk]))
        self.assertContains(resp_detail, reverse('accreditation:self_study_indicators_edit', args=[app.pk]))

        # --- POINT 4: Submit Self-Study Report -> Notification to DG Accreditation -> Open Self-Study Report ---
        EvidenceDocument.objects.create(
            application=app,
            indicator=self.ind_1,
            code="EV-P1-01",
            title="شاهد اللائحة التنظيمية للجامعة",
            document_file=SimpleUploadedFile("ev_p1.pdf", b"%PDF-1.4 evidence content", content_type="application/pdf"),
        )
        resp_ssr = self.client.post(reverse('accreditation:self_study_edit', args=[app.pk]), {
            'executive_summary': 'الملخص التنفيذي الأولي الأصلي للتقييم الذاتي',
            'internal_committee_names': 'لجنة التقييم الذاتي المركزية',
            'methodology': 'منهجية المسح الميداني والوثائقي',
            'strengths_overview': 'نقاط قوة بارزة',
            'weaknesses_and_challenges': 'فرص تحسين محددة',
            'submit_ssr_officially': '1',
        })
        self.assertEqual(resp_ssr.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        self.assertTrue(app.self_study_report.is_locked)

        # Verify DG Accreditation received notification pointing directly to /accreditation/<pk>/self-study/report/
        ssr_notif_dg = Notification.objects.filter(
            recipient=self.dg_accreditation,
            title="تم استلام تقرير التقييم الذاتي",
            url=f"/accreditation/{app.pk}/self-study/report/"
        ).first()
        self.assertIsNotNone(ssr_notif_dg)

        # --- POINT 5: External Reviewer <-> Institution (Modification Report & SSR Unlock) & External Reviewer -> DG Evaluation -> Comparison with Evidences -> Council ---
        # Set up review team for External Reviewer
        team = ReviewTeam.objects.create(
            application=app,
            decree_number="DEC-TEAM-P1",
            chairperson=self.reviewer_chair,
            formation_date=timezone.now().date(),
        )
        ReviewTeamMember.objects.create(team=team, user=self.reviewer_chair, role_in_team='CHAIR')
        ConflictOfInterestDeclaration.objects.create(
            application=app,
            reviewer=self.reviewer_chair,
            has_taught_in_institution=False,
            has_relatives_or_graduates=False,
            has_financial_or_consulting=False,
            is_conflict_acknowledged=False,
        )
        app.status = ApplicationStatus.SITE_VISIT_COMPLETED
        app.current_stage = StageChoices.STAGE_5
        app.save()

        # 5.1 External Reviewer sends modification report to Institution -> unlocks SSR & preserves Original SSR in My Library
        self.client.login(username="rev_chair", password="password123")
        resp_ext_draft = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'save_draft',
            'draft_executive_summary': 'مسودة تقرير الملاحظات وطلب التعديل للمؤسسة',
            'draft_findings_per_standard': 'يرجى تعديل واستكمال بيانات المعيار الأول في التقييم الذاتي.',
        })
        self.assertEqual(resp_ext_draft.status_code, 302)
        app.refresh_from_db()
        app.self_study_report.refresh_from_db()
        self.assertFalse(app.self_study_report.is_locked)  # Unlocked so institution can modify SSR!
        self.assertTrue(Notification.objects.filter(
            recipient=self.officer_a,
            url=f"/accreditation/{app.pk}/external-report/"
        ).exists())

        # Institution modifies Self-Study Report and submits reply
        self.client.login(username="officer_univ_a", password="password123")
        resp_mod_ssr = self.client.post(reverse('accreditation:self_study_edit', args=[app.pk]), {
            'executive_summary': 'الملخص التنفيذي المعدل بعد ملاحظات المقيم الخارجي',
            'internal_committee_names': 'لجنة التقييم الذاتي المركزية',
            'methodology': 'منهجية محدثة',
            'strengths_overview': 'نقاط قوة محدثة',
            'weaknesses_and_challenges': 'تمت معالجة الملاحظات',
            'submit_ssr_officially': '1',
        })
        self.assertEqual(resp_mod_ssr.status_code, 302)
        resp_reply = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'submit_institution_reply',
            'institution_reply_text': 'تم تعديل التقييم الذاتي وفق ملاحظات المقيم الخارجي وإرفاق الشواهد.',
        })
        self.assertEqual(resp_reply.status_code, 302)

        # 5.2 External Reviewer finalizes & sends External Evaluation to DG Evaluation
        self.client.login(username="rev_chair", password="password123")
        IndicatorEvaluationScore.objects.update_or_create(
            application=app,
            indicator=self.ind_1,
            evaluator=self.reviewer_chair,
            defaults={'score_level': RubricEvaluationLevel.FULLY_MET, 'strengths': 'مستوفى بالكامل بعد التعديل'}
        )
        resp_ext_final = self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'finalize_report',
            'team_response_to_reply': 'تم التحقق من التعديلات في التقييم الذاتي المعدل.',
            'final_report_text': 'التقرير النهائي للتقييم الخارجي المعتمد والمرسل لمدير عام التقييم.',
            'final_recommendation': ExternalReviewReport.FinalRecommendation.FULL_ACCREDITATION,
        })
        self.assertEqual(resp_ext_final.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.FINAL_REPORT_READY)

        # Verify DG Evaluation received direct notification to /accreditation/<pk>/external-report/
        self.assertTrue(Notification.objects.filter(
            recipient=self.dg_evaluation,
            url=f"/accreditation/{app.pk}/external-report/"
        ).exists())

        # Verify DG Evaluation's My Library contains: External Evaluation Report + Original SSR + Modified SSR
        ssr_docs_for_app = UserDocument.objects.filter(application=app, doc_type=UserDocument.DocumentType.SELF_STUDY)
        self.assertGreaterEqual(ssr_docs_for_app.count(), 2)  # Both Original and Modified SSR!
        ext_doc_for_app = UserDocument.objects.filter(application=app, doc_type=UserDocument.DocumentType.EXTERNAL_REPORT).first()
        self.assertIsNotNone(ext_doc_for_app)
        self.assertTrue(DocumentShare.objects.filter(document=ext_doc_for_app, recipient=self.dg_evaluation).exists() or ext_doc_for_app.owner == self.dg_evaluation)

        # 5.3 DG Evaluation performs Analytical Comparison with Evidences & saves/sends to Council
        self.client.login(username="dg_eval_user", password="password123")
        resp_comp_get = self.client.get(reverse('accreditation:secretariat_comparison_dashboard', args=[app.pk]))
        self.assertEqual(resp_comp_get.status_code, 200)
        self.assertContains(resp_comp_get, "EV-P1-01")  # Evidence code shown in comparison dashboard!

        resp_comp_post = self.client.post(reverse('accreditation:secretariat_comparison_dashboard', args=[app.pk]), {
            'save_comparison_report': '1',
            'comparison_title': f'تقرير المقارنة التحليلية مع الشواهد - {app.application_number}',
            'secretariat_analytical_summary': 'توصية مدير عام التقييم والمراجعة الخارجية بالموافقة وإحالة الملف مع الشواهد للمجلس.',
        })
        self.assertEqual(resp_comp_post.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.IN_COUNCIL_REVIEW)

        comp_rep = SecretariatAssessmentComparisonReport.objects.filter(application=app).first()
        self.assertIsNotNone(comp_rep)
        self.assertEqual(comp_rep.comparison_data_json.get('total_evidences_count'), 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.board_1,
            url=f"/accreditation/{app.pk}/comparison-dashboard/"
        ).exists())

    def test_56_phase2_targeted_repairs_and_full_post_workflows(self):
        """
        56. End-to-End Verification of Phase 2 (Final Phase) Targeted Repairs:
        1) Council Secretary / Desk Reviewer: SSR & Evidence notification -> DeskReviewEvaluation -> Minutes & Reservations.
        2) DG Finance & Admin: Invoice creation per FeeSchedule -> Receipt review -> FINANCIAL_CLEARED confirmation & My Library sync.
        3) DG Evaluation: ReviewTeam assignment -> COI tracking & replacing conflicted reviewer -> SiteVisit supervision -> External Reports.
        4) External Reviewer: COI signature -> SSR & Evidence access -> SiteVisit & FacilityInspection -> Rubrics -> Draft & Final Reports.
        5) & 7) Secretary General: Analytical Comparison Report + Integrated 17-Section Dossier (IN_COUNCIL_REVIEW) sent to Council Chairman & Board Members.
        6) & 8) Council Chairman & Post-Decision Operations: Meeting invitations -> Quorum badge -> Secret Ballot & Article 6 Tie-Breaker -> Minutes approval -> Decision & Certificate -> Grievance -> Surveillance.
        """
        app = self._create_base_application(status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        app.current_stage = StageChoices.STAGE_2
        app.save()

        # ---------------------------------------------------------------------
        # 1. أولاً: سكرتارية المجلس / الفاحص المكتبي (إشعار التقييم الذاتي والشواهد + الفحص المكتبي)
        # ---------------------------------------------------------------------
        self.client.login(username="officer_univ_a", password="password123")
        pdf_ev = SimpleUploadedFile("phase2_ev.pdf", b"%PDF-1.4 phase2 evidence", content_type="application/pdf")
        self.client.post(reverse('accreditation:evidence_manage', args=[app.pk]), {
            'indicator': self.ind_1.pk,
            'code': 'EV-P2-01',
            'title': 'شاهد المرحلة الثانية',
            'description': 'شاهد رسمي للمرحلة الثانية',
            'document_file': pdf_ev,
        })
        self.assertTrue(Notification.objects.filter(
            recipient=self.council_sec,
            url=f"/accreditation/{app.pk}/desk-review/"
        ).exists())

        SelfStudyReport.objects.update_or_create(
            application=app,
            defaults={'executive_summary': 'ملخص الدراسة الذاتية للمرحلة الثانية'}
        )
        self.client.post(reverse('accreditation:self_study_edit', args=[app.pk]), {
            'executive_summary': 'ملخص الدراسة الذاتية للمرحلة الثانية المعتمد',
            'internal_committee_names': 'لجنة الجودة',
            'methodology': 'منهجية شاملة',
            'strengths_overview': 'نقاط قوة',
            'weaknesses_and_challenges': 'فرص تحسين',
            'submit_ssr_officially': '1',
        })
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        self.assertTrue(Notification.objects.filter(
            recipient=self.council_sec,
            title__icontains="تم إرسال التقييم الذاتي من المؤسسة والشواهد",
            url=f"/accreditation/{app.pk}/desk-review/"
        ).exists())

        # Conduct Desk Review (DeskReviewEvaluation) by COUNCIL_SECRETARY
        self.client.login(username="council_sec_user", password="password123")
        resp_dr = self.client.post(reverse('accreditation:desk_review_process', args=[app.pk]), {
            'decision': DeskReviewEvaluation.DeskDecision.ACCEPTED,
            'completeness_percentage': 95,
            'formal_criteria_met': 'on',
            'technical_remarks': 'مستوفٍ لكافة المتطلبات الشكلية والموضوعية.',
        })
        self.assertEqual(resp_dr.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.DESK_ACCEPTED)
        self.assertTrue(UserDocument.objects.filter(
            application=app,
            system_source_url=f"/accreditation/{app.pk}/desk-review/"
        ).exists())

        # ---------------------------------------------------------------------
        # 2. ثانياً: مدير عام الشؤون المالية والإدارية (إصدار المطالبة، مراجعة السند، وتأكيد السداد FINANCIAL_CLEARED)
        # ---------------------------------------------------------------------
        self.client.login(username="dg_finance_user", password="password123")
        resp_inv = self.client.post(reverse('operations:invoice_create'), {
            'application_id': app.pk,
            'fee_schedule_id': self.fee_schedule.pk,
            'custom_amount': '1500000',
        })
        self.assertEqual(resp_inv.status_code, 302)
        inv = Invoice.objects.filter(application=app).order_by('-id').first()
        self.assertIsNotNone(inv)

        # Institution uploads bank deposit receipt
        self.client.login(username="officer_univ_a", password="password123")
        receipt_pdf = SimpleUploadedFile("bank_receipt_p2.pdf", b"%PDF-1.4 receipt", content_type="application/pdf")
        self.client.post(reverse('operations:invoice_detail', args=[inv.pk]), {
            'upload_proof': '1',
            'payment_reference': 'BNK-2026-9988',
            'proof_of_payment': receipt_pdf,
        })
        self.assertTrue(Notification.objects.filter(
            recipient=self.dg_finance,
            url=f"/operations/invoices/{inv.pk}/"
        ).exists())

        # DG Finance confirms payment -> FINANCIAL_CLEARED
        self.client.login(username="dg_finance_user", password="password123")
        self.client.post(reverse('operations:invoice_detail', args=[inv.pk]), {
            'confirm_payment': '1',
        })
        inv.refresh_from_db()
        app.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PaymentStatus.PAID)
        self.assertEqual(app.status, ApplicationStatus.FINANCIAL_CLEARED)
        self.assertTrue(UserDocument.objects.filter(
            application=app,
            system_source_url=f"/operations/invoices/{inv.pk}/"
        ).exists())

        # ---------------------------------------------------------------------
        # 3 & 4. ثالثاً ورابعاً: مدير عام التقييم والمراجعة الخارجية + رئيس وأعضاء لجنة المراجعة الخارجية
        # ---------------------------------------------------------------------
        self.client.login(username="dg_eval_user", password="password123")
        resp_team = self.client.post(reverse('accreditation:assign_review_team', args=[app.pk]), {
            'decree_number': 'DEC-TEAM-P2-2026',
            'chairperson': self.reviewer_chair.pk,
            'member_ids': [self.reviewer_conflicted.pk],
        })
        self.assertEqual(resp_team.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PANEL_ASSIGNED)

        # Reviewer 2 declares Conflict of Interest -> DG Evaluation receives notification & replaces him
        self.client.login(username="rev_conflicted", password="password123")
        self.client.post(reverse('accreditation:coi_declare', args=[app.pk]), {
            'has_taught': 'on',
            'is_conflict_acknowledged': 'on',
            'other_conflict_details': 'عملت سابقاً في هذه الجامعة.',
        })
        self.assertTrue(Notification.objects.filter(
            recipient=self.dg_evaluation,
            title__icontains="تعارض مصالح",
            url=f"/accreditation/{app.pk}/review-team/"
        ).exists())

        # DG Evaluation replaces conflicted member with reviewer_member
        self.client.login(username="dg_eval_user", password="password123")
        self.client.post(reverse('accreditation:assign_review_team', args=[app.pk]), {
            'replace_member_id': self.reviewer_conflicted.pk,
            'replacement_user_id': self.reviewer_member.pk,
        })
        team = ReviewTeam.objects.get(application=app)
        self.assertFalse(team.members.filter(user=self.reviewer_conflicted).exists())
        self.assertTrue(team.members.filter(user=self.reviewer_member).exists())

        # Chairperson & replacement member sign clean COI
        for rev_uname in ["rev_chair", "rev_member"]:
            self.client.login(username=rev_uname, password="password123")
            self.client.post(reverse('accreditation:coi_declare', args=[app.pk]), {})

        # External Reviewer conducts Site Visit, Facility Inspection, Rubrics, Draft & Final External Report
        self.client.login(username="rev_chair", password="password123")
        self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'update_schedule',
            'start_date': '2026-05-01',
            'end_date': '2026-05-03',
            'visit_location': 'الحرم الجامعي الرئيسي',
            'status': SiteVisitSchedule.VisitStatus.SCHEDULED,
        })
        self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'add_facility',
            'category': FacilityInspection.FacilityCategory.LABS,
            'facility_name': 'معمل الحاسوب المركزي',
            'capacity_students': 45,
            'adequacy_rating': FacilityInspection.AdequacyLevel.EXCELLENT,
            'safety_compliance': 'on',
            'detailed_observations': 'تجهيزات ممتازة ومطابقة للمعايير.',
        })
        self.client.post(reverse('site_visits:console', args=[app.pk]), {
            'action': 'update_schedule',
            'start_date': '2026-05-01',
            'end_date': '2026-05-03',
            'visit_location': 'الحرم الجامعي الرئيسي',
            'status': SiteVisitSchedule.VisitStatus.COMPLETED,
            'final_exit_meeting_notes': 'تم اختتام الزيارة الميدانية بنجاح.',
        })
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.SITE_VISIT_COMPLETED)

        # Score Rubrics
        self.client.post(reverse('accreditation:external_rubrics_evaluation', args=[app.pk]), {
            f'score_{self.ind_1.id}': RubricEvaluationLevel.FULLY_MET,
            f'strengths_{self.ind_1.id}': 'استيفاء كامل للمؤشر والشواهد.',
            'submit_to_external_report': '1',
        })
        # Draft External Report -> Institution Reply -> Final External Report
        self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'save_draft',
            'draft_executive_summary': 'مسودة التقرير الخارجي',
            'draft_findings_per_standard': 'نتائج المعايير',
        })
        self.client.login(username="officer_univ_a", password="password123")
        self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'submit_institution_reply',
            'institution_reply_text': 'رد المؤسسة الرسمي بالموافقة على الملاحظات.',
        })
        self.client.login(username="rev_chair", password="password123")
        self.client.post(reverse('accreditation:external_report_manage', args=[app.pk]), {
            'action': 'finalize_report',
            'team_response_to_reply': 'تم استيعاب رد المؤسسة.',
            'final_report_text': 'التقرير النهائي المعتمد من لجنة المراجعة الخارجية.',
            'final_recommendation': ExternalReviewReport.FinalRecommendation.FULL_ACCREDITATION,
        })
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.FINAL_REPORT_READY)

        # ---------------------------------------------------------------------
        # 5 & 7. خامساً وسابعاً: الأمين العام للمجلس يعتمد ويرسل تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) إلى رئيس وأعضاء مجلس الإدارة
        # ---------------------------------------------------------------------
        self.client.login(username="sec_gen_user", password="password123")
        resp_dos17_get = self.client.get(reverse('accreditation:application_dossier_17_view', args=[app.pk]))
        self.assertEqual(resp_dos17_get.status_code, 200)

        resp_dos17_post = self.client.post(reverse('accreditation:application_dossier_17_view', args=[app.pk]), {
            'refer_dossier_17_to_council': '1',
            'comparison_title': f'تقرير المقارنة التحليلي وملف الاعتماد المتكامل (17 قسماً) - {app.application_number}',
            'secretariat_analytical_summary': 'توصية الأمين العام للمجلس بإحالة تقرير المقارنة التحليلي وملف الاعتماد المتكامل (17 قسماً) إلى رئيس وأعضاء مجلس الإدارة.',
        })
        self.assertEqual(resp_dos17_post.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.IN_COUNCIL_REVIEW)

        # Verify Council Chairman & Board Members received notifications & My Library copies of BOTH Comparison Report & 17-Section Dossier
        from apps.accounts.models import DocumentShare
        for recipient_user in [self.chairman, self.board_1]:
            self.assertTrue(Notification.objects.filter(
                recipient=recipient_user,
                url=f"/accreditation/{app.pk}/dossier-17/"
            ).exists())
            dossier_doc = UserDocument.objects.filter(
                application=app,
                system_source_url=f"/accreditation/{app.pk}/dossier-17/"
            ).first()
            self.assertIsNotNone(dossier_doc)
            self.assertTrue(
                dossier_doc.owner == recipient_user or
                DocumentShare.objects.filter(document=dossier_doc, recipient=recipient_user).exists()
            )

        # ---------------------------------------------------------------------
        # 6 & 8. سادساً وثامناً: رئيس مجلس الإدارة، الجلسة، النصاب، الاقتراع السري وترجيح الكفة، المحضر، القرار والشهادة، التظلمات، والرقابة اللاحقة
        # ---------------------------------------------------------------------
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:meeting_create'), {
            'meeting_number': 'جلسة المرحلة الثانية رقم (99)',
            'meeting_type': CouncilMeeting.MeetingType.ORDINARY,
            'meeting_date': str(timezone.now().date()),
            'location': 'المقر الرئيسي للمجلس',
            'quorum_required': 2,
        })
        meeting = CouncilMeeting.objects.get(meeting_number='جلسة المرحلة الثانية رقم (99)')
        self.client.post(reverse('decisions:meeting_send_invitations', args=[meeting.pk]))

        # RSVP confirmation -> Quorum met notification
        for bm_uname in ["council_chair", "board_mem_1"]:
            self.client.login(username=bm_uname, password="password123")
            self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {
                'status': CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
                'participation_mode': CouncilMeetingAttendance.ParticipationMode.IN_PERSON,
            })
        self.assertTrue(meeting.is_quorum_met())
        self.assertTrue(Notification.objects.filter(
            recipient=self.chairman,
            title__icontains="النصاب القانوني مكتمل ومتحقق"
        ).exists())

        # Create Agenda Item & record member reservation
        self.client.login(username="sec_gen_user", password="password123")
        self.client.post(reverse('decisions:agenda_item_create', args=[meeting.pk]), {
            'item_number': 'بند (1)',
            'title': f'البت في ملف الاعتماد المتكامل (17 قسماً) لـ {app.application_number}',
            'item_category': CouncilAgendaItem.ItemCategory.INSTITUTIONAL_ACCREDITATION,
            'application_id': app.pk,
            'required_action': CouncilAgendaItem.RequiredAction.APPROVAL,
        })
        agenda_item = CouncilAgendaItem.objects.get(meeting=meeting, application=app)

        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:agenda_item_add_discussion', args=[agenda_item.pk]), {
            'intervention_type': CouncilAgendaDiscussion.InterventionType.RESERVATION,
            'content': 'تسجيل تحفظ رسمي في محضر الجلسة حول ضرورة متابعة خطة التحسين بعد سنة.',
        })

        # Open Secret Ballot -> Cast tied votes (1 APPROVE, 1 REJECT) -> Chairman Tie-Breaker (Article 6)
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:agenda_item_ballot_open', args=[agenda_item.pk]), {
            'voting_mode': CouncilBallot.VotingMode.SECRET,
        })
        ballot = CouncilBallot.objects.get(agenda_item=agenda_item)

        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.APPROVE,
        })
        self.client.login(username="board_mem_1", password="password123")
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.REJECT,
        })

        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot.pk]), {
            'chairperson_tie_break': 'APPROVE',
        })
        ballot.refresh_from_db()
        self.assertTrue(ballot.tie_occurred)
        self.assertTrue(ballot.tie_broken_by_chairperson)
        self.assertEqual(ballot.final_result, 'APPROVED_BY_CHAIR_TIEBREAK')

        # Council Secretary drafts Official Meeting Minutes -> Chairman approves & locks
        self.client.login(username="council_sec_user", password="password123")
        self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'submit_for_approval': '1',
        })
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('decisions:meeting_minutes_approve', args=[meeting.pk]), {})
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.MINUTES_RATIFIED)
        self.assertTrue(UserDocument.objects.filter(
            system_source_url=f"/decisions/meetings/{meeting.pk}/minutes/print/"
        ).exists())

        # Issue Accreditation Decision & Official Certificate
        self.client.post(reverse('decisions:issue_decision', args=[app.pk]), {
            'meeting_id': meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
            'decree_number': f'DEC-P2-CERT-{app.pk}',
            'validity_years': 5,
            'legal_justifications': 'استيفاء المعايير مع اشتراط خطة تحسين مستمر.',
            'corrective_requirements': 'تحديث معامل الحاسوب خلال عام.',
        })
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.CONDITIONAL_ACCREDITATION)
        decision = AccreditationDecision.objects.get(application=app)

        # Post-Decision 1: Grievance submission -> Legal Director review -> Council Chairman resolution
        self.client.login(username="officer_univ_a", password="password123")
        self.client.post(reverse('accreditation:grievance_create', args=[app.pk]), {
            'grounds_of_appeal': 'تظلم لتحويل الاعتماد المشروط إلى اعتماد كامل.',
        })
        grievance = GrievanceAppeal.objects.filter(application=app).first()
        self.assertIsNotNone(grievance)

        self.client.login(username="legal_dir", password="password123")
        self.client.post(reverse('accreditation:grievance_review', args=[grievance.pk]), {
            'action': 'save_legal_report',
            'committee_report': 'التظلم مستوفٍ للشروط الشكلية ويُرفع لمجلس الإدارة.',
        })
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('accreditation:grievance_review', args=[grievance.pk]), {
            'action': 'resolve_board',
            'final_resolution': 'modify',
            'final_resolution_notes': 'قبول التظلم وتعديل مهلة الاستيفاء.',
        })
        grievance.refresh_from_db()
        self.assertEqual(grievance.status, GrievanceAppeal.AppealStatus.DECISION_MODIFIED)

        # Post-Decision 2: Surveillance & Continuous Improvement Plan -> Secretary General review -> Council Chairman approval
        self.client.login(username="officer_univ_a", password="password123")
        self.client.get(reverse('surveillance:manage', args=[decision.pk]))
        plan = ContinuousImprovementPlan.objects.get(decision=decision)
        self.client.post(reverse('surveillance:action_item_create', args=[plan.pk]), {
            'deficiency_title': 'تحديث المعامل',
            'corrective_activity': 'شراء 30 جهاز حاسوب حديث',
            'responsible_person': 'عميد الكلية',
            'department': 'قسم تقنية المعلومات',
            'due_date': '2026-12-31',
            'kpi_measure': 'تركيب وتشغيل 30 جهازاً',
        })
        self.client.post(reverse('surveillance:plan_submit', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.SUBMITTED)

        # Secretary General reviews & refers plan to Council
        self.client.login(username="sec_gen_user", password="password123")
        self.client.post(reverse('surveillance:plan_secretariat_review', args=[plan.pk]), {
            'review_action': 'refer_to_council',
            'secretariat_review_notes': 'الخطة مكتملة فنياً وتُرفع لمجلس الإدارة للاعتماد.',
        })
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.REFERRED_TO_COUNCIL)

        # Council Chairman approves Continuous Improvement Plan
        self.client.login(username="council_chair", password="password123")
        self.client.post(reverse('surveillance:plan_council_decision', args=[plan.pk]), {
            'council_decision_action': 'approve',
            'approval_notes': 'معتمدة رسمياً من مجلس الإدارة.',
        })
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.APPROVED_BY_COUNCIL)
        self.assertTrue(plan.is_approved_by_council)

    def test_57_ai_quality_analyzer_and_draft_comparison_generator(self):
        """
        57. Verify AI Quality Analyzer (المساعد الذكي لتحليل الدراسة الذاتية واكتشاف الفجوات واقتراح مسودة تقرير المقارنة التحليلي):
        - Detects unverified claims (MET without digital evidence) and overestimation gaps between SSR and External Review.
        - Calculates AI Readiness Score, Alignment Index, and Evidence Coverage %.
        - Generates and saves the Secretariat Analytical Comparison Report draft and syncs to My Library.
        """
        app = self._create_base_application(status=ApplicationStatus.FINAL_REPORT_READY)
        app.current_stage = StageChoices.STAGE_6
        app.save()
        ssr, _ = SelfStudyReport.objects.update_or_create(
            application=app,
            defaults={
                'executive_summary': "ملخص تنفيذي شامل للدراسة الذاتية للجامعة يتضمن كافة عناصر الجودة والتطوير المؤسسي.",
                'internal_committee_names': "أ.د. رئيس لجنة الجودة وعميد الكلية وأعضاء هيئة التدريس",
                'methodology': "منهجية جمع البيانات المسحية والميدانية وتحليل مؤشرات الأداء",
            }
        )
        # Clear any default evidences so Indicator 1 claimed MET without evidence triggers Unverified Claim + Overestimation Gap
        app.evidences.all().delete()
        SelfStudyIndicatorResponse.objects.update_or_create(
            report=ssr,
            indicator=self.ind_1,
            defaults={
                'compliance_level': SelfStudyIndicatorResponse.ComplianceLevel.MET,
                'justification': "مستوفى بالكامل حسب رأي المؤسسة",
            }
        )
        IndicatorEvaluationScore.objects.update_or_create(
            application=app,
            indicator=self.ind_1,
            evaluator=self.reviewer_chair,
            defaults={
                'score_level': RubricEvaluationLevel.PARTIALLY_MET,
                'weaknesses': "نقص في التوثيق الرقمي والشواهد الميدانية",
            }
        )
        ExternalReviewReport.objects.update_or_create(
            application=app,
            defaults={
                'draft_executive_summary': "مسودة التقرير الخارجي",
                'draft_findings_per_standard': "نتائج المعايير",
                'institution_reply_text': "تم البدء باستكمال الشواهد الرقمية.",
                'final_report_text': "التقرير النهائي للجنة المراجعة الخارجية",
                'final_recommendation': ExternalReviewReport.FinalRecommendation.CONDITIONAL_ACCREDITATION,
            }
        )

        self.client.login(username="sec_gen_user", password="password123")
        res = self.client.get(reverse('accreditation:ai_quality_analyzer', args=[app.pk]))
        self.assertEqual(res.status_code, 200)
        ai_data = res.context['ai']
        self.assertGreater(ai_data['total_gaps_count'], 0)
        self.assertIn('readiness_score', ai_data)
        self.assertIn('alignment_index', ai_data)
        self.assertIn('أولاً: الملخص التنفيذي ومؤشرات الجاهزية الذكية', ai_data['draft_analytical_summary'])

        # Generate and refer comparison draft via POST
        post_res = self.client.post(reverse('accreditation:ai_quality_analyzer', args=[app.pk]), {
            'generate_comparison_draft': '1',
            'comparison_title': ai_data['draft_comparison_title'],
            'secretariat_analytical_summary': ai_data['draft_analytical_summary'],
            'refer_to_council': '1',
        })
        self.assertEqual(post_res.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.IN_COUNCIL_REVIEW)
        self.assertTrue(SecretariatAssessmentComparisonReport.objects.filter(
            application=app,
            title__icontains='AI Quality Analyzer'
        ).exists())



