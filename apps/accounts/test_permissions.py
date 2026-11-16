import datetime
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model

from apps.accounts.models import (
    User,
    DynamicPermission,
    RolePermissionAssignment,
    UserPermissionOverride,
    PermissionAuditRecord,
    ScheduledReminderLog,
)
from apps.accounts.permissions import (
    has_permission,
    seed_default_permissions,
    rotate_user_override,
    revoke_user_override,
    redact_sensitive_diagnostics,
    GOVERNANCE_LOCKED_PERMISSIONS,
)
from apps.standards.models import AccreditationTrackType
from apps.institutions.models import Institution, AcademicProgram, College
from apps.accreditation.models import (
    AccreditationApplication,
    ApplicationStatus,
    ReviewTeam,
    ReviewTeamMember,
    ConflictOfInterestDeclaration,
    GrievanceAppeal,
)
from apps.decisions.models import CouncilMeeting, AccreditationDecision


class DynamicPermissionsComprehensiveTests(TestCase):
    """
    Exhaustive Test Suite for Phase 2:
    Covers Groups A through J testing all mandatory governance restrictions,
    precedence rules, tenant isolation, COI clearance, and audit integrity.
    """

    def setUp(self):
        self.factory = RequestFactory()

        # Seed catalog and default assignments
        seed_default_permissions()

        # Create Institutions
        self.inst_a = Institution.objects.create(
            name="جامعة صنعاء الأولى",
            code="UNIV_A",
            institution_type="PUBLIC"
        )
        self.inst_b = Institution.objects.create(
            name="جامعة عدن الثانية",
            code="UNIV_B",
            institution_type="PUBLIC"
        )

        # Create Colleges and Academic Programs
        self.college_a = College.objects.create(
            institution=self.inst_a,
            name="كلية الهندسة والحاسوب"
        )
        self.program_a = AcademicProgram.objects.create(
            college=self.college_a,
            name="هندسة البرمجيات",
            code="SWE-01",
            degree_level="BACHELOR"
        )

        # Create Users for Each Role
        self.admin_user = User.objects.create_user(
            username="sysadmin",
            password="Password123!",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_superuser=True
        )

        self.sec_user = User.objects.create_user(
            username="council_sec",
            password="Password123!",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        self.board_user = User.objects.create_user(
            username="board_member1",
            password="Password123!",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        self.inst_user_a = User.objects.create_user(
            username="officer_a",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.inst_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        self.inst_user_b = User.objects.create_user(
            username="officer_b",
            password="Password123!",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.inst_b,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        self.reviewer_assigned = User.objects.create_user(
            username="reviewer_assigned",
            password="Password123!",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        self.reviewer_unassigned = User.objects.create_user(
            username="reviewer_unassigned",
            password="Password123!",
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=False
        )

        # Create an Application for Institution A
        self.app_a = AccreditationApplication.objects.create(
            institution=self.inst_a,
            program=self.program_a,
            track=AccreditationTrackType.PROGRAMMATIC,
            application_number="APP-TEST-2026-A",
            status=ApplicationStatus.DESK_UNDER_REVIEW,
            applicant_user=self.inst_user_a
        )

        # Create Review Team for Application A
        self.team_a = ReviewTeam.objects.create(
            application=self.app_a,
            decree_number="DEC-TEAM-001",
            formation_date=timezone.now().date(),
            chairperson=self.reviewer_assigned
        )
        ReviewTeamMember.objects.create(
            team=self.team_a,
            user=self.reviewer_assigned,
            role_in_team="CHAIR",
            conflict_of_interest_signed=True
        )

    # --------------------------------------------------------------------------
    # A. ADMIN Governance Restrictions
    # --------------------------------------------------------------------------
    def test_admin_cannot_vote_on_council_decisions(self):
        """ADMIN cannot vote on council decisions even if is_superuser=True."""
        allowed = has_permission(self.admin_user, 'can_record_individual_vote')
        self.assertFalse(allowed)

    def test_admin_cannot_finalize_collective_decision(self):
        """ADMIN cannot finalize collective decisions even if is_superuser=True."""
        allowed = has_permission(self.admin_user, 'can_finalize_collective_decision')
        self.assertFalse(allowed)

    def test_admin_cannot_decide_grievance(self):
        """ADMIN cannot decide grievances."""
        allowed = has_permission(self.admin_user, 'can_decide_grievance')
        self.assertFalse(allowed)

    def test_admin_cannot_conduct_desk_review_by_default(self):
        """ADMIN does not have desk review authority by default."""
        allowed = has_permission(self.admin_user, 'can_conduct_desk_review')
        self.assertFalse(allowed)

    def test_admin_cannot_verify_payment_by_default(self):
        """ADMIN does not have payment verification authority by default."""
        allowed = has_permission(self.admin_user, 'can_verify_payment')
        self.assertFalse(allowed)

    def test_admin_cannot_nominate_reviewers_by_default(self):
        """ADMIN does not have reviewer nomination authority by default."""
        allowed = has_permission(self.admin_user, 'can_nominate_reviewers')
        self.assertFalse(allowed)

    # --------------------------------------------------------------------------
    # B. Technical Diagnostics
    # --------------------------------------------------------------------------
    def test_admin_with_permission_can_view_technical_diagnostics(self):
        """ADMIN with can_view_technical_audit is allowed diagnostic access."""
        allowed = has_permission(self.admin_user, 'can_view_technical_audit')
        self.assertTrue(allowed)

    def test_non_admin_cannot_view_technical_diagnostics(self):
        """Non-admin roles cannot view technical diagnostics."""
        for user in [self.sec_user, self.board_user, self.inst_user_a, self.reviewer_assigned]:
            self.assertFalse(has_permission(user, 'can_view_technical_audit'))

    def test_redact_sensitive_diagnostics_masks_secrets(self):
        """Sensitive keys like password, token, secret are scrubbed server-side."""
        raw_data = {
            'database_password': 'SuperSecretPassword123',
            'api_token': 'abc123token',
            'django_secret_key': 'django-insecure-key',
            'safe_platform': 'Windows 11',
            'nested': {
                'auth_credential': 'private-credential',
                'safe_count': 42
            }
        }
        scrubbed = redact_sensitive_diagnostics(raw_data)
        self.assertIn('REDACTED', scrubbed['database_password'])
        self.assertIn('REDACTED', scrubbed['api_token'])
        self.assertIn('REDACTED', scrubbed['django_secret_key'])
        self.assertEqual(scrubbed['safe_platform'], 'Windows 11')
        self.assertIn('REDACTED', scrubbed['nested']['auth_credential'])
        self.assertEqual(scrubbed['nested']['safe_count'], 42)

    # --------------------------------------------------------------------------
    # C. Secretariat Restrictions
    # --------------------------------------------------------------------------
    def test_secretariat_cannot_vote(self):
        """COUNCIL_SECRETARY cannot vote."""
        self.assertFalse(has_permission(self.sec_user, 'can_record_individual_vote'))

    def test_secretariat_cannot_finalize_decision(self):
        """COUNCIL_SECRETARY cannot finalize collective decisions."""
        self.assertFalse(has_permission(self.sec_user, 'can_finalize_collective_decision'))

    def test_secretariat_cannot_decide_grievance(self):
        """COUNCIL_SECRETARY cannot decide grievances."""
        self.assertFalse(has_permission(self.sec_user, 'can_decide_grievance'))

    def test_secretariat_cannot_submit_application_on_behalf_of_institution(self):
        """COUNCIL_SECRETARY cannot submit applications or edit self-assessments."""
        self.assertFalse(has_permission(self.sec_user, 'can_submit_application'))
        self.assertFalse(has_permission(self.sec_user, 'can_edit_self_study'))

    def test_secretariat_can_perform_authorized_operational_tasks(self):
        """COUNCIL_SECRETARY has authorized desk review, comparison, and scheduling."""
        self.assertTrue(has_permission(self.sec_user, 'can_conduct_desk_review'))
        self.assertTrue(has_permission(self.sec_user, 'can_generate_comparison'))
        self.assertTrue(has_permission(self.sec_user, 'can_schedule_site_visit'))

    # --------------------------------------------------------------------------
    # D. Self-Escalation Protection
    # --------------------------------------------------------------------------
    def test_user_cannot_grant_permission_override_to_themselves(self):
        """Anti-self-escalation: rotate_user_override raises PermissionDenied when user=granted_by."""
        perm = DynamicPermission.objects.get(codename='can_conduct_desk_review')
        with self.assertRaises(PermissionDenied):
            rotate_user_override(
                user=self.admin_user,
                permission=perm,
                override_type=UserPermissionOverride.OverrideType.GRANT,
                reason="Self-grant attempt",
                granted_by=self.admin_user
            )

    def test_user_cannot_modify_own_role_via_has_permission(self):
        """Anti-self-escalation check blocks self modification in workflow context."""
        context = {'target_user': self.admin_user}
        allowed = has_permission(self.admin_user, 'can_manage_permissions', workflow_context=context)
        self.assertFalse(allowed)

    # --------------------------------------------------------------------------
    # E. Tenant Isolation
    # --------------------------------------------------------------------------
    def test_institution_a_officer_can_access_own_application(self):
        """Institution A officer can access Institution A application."""
        self.assertTrue(has_permission(self.inst_user_a, 'can_view_application', resource=self.app_a))

    def test_institution_b_officer_cannot_access_institution_a_application(self):
        """Tenant isolation: Institution B officer is strictly blocked from Institution A application."""
        self.assertFalse(has_permission(self.inst_user_b, 'can_view_application', resource=self.app_a))

    def test_grant_override_cannot_bypass_tenant_isolation(self):
        """Even with an active GRANT override, an officer cannot access another institution's resource."""
        perm = DynamicPermission.objects.get(codename='can_view_application')
        rotate_user_override(
            user=self.inst_user_b,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.GRANT,
            reason="Temporary grant test",
            granted_by=self.admin_user
        )
        # Check that Level 4 tenant check still rejects access to App A
        self.assertFalse(has_permission(self.inst_user_b, 'can_view_application', resource=self.app_a))

    # --------------------------------------------------------------------------
    # F. Reviewer Scope and Conflict of Interest (COI)
    # --------------------------------------------------------------------------
    def test_unassigned_reviewer_cannot_evaluate_application(self):
        """Unassigned reviewer cannot submit evaluation on application A."""
        self.assertFalse(has_permission(self.reviewer_unassigned, 'can_submit_evaluation', resource=self.app_a))

    def test_assigned_reviewer_with_declared_coi_is_blocked(self):
        """Assigned reviewer who acknowledged a conflict of interest is blocked from evaluating."""
        # Create a COI with conflict acknowledged
        ConflictOfInterestDeclaration.objects.create(
            application=self.app_a,
            reviewer=self.reviewer_assigned,
            has_taught_in_institution=True,
            is_conflict_acknowledged=True,
            signature_statement="Conflict acknowledged"
        )
        self.assertFalse(has_permission(self.reviewer_assigned, 'can_submit_evaluation', resource=self.app_a))

    def test_assigned_reviewer_without_coi_can_evaluate(self):
        """Assigned reviewer with clean COI declaration can evaluate."""
        ConflictOfInterestDeclaration.objects.create(
            application=self.app_a,
            reviewer=self.reviewer_assigned,
            has_taught_in_institution=False,
            has_relatives_or_graduates=False,
            has_financial_or_consulting=False,
            is_conflict_acknowledged=False,
            signature_statement="Clean declaration"
        )
        self.assertTrue(has_permission(self.reviewer_assigned, 'can_submit_evaluation', resource=self.app_a))

    def test_grant_override_cannot_bypass_coi_lockout(self):
        """GRANT override cannot bypass COI restrictions."""
        ConflictOfInterestDeclaration.objects.create(
            application=self.app_a,
            reviewer=self.reviewer_assigned,
            is_conflict_acknowledged=True
        )
        # Attempt to grant override
        perm = DynamicPermission.objects.get(codename='can_submit_evaluation')
        rotate_user_override(
            user=self.reviewer_assigned,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.GRANT,
            reason="Override test on COI",
            granted_by=self.admin_user
        )
        self.assertFalse(has_permission(self.reviewer_assigned, 'can_submit_evaluation', resource=self.app_a))

    # --------------------------------------------------------------------------
    # G. Council Governance & Collective Decisions
    # --------------------------------------------------------------------------
    def test_board_member_can_vote(self):
        """BOARD_MEMBER role has can_record_individual_vote."""
        self.assertTrue(has_permission(self.board_user, 'can_record_individual_vote'))

    def test_single_board_member_cannot_finalize_decision_without_meeting(self):
        """Finalizing collective decision requires valid meeting context."""
        self.assertFalse(has_permission(self.board_user, 'can_finalize_collective_decision', workflow_context={}))

    def test_board_member_can_finalize_with_meeting_context(self):
        """With meeting context, authorized board member can finalize."""
        meeting = CouncilMeeting.objects.create(
            meeting_number="MTG-2026-001",
            meeting_date=timezone.now().date(),
            location="قاعة المجلس الرئيسية",
            chairperson_name="د. رئيس المجلس",
            meeting_agenda="مداولة قرارات الاعتماد الأكاديمي",
            minutes_summary="محضر الجلسة الرسمية"
        )
        context = {'meeting': meeting}
        self.assertTrue(has_permission(self.board_user, 'can_finalize_collective_decision', workflow_context=context))

    # --------------------------------------------------------------------------
    # H. Override Precedence & Historical Archiving
    # --------------------------------------------------------------------------
    def test_active_revoke_override_overrides_role_grant(self):
        """Active REVOKE blocks permission even though BOARD_MEMBER role has it."""
        perm = DynamicPermission.objects.get(codename='can_approve_review_team')
        self.assertTrue(has_permission(self.board_user, 'can_approve_review_team'))

        # Add REVOKE override
        rotate_user_override(
            user=self.board_user,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.REVOKE,
            reason="Temporary administrative suspension",
            granted_by=self.admin_user
        )
        self.assertFalse(has_permission(self.board_user, 'can_approve_review_team'))

    def test_expired_grant_override_does_not_grant_access(self):
        """Expired GRANT override is treated as inactive."""
        perm = DynamicPermission.objects.get(codename='can_conduct_desk_review')
        past_time = timezone.now() - datetime.timedelta(days=2)

        rotate_user_override(
            user=self.inst_user_a,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.GRANT,
            reason="Expired grant test",
            granted_by=self.admin_user,
            expires_at=past_time
        )
        # Should be denied because override is expired and role does not have it
        self.assertFalse(has_permission(self.inst_user_a, 'can_conduct_desk_review'))

    def test_new_override_archives_previous_active_override(self):
        """Creating a new override archives previous active override without deleting."""
        perm = DynamicPermission.objects.get(codename='can_view_finance')

        # First override
        ov1 = rotate_user_override(
            user=self.reviewer_assigned,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.GRANT,
            reason="First grant",
            granted_by=self.admin_user
        )
        self.assertTrue(ov1.is_active)

        # Second override (rotates first)
        ov2 = rotate_user_override(
            user=self.reviewer_assigned,
            permission=perm,
            override_type=UserPermissionOverride.OverrideType.REVOKE,
            reason="Replaced with revoke",
            granted_by=self.admin_user
        )

        ov1.refresh_from_db()
        self.assertFalse(ov1.is_active)
        self.assertIsNotNone(ov1.revoked_at)
        self.assertEqual(ov1.revoked_by, self.admin_user)

        self.assertTrue(ov2.is_active)
        self.assertEqual(UserPermissionOverride.objects.filter(user=self.reviewer_assigned, permission=perm).count(), 2)

    # --------------------------------------------------------------------------
    # I. Audit Integrity
    # --------------------------------------------------------------------------
    def test_permission_audit_record_cannot_be_modified(self):
        """Attempt to modify an existing PermissionAuditRecord raises PermissionDenied."""
        record = PermissionAuditRecord.objects.create(
            actor=self.admin_user,
            action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
            permission_codename='can_view_application',
            reason="Initial test"
        )
        record.reason = "Tampered reason"
        with self.assertRaises(PermissionDenied):
            record.save()

    def test_permission_audit_record_cannot_be_deleted(self):
        """Attempt to delete a PermissionAuditRecord raises PermissionDenied."""
        record = PermissionAuditRecord.objects.create(
            actor=self.admin_user,
            action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
            permission_codename='can_view_application',
            reason="Deletion test"
        )
        with self.assertRaises(PermissionDenied):
            record.delete()

    def test_permission_audit_record_bulk_update_blocked(self):
        """Bulk update on PermissionAuditRecord queryset raises PermissionDenied."""
        PermissionAuditRecord.objects.create(
            actor=self.admin_user,
            action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
            permission_codename='can_view_application',
            reason="Bulk update test"
        )
        with self.assertRaises(PermissionDenied):
            PermissionAuditRecord.objects.filter(permission_codename='can_view_application').update(reason="Tampered bulk")

    def test_permission_audit_record_bulk_delete_blocked(self):
        """Bulk delete on PermissionAuditRecord queryset raises PermissionDenied."""
        PermissionAuditRecord.objects.create(
            actor=self.admin_user,
            action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
            permission_codename='can_view_application',
            reason="Bulk delete test"
        )
        with self.assertRaises(PermissionDenied):
            PermissionAuditRecord.objects.filter(permission_codename='can_view_application').delete()

    def test_governance_gate_blocks_create_audit_record(self):
        """Attempt to bypass governance gate creates a SECURITY_GATE_BLOCKED audit record."""
        initial_count = PermissionAuditRecord.objects.filter(
            action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED
        ).count()

        # Admin tries to finalize collective decision
        has_permission(self.admin_user, 'can_finalize_collective_decision')

        new_count = PermissionAuditRecord.objects.filter(
            action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED
        ).count()
        self.assertEqual(new_count, initial_count + 1)

    # --------------------------------------------------------------------------
    # J. Backward Compatibility
    # --------------------------------------------------------------------------
    def test_existing_role_helpers_remain_functional(self):
        """User helper properties (is_council, is_board, is_institution_rep, is_reviewer) continue working."""
        self.assertTrue(self.sec_user.is_council)
        self.assertTrue(self.admin_user.is_council)
        self.assertTrue(self.board_user.is_board)
        self.assertTrue(self.admin_user.is_board)
        self.assertTrue(self.inst_user_a.is_institution_rep)
        self.assertTrue(self.reviewer_assigned.is_reviewer)
        self.assertTrue(self.inst_user_a.is_approved)

    def test_permission_seeding_is_idempotent(self):
        """Running seed_default_permissions multiple times does not duplicate or overwrite entries."""
        initial_perms = DynamicPermission.objects.count()
        initial_assignments = RolePermissionAssignment.objects.count()

        res = seed_default_permissions()
        self.assertEqual(res['permissions_created'], 0)
        self.assertEqual(res['assignments_created'], 0)
        self.assertEqual(DynamicPermission.objects.count(), initial_perms)
        self.assertEqual(RolePermissionAssignment.objects.count(), initial_assignments)
