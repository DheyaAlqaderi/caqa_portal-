from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User, Notification, AuditLog
from apps.institutions.models import Institution, AcademicProgram, College
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus
from apps.decisions.models import CouncilMeeting, AccreditationDecision
from apps.surveillance.models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
    CorrectiveActionItem,
    ImprovementPlanEvidence,
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SurveillanceWorkflowAndAuthorizationTests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Institutions
        self.inst_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-SNA",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.inst_b = Institution.objects.create(
            name="جامعة تعز",
            code="UNIV-TAIZ",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        # 2. Users
        self.officer_a = User.objects.create_user(
            username="officer_a",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.inst_a,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.officer_b = User.objects.create_user(
            username="officer_b",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.inst_b,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.secretariat_user = User.objects.create_user(
            username="sec_user",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.board_member = User.objects.create_user(
            username="board_user",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.reviewer_assigned = User.objects.create_user(
            username="rev_assigned",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.reviewer_unassigned = User.objects.create_user(
            username="rev_unassigned",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # 3. Standard & Applications
        self.std_ver = StandardVersion.objects.create(
            title="المعايير المؤسسية الوطنية",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="1.0"
        )
        self.meeting = CouncilMeeting.objects.create(
            meeting_number="COUNCIL-2026-M05",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="جلسة البت في المتابعة والاعتماد",
            minutes_summary="محضر الجلسة"
        )

        self.app_a = AccreditationApplication.objects.create(
            application_number="APP-ACCRED-SNA-001",
            institution=self.inst_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            standard_version=self.std_ver,
            applicant_user=self.officer_a,
            current_stage=StageChoices.STAGE_7,
            status=ApplicationStatus.FULL_ACCREDITATION
        )
        self.decision_a = AccreditationDecision.objects.create(
            application=self.app_a,
            meeting=self.meeting,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decision_date=timezone.now().date(),
            decree_number="قرار مجلس الاعتماد رقم (101) لسنة 2026",
            validity_years=5,
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date().replace(year=timezone.now().date().year + 5),
            legal_justifications="استيفاء معايير الجودة والاعتماد المؤسسي"
        )

        self.app_b = AccreditationApplication.objects.create(
            application_number="APP-ACCRED-TAIZ-002",
            institution=self.inst_b,
            track=AccreditationTrackType.INSTITUTIONAL,
            standard_version=self.std_ver,
            applicant_user=self.officer_b,
            current_stage=StageChoices.STAGE_7,
            status=ApplicationStatus.CONDITIONAL_ACCREDITATION
        )
        self.decision_b = AccreditationDecision.objects.create(
            application=self.app_b,
            meeting=self.meeting,
            decision_type=AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
            decision_date=timezone.now().date(),
            decree_number="قرار مجلس الاعتماد رقم (102) لسنة 2026",
            validity_years=2,
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date().replace(year=timezone.now().date().year + 2),
            legal_justifications="منح اعتماد مشروط لاستكمال خطة التحسين"
        )

    # =========================================================================
    # 1. Institution Access & Tenant Isolation
    # =========================================================================
    def test_institution_access_own_plan_and_tenant_isolation(self):
        """
        Officer A can access their institution's surveillance page.
        Officer B attempting to access Institution A's page is redirected (tenant isolation).
        """
        # Officer A accesses Institution A's decision
        self.client.login(username="officer_a", password="password123")
        res_a = self.client.get(reverse('surveillance:manage', args=[self.decision_a.pk]))
        self.assertEqual(res_a.status_code, 200)

        # Officer B attempts to access Institution A's decision -> redirected
        self.client.login(username="officer_b", password="password123")
        res_b = self.client.get(reverse('surveillance:manage', args=[self.decision_a.pk]))
        self.assertEqual(res_b.status_code, 302)

        # Officer B dashboard lists only Institution B's decisions
        res_dash_b = self.client.get(reverse('surveillance:dashboard'))
        self.assertEqual(res_dash_b.status_code, 200)
        self.assertEqual(len(res_dash_b.context['decisions']), 1)
        self.assertEqual(res_dash_b.context['decisions'][0].pk, self.decision_b.pk)

    # =========================================================================
    # 2. Institution CIP Preparation, Action Items & Official Submission
    # =========================================================================
    def test_institution_creates_action_item_and_submits_cip(self):
        """
        Institution officer adds an action item and submits the plan.
        Plan transitions to SUBMITTED and locks editing for the institution.
        Secretariat is notified.
        """
        self.client.login(username="officer_a", password="password123")
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة تحسين جامعة صنعاء",
            implementation_timeframe="3 سنوات",
            status=ContinuousImprovementPlan.PlanStatus.DRAFT
        )

        # 1. Add action item
        res_action = self.client.post(reverse('surveillance:action_item_create', args=[plan.pk]), {
            'deficiency_title': 'تحديث شبكة المعامل',
            'corrective_activity': 'شراء خوادم جديدة وتفعيل منصة التعلم الإلكتروني',
            'responsible_person': 'د. خالد رئيس قسم الحاسوب',
            'department': 'مركز تقنية المعلومات',
            'due_date': '2026-12-31',
            'kpi_measure': 'اكتمال التجهيز بنسبة 100%'
        })
        self.assertEqual(res_action.status_code, 302)
        self.assertEqual(plan.action_items.count(), 1)
        item = plan.action_items.first()
        self.assertEqual(item.deficiency_title, 'تحديث شبكة المعامل')
        self.assertEqual(item.department, 'مركز تقنية المعلومات')

        # 2. Submit plan
        res_submit = self.client.post(reverse('surveillance:plan_submit', args=[plan.pk]))
        self.assertEqual(res_submit.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.SUBMITTED)
        self.assertEqual(plan.submitted_by, self.officer_a)
        self.assertIsNotNone(plan.submitted_at)

        # Secretariat user received notification
        notif = Notification.objects.filter(recipient=self.secretariat_user).first()
        self.assertIsNotNone(notif)
        self.assertIn("تقديم خطة تحسين", notif.title)

        # 3. Institution cannot edit plan while SUBMITTED
        res_edit_locked = self.client.post(reverse('surveillance:manage', args=[self.decision_a.pk]), {
            'action': 'save_plan',
            'plan_title': 'محاولة تعديل غير مسموح بها'
        })
        plan.refresh_from_db()
        self.assertEqual(plan.plan_title, "خطة تحسين جامعة صنعاء")

    # =========================================================================
    # 3. Institution Forbidden from Secretariat & Council Actions
    # =========================================================================
    def test_institution_cannot_perform_secretariat_or_council_actions(self):
        """
        Institution officer attempting to perform secretariat review or council decision
        is forbidden and rejected with 302/redirect and no status change.
        """
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة قيد المراجعة",
            status=ContinuousImprovementPlan.PlanStatus.SUBMITTED
        )
        self.client.login(username="officer_a", password="password123")

        # Attempt Secretariat Review -> Forbidden
        res_sec = self.client.post(reverse('surveillance:plan_secretariat_review', args=[plan.pk]), {
            'review_action': 'mark_technically_reviewed',
            'secretariat_review_notes': 'محاولة احتيال'
        })
        self.assertEqual(res_sec.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.SUBMITTED)

        # Attempt Council Decision -> Forbidden
        res_counc = self.client.post(reverse('surveillance:plan_council_decision', args=[plan.pk]), {
            'council_decision_action': 'approve',
            'approval_notes': 'محاولة اعتماد ذاتي'
        })
        self.assertEqual(res_counc.status_code, 302)
        plan.refresh_from_db()
        self.assertFalse(plan.is_approved_by_council)
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.SUBMITTED)

    # =========================================================================
    # 4. Secretariat Reviews CIP & Requests Revision
    # =========================================================================
    def test_secretariat_reviews_cip_and_requests_revision(self):
        """
        Secretariat returns submitted plan for revision (NEEDS_REVISION).
        Institution is notified and plan becomes editable again.
        """
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة بحاجة لاستكمال",
            status=ContinuousImprovementPlan.PlanStatus.SUBMITTED
        )
        self.client.login(username="sec_user", password="password123")

        res = self.client.post(reverse('surveillance:plan_secretariat_review', args=[plan.pk]), {
            'review_action': 'request_revision',
            'secretariat_review_notes': 'يرجى تفصيل الموازنة وتحديد المخرجات لكل بند بدقة.'
        })
        self.assertEqual(res.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.NEEDS_REVISION)
        self.assertTrue(plan.is_editable_by_institution)

        # Institution officer notified
        notif = Notification.objects.filter(recipient=self.officer_a).first()
        self.assertIsNotNone(notif)
        self.assertIn("إعادة خطة التحسين", notif.title)

        # Institution can now edit and resubmit
        self.client.login(username="officer_a", password="password123")
        self.client.post(reverse('surveillance:manage', args=[self.decision_a.pk]), {
            'action': 'save_plan',
            'plan_title': 'خطة معدلة ومستوفية',
            'budget_allocated': '50,000 USD'
        })
        plan.refresh_from_db()
        self.assertEqual(plan.plan_title, 'خطة معدلة ومستوفية')

    # =========================================================================
    # 5. Secretariat Refers to Council & Board Endorses CIP
    # =========================================================================
    def test_secretariat_refers_and_council_board_approves_cip(self):
        """
        Secretariat refers technically reviewed plan to Council.
        Council Board officially approves the plan.
        """
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة جاهزة للاعتماد",
            status=ContinuousImprovementPlan.PlanStatus.SUBMITTED
        )

        # 1. Secretariat refers to Council
        self.client.login(username="sec_user", password="password123")
        res_sec = self.client.post(reverse('surveillance:plan_secretariat_review', args=[plan.pk]), {
            'review_action': 'refer_to_council',
            'secretariat_review_notes': 'الخطة مستوفية للشروط الفنية وتوصي الأمانة باعتمادها.'
        })
        self.assertEqual(res_sec.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.REFERRED_TO_COUNCIL)

        # Board member notified
        notif_bm = Notification.objects.filter(recipient=self.board_member).first()
        self.assertIsNotNone(notif_bm)
        self.assertIn("إحالة خطة تحسين", notif_bm.title)

        # 2. Council Board approves
        self.client.login(username="board_user", password="password123")
        res_board = self.client.post(reverse('surveillance:plan_council_decision', args=[plan.pk]), {
            'council_decision_action': 'approve',
            'approval_notes': 'وافق مجلس الإدارة في اجتماعه الخامس على اعتماد الخطة.'
        })
        self.assertEqual(res_board.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ContinuousImprovementPlan.PlanStatus.APPROVED_BY_COUNCIL)
        self.assertTrue(plan.is_approved_by_council)
        self.assertEqual(plan.decided_by, self.board_member)

        # Institution officer notified
        notif_officer = Notification.objects.filter(recipient=self.officer_a, title__contains="اعتماد خطة التحسين").first()
        self.assertIsNotNone(notif_officer)

    # =========================================================================
    # 6. Annual Monitoring Report Lifecycle & Compliance Decisions
    # =========================================================================
    def test_annual_report_lifecycle_and_compliance_decision(self):
        """
        Institution submits annual report.
        Secretariat reviews and refers to Council.
        Council Board records compliance decision (SATISFACTORY).
        """
        self.client.login(username="officer_a", password="password123")
        res_submit = self.client.post(reverse('surveillance:manage', args=[self.decision_a.pk]), {
            'action': 'submit_annual_report',
            'year_number': 1,
            'reporting_period': '2026/2027',
            'progress_summary': 'تنفيذ 80% من توصيات فريق التقييم الخارجي',
            'quality_improvements_achieved': 'استحداث وحدة ضمان الجودة وتطوير المعامل'
        })
        self.assertEqual(res_submit.status_code, 302)
        report = AnnualMonitoringReport.objects.filter(decision=self.decision_a).first()
        self.assertIsNotNone(report)
        self.assertEqual(report.review_status, AnnualMonitoringReport.ReviewStatus.SUBMITTED)

        # Secretariat reviews and refers to council
        self.client.login(username="sec_user", password="password123")
        res_sec = self.client.post(reverse('surveillance:report_secretariat_review', args=[report.pk]), {
            'review_action': 'refer_to_council',
            'secretariat_review_comments': 'التقرير السنوي يعكس تقدماً ملموساً ونوصي بتأييد استمرار السريان.'
        })
        self.assertEqual(res_sec.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.review_status, AnnualMonitoringReport.ReviewStatus.REFERRED_TO_COUNCIL)

        # Council Board decides SATISFACTORY
        self.client.login(username="board_user", password="password123")
        res_board = self.client.post(reverse('surveillance:report_council_decision', args=[report.pk]), {
            'council_action': 'satisfactory',
            'council_feedback_comments': 'الموافقة على استمرار سريان الاعتماد الكامل للجامعة.'
        })
        self.assertEqual(res_board.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.review_status, AnnualMonitoringReport.ReviewStatus.SATISFACTORY)

        # Institution officer notified
        notif = Notification.objects.filter(recipient=self.officer_a, title__contains="اعتماد التقرير السنوي").first()
        self.assertIsNotNone(notif)

    # =========================================================================
    # 7. External Reviewer: Assigned Assessment Only, COI & Report Submission
    # =========================================================================
    def test_external_reviewer_assigned_only_and_coi(self):
        """
        External Reviewer:
        - Secretariat assigns Reviewer X to a visit.
        - Reviewer X can see assigned visit in their dashboard.
        - Unassigned Reviewer Y cannot access the visit (redirected).
        - Reviewer X cannot access documents or submit report until COI declared.
        - Once COI declared, Reviewer X submits follow-up report to Secretariat.
        - Reviewer X cannot access general surveillance dashboard (redirected).
        """
        # 1. Secretariat assigns Reviewer X
        self.client.login(username="sec_user", password="password123")
        res_assign = self.client.post(reverse('surveillance:visit_assign', args=[self.decision_a.pk]), {
            'visit_type': SurveillanceVisit.VisitReason.ROUTINE,
            'visit_date': '2026-11-15',
            'scope_and_deliverables': 'التحقق من إنجاز معامل المحاكاة',
            'auditor_ids': [self.reviewer_assigned.pk]
        })
        self.assertEqual(res_assign.status_code, 302)
        visit = SurveillanceVisit.objects.filter(decision=self.decision_a).first()
        self.assertIsNotNone(visit)
        self.assertIn(self.reviewer_assigned, visit.auditors.all())

        # Reviewer X was notified
        notif_rev = Notification.objects.filter(recipient=self.reviewer_assigned).first()
        self.assertIsNotNone(notif_rev)
        self.assertIn("تكليف بمهمة زيارة", notif_rev.title)

        # 2. Reviewer X accesses reviewer assignments dashboard
        self.client.login(username="rev_assigned", password="password123")
        res_dash = self.client.get(reverse('surveillance:reviewer_assignments'))
        self.assertEqual(res_dash.status_code, 200)
        self.assertEqual(len(res_dash.context['assigned_visits']), 1)

        # Reviewer X accessing root surveillance dashboard is redirected to reviewer assignments
        res_root = self.client.get(reverse('surveillance:dashboard'))
        self.assertEqual(res_root.status_code, 302)
        self.assertRedirects(res_root, reverse('surveillance:reviewer_assignments'))

        # 3. Unassigned Reviewer Y cannot access the visit detail
        self.client.login(username="rev_unassigned", password="password123")
        res_unassigned = self.client.get(reverse('surveillance:reviewer_visit_detail', args=[visit.pk]))
        self.assertEqual(res_unassigned.status_code, 302)

        # 4. Reviewer X accesses visit detail before COI -> has_declared_coi is False
        self.client.login(username="rev_assigned", password="password123")
        res_detail = self.client.get(reverse('surveillance:reviewer_visit_detail', args=[visit.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertFalse(res_detail.context['has_declared_coi'])

        # Attempt to submit report without COI -> rejected
        res_no_coi = self.client.post(reverse('surveillance:reviewer_visit_detail', args=[visit.pk]), {
            'field_audit_report': 'تقرير المعاينة قبل الإقرار',
            'recommendations_to_council': 'توصيات'
        })
        self.assertEqual(res_no_coi.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, SurveillanceVisit.VisitStatus.ASSIGNED)

        # 5. Reviewer X signs COI
        res_coi = self.client.post(reverse('surveillance:reviewer_visit_coi', args=[visit.pk]), {
            'acknowledge_coi': '1'
        })
        self.assertEqual(res_coi.status_code, 302)
        self.assertIn(self.reviewer_assigned, visit.coi_declared_by.all())

        # 6. Reviewer X submits follow-up report
        res_submit_rep = self.client.post(reverse('surveillance:reviewer_visit_detail', args=[visit.pk]), {
            'field_audit_report': 'تمت معاينة المعامل وتبين اكتمال تجهيزها بنسبة 95%.',
            'findings_verified_progress': 'اكتمال ربط الخوادم وتدريب الكادر الفني.',
            'remaining_gaps': 'الحاجة لزيادة عدد تراخيص البرمجيات التخصصية.',
            'compliance_result': SurveillanceVisit.ComplianceStatus.MAINTAINED,
            'recommendations_to_council': 'التوصية باستمرار سريان الاعتماد مع متابعة التراخيص.'
        })
        self.assertEqual(res_submit_rep.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, SurveillanceVisit.VisitStatus.REPORT_SUBMITTED)
        self.assertEqual(visit.compliance_result, SurveillanceVisit.ComplianceStatus.MAINTAINED)

        # Secretariat notified of reviewer submission
        notif_sec = Notification.objects.filter(recipient=self.secretariat_user, title__contains="تسليم تقرير محكم").first()
        self.assertIsNotNone(notif_sec)

    # =========================================================================
    # 8. Document Access Protection (Multi-tenant Authorization)
    # =========================================================================
    def test_secure_document_download(self):
        """
        Document downloads enforce tenant and role isolation:
        - Institution A officer can download Institution A's evidence.
        - Institution B officer gets 403 Forbidden.
        - Assigned reviewer with COI can download.
        - Unassigned reviewer gets 403 Forbidden.
        """
        plan = ContinuousImprovementPlan.objects.create(
            decision=self.decision_a,
            plan_title="خطة مع شواهد"
        )
        fake_file = SimpleUploadedFile("evidence_doc.pdf", b"Confidential Institution A Evidence Content")
        evidence = ImprovementPlanEvidence.objects.create(
            plan=plan,
            title="وثيقة الشاهد الثبوتي",
            evidence_file=fake_file,
            uploaded_by=self.officer_a
        )

        download_url = reverse('surveillance:download_evidence', args=[evidence.pk])

        # 1. Institution A officer allowed (200)
        self.client.login(username="officer_a", password="password123")
        res_a = self.client.get(download_url)
        self.assertEqual(res_a.status_code, 200)
        self.assertIn(b"Confidential", res_a.content)

        # 2. Institution B officer forbidden (403)
        self.client.login(username="officer_b", password="password123")
        res_b = self.client.get(download_url)
        self.assertEqual(res_b.status_code, 403)

        # 3. Unassigned reviewer forbidden (403)
        self.client.login(username="rev_unassigned", password="password123")
        res_unassigned = self.client.get(download_url)
        self.assertEqual(res_unassigned.status_code, 403)

        # 4. Assigned reviewer with COI allowed (200)
        visit = SurveillanceVisit.objects.create(
            decision=self.decision_a,
            visit_date=timezone.now().date(),
            field_audit_report='',
            recommendations_to_council=''
        )
        visit.auditors.add(self.reviewer_assigned)
        visit.coi_declared_by.add(self.reviewer_assigned)

        self.client.login(username="rev_assigned", password="password123")
        res_assigned = self.client.get(download_url)
        self.assertEqual(res_assigned.status_code, 200)
