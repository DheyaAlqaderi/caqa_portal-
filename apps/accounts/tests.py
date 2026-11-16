from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Notification, send_notification, notify_institution
from apps.institutions.models import Institution, College, AcademicProgram
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus


class AccountsAndRoleApprovalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="جامعة العلوم والتكنولوجيا",
            code="UST-01",
            institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY
        )
        self.admin = User.objects.create_superuser(
            username="system_admin",
            password="adminpassword123",
            email="admin@caqa.gov.ye",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED
        )

    def test_user_registration_sets_pending_approval(self):
        """New users should register with PENDING_APPROVAL status."""
        response = self.client.post(reverse('accounts:register'), {
            'full_name': 'د. أحمد اليماني',
            'username': 'new_dr_ahmed',
            'email': 'ahmed@ust.edu',
            'phone': '777123456',
            'national_id': '0101001234',
            'password': 'StrongPassword123!',
            'password_confirm': 'StrongPassword123!',
        })
        # Should redirect to select-role
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('accounts:select_role'))
        new_user = User.objects.get(username='new_dr_ahmed')
        self.assertEqual(new_user.approval_status, User.ApprovalStatus.PENDING_APPROVAL)
        self.assertFalse(new_user.is_approved)

    def test_unapproved_user_redirected_to_pending_approval_page(self):
        """Unapproved users attempting to view dashboard must be redirected to pending-approval page."""
        user = User.objects.create_user(
            username="pending_user",
            password="password123",
            role_requested=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL
        )
        self.client.login(username="pending_user", password="password123")
        response = self.client.get(reverse('core_dashboard'))
        self.assertRedirects(response, reverse('accounts:pending_approval'))

    def test_admin_approves_user_role(self):
        """Admin can approve pending user and assign official role, which sends notification."""
        pending_user = User.objects.create_user(
            username="dr_khalid",
            password="password123",
            institution=self.institution,
            role_requested=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL
        )
        self.client.login(username="system_admin", password="adminpassword123")
        
        response = self.client.post(reverse('accounts:admin_approve_user', args=[pending_user.pk]), {
            'assigned_role': User.Roles.INSTITUTION_OFFICER,
            'is_certified_evaluator': '1',
            'evaluator_certificate_number': 'CAQA-CERT-9901'
        })
        self.assertEqual(response.status_code, 302)

        pending_user.refresh_from_db()
        self.assertEqual(pending_user.approval_status, User.ApprovalStatus.APPROVED)
        self.assertEqual(pending_user.role, User.Roles.INSTITUTION_OFFICER)
        self.assertTrue(pending_user.is_approved)
        self.assertTrue(pending_user.is_certified_evaluator)
        self.assertEqual(pending_user.evaluator_certificate_number, 'CAQA-CERT-9901')

        # Check notification sent to user
        notification = Notification.objects.filter(recipient=pending_user).first()
        self.assertIsNotNone(notification)
        self.assertTrue(len(notification.title) > 0)

    def test_restricted_role_change_permissions(self):
        """
        Only System Administrator (ADMIN) and Council Board Member (BOARD_MEMBER)
        can change roles. Institution Officers, Reviewers, and Secretariat users are forbidden.
        """
        target_user = User.objects.create_user(
            username="test_subject",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        board_member = User.objects.create_user(
            username="board_user",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        secretariat_user = User.objects.create_user(
            username="sec_user",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED
        )

        officer_user = User.objects.create_user(
            username="officer_user",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.institution,
            approval_status=User.ApprovalStatus.APPROVED
        )

        reviewer_user = User.objects.create_user(
            username="rev_user",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # 1. Institution Officer trying to change role -> 302 redirect / Access Denied
        self.client.login(username="officer_user", password="password123")
        res = self.client.post(reverse('accounts:change_user_role', args=[target_user.pk]), {
            'new_role': User.Roles.COUNCIL_SECRETARY
        })
        self.assertEqual(res.status_code, 302)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Roles.INSTITUTION_OFFICER)

        # 2. External Reviewer trying to change role -> 302 redirect / Access Denied
        self.client.login(username="rev_user", password="password123")
        res = self.client.post(reverse('accounts:change_user_role', args=[target_user.pk]), {
            'new_role': User.Roles.ADMIN
        })
        self.assertEqual(res.status_code, 302)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Roles.INSTITUTION_OFFICER)

        # 3. Secretariat user trying to change role -> 302 redirect / Access Denied
        self.client.login(username="sec_user", password="password123")
        res = self.client.post(reverse('accounts:change_user_role', args=[target_user.pk]), {
            'new_role': User.Roles.BOARD_MEMBER
        })
        self.assertEqual(res.status_code, 302)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Roles.INSTITUTION_OFFICER)

        # 4. Council Board Member successfully changes role
        self.client.login(username="board_user", password="password123")
        res = self.client.post(reverse('accounts:change_user_role', args=[target_user.pk]), {
            'new_role': User.Roles.EXTERNAL_REVIEWER,
            'change_reason': 'تكليف خبير تقييم'
        })
        self.assertEqual(res.status_code, 302)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Roles.EXTERNAL_REVIEWER)

        # 5. System Administrator successfully changes role
        self.client.login(username="system_admin", password="adminpassword123")
        res = self.client.post(reverse('accounts:change_user_role', args=[target_user.pk]), {
            'new_role': User.Roles.COUNCIL_SECRETARY,
            'change_reason': 'نقل إداري'
        })
        self.assertEqual(res.status_code, 302)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Roles.COUNCIL_SECRETARY)


    def test_admin_rejects_user_requires_reason(self):
        """Admin rejecting user requires a mandatory reason and records rejection."""
        pending_user = User.objects.create_user(
            username="invalid_applicant",
            password="password123",
            role_requested=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL
        )
        self.client.login(username="system_admin", password="adminpassword123")
        
        # Empty reason should be rejected
        response = self.client.post(reverse('accounts:admin_reject_user', args=[pending_user.pk]), {
            'rejection_reason': ''
        })
        pending_user.refresh_from_db()
        self.assertEqual(pending_user.approval_status, User.ApprovalStatus.PENDING_APPROVAL)

        # Non-empty reason succeeds
        response = self.client.post(reverse('accounts:admin_reject_user', args=[pending_user.pk]), {
            'rejection_reason': 'الوثائق الأكاديمية وشهادة الخبرة المرفقة غير مكتملة.'
        })
        self.assertEqual(response.status_code, 302)
        pending_user.refresh_from_db()
        self.assertEqual(pending_user.approval_status, User.ApprovalStatus.REJECTED)
        self.assertEqual(pending_user.role_rejection_reason, 'الوثائق الأكاديمية وشهادة الخبرة المرفقة غير مكتملة.')

        notification = Notification.objects.filter(recipient=pending_user).first()
        self.assertIsNotNone(notification)
        self.assertTrue(len(notification.title) > 0)


class NotificationPhase1SecurityAndGovernanceTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Institutions
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-A",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.univ_b = Institution.objects.create(
            name="جامعة العلوم والتكنولوجيا",
            code="UNIV-B",
            institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY
        )

        # Standard & College for applications
        self.std_ver = StandardVersion.objects.create(
            title="المعايير المؤسسية الوطنية",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="1.0"
        )
        self.college_a = College.objects.create(
            institution=self.univ_a,
            name="كلية الطب والعلوم الصحية"
        )
        self.program_a = AcademicProgram.objects.create(
            college=self.college_a,
            name="برنامج الطب البشري",
            degree_level="بكالوريوس",
            )

        # Institution A users
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
        self.officer_a_pending = User.objects.create_user(
            username="officer_a_pending",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL,
            is_active=True
        )

        # Institution B users
        self.officer_b1 = User.objects.create_user(
            username="officer_b1",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # Secretariat, Board Member, Admin users
        self.sec_user = User.objects.create_user(
            username="sec_user",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_active=True
        )
        self.board_user = User.objects.create_user(
            username="board_user",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username="admin_user",
            password="password123",
            email="admin@caqa.gov.ye",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

    def test_multiple_authorized_officers_same_institution_receive_notification(self):
        """All approved, active officers belonging to Institution A receive the notification."""
        notifs = notify_institution(
            institution=self.univ_a,
            title="إشعار مؤسسي تجريبي",
            message="رسالة تجريبية موجهة لممثلي جودة المؤسسة",
            url="/accreditation/test/"
        )
        self.assertEqual(len(notifs), 2)

        # Verify both officer_a1 and officer_a2 received it
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title="إشعار مؤسسي تجريبي").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title="إشعار مؤسسي تجريبي").exists())

    def test_inactive_and_unapproved_officers_do_not_receive_notification(self):
        """Inactive or pending-approval officers must NOT receive institution notifications."""
        notify_institution(
            institution=self.univ_a,
            title="فحص استبعاد غير النشطين",
            message="رسالة سرية",
            url="/test/"
        )
        self.assertFalse(Notification.objects.filter(recipient=self.officer_a_inactive).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.officer_a_pending).exists())

    def test_officers_from_other_institutions_never_receive_notification(self):
        """Strict institution isolation: Officers of Institution B must NEVER receive Institution A notifications."""
        notify_institution(
            institution=self.univ_a,
            title="عزل مؤسسي صارم",
            message="بيانات خاصة بمؤسسة أ",
            url="/test/univ_a/",
            extra_recipients=[self.officer_b1]  # Even if maliciously or mistakenly passed as extra recipient!
        )
        # Officer B of University B must NOT receive anything
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b1).count(), 0)

    def test_preliminary_submission_notifies_secretariat_and_admin_only_not_board(self):
        """
        Preliminary application submissions must notify Secretariat and Admin staff,
        and must NOT notify Board Members at this preliminary stage.
        """
        self.client.login(username="officer_a1", password="password123")

        # Count initial notifications
        init_sec_count = Notification.objects.filter(recipient=self.sec_user).count()
        init_admin_count = Notification.objects.filter(recipient=self.admin_user).count()
        init_board_count = Notification.objects.filter(recipient=self.board_user).count()

        # Submit official preliminary application
        response = self.client.post(reverse('accreditation:application_create'), {
            'institution': self.univ_a.pk,
            'track': AccreditationTrackType.INSTITUTIONAL,
            'standard_version': self.std_ver.pk,
            'scope_description': 'طلب اعتماد مؤسسي أولي تجريبي',
            'notes': 'ملاحظات تقديم الطلب',
            'submit_official': '1'
        })
        self.assertEqual(response.status_code, 302)

        # Secretariat and Admin must have received notification
        self.assertEqual(Notification.objects.filter(recipient=self.sec_user).count(), init_sec_count + 1)
        self.assertEqual(Notification.objects.filter(recipient=self.admin_user).count(), init_admin_count + 1)

        # Board member must NOT have received any notification at preliminary stage!
        self.assertEqual(Notification.objects.filter(recipient=self.board_user).count(), init_board_count)

        # Both Institution A officers (a1 and a2) received confirmation notification
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="طلب الاعتماد").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title__contains="طلب الاعتماد").exists())

    def test_duplicate_notifications_prevented_on_repeated_events(self):
        """Processing the exact same event multiple times does not generate duplicate unread notifications."""
        # 1st execution
        notifs_1 = notify_institution(
            institution=self.univ_a,
            title="قرار مهم غير مكرر",
            message="تفاصيل القرار",
            url="/decision/1/"
        )
        self.assertEqual(len(notifs_1), 2)
        count_after_1 = Notification.objects.filter(title="قرار مهم غير مكرر").count()
        self.assertEqual(count_after_1, 2)

        # 2nd execution (re-processing same event)
        notifs_2 = notify_institution(
            institution=self.univ_a,
            title="قرار مهم غير مكرر",
            message="تفاصيل القرار",
            url="/decision/1/"
        )
        self.assertEqual(len(notifs_2), 0)
        count_after_2 = Notification.objects.filter(title="قرار مهم غير مكرر").count()
        # Count remains 2! Duplicate was successfully prevented
        self.assertEqual(count_after_2, 2)

    def test_user_cannot_view_or_mark_another_users_notification_as_read(self):
        """Users can only access their own notifications and cannot mark another user's notification as read."""
        notif_a1 = Notification.objects.create(
            recipient=self.officer_a1,
            title="إشعار سري للضابط الأول",
            message="بيانات حساب 1",
            url="/accounts/profile/"
        )

        # Officer B logs in and tries to mark Officer A1's notification as read
        self.client.login(username="officer_b1", password="password123")
        mark_res = self.client.get(reverse('accounts:notification_mark_read', args=[notif_a1.pk]))
        self.assertEqual(mark_res.status_code, 404)

        # Verify notif_a1 remains unread
        notif_a1.refresh_from_db()
        self.assertFalse(notif_a1.is_read)

        # Officer B views notifications list -> Officer A1's notification is not present
        list_res = self.client.get(reverse('accounts:notifications_list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertNotContains(list_res, "إشعار سري للضابط الأول")


    def test_governance_separation_of_powers_and_hard_gates(self):
        from apps.accounts.permissions import (
            has_permission,
            rotate_user_override,
            seed_default_permissions,
            GOVERNANCE_LOCKED_PERMISSIONS
        )
        from django.core.exceptions import PermissionDenied

        seed_default_permissions()

        # 1. Create representative users for each tier
        chairman = User.objects.create_user(username='test_chair', password='password123', role=User.Roles.COUNCIL_CHAIRMAN)
        board_mem = User.objects.create_user(username='test_board_mem', password='password123', role=User.Roles.BOARD_MEMBER)
        sec_gen = User.objects.create_user(username='test_sec_gen', password='password123', role=User.Roles.COUNCIL_SECRETARY_GENERAL)
        dg_finance = User.objects.create_user(username='test_dg_fin', password='password123', role=User.Roles.DG_FINANCE_ADMIN)
        dg_accred = User.objects.create_user(username='test_dg_accred', password='password123', role=User.Roles.DG_ACCREDITATION)
        dg_eval = User.objects.create_user(username='test_dg_eval', password='password123', role=User.Roles.DG_EVALUATION)
        inst_officer = User.objects.create_user(username='test_inst_off', password='password123', role=User.Roles.INSTITUTION_OFFICER)
        admin_actor = User.objects.create_user(username='test_admin_actor', password='password123', role=User.Roles.ADMIN)

        # 2. Check Default Tiered Permissions
        self.assertTrue(has_permission(chairman, 'can_sign_council_decrees'))
        self.assertTrue(has_permission(chairman, 'can_finalize_collective_decision'))

        self.assertTrue(has_permission(board_mem, 'can_record_individual_vote'))
        self.assertFalse(has_permission(board_mem, 'can_conduct_desk_review'))

        self.assertTrue(has_permission(sec_gen, 'can_conduct_desk_review'))
        self.assertTrue(has_permission(sec_gen, 'can_generate_comparison'))
        self.assertFalse(has_permission(sec_gen, 'can_record_individual_vote'))

        self.assertTrue(has_permission(dg_finance, 'can_issue_financial_clearance'))
        self.assertTrue(has_permission(dg_finance, 'can_verify_payment'))
        self.assertFalse(has_permission(dg_finance, 'can_conduct_desk_review'))

        self.assertTrue(has_permission(dg_accred, 'can_conduct_desk_review'))
        self.assertTrue(has_permission(dg_accred, 'can_request_corrections'))
        self.assertFalse(has_permission(dg_accred, 'can_issue_financial_clearance'))

        self.assertTrue(has_permission(dg_eval, 'can_nominate_reviewers'))
        self.assertTrue(has_permission(dg_eval, 'can_schedule_site_visit'))
        self.assertFalse(has_permission(dg_eval, 'can_verify_payment'))

        # 3. Test Level 1 Hard Gates (Anti-Conflict-of-Interest & Anti-Tampering)
        # Rule A: Board Member CANNOT be granted External Reviewer capability
        with self.assertRaises(PermissionDenied):
            rotate_user_override(
                user=board_mem,
                permission='can_submit_evaluation',
                override_type='GRANT',
                reason='Illegal attempt to let board member review university',
                granted_by=admin_actor
            )

        # Rule B: Secretariat staff CANNOT vote on Board decisions
        with self.assertRaises(PermissionDenied):
            rotate_user_override(
                user=dg_accred,
                permission='can_record_individual_vote',
                override_type='GRANT',
                reason='Illegal attempt to let secretariat staff vote in council meeting',
                granted_by=admin_actor
            )

        # Rule C: Institution Officer CANNOT issue financial clearance for themselves
        with self.assertRaises(PermissionDenied):
            rotate_user_override(
                user=inst_officer,
                permission='can_issue_financial_clearance',
                override_type='GRANT',
                reason='Illegal attempt to let university officer approve own fees',
                granted_by=admin_actor
            )



class MyLibraryAndDocumentVaultTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-SANAA-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.other_institution = Institution.objects.create(
            name="جامعة العلوم والتكنولوجيا",
            code="UST-01",
            institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY
        )

        self.chairman = User.objects.create_user(
            username="test_chairman",
            password="password123",
            role=User.Roles.COUNCIL_CHAIRMAN,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.sec_gen = User.objects.create_user(
            username="test_sec_gen",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY_GENERAL,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.univ_officer = User.objects.create_user(
            username="test_officer_sanaa",
            password="password123",
            institution=self.institution,
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.reviewer = User.objects.create_user(
            username="test_external_reviewer",
            password="password123",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED
        )
        self.other_officer = User.objects.create_user(
            username="test_officer_other",
            password="password123",
            institution=self.other_institution,
            role=User.Roles.INSTITUTION_OFFICER,
            approval_status=User.ApprovalStatus.APPROVED
        )

        from apps.accounts.models import UserDocument, DocumentShare
        from apps.accounts.library_service import get_authorized_recipients, sync_system_assets_to_library
        self.UserDocument = UserDocument
        self.DocumentShare = DocumentShare
        self.get_authorized_recipients = staticmethod(get_authorized_recipients)
        self.sync_system_assets_to_library = staticmethod(sync_system_assets_to_library)

    def test_library_view_accessible(self):
        """User can access their library page."""
        self.client.login(username="test_officer_sanaa", password="password123")
        response = self.client.get(reverse('accounts:library_index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/library.html')

    def test_separation_of_powers_in_recipients(self):
        """Institution officers cannot directly send documents to external reviewers (Strict anti-tampering)."""
        allowed_recipients = self.get_authorized_recipients(self.univ_officer)
        self.assertNotIn(self.reviewer, allowed_recipients)
        self.assertIn(self.sec_gen, allowed_recipients)

    def test_sharing_document_enforces_governance_matrix(self):
        """Attempting to share document with an unauthorized recipient is rejected."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        test_file = SimpleUploadedFile("evidence.pdf", b"%PDF-1.4 test content", content_type="application/pdf")
        doc = self.UserDocument.objects.create(
            owner=self.univ_officer,
            title="تقرير الجودة الداخلي",
            doc_type=self.UserDocument.DocumentType.REPORT,
            file=test_file
        )
        self.client.login(username="test_officer_sanaa", password="password123")
        # Try sending to reviewer (forbidden)
        response = self.client.post(reverse('accounts:library_send', args=[doc.pk]), {
            'recipient_id': self.reviewer.pk,
            'notes': 'محاولة غير مصرح بها'
        })
        self.assertEqual(response.status_code, 302)
        # Should NOT create share
        self.assertFalse(self.DocumentShare.objects.filter(document=doc, recipient=self.reviewer).exists())

        # Now send to authorized Secretariat (allowed)
        response = self.client.post(reverse('accounts:library_send', args=[doc.pk]), {
            'recipient_id': self.sec_gen.pk,
            'notes': 'إحالة رسمية للأمانة العامة'
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.DocumentShare.objects.filter(document=doc, recipient=self.sec_gen).exists())

    def test_tenant_isolation_on_document_download(self):
        """Officer from other university cannot access or download Sana'a university document."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        test_file = SimpleUploadedFile("confidential.pdf", b"%PDF-1.4 secret", content_type="application/pdf")
        doc = self.UserDocument.objects.create(
            owner=self.univ_officer,
            title="وثيقة سرية",
            doc_type=self.UserDocument.DocumentType.REPORT,
            file=test_file
        )
        self.client.login(username="test_officer_other", password="password123")
        response = self.client.get(reverse('accounts:library_download', args=[doc.pk]))
        self.assertEqual(response.status_code, 403)
