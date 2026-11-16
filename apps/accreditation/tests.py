from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, AuditLog, Notification
from apps.institutions.models import Institution, AcademicProgram, College
from apps.standards.models import StandardCategory, StandardIndicator, StandardVersion, AccreditationTrackType, RubricEvaluationLevel
from apps.accreditation.models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    SelfStudyReport,
    SelfStudyIndicatorResponse,
    EvidenceDocument,
    DeskReviewEvaluation,
    ReviewTeam,
    ReviewTeamMember,
    ConflictOfInterestDeclaration,
    ExternalReviewReport,
    IndicatorEvaluationScore,
    SecretariatAssessmentComparisonReport,
)
from apps.accreditation.workflow import WorkflowEngine
from apps.decisions.models import CouncilMeeting, AccreditationDecision, AccreditationCertificate
from apps.site_visits.models import SiteVisitSchedule
from apps.surveillance.models import ContinuousImprovementPlan
from apps.operations.models import FeeSchedule, Invoice


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CAQASystemSecurityAndWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Setup Institutions
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء", code="UNIV-A", institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.univ_b = Institution.objects.create(
            name="جامعة عدن", code="UNIV-B", institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        # 2. Setup Standard Version & Indicators
        self.std_version = StandardVersion.objects.create(
            title="الدليل الوطني لمعايير الاعتماد المؤسسي",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="2.0",
            status=StandardVersion.VersionStatus.ACTIVE
        )
        self.cat1 = StandardCategory.objects.create(
            version=self.std_version,
            track=AccreditationTrackType.INSTITUTIONAL,
            code="STD-01",
            title="الرسالة والأهداف",
            order=1
        )
        self.ind1 = StandardIndicator.objects.create(
            category=self.cat1,
            code="IND-1.1",
            title="وضوح ومشاركة الرسالة",
            order=1
        )

        # 3. Setup Users with distinct RBAC roles
        self.officer_a = User.objects.create_user(
            username="officer_a", password="password123",
            role=User.Roles.INSTITUTION_OFFICER, institution=self.univ_a
        )
        self.officer_b = User.objects.create_user(
            username="officer_b", password="password123",
            role=User.Roles.INSTITUTION_OFFICER, institution=self.univ_b
        )
        self.council_sec = User.objects.create_user(
            username="council_sec", password="password123",
            role=User.Roles.COUNCIL_SECRETARY, is_staff=True
        )
        self.reviewer_assigned = User.objects.create_user(
            username="reviewer_assigned", password="password123",
            role=User.Roles.EXTERNAL_REVIEWER
        )
        self.reviewer_unassigned = User.objects.create_user(
            username="reviewer_unassigned", password="password123",
            role=User.Roles.EXTERNAL_REVIEWER
        )
        self.board_member = User.objects.create_user(
            username="board_member", password="password123",
            role=User.Roles.BOARD_MEMBER, is_staff=True
        )

        # 4. Setup Applications
        self.app_a = AccreditationApplication.objects.create(
            application_number="CAQA-INST-2026-TEST-A",
            track=AccreditationTrackType.INSTITUTIONAL,
            institution=self.univ_a,
            standard_version=self.std_version,
            applicant_user=self.officer_a,
            current_stage=StageChoices.STAGE_1,
            status=ApplicationStatus.DRAFT
        )
        self.ssr_a = SelfStudyReport.objects.create(
            application=self.app_a,
            executive_summary="ملخص الدراسة الذاتية لجامعة صنعاء",
            internal_committee_names="لجنة الجودة"
        )
        self.evidence_a = EvidenceDocument.objects.create(
            application=self.app_a,
            indicator=self.ind1,
            code="EV-001",
            title="الخطة الاستراتيجية للجامعة",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

        self.app_b = AccreditationApplication.objects.create(
            application_number="CAQA-INST-2026-TEST-B",
            track=AccreditationTrackType.INSTITUTIONAL,
            institution=self.univ_b,
            standard_version=self.std_version,
            applicant_user=self.officer_b,
            current_stage=StageChoices.STAGE_1,
            status=ApplicationStatus.DRAFT
        )

    # =========================================================================
    # Test 1: Tenant Isolation (Horizontal Privilege Escalation Prevention)
    # =========================================================================
    def test_tenant_isolation_institution_cannot_access_other_institution(self):
        """Institution Officer A must NOT be able to view or edit Application B."""
        self.client.login(username="officer_a", password="password123")
        
        # Detail view
        response = self.client.get(reverse('accreditation:application_detail', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 302)  # redirected away
        
        # Self-study edit view
        response = self.client.get(reverse('accreditation:self_study_edit', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 302)

        # Evidences manage view
        response = self.client.get(reverse('accreditation:evidence_manage', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 302)

    # =========================================================================
    # Test 2: Reviewer Panel Assignment Isolation
    # =========================================================================
    def test_unassigned_reviewer_cannot_access_evaluation(self):
        """Reviewer not assigned to the panel must be blocked from evaluation."""
        self.client.login(username="reviewer_unassigned", password="password123")
        response = self.client.get(reverse('accreditation:external_rubrics_evaluation', args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 302)

    # =========================================================================
    # Test 3: Conflict of Interest (COI) Guard
    # =========================================================================
    def test_reviewer_must_sign_coi_before_evaluating(self):
        """Reviewer cannot access rubrics evaluation until COI is declared."""
        # Assign reviewer to team
        team = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-REV-01",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_assigned
        )
        self.client.login(username="reviewer_assigned", password="password123")
        
        # Try accessing rubrics without signing COI
        response = self.client.get(reverse('accreditation:external_rubrics_evaluation', args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accreditation:coi_declare', args=[self.app_a.pk]), response.url)

    def test_acknowledged_conflict_blocks_evaluation(self):
        """Reviewer with acknowledged conflict of interest is strictly blocked from scoring."""
        team = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-REV-01",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_assigned
        )
        # Reviewer declares conflict
        ConflictOfInterestDeclaration.objects.create(
            application=self.app_a,
            reviewer=self.reviewer_assigned,
            has_taught_in_institution=True,
            is_conflict_acknowledged=True
        )
        self.client.login(username="reviewer_assigned", password="password123")
        response = self.client.get(reverse('accreditation:external_rubrics_evaluation', args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accreditation:application_detail', args=[self.app_a.pk]), response.url)

    def test_coi_post_submission_redirects_to_external_rubrics_evaluation(self):
        """Reviewer submitting COI declaration with no conflict redirects to external rubrics evaluation without NoReverseMatch."""
        team = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-REV-01",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_assigned
        )
        self.client.login(username="reviewer_assigned", password="password123")
        response = self.client.post(reverse('accreditation:coi_declare', args=[self.app_a.pk]), {
            'other_conflict_details': 'لا يوجد أي تعارض مصالح'
        })
        # Must redirect to external_rubrics_evaluation with 302
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('accreditation:external_rubrics_evaluation', args=[self.app_a.pk])
        self.assertRedirects(response, expected_url)

        # Verify declaration is saved
        declaration = ConflictOfInterestDeclaration.objects.get(application=self.app_a, reviewer=self.reviewer_assigned)
        self.assertFalse(declaration.is_conflict_acknowledged)
        self.assertEqual(declaration.other_conflict_details, 'لا يوجد أي تعارض مصالح')

    def test_coi_post_with_acknowledged_conflict_redirects_to_application_detail(self):
        """Reviewer acknowledging conflict in POST redirects to application detail with warning."""
        team = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-REV-01",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_assigned
        )
        self.client.login(username="reviewer_assigned", password="password123")
        response = self.client.post(reverse('accreditation:coi_declare', args=[self.app_a.pk]), {
            'has_taught': 'on',
            'is_conflict_acknowledged': 'on',
            'other_conflict_details': 'قمت بالتدريس في الجامعة سابقاً'
        })
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('accreditation:application_detail', args=[self.app_a.pk])
        self.assertRedirects(response, expected_url)

        declaration = ConflictOfInterestDeclaration.objects.get(application=self.app_a, reviewer=self.reviewer_assigned)
        self.assertTrue(declaration.is_conflict_acknowledged)
        self.assertTrue(declaration.has_taught_in_institution)

    def test_coi_unauthorized_user_blocked(self):
        """Non-reviewer users (such as institution officers) are blocked from accessing COI declaration."""
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('accreditation:coi_declare', args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('accreditation:application_detail', args=[self.app_a.pk]))

    # =========================================================================
    # Test 4: Workflow Engine Transitions & Guard Enforcement
    # =========================================================================
    def test_workflow_valid_transition_and_history_logging(self):
        """Valid transition from DRAFT to SUBMITTED updates status, stage, and writes history."""
        can_move, reason = WorkflowEngine.can_transition(self.app_a, ApplicationStatus.SUBMITTED, self.officer_a)
        self.assertTrue(can_move)

        WorkflowEngine.execute_transition(
            application=self.app_a,
            target_status=ApplicationStatus.SUBMITTED,
            user=self.officer_a,
            reason="تسليم رسمي من ممثل المؤسسة"
        )
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, ApplicationStatus.SUBMITTED)
        self.assertEqual(self.app_a.current_stage, StageChoices.STAGE_2)
        
        # Verify history record created
        self.assertEqual(self.app_a.status_history.count(), 1)
        hist = self.app_a.status_history.first()
        self.assertEqual(hist.from_status, ApplicationStatus.DRAFT)
        self.assertEqual(hist.to_status, ApplicationStatus.SUBMITTED)
        self.assertEqual(hist.changed_by, self.officer_a)

    def test_workflow_illegal_stage_jump_is_prevented(self):
        """Direct jump from DRAFT to FULL_ACCREDITATION must be strictly rejected."""
        can_move, reason = WorkflowEngine.can_transition(self.app_a, ApplicationStatus.FULL_ACCREDITATION, self.officer_a)
        self.assertFalse(can_move)

    # =========================================================================
    # Test 5: Certificate Issuance and Live QR Verification
    # =========================================================================
    def test_certificate_public_verification_and_revocation(self):
        """Certificate verification endpoint returns active status, and reflects revocation immediately."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="جلسة رقم (1) لسنة 2026",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس"
        )
        decision = AccreditationDecision.objects.create(
            meeting=meeting,
            application=self.app_a,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار مجلس الاعتماد رقم (TEST-CERT-01) لسنة 2026",
            decision_date=timezone.now().date(),
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=1825),
            validity_years=5
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code="YEM-CAQA-TEST-0001",
            issue_date=timezone.now().date(),
            status=AccreditationCertificate.CertificateStatus.ACTIVE
        )

        # Public verification lookup
        response = self.client.get(reverse('decisions:verify_certificate_public', args=[cert.certificate_uuid]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وثيقة اعتماد أكاديمي رسمية وموثقة")

        # Now revoke certificate
        cert.status = AccreditationCertificate.CertificateStatus.REVOKED
        cert.is_revoked = True
        cert.revocation_decree = "قرار سحب رقم (9) لسنة 2026م"
        cert.revocation_reason = "مخالفة جسيمة في معايير المستشفى السريري"
        cert.save()

        # Public verification should now show revoked warning
        response = self.client.get(reverse('decisions:verify_certificate_public', args=[cert.certificate_uuid]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وثيقة اعتماد ملغاة أو مسحوبة")

    # =========================================================================
    # Test 6: RESTful API Endpoints
    # =========================================================================
    def test_public_verify_api_endpoint(self):
        """API endpoint returns JSON with live verification data."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="جلسة 2",
            meeting_date=timezone.now().date(),
            chairperson_name="رئيس المجلس"
        )
        decision = AccreditationDecision.objects.create(
            meeting=meeting,
            application=self.app_a,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار رقم (API-TEST-01) لسنة 2026",
            decision_date=timezone.now().date(),
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        cert = AccreditationCertificate.objects.create(
            decision=decision,
            national_registry_code="YEM-CAQA-API-0001",
            issue_date=timezone.now().date(),
            status=AccreditationCertificate.CertificateStatus.ACTIVE
        )

        response = self.client.get(reverse('api_v1:public_verify', args=[cert.certificate_uuid]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['certificate']['national_registry_code'], "YEM-CAQA-API-0001")
        self.assertTrue(data['certificate']['is_valid'])

    # =========================================================================
    # Test 7: Audit Logging of Sensitive Actions
    # =========================================================================
    def test_audit_log_captures_sensitive_events(self):
        """All critical actions must write to AuditLog."""
        initial_count = AuditLog.objects.count()
        WorkflowEngine.execute_transition(
            application=self.app_a,
            target_status=ApplicationStatus.SUBMITTED,
            user=self.officer_a,
            reason="اختبار التدقيق الأمني"
        )
        self.assertGreater(AuditLog.objects.count(), initial_count)
        latest_log = AuditLog.objects.first()
        self.assertEqual(latest_log.action, 'WORKFLOW_TRANSITION')
        self.assertEqual(latest_log.user, self.officer_a)

    # =========================================================================
    # Test 8: Site Visits Cross-Tenant Isolation (IDOR Protection)
    # =========================================================================
    def test_site_visit_console_tenant_isolation(self):
        """Officer A cannot view or console Site Visits for Application B."""
        visit_b = SiteVisitSchedule.objects.create(
            application=self.app_b,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=2),
            visit_location="مقر جامعة عدن"
        )
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('site_visits:console', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 302)

    # =========================================================================
    # Test 9: Surveillance Dashboard & Plan Tenant Scoping
    # =========================================================================
    def test_surveillance_dashboard_tenant_scoping(self):
        """Institution Officer only sees their own institution decisions in surveillance."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="جلسة المتابعة",
            meeting_date=timezone.now().date(),
            chairperson_name="رئيس المجلس"
        )
        dec_a = AccreditationDecision.objects.create(
            meeting=meeting,
            application=self.app_a,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار (SURV-A) 2026",
            decision_date=timezone.now().date(),
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        dec_b = AccreditationDecision.objects.create(
            meeting=meeting,
            application=self.app_b,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار (SURV-B) 2026",
            decision_date=timezone.now().date(),
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('surveillance:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, dec_a.decree_number)
        self.assertNotContains(response, dec_b.decree_number)

    # =========================================================================
    # Test 10: Decision Certificate Detail Tenant Isolation
    # =========================================================================
    def test_certificate_detail_tenant_isolation(self):
        """Officer A cannot view certificate details of Institution B."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="جلسة الشهادات",
            meeting_date=timezone.now().date(),
            chairperson_name="رئيس المجلس"
        )
        dec_b = AccreditationDecision.objects.create(
            meeting=meeting,
            application=self.app_b,
            decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            decree_number="قرار شهادة ب 2026",
            decision_date=timezone.now().date(),
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        cert_b = AccreditationCertificate.objects.create(
            decision=dec_b,
            national_registry_code="YEM-CERT-B-001",
            issue_date=timezone.now().date(),
            status=AccreditationCertificate.CertificateStatus.ACTIVE
        )
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('decisions:certificate_detail', args=[cert_b.pk]))
        self.assertEqual(response.status_code, 302)

    # =========================================================================
    # Test 11: Invoice & Financial Details Tenant Isolation
    # =========================================================================
    def test_invoice_detail_tenant_isolation(self):
        """Officer A cannot view or submit proof for Invoice belonging to Institution B."""
        fee = FeeSchedule.objects.create(
            service_name="رسوم اعتماد مؤسسي",
            track=AccreditationTrackType.INSTITUTIONAL,
            regulatory_reference="قرار رقم 10",
            amount_yer=5000000.00
        )
        inv_b = Invoice.objects.create(
            invoice_number="INV-2026-TEST-B",
            application=self.app_b,
            fee_schedule=fee,
            total_amount=5000000.00
        )
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('operations:invoice_detail', args=[inv_b.pk]))
        self.assertEqual(response.status_code, 302)

    # =========================================================================
    # Test 12: API Timeline Protection & Cross-Tenant Defense
    # =========================================================================
    def test_application_timeline_api_security(self):
        """Timeline API requires authentication and forbids cross-tenant access."""
        # Unauthenticated request must redirect or fail
        anon_client = Client()
        response = anon_client.get(reverse('api_v1:application_timeline', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 302)

        # Authenticated as Officer A trying to read App B timeline
        self.client.login(username="officer_a", password="password123")
        response = self.client.get(reverse('api_v1:application_timeline', args=[self.app_b.pk]))
        self.assertEqual(response.status_code, 403)

        # Officer A reading their own App A timeline
        response = self.client.get(reverse('api_v1:application_timeline', args=[self.app_a.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['application_number'], self.app_a.application_number)

    # =========================================================================
    # Test 13: Authentication Audit Logging (Login Success & Failed)
    # =========================================================================
    def test_login_and_failed_login_audit_logging(self):
        """Login attempts (successful or failed) are recorded in AuditLog."""
        # Failed login attempt
        self.client.post(reverse('accounts:login'), {
            'username': 'officer_a',
            'password': 'WRONG_PASSWORD_XYZ'
        })
        failed_log = AuditLog.objects.filter(action='LOGIN_FAILED', details__contains='officer_a').exists()
        self.assertTrue(failed_log)

        # Successful login attempt
        self.client.post(reverse('accounts:login'), {
            'username': 'officer_a',
            'password': 'password123'
        })
        success_log = AuditLog.objects.filter(action='LOGIN_SUCCESS', user=self.officer_a).exists()
        self.assertTrue(success_log)

    # =========================================================================
    # Test 14: Council Board Application Review (Accept with Cost & Invoice)
    # =========================================================================
    def test_board_review_accept_with_cost_and_invoice(self):
        """Council secretary accepts application with cost, creating an invoice and notifying applicant."""
        app = AccreditationApplication.objects.create(
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.PENDING_REVIEW,
            current_stage=StageChoices.STAGE_1,
            application_number="TEST-APP-ACCEPT-01"
        )
        self.client.login(username="council_sec", password="password123")
        
        response = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'accept_application',
            'cost_amount': '6000000.00',
            'cost_currency': 'YER',
            'cost_breakdown_notes': 'رسوم فحص مكتبي وزيارة ميدانية',
            'council_approval_notes': 'تم قبول الطلب مبدئياً والموافقة على بدء التقييم الذاتي'
        })
        self.assertEqual(response.status_code, 302)

        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION)
        self.assertEqual(float(app.cost_amount), 6000000.00)
        self.assertEqual(app.cost_currency, 'YER')
        self.assertEqual(app.reviewed_by, self.council_sec)
        self.assertTrue(app.can_start_self_study)

        # Check invoice created
        invoice = Invoice.objects.filter(application=app).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(float(invoice.total_amount), 6000000.00)

        # Check applicant notification
        notif = Notification.objects.filter(recipient=self.officer_a).first()
        self.assertIsNotNone(notif)
        self.assertTrue(len(notif.title) > 0)

    # =========================================================================
    # Test 15: Council Board Application Review (Reject with Mandatory Reason)
    # =========================================================================
    def test_board_review_reject_with_mandatory_reason(self):
        """Council rejecting an application requires a mandatory justification."""
        app = AccreditationApplication.objects.create(
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.PENDING_REVIEW,
            current_stage=StageChoices.STAGE_1,
            application_number="TEST-APP-REJECT-01"
        )
        self.client.login(username="council_sec", password="password123")

        # Empty reason fails
        response = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'reject_application',
            'rejection_reason': ''
        })
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PENDING_REVIEW)

        # Providing reason rejects application
        response = self.client.post(reverse('accreditation:board_application_review', args=[app.pk]), {
            'action': 'reject_application',
            'rejection_reason': 'عدم استيفاء شرط تخريج دفعة أولى بموجب المعايير الوطنية.'
        })
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.REJECTED)
        self.assertIn('عدم استيفاء شرط تخريج دفعة', app.rejection_reason)
        self.assertFalse(app.can_start_self_study)

    # =========================================================================
    # Test 16: Draft Application Submission
    # =========================================================================
    def test_application_draft_to_pending_review_submission(self):
        """Institution officer can create a draft and later submit it officially to the Council."""
        app = AccreditationApplication.objects.create(
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.DRAFT,
            current_stage=StageChoices.STAGE_1,
            application_number="TEST-APP-DRAFT-01"
        )
        self.client.login(username="officer_a", password="password123")
        response = self.client.post(reverse('accreditation:application_submit_draft', args=[app.pk]))
        self.assertEqual(response.status_code, 302)

        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.PENDING_REVIEW)

    # =========================================================================
    # Test 17: Self-Study Indicator Evaluation & Submission
    # =========================================================================
    def test_self_study_indicator_responses_and_submission(self):
        """Institution fills indicators responses and officially submits completed SSR."""
        app = AccreditationApplication.objects.create(
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION,
            current_stage=StageChoices.STAGE_1,
            application_number="TEST-APP-SSR-01"
        )
        self.client.login(username="officer_a", password="password123")

        # 1. Fill draft responses
        post_data = {
            f'compliance_{self.ind1.id}': SelfStudyIndicatorResponse.ComplianceLevel.MET,
            f'justification_{self.ind1.id}': 'تمت صياغة الرسالة بمشاركة كافة الأطراف ومجلس الجامعة.',
            f'strengths_{self.ind1.id}': 'مشاركة مجتمعية واسعة',
            f'gaps_{self.ind1.id}': 'نحتاج تحديث دوري للرسالة',
            f'corrective_{self.ind1.id}': 'ورشة عمل سنوية للمراجعة',
            f'responsible_{self.ind1.id}': 'مركز ضمان الجودة',
            'executive_summary': 'ملخص دراسة التقييم الذاتي لجامعة صنعاء',
        }
        response = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[app.pk]), post_data)
        self.assertEqual(response.status_code, 302)

        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.SELF_EVALUATION_IN_PROGRESS)

        ssr = app.self_study_report
        resp = SelfStudyIndicatorResponse.objects.filter(report=ssr, indicator=self.ind1).first()
        self.assertIsNotNone(resp)
        self.assertEqual(resp.compliance_level, SelfStudyIndicatorResponse.ComplianceLevel.MET)

        # 2. Officially submit completed SSR
        post_data['submit_self_study_official'] = '1'
        response = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[app.pk]), post_data)
        self.assertEqual(response.status_code, 302)

        ssr.refresh_from_db()
        app.refresh_from_db()
        self.assertTrue(ssr.is_locked)
        self.assertEqual(app.status, ApplicationStatus.SELF_EVALUATION_SUBMITTED)
        self.assertEqual(app.current_stage, StageChoices.STAGE_2)

    # =========================================================================
    # Test 18: Board Review Safe Decree and License Rendering
    # =========================================================================
    def test_board_review_safe_decree_and_license_rendering(self):
        """Board review page renders correctly when decree number is present, missing, or optional."""
        self.client.login(username="council_sec", password="password123")

        # Case 1: Institution without decree_number
        inst_no_decree = Institution.objects.create(
            name="جامعة تجريبية بدون قرار",
            code="UNIV-NO-DEC",
            institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY,
            decree_number=""
        )
        app_no_decree = AccreditationApplication.objects.create(
            institution=inst_no_decree,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.PENDING_REVIEW,
            application_number="APP-TEST-NO-DEC"
        )
        response = self.client.get(reverse('accreditation:board_application_review', args=[app_no_decree.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "غير مسجل")
        # Ensure property is safe
        self.assertEqual(app_no_decree.establishment_decree_number, "")
        self.assertEqual(inst_no_decree.license_number, "")

        # Case 2: Institution with decree_number populated
        inst_with_decree = Institution.objects.create(
            name="جامعة الأحقاف",
            code="UNIV-AHQ",
            institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY,
            decree_number="قرار وزاري رقم (123) لسنة 1995م"
        )
        app_with_decree = AccreditationApplication.objects.create(
            institution=inst_with_decree,
            track=AccreditationTrackType.INSTITUTIONAL,
            applicant_user=self.officer_a,
            status=ApplicationStatus.PENDING_REVIEW,
            application_number="APP-TEST-WITH-DEC"
        )
        response = self.client.get(reverse('accreditation:board_application_review', args=[app_with_decree.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "قرار وزاري رقم (123) لسنة 1995م")
        self.assertEqual(app_with_decree.establishment_decree_number, "قرار وزاري رقم (123) لسنة 1995م")
        self.assertEqual(inst_with_decree.license_number, "قرار وزاري رقم (123) لسنة 1995م")

    # =========================================================================
    # Test 19: Secretariat Assessment Comparison Dashboard Access Control
    # =========================================================================
    def test_secretariat_comparison_dashboard_access_control(self):
        """Only Council Board Members, Council Secretariat and Staff can access the comparison dashboard."""
        url = reverse('accreditation:secretariat_comparison_dashboard', args=[self.app_a.pk])

        # 1. Council Secretariat allowed
        self.client.login(username="council_sec", password="password123")
        res_sec = self.client.get(url)
        self.assertEqual(res_sec.status_code, 200)

        # 2. Board Member allowed
        self.client.login(username="board_member", password="password123")
        res_bm = self.client.get(url)
        self.assertEqual(res_bm.status_code, 200)

        # 3. Institution Officer forbidden -> redirect
        self.client.login(username="officer_a", password="password123")
        res_off = self.client.get(url)
        self.assertEqual(res_off.status_code, 302)

        # 4. External Reviewer forbidden -> redirect
        self.client.login(username="reviewer_assigned", password="password123")
        res_rev = self.client.get(url)
        self.assertEqual(res_rev.status_code, 302)

    # =========================================================================
    # Test 20: Secretariat Comparison Computation and Report Saving
    # =========================================================================
    def test_secretariat_comparison_computation_and_report_saving(self):
        """Secretariat can view compared scores (SSR vs External), differences, and save comparison report."""
        # 1. Setup SSR score (MET = 3.0)
        SelfStudyIndicatorResponse.objects.create(
            report=self.ssr_a,
            indicator=self.ind1,
            compliance_level=SelfStudyIndicatorResponse.ComplianceLevel.MET,
            justification="استيفاء تام للمعيار"
        )

        # 2. Setup External Evaluator score (SUBSTANTIALLY_MET = 2.0)
        IndicatorEvaluationScore.objects.create(
            application=self.app_a,
            indicator=self.ind1,
            evaluator=self.reviewer_assigned,
            score_level=RubricEvaluationLevel.SUBSTANTIALLY_MET,
            strengths="توفر وثائق قوية",
            weaknesses="بحاجة لتفعيل خطة النشر"
        )

        self.client.login(username="council_sec", password="password123")
        dash_url = reverse('accreditation:secretariat_comparison_dashboard', args=[self.app_a.pk])

        # 3. Verify comparison calculation on GET
        res_get = self.client.get(dash_url)
        self.assertEqual(res_get.status_code, 200)
        summary = res_get.context['category_summary']
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]['avg_ssr'], 3.0)
        self.assertEqual(summary[0]['avg_ext'], 2.0)
        self.assertEqual(summary[0]['avg_diff'], 1.0)

        # 4. POST to save comparison report
        res_post = self.client.post(dash_url, {
            'save_comparison_report': '1',
            'comparison_title': 'تقرير مقارنة التقييم الذاتي بالمراجعة لجامعة صنعاء',
            'secretariat_analytical_summary': 'فجوة إيجابية بمقدار درجة واحدة في معيار الرسالة والأهداف.'
        })
        self.assertEqual(res_post.status_code, 302)

        # Verify report is created in database
        report = SecretariatAssessmentComparisonReport.objects.filter(application=self.app_a).first()
        self.assertIsNotNone(report)
        self.assertEqual(report.title, 'تقرير مقارنة التقييم الذاتي بالمراجعة لجامعة صنعاء')
        self.assertTrue(report.attached_to_council_briefing)
        self.assertIn('فجوة إيجابية', report.secretariat_analytical_summary)
        self.assertIn('category_summary', report.comparison_data_json)

        # 5. Export printable view loads saved report
        export_url = reverse('accreditation:secretariat_comparison_export', args=[self.app_a.pk])
        res_export = self.client.get(export_url)
        self.assertEqual(res_export.status_code, 200)
        self.assertContains(res_export, "تقرير مطابقة ومقارنة التقييم الذاتي والتقييم الخارجي")
        self.assertContains(res_export, "فجوة إيجابية")

    # =========================================================================
    # Test 21: Council Board Restrictions - Cannot Create/Submit Application
    # =========================================================================
    def test_board_member_cannot_create_or_submit_application(self):
        """Board Member is prohibited from creating applications or submitting drafts."""
        self.client.login(username="board_member", password="password123")

        # 1. Direct GET on application_create returns 403 Forbidden
        res_get = self.client.get(reverse('accreditation:application_create'))
        self.assertEqual(res_get.status_code, 403)

        # 2. Direct POST on application_create returns 403 Forbidden
        initial_apps_count = AccreditationApplication.objects.count()
        res_post = self.client.post(reverse('accreditation:application_create'), {
            'track': AccreditationTrackType.INSTITUTIONAL,
            'institution': self.univ_a.pk,
            'submit_official': '1'
        })
        self.assertEqual(res_post.status_code, 403)
        self.assertEqual(AccreditationApplication.objects.count(), initial_apps_count)

        # 3. Direct POST to submit draft returns 403 Forbidden
        res_submit = self.client.post(reverse('accreditation:application_submit_draft', args=[self.app_a.pk]))
        self.assertEqual(res_submit.status_code, 403)
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, ApplicationStatus.DRAFT)

    # =========================================================================
    # Test 22: Council Secretariat Restrictions - Cannot Create/Submit Application
    # =========================================================================
    def test_secretariat_cannot_create_or_submit_application(self):
        """Secretariat is prohibited from creating applications or submitting drafts."""
        self.client.login(username="council_sec", password="password123")

        # 1. Direct GET on application_create returns 403 Forbidden
        res_get = self.client.get(reverse('accreditation:application_create'))
        self.assertEqual(res_get.status_code, 403)

        # 2. Direct POST on application_create returns 403 Forbidden
        initial_apps_count = AccreditationApplication.objects.count()
        res_post = self.client.post(reverse('accreditation:application_create'), {
            'track': AccreditationTrackType.INSTITUTIONAL,
            'institution': self.univ_a.pk,
            'submit_official': '1'
        })
        self.assertEqual(res_post.status_code, 403)
        self.assertEqual(AccreditationApplication.objects.count(), initial_apps_count)

        # 3. Direct POST to submit draft returns 403 Forbidden
        res_submit = self.client.post(reverse('accreditation:application_submit_draft', args=[self.app_a.pk]))
        self.assertEqual(res_submit.status_code, 403)
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, ApplicationStatus.DRAFT)

    # =========================================================================
    # Test 23: Council Board Restrictions - Cannot Edit/Score/Submit SSR
    # =========================================================================
    def test_board_member_cannot_edit_score_or_submit_self_assessment(self):
        """Board Member cannot access SSR edit form or enter/submit self-study scores."""
        self.client.login(username="board_member", password="password123")

        # 1. GET on self_study_indicators_edit redirects to read-only report view
        res_get_ind = self.client.get(reverse('accreditation:self_study_indicators_edit', args=[self.app_a.pk]))
        self.assertEqual(res_get_ind.status_code, 302)
        self.assertIn(reverse('accreditation:self_study_report_view', args=[self.app_a.pk]), res_get_ind.url)

        # 2. POST to self_study_indicators_edit returns 403 Forbidden
        res_post_ind = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[self.app_a.pk]), {
            f"compliance_{self.ind1.id}": SelfStudyIndicatorResponse.ComplianceLevel.MET,
            'submit_self_study_official': '1'
        })
        self.assertEqual(res_post_ind.status_code, 403)
        self.assertFalse(SelfStudyIndicatorResponse.objects.filter(report=self.ssr_a).exists())

        # 3. POST to self_study_edit returns 403 Forbidden
        res_post_ssr = self.client.post(reverse('accreditation:self_study_edit', args=[self.app_a.pk]), {
            'executive_summary': 'محاولة تعديل غير مصرح بها'
        })
        self.assertEqual(res_post_ssr.status_code, 403)

    # =========================================================================
    # Test 24: Council Secretariat Restrictions - Cannot Edit/Score/Submit SSR
    # =========================================================================
    def test_secretariat_cannot_edit_score_or_submit_self_assessment(self):
        """Secretariat user cannot access SSR edit form or enter/submit self-study scores."""
        self.client.login(username="council_sec", password="password123")

        # 1. GET on self_study_indicators_edit redirects to read-only report view
        res_get_ind = self.client.get(reverse('accreditation:self_study_indicators_edit', args=[self.app_a.pk]))
        self.assertEqual(res_get_ind.status_code, 302)
        self.assertIn(reverse('accreditation:self_study_report_view', args=[self.app_a.pk]), res_get_ind.url)

        # 2. POST to self_study_indicators_edit returns 403 Forbidden
        res_post_ind = self.client.post(reverse('accreditation:self_study_indicators_edit', args=[self.app_a.pk]), {
            f"compliance_{self.ind1.id}": SelfStudyIndicatorResponse.ComplianceLevel.MET,
            'submit_self_study_official': '1'
        })
        self.assertEqual(res_post_ind.status_code, 403)
        self.assertFalse(SelfStudyIndicatorResponse.objects.filter(report=self.ssr_a).exists())

        # 3. POST to self_study_edit returns 403 Forbidden
        res_post_ssr = self.client.post(reverse('accreditation:self_study_edit', args=[self.app_a.pk]), {
            'executive_summary': 'محاولة تعديل غير مصرح بها من الأمانة'
        })
        self.assertEqual(res_post_ssr.status_code, 403)

    # =========================================================================
    # Test 25: Evidence Upload Forbidden for Board & Secretariat
    # =========================================================================
    def test_board_and_secretariat_cannot_upload_evidence(self):
        """Council Board and Secretariat cannot upload evidence for an institution."""
        initial_ev_count = self.app_a.evidences.count()

        # 1. Board Member POST returns 403 Forbidden
        self.client.login(username="board_member", password="password123")
        res_board = self.client.post(reverse('accreditation:evidence_manage', args=[self.app_a.pk]), {
            'indicator': self.ind1.pk,
            'title': 'وثيقة شاهد مرفوعة من عضو المجلس'
        })
        self.assertEqual(res_board.status_code, 403)

        # 2. Secretariat POST returns 403 Forbidden
        self.client.login(username="council_sec", password="password123")
        res_sec = self.client.post(reverse('accreditation:evidence_manage', args=[self.app_a.pk]), {
            'indicator': self.ind1.pk,
            'title': 'وثيقة شاهد مرفوعة من الأمانة'
        })
        self.assertEqual(res_sec.status_code, 403)
        self.assertEqual(self.app_a.evidences.count(), initial_ev_count)

        # 3. Both can still view evidence list in read-only mode
        res_sec_get = self.client.get(reverse('accreditation:evidence_manage', args=[self.app_a.pk]))
        self.assertEqual(res_sec_get.status_code, 200)
        self.assertFalse(res_sec_get.context['can_upload_evidence'])
        self.assertNotContains(res_sec_get, "إضافة وثيقة شاهد جديدة")

    # =========================================================================
    # Test 26: Authorized Institution Officer Can Create & Submit Application
    # =========================================================================
    def test_authorized_institution_officer_can_create_and_submit_application(self):
        """Institution officer can create an application for their own university and submit draft."""
        self.client.login(username="officer_a", password="password123")

        # 1. GET application_create allowed (200)
        res_get = self.client.get(reverse('accreditation:application_create'))
        self.assertEqual(res_get.status_code, 200)

        # 2. POST application_create creates application for Univ A
        res_post = self.client.post(reverse('accreditation:application_create'), {
            'track': AccreditationTrackType.INSTITUTIONAL,
            'academic_year': '2025/2026',
            'contact_person_name': 'د. مسؤول الجودة',
            'contact_phone': '777000000',
            'contact_email': 'quality@univ-a.edu.ye'
        })
        self.assertEqual(res_post.status_code, 302)
        new_app = AccreditationApplication.objects.filter(institution=self.univ_a, applicant_user=self.officer_a).last()
        self.assertIsNotNone(new_app)
        self.assertEqual(new_app.status, ApplicationStatus.DRAFT)

        # 3. Officer A can upload evidence
        res_ev = self.client.post(reverse('accreditation:evidence_manage', args=[new_app.pk]), {
            'indicator': self.ind1.pk,
            'title': 'الخطة الإستراتيجية 2026',
            'code': 'EV-TEST-01'
        })
        self.assertEqual(res_ev.status_code, 302)
        self.assertTrue(new_app.evidences.filter(code='EV-TEST-01').exists())

        # 4. Officer A can submit draft officially
        res_submit = self.client.post(reverse('accreditation:application_submit_draft', args=[new_app.pk]))
        self.assertEqual(res_submit.status_code, 302)
        new_app.refresh_from_db()
        self.assertEqual(new_app.status, ApplicationStatus.PENDING_REVIEW)

    # =========================================================================
    # Test 27: Board and Secretariat Retain Legitimate Review and Decision Powers
    # =========================================================================
    def test_board_and_secretariat_retain_legitimate_powers(self):
        """Board members and Secretariat retain full review, oversight, and decision-making capabilities."""
        # 1. Board Member can view board review and applications list
        self.client.login(username="board_member", password="password123")
        res_board_list = self.client.get(reverse('accreditation:board_applications_list'))
        self.assertEqual(res_board_list.status_code, 200)

        res_board_rev = self.client.get(reverse('accreditation:board_application_review', args=[self.app_a.pk]))
        self.assertEqual(res_board_rev.status_code, 200)

        # 2. Secretariat can perform desk review and team assignment
        self.client.login(username="council_sec", password="password123")
        res_desk = self.client.get(reverse('accreditation:desk_review_process', args=[self.app_a.pk]))
        self.assertEqual(res_desk.status_code, 200)

        res_team = self.client.get(reverse('accreditation:assign_review_team', args=[self.app_a.pk]))
        self.assertEqual(res_team.status_code, 200)

        # 3. Read-only SSR report view accessible to Secretariat and Board
        res_ssr_rep = self.client.get(reverse('accreditation:self_study_report_view', args=[self.app_a.pk]))
        self.assertEqual(res_ssr_rep.status_code, 200)

    # =========================================================================
    # Test 28: Inter-Departmental Workflow State Machine and Separation of Powers
    # =========================================================================
    def test_inter_departmental_workflow_state_machine_and_routing(self):
        """
        Verify each stage routes through its legally mandated General Directorate:
        1. DG Accreditation -> Desk Review
        2. DG Finance -> Invoice Verification & Clearance
        3. DG Evaluation -> Review Team Assignment & Schedule
        4. Council Leadership / Board -> Board Review & Decision
        5. Legal Directorate -> Grievance Examination
        """
        from apps.accreditation.models import GrievanceAppeal
        from apps.operations.models import Invoice, FeeSchedule

        # Create Directorate users
        dg_accred = User.objects.create_user(
            username="test_dg_accred", password="password123",
            role=User.Roles.DG_ACCREDITATION, is_staff=True
        )
        dg_fin = User.objects.create_user(
            username="test_dg_fin", password="password123",
            role=User.Roles.DG_FINANCE_ADMIN, is_staff=True
        )
        dg_eval = User.objects.create_user(
            username="test_dg_eval", password="password123",
            role=User.Roles.DG_EVALUATION, is_staff=True
        )
        sec_gen = User.objects.create_user(
            username="test_sec_gen", password="password123",
            role=User.Roles.COUNCIL_SECRETARY_GENERAL, is_staff=True
        )
        legal_dir = User.objects.create_user(
            username="test_legal_dir", password="password123",
            role=User.Roles.LEGAL_DIRECTOR, is_staff=True
        )
        chairman = User.objects.create_user(
            username="test_chairman", password="password123",
            role=User.Roles.COUNCIL_CHAIRMAN, is_staff=True
        )

        # 1. DG Accreditation performs desk review
        self.app_a.status = ApplicationStatus.DESK_UNDER_REVIEW
        self.app_a.current_stage = StageChoices.STAGE_2
        self.app_a.save()

        self.client.login(username="test_dg_accred", password="password123")
        res_desk = self.client.get(reverse('accreditation:desk_review_process', args=[self.app_a.pk]))
        self.assertEqual(res_desk.status_code, 200)

        # Non-accreditation user (e.g. officer or reviewer) is blocked from desk review
        self.client.login(username="officer_a", password="password123")
        res_desk_block = self.client.get(reverse('accreditation:desk_review_process', args=[self.app_a.pk]))
        self.assertRedirects(res_desk_block, reverse('accreditation:application_detail', args=[self.app_a.pk]))

        # 2. DG Finance confirms invoice payment and issues clearance
        fee = FeeSchedule.objects.create(
            service_name="رسوم فحص",
            track=self.app_a.track,
            regulatory_reference="اللائحة",
            amount_yer=500000
        )
        inv = Invoice.objects.create(
            application=self.app_a,
            fee_schedule=fee,
            invoice_number="INV-FIN-TEST-001",
            total_amount=500000,
            status=Invoice.PaymentStatus.UNPAID
        )

        # Institution officer cannot confirm payment
        self.client.login(username="officer_a", password="password123")
        res_inv_block = self.client.post(reverse('operations:invoice_detail', args=[inv.pk]), {'confirm_payment': '1'})
        inv.refresh_from_db()
        self.assertNotEqual(inv.status, Invoice.PaymentStatus.PAID)

        # DG Finance confirms payment
        self.client.login(username="test_dg_fin", password="password123")
        res_inv_confirm = self.client.post(reverse('operations:invoice_detail', args=[inv.pk]), {'confirm_payment': '1'})
        self.assertEqual(res_inv_confirm.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PaymentStatus.PAID)
        self.assertEqual(inv.verified_by, dg_fin)

        # 3. DG Evaluation assigns review team
        self.app_a.status = ApplicationStatus.DESK_ACCEPTED
        self.app_a.save()

        # DG Evaluation can access team assignment
        self.client.login(username="test_dg_eval", password="password123")
        res_team = self.client.get(reverse('accreditation:assign_review_team', args=[self.app_a.pk]))
        self.assertEqual(res_team.status_code, 200)

        # 4. Grievance Review: Legal Directorate examines and Council resolves
        appeal = GrievanceAppeal.objects.create(
            application=self.app_a,
            appellant_user=self.officer_a,
            appeal_number="GRV-2026-TEST-99",
            grounds_of_appeal="اعتراض على نتيجة التقييم",
            status=GrievanceAppeal.AppealStatus.SUBMITTED
        )

        # Legal director submits report
        self.client.login(username="test_legal_dir", password="password123")
        res_grv_legal = self.client.post(
            reverse('accreditation:grievance_review', args=[appeal.pk]),
            {'action': 'save_legal_report', 'committee_report': 'تم استيفاء الشروط الشكلية للتظلم'}
        )
        self.assertEqual(res_grv_legal.status_code, 302)
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW)
        self.assertIn("استيفاء الشروط الشكلية", appeal.committee_report)

        # Chairman resolves grievance
        self.client.login(username="test_chairman", password="password123")
        res_grv_board = self.client.post(
            reverse('accreditation:grievance_review', args=[appeal.pk]),
            {'action': 'resolve_board', 'final_resolution': 'accept', 'final_resolution_notes': 'الموافقة على إعادة المداولة'}
        )
        self.assertEqual(res_grv_board.status_code, 302)
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION)





