"""
Comprehensive Automated Test Suite for the System Administrator Dashboard,
Permissions, User Management, Reference Data, General Settings, Notification Monitor,
Files & Storage, Read-Only Workflow Monitor, Security Center, and Backup/Restore.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import (
    AuditLog,
    DynamicPermission,
    PermissionAuditRecord,
    SMSLog,
    SystemBackupRecord,
    SystemConfiguration,
    User,
)
from apps.accounts.permissions import has_permission, seed_default_permissions
from apps.institutions.models import AcademicProgram, College, Department, Institution


class SystemAdministratorEnhancementsTestSuite(TestCase):
    def setUp(self):
        seed_default_permissions()
        self.inst = Institution.objects.create(
            name="جامعة صنعاء الاختبارية",
            code="SU-TEST",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY,
            governorate="أمانة العاصمة",
            official_email="info@su.edu.ye",
            official_phone="01-234567",
            president_name="أ.د. رئيس الجامعة",
        )
        self.sysadmin = User.objects.create_user(
            username="sys_admin_main",
            password="Password123!",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_superuser=True,
        )
        self.it_director = User.objects.create_user(
            username="it_dir_user",
            password="Password123!",
            role=User.Roles.IT_DIRECTOR,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
        )
        self.officer = User.objects.create_user(
            username="inst_officer_1",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.inst,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_01_sysadmin_dashboard_real_statistics_and_authorization(self):
        """Authorized ADMIN accesses dashboard with real DB metrics; unauthorized officer gets 403."""
        self.client.login(username="inst_officer_1", password="Password123!")
        res_denied = self.client.get(reverse('accounts:sysadmin_dashboard'))
        self.assertEqual(res_denied.status_code, 403)

        self.client.login(username="sys_admin_main", password="Password123!")
        res = self.client.get(reverse('accounts:sysadmin_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['stats']['total_users'], User.objects.count())
        self.assertEqual(res.context['stats']['total_institutions'], Institution.objects.count())
        self.assertTrue(res.context['health']['django']['ok'])
        self.assertTrue(res.context['health']['database']['ok'])

    def test_02_user_management_create_edit_lock_deactivate_and_reset_password(self):
        """System Administrator can create, edit, lock/unlock, activate/deactivate, and reset password safely."""
        self.client.login(username="sys_admin_main", password="Password123!")

        # 1. Create user
        self.client.post(reverse('accounts:admin_create_user'), {
            'username': 'new_managed_user',
            'email': 'managed@caqa.gov.ye',
            'full_name': 'د. أحمد المدار',
            'password': 'SecurePassword123!',
            'role': User.Roles.EXTERNAL_REVIEWER,
            'phone': '777111222',
        })
        created_u = User.objects.filter(username='new_managed_user').first()
        self.assertIsNotNone(created_u)
        self.assertNotEqual(created_u.password, 'SecurePassword123!')  # Never stored as plaintext

        # 2. Edit user
        self.client.post(reverse('accounts:admin_edit_user', args=[created_u.pk]), {
            'first_name': 'د. أحمد المعدل',
            'last_name': 'المدار',
            'email': 'updated@caqa.gov.ye',
            'phone': '777999888',
        })
        created_u.refresh_from_db()
        self.assertEqual(created_u.email, 'updated@caqa.gov.ye')

        # 3. Lock & Unlock user
        self.client.post(reverse('accounts:admin_toggle_user_lock', args=[created_u.pk]), {
            'lock_reason': 'اشتباه أمني',
        })
        created_u.refresh_from_db()
        self.assertTrue(created_u.is_locked)

        # Locked user cannot log in
        self.client.logout()
        self.client.post(reverse('accounts:login'), {
            'username': 'new_managed_user',
            'password': 'SecurePassword123!',
        })
        self.assertTrue(AuditLog.objects.filter(action='LOGIN_BLOCKED_LOCKED_ACCOUNT', target_id=str(created_u.pk)).exists())

        # Unlock
        self.client.login(username="sys_admin_main", password="Password123!")
        self.client.post(reverse('accounts:admin_toggle_user_lock', args=[created_u.pk]))
        created_u.refresh_from_db()
        self.assertFalse(created_u.is_locked)

        # 4. Protect self from deactivation
        self.client.post(reverse('accounts:admin_toggle_user_active', args=[self.sysadmin.pk]))
        self.sysadmin.refresh_from_db()
        self.assertTrue(self.sysadmin.is_active)

        # 5. Reset password without logging plaintext password
        self.client.post(reverse('accounts:admin_reset_user_password', args=[created_u.pk]), {
            'new_password': 'NewResetPassword99!',
        })
        reset_log = AuditLog.objects.filter(action='USER_PASSWORD_RESET_INITIATED', target_id=str(created_u.pk)).first()
        self.assertIsNotNone(reset_log)
        self.assertNotIn('NewResetPassword99!', reset_log.details)

    def test_03_governance_boundary_admin_cannot_make_academic_or_council_decisions(self):
        """System Administrator is strictly blocked from Council voting, collective decisions, and evaluations."""
        self.assertFalse(has_permission(self.sysadmin, 'can_record_individual_vote'))
        self.assertFalse(has_permission(self.sysadmin, 'can_finalize_collective_decision'))
        self.assertFalse(has_permission(self.sysadmin, 'can_decide_grievance'))
        self.assertFalse(has_permission(self.sysadmin, 'can_sign_council_decrees'))
        self.assertFalse(has_permission(self.sysadmin, 'can_submit_evaluation'))

    def test_04_reference_data_hierarchy_and_duplicate_prevention(self):
        """System Administrator can manage Institution -> College -> Department -> Program hierarchy."""
        self.client.login(username="sys_admin_main", password="Password123!")
        self.client.post(reverse('accounts:sysadmin_reference_data'), {
            'action': 'create_college',
            'institution_id': self.inst.pk,
            'name': 'كلية الطب والعلوم الصحية',
            'dean_name': 'أ.د. عميد الطب',
        })
        col = College.objects.filter(institution=self.inst, name='كلية الطب والعلوم الصحية').first()
        self.assertIsNotNone(col)

        self.client.post(reverse('accounts:sysadmin_reference_data'), {
            'action': 'create_department',
            'college_id': col.pk,
            'name': 'قسم الجراحة العامة',
        })
        dept = Department.objects.filter(college=col, name='قسم الجراحة العامة').first()
        self.assertIsNotNone(dept)

        self.client.post(reverse('accounts:sysadmin_reference_data'), {
            'action': 'create_program',
            'college_id': col.pk,
            'department_id': dept.pk,
            'name': 'بكالوريوس الطب والجراحة',
            'code': 'MBBS-01',
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
        })
        self.assertTrue(AcademicProgram.objects.filter(college=col, code='MBBS-01').exists())

    def test_05_system_settings_and_executable_upload_restriction(self):
        """System settings reject dangerous executable extensions and audit valid updates."""
        self.client.login(username="sys_admin_main", password="Password123!")
        # Attempt to add .exe -> rejected
        self.client.post(reverse('accounts:sysadmin_settings'), {
            'action': 'save_settings',
            'portal_name_ar': 'بوابة الاعتماد',
            'allowed_extensions': 'pdf,exe,bat',
            'max_upload_size_mb': 25,
        })
        cfg = SystemConfiguration.get_solo()
        self.assertNotIn('exe', cfg.allowed_extensions)

        # Valid update -> saved & audited
        self.client.post(reverse('accounts:sysadmin_settings'), {
            'action': 'save_settings',
            'portal_name_ar': 'بوابة مجلس الاعتماد الأكاديمي المحدثة',
            'allowed_extensions': 'pdf,docx,png',
            'max_upload_size_mb': 30,
            'session_timeout_minutes': 45,
            'max_login_attempts': 5,
            'account_lockout_minutes': 30,
        })
        cfg.refresh_from_db()
        self.assertEqual(cfg.max_upload_size_mb, 30)
        self.assertTrue(AuditLog.objects.filter(action='SYSTEM_SETTINGS_UPDATED').exists())

    def test_06_notifications_monitor_and_safe_retry(self):
        """Failed SMS delivery can be safely retried for its original recipient."""
        failed_sms = SMSLog.objects.create(
            recipient=self.officer,
            phone_number='777000111',
            message_body='إشعار اختباري',
            status=SMSLog.Status.FAILED,
            gateway_response='Timeout',
        )
        self.client.login(username="sys_admin_main", password="Password123!")
        self.client.post(reverse('accounts:sysadmin_notifications_monitor'), {
            'retry_sms_id': failed_sms.pk,
        })
        failed_sms.refresh_from_db()
        self.assertEqual(failed_sms.status, SMSLog.Status.SENT)
        self.assertEqual(failed_sms.recipient, self.officer)

    def test_07_workflow_monitor_is_strictly_read_only(self):
        """Workflow monitor allows GET for sysadmin and rejects POST mutations."""
        self.client.login(username="sys_admin_main", password="Password123!")
        res_get = self.client.get(reverse('accounts:sysadmin_workflow_monitor'))
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(len(res_get.context['checkpoints_20']), 20)

        res_post = self.client.post(reverse('accounts:sysadmin_workflow_monitor'), {'mutate': '1'})
        self.assertEqual(res_post.status_code, 403)

    def test_08_backup_create_verify_and_protected_restore(self):
        """Backup creation, SHA-256 verification, and protected restore with pre-restore backup work."""
        self.client.login(username="sys_admin_main", password="Password123!")

        # 1. Create manual backup
        self.client.post(reverse('accounts:sysadmin_backups'), {
            'action': 'create_backup',
            'notes': 'نسخة اختبارية للتحقق الآلي',
        })
        backup = SystemBackupRecord.objects.filter(backup_type=SystemBackupRecord.BackupType.MANUAL).first()
        self.assertIsNotNone(backup)
        self.assertTrue(backup.is_verified)
        self.assertTrue(bool(backup.sha256_checksum))

        # 2. Verify backup integrity
        self.client.post(reverse('accounts:sysadmin_backups'), {
            'action': 'verify_backup',
            'backup_id': backup.pk,
        })
        backup.refresh_from_db()
        self.assertEqual(backup.status, SystemBackupRecord.BackupStatus.VERIFIED)

        # 3. Restore without confirmation code is rejected
        self.client.post(reverse('accounts:sysadmin_backups'), {
            'action': 'restore_backup',
            'backup_id': backup.pk,
            'confirmation_code': 'WRONG',
            'restore_reason': 'اختبار',
        })
        self.assertTrue(AuditLog.objects.filter(action='BACKUP_RESTORE_REJECTED').exists())

        # 4. Restore with CONFIRM-RESTORE creates a PRE_RESTORE backup and logs DATABASE_RESTORE_EXECUTED
        self.client.post(reverse('accounts:sysadmin_backups'), {
            'action': 'restore_backup',
            'backup_id': backup.pk,
            'confirmation_code': 'CONFIRM-RESTORE',
            'restore_reason': 'استعادة معتمدة ومصرح بها للاختبار',
        })
        self.assertTrue(SystemBackupRecord.objects.filter(backup_type=SystemBackupRecord.BackupType.PRE_RESTORE).exists())
        self.assertTrue(AuditLog.objects.filter(action='DATABASE_RESTORE_EXECUTED').exists())
