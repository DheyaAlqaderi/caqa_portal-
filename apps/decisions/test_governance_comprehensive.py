import hashlib
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Notification
from apps.institutions.models import Institution
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus, GrievanceAppeal
from apps.decisions.models import (
    CouncilMeeting,
    CouncilMeetingAttendance,
    CouncilBallot,
    CouncilBallotVoterRecord,
    CouncilSecretVote,
    BoardNomination,
    CouncilPolicy,
    AccreditationDecision,
    AccreditationCertificate,
    SovereignTransaction,
    TransactionMovementHistory,
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GovernanceWorkflowsComprehensiveTests(TestCase):
    """
    Comprehensive verification and audit tests for all 7 Sovereign Governance workflows
    and the Central Sovereign Transaction Engine.
    """

    def setUp(self):
        self.client = Client()

        # Institutions
        self.university = Institution.objects.create(
            name="جامعة صنعاء الحكومية",
            code="UNIV-SNA-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        # Users
        self.minister = User.objects.create_user(
            username="minister_user",
            password="password123",
            role=User.Roles.MINISTER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.prime_minister = User.objects.create_user(
            username="pm_user",
            password="password123",
            role=User.Roles.PRIME_MINISTER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.chairman = User.objects.create_user(
            username="chairman_user",
            password="password123",
            role=User.Roles.COUNCIL_CHAIRMAN,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.sec_gen = User.objects.create_user(
            username="secgen_user",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY_GENERAL,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.legal_director = User.objects.create_user(
            username="legal_user",
            password="password123",
            role=User.Roles.LEGAL_DIRECTOR,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.grievance_member = User.objects.create_user(
            username="grievance_judge",
            password="password123",
            role=User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.board_member_1 = User.objects.create_user(
            username="board_member_1",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.board_member_2 = User.objects.create_user(
            username="board_member_2",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.univ_president = User.objects.create_user(
            username="univ_president_user",
            password="password123",
            role=User.Roles.UNIVERSITY_PRESIDENT,
            institution=self.university,
            approval_status=User.ApprovalStatus.APPROVED
        )

        self.inst_officer = User.objects.create_user(
            username="inst_officer_user",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.university,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # Standard Version & Application
        self.std_ver = StandardVersion.objects.create(
            title="المعايير المؤسسية الوطنية",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="2026.1"
        )

        self.application = AccreditationApplication.objects.create(
            application_number="APP-GOV-2026-100",
            institution=self.university,
            track=AccreditationTrackType.INSTITUTIONAL,
            standard_version=self.std_ver,
            applicant_user=self.inst_officer,
            current_stage=StageChoices.STAGE_6,
            status=ApplicationStatus.IN_COUNCIL_REVIEW
        )

    # -------------------------------------------------------------------------
    # WORKFLOW 1 & 2: Board Nomination Memo & Prime Minister Appointment Decree
    # -------------------------------------------------------------------------
    def test_workflow_1_and_2_board_nomination_and_pm_decree(self):
        """
        Test Workflow 1 & 2:
        - Minister creates board nomination memo -> auto ref, sovereign trx created, PM notified.
        - PM issues appointment decree -> active appointment dates, sovereign trx approved, Minister/Chairman notified.
        """
        self.client.login(username="minister_user", password="password123")

        # 1. Minister creates nomination
        resp = self.client.post(reverse('decisions:minister_nomination_create'), {
            'nominee_name': 'أ.د. حامد محمد القاسمي',
            'academic_rank': 'أستاذ دكتور (بروفيسور)',
            'proposed_position': BoardNomination.ProposedPosition.BOARD_MEMBER_TECH,
            'specialization': 'ضمان الجودة الطبية',
            'current_institution': 'جامعة صنعاء',
            'cv_summary': 'خبرة 20 عاماً في تقييم البرامج الطبية الدولية',
            'minister_notes': 'مرشح ذو كفاءة عالية لشغل عضوية مجلس الإدارة'
        })
        self.assertEqual(resp.status_code, 302)

        nom = BoardNomination.objects.filter(nominee_name='أ.د. حامد محمد القاسمي').first()
        self.assertIsNotNone(nom)
        self.assertTrue(nom.nomination_letter_ref.startswith('NOM-2026-'))
        self.assertEqual(nom.status, BoardNomination.NominationStatus.SUBMITTED_TO_PM)

        # Verify Sovereign Transaction created
        trx = SovereignTransaction.objects.filter(reference_number=nom.nomination_letter_ref).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.transaction_type, SovereignTransaction.TransactionType.NOMINATION_MEMO)
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.SUBMITTED)

        # Verify Prime Minister notification
        pm_notifs = Notification.objects.filter(recipient=self.prime_minister)
        self.assertTrue(pm_notifs.filter(title__contains=nom.nomination_letter_ref).exists())

        # 2. Prime Minister reviews and issues Republican Decree
        self.client.login(username="pm_user", password="password123")
        resp_pm = self.client.post(reverse('decisions:pm_nomination_decree', args=[nom.pk]), {
            'action_type': 'issue_decree',
            'republican_decree_number': 'قرار جمهوري رقم (12) لسنة 2026',
            'decree_date': timezone.now().date().isoformat(),
            'term_years': 4,
            'pm_notes': 'معتمد وموجه بالتعيين ونشره في الجريدة الرسمية'
        })
        self.assertEqual(resp_pm.status_code, 302)

        nom.refresh_from_db()
        self.assertEqual(nom.status, BoardNomination.NominationStatus.DECREE_ISSUED)
        self.assertEqual(nom.republican_decree_number, 'قرار جمهوري رقم (12) لسنة 2026')
        self.assertIsNotNone(nom.appointment_start_date)
        self.assertIsNotNone(nom.appointment_end_date)
        self.assertTrue(nom.is_appointment_active())

        # Verify Sovereign Transaction transitioned to APPROVED
        trx.refresh_from_db()
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.APPROVED)

        # Verify Minister and Chairman received decree notifications
        minister_notifs = Notification.objects.filter(recipient=self.minister)
        self.assertTrue(minister_notifs.filter(title__contains='قرار تعيين جمهوري').exists())

        chairman_notifs = Notification.objects.filter(recipient=self.chairman)
        self.assertTrue(chairman_notifs.filter(title__contains='قرار تعيين جمهوري').exists())

    # -------------------------------------------------------------------------
    # WORKFLOW 3: Council Regulations & Policy Approval (Chairman -> Minister)
    # -------------------------------------------------------------------------
    def test_workflow_3_policy_submission_and_minister_ratification(self):
        """
        Test Workflow 3:
        - Council submits policy/regulation -> Sovereign trx created, Minister notified.
        - Minister ratifies policy -> Ministerial decree recorded, Sovereign trx APPROVED, Chairman notified.
        """
        self.client.login(username="chairman_user", password="password123")

        resp = self.client.post(reverse('decisions:minister_policy_create'), {
            'title': 'اللائحة التنفيذية لمعايير الاعتماد الأكاديمي الوطني',
            'policy_type': CouncilPolicy.PolicyType.EXECUTIVE_REGULATION,
            'version_number': '1.0',
            'council_session_ref': 'محضر مجلس الإدارة رقم 04/2026',
            'summary': 'تنظيم شروط ومعايير الاعتماد المؤسسي والبرامجي وضوابط الزيارات'
        })
        self.assertEqual(resp.status_code, 302)

        policy = CouncilPolicy.objects.filter(title='اللائحة التنفيذية لمعايير الاعتماد الأكاديمي الوطني').first()
        self.assertIsNotNone(policy)
        self.assertEqual(policy.status, CouncilPolicy.RatificationStatus.PENDING_RATIFICATION)

        # Check Sovereign Transaction
        trx = SovereignTransaction.objects.filter(subject__contains=policy.title).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.transaction_type, SovereignTransaction.TransactionType.POLICY_RATIFICATION)

        # Minister notified
        min_notifs = Notification.objects.filter(recipient=self.minister)
        self.assertTrue(min_notifs.filter(title__contains='لائحة/سياسة').exists())

        # Minister ratifies
        self.client.login(username="minister_user", password="password123")
        resp_ratify = self.client.post(reverse('decisions:minister_policy_ratify', args=[policy.pk]), {
            'action_decision': 'RATIFY',
            'ministerial_decree_number': 'قرار وزاري رقم (35) لسنة 2026',
            'ratification_date': timezone.now().date().isoformat(),
            'effective_date': timezone.now().date().isoformat(),
            'minister_directive': 'تعتمد اللائحة ويعمل بها في كافة مؤسسات التعليم العالي'
        })
        self.assertEqual(resp_ratify.status_code, 302)

        policy.refresh_from_db()
        self.assertEqual(policy.status, CouncilPolicy.RatificationStatus.RATIFIED)
        self.assertEqual(policy.ministerial_decree_number, 'قرار وزاري رقم (35) لسنة 2026')

        trx.refresh_from_db()
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.APPROVED)

    # -------------------------------------------------------------------------
    # WORKFLOW 4: Board Meeting Invitations, Agenda, Attendance & Quorum
    # -------------------------------------------------------------------------
    def test_workflow_4_meeting_invitations_and_quorum_calculation(self):
        """
        Test Workflow 4:
        - Meeting created with quorum requirement (e.g. 3 members).
        - Invitations sent -> attendance records created, in-app notifications delivered.
        - Board members RSVP -> Quorum accurately checked.
        """
        meeting = CouncilMeeting.objects.create(
            meeting_number="COUNCIL-2026-M10",
            meeting_type=CouncilMeeting.MeetingType.ORDINARY,
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            meeting_agenda="البت في طلبات الاعتماد المؤسسي للدورة الأولى 2026",
            quorum_required=3
        )
        self.assertFalse(meeting.is_quorum_met())

        self.client.login(username="chairman_user", password="password123")
        resp_inv = self.client.post(reverse('decisions:meeting_send_invitations', args=[meeting.pk]))
        self.assertEqual(resp_inv.status_code, 302)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.INVITATIONS_SENT)

        # Verify attendance records created for board members
        att_1 = CouncilMeetingAttendance.objects.filter(meeting=meeting, member=self.board_member_1).first()
        self.assertIsNotNone(att_1)
        self.assertEqual(att_1.status, CouncilMeetingAttendance.RSVPStatus.INVITED)

        # Board Member 1 confirms attendance
        self.client.login(username="board_member_1", password="password123")
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {'status': 'CONFIRMED'})
        meeting.refresh_from_db()
        self.assertEqual(meeting.confirmed_attendance_count(), 1)
        self.assertFalse(meeting.is_quorum_met())

        # Board Member 2 confirms attendance
        self.client.login(username="board_member_2", password="password123")
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {'status': 'CONFIRMED'})
        meeting.refresh_from_db()
        self.assertEqual(meeting.confirmed_attendance_count(), 2)
        self.assertFalse(meeting.is_quorum_met())

        # Chairman confirms attendance
        self.client.login(username="chairman_user", password="password123")
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {'status': 'CONFIRMED'})
        meeting.refresh_from_db()
        self.assertEqual(meeting.confirmed_attendance_count(), 3)
        # Quorum is now met!
        self.assertTrue(meeting.is_quorum_met())

    # -------------------------------------------------------------------------
    # WORKFLOW 5: Individual Secret Ballot Voting (Quorum Guard & Anonymity)
    # -------------------------------------------------------------------------
    def test_workflow_5_secret_ballot_anonymity_and_tally(self):
        """
        Test Workflow 5:
        - Opening ballot checks quorum.
        - Board members cast secret votes.
        - Double-voting prevented.
        - Voter choice decoupled from voter identity (no voter foreign key on vote record).
        - Ballot closing auto-tallies results.
        """
        meeting = CouncilMeeting.objects.create(
            meeting_number="COUNCIL-2026-M11",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            quorum_required=2
        )
        # Create confirmed attendances to meet quorum
        CouncilMeetingAttendance.objects.create(meeting=meeting, member=self.board_member_1, status='CONFIRMED')
        CouncilMeetingAttendance.objects.create(meeting=meeting, member=self.board_member_2, status='CONFIRMED')
        self.assertTrue(meeting.is_quorum_met())

        self.client.login(username="chairman_user", password="password123")

        # Open ballot session
        resp_open = self.client.post(reverse('decisions:ballot_open', args=[meeting.pk, self.application.pk]))
        self.assertEqual(resp_open.status_code, 302)

        ballot = CouncilBallot.objects.filter(meeting=meeting, application=self.application).first()
        self.assertIsNotNone(ballot)
        self.assertEqual(ballot.status, CouncilBallot.BallotStatus.OPEN)

        # Board member 1 casts vote: FULL
        self.client.login(username="board_member_1", password="password123")
        resp_vote1 = self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL
        })
        self.assertEqual(resp_vote1.status_code, 302)

        # Check voter record exists
        self.assertTrue(CouncilBallotVoterRecord.objects.filter(ballot=ballot, voter=self.board_member_1).exists())

        # Attempt double-voting by Member 1 -> Must be rejected!
        resp_double = self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.DENIED
        })
        self.assertEqual(resp_double.status_code, 302)
        # Total votes should still be 1
        self.assertEqual(CouncilSecretVote.objects.filter(ballot=ballot).count(), 1)

        # Board member 2 casts vote: FULL
        self.client.login(username="board_member_2", password="password123")
        resp_vote2 = self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot.pk]), {
            'vote_choice': CouncilSecretVote.VoteChoice.FULL
        })
        self.assertEqual(resp_vote2.status_code, 302)
        self.assertEqual(CouncilSecretVote.objects.filter(ballot=ballot).count(), 2)

        # Verify anonymity: CouncilSecretVote has NO foreign key to User
        secret_vote = CouncilSecretVote.objects.filter(ballot=ballot).first()
        self.assertFalse(hasattr(secret_vote, 'voter'))
        self.assertFalse(hasattr(secret_vote, 'user'))
        self.assertTrue(len(secret_vote.cast_hash) == 64)  # Valid SHA-256

        # Close ballot & tally
        self.client.login(username="chairman_user", password="password123")
        resp_close = self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot.pk]))
        self.assertEqual(resp_close.status_code, 302)

        ballot.refresh_from_db()
        self.assertEqual(ballot.status, CouncilBallot.BallotStatus.CLOSED)
        self.assertEqual(ballot.votes_full_count, 2)
        self.assertEqual(ballot.votes_conditional_count, 0)
        self.assertEqual(ballot.votes_denied_count, 0)

    # -------------------------------------------------------------------------
    # WORKFLOW 6: Collective Final Accreditation Decision & Certificate Issuance
    # -------------------------------------------------------------------------
    def test_workflow_6_decision_and_certificate_issuance_with_sovereign_sync(self):
        """
        Test Workflow 6:
        - Quorum verified.
        - Decision issued -> AccreditationDecision & AccreditationCertificate with QR generated.
        - SovereignTransaction recorded.
        - University President & Institution Officer notified.
        """
        meeting = CouncilMeeting.objects.create(
            meeting_number="COUNCIL-2026-M12",
            meeting_date=timezone.now().date(),
            chairperson_name="أ.د. رئيس المجلس",
            quorum_required=1
        )
        CouncilMeetingAttendance.objects.create(meeting=meeting, member=self.chairman, status='CONFIRMED')

        self.client.login(username="chairman_user", password="password123")
        resp = self.client.post(reverse('decisions:issue_decision', args=[self.application.pk]), {
            'meeting': meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': '88/2026',
            'validity_years': 5,
            'conditions': 'الالتزام بمعايير الجودة والتحسين المستمر'
        })
        self.assertEqual(resp.status_code, 302)

        decision = AccreditationDecision.objects.filter(application=self.application).first()
        self.assertIsNotNone(decision)
        self.assertEqual(decision.decree_number, '88/2026')

        # Certificate issued
        cert = AccreditationCertificate.objects.filter(decision=decision).first()
        self.assertIsNotNone(cert)
        self.assertIsNotNone(cert.certificate_uuid)

        # Sovereign Transaction created
        trx = SovereignTransaction.objects.filter(reference_number__contains=decision.decree_number).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.transaction_type, SovereignTransaction.TransactionType.ACCREDITATION_DECISION)

        # Notifications delivered to University President
        pres_notifs = Notification.objects.filter(recipient=self.univ_president)
        self.assertTrue(pres_notifs.filter(title__contains='شهادة الاعتماد').exists())

    # -------------------------------------------------------------------------
    # WORKFLOW 7: Final Grievance & Appeal Resolution
    # -------------------------------------------------------------------------
    def test_workflow_7_grievance_submission_examination_and_board_resolution(self):
        """
        Test Workflow 7:
        - Institution submits grievance appeal -> auto ref GRV-2026-XXX, sovereign trx created,
          Independent Grievance Committee, Legal Directorate, and University President notified.
        - Grievance Committee / Legal Directorate records report -> Sovereign trx transitions to UNDER_REVIEW.
        - Board resolves grievance (e.g. ACCEPTED_RECONSIDERATION) -> Sovereign trx transitions to APPROVED,
          University President and Appellant notified.
        """
        self.client.login(username="inst_officer_user", password="password123")

        resp = self.client.post(reverse('accreditation:grievance_create', args=[self.application.pk]), {
            'grounds_of_appeal': 'نطعن في تقييم مؤشر المختبرات العلمية حيث تم استيفاء التجهيزات بالكامل ولم تحتسب.'
        })
        self.assertEqual(resp.status_code, 302)

        grievance = GrievanceAppeal.objects.filter(application=self.application).first()
        self.assertIsNotNone(grievance)
        self.assertTrue(grievance.appeal_number.startswith('GRV-2026-'))
        self.assertEqual(grievance.status, GrievanceAppeal.AppealStatus.SUBMITTED)

        # Sovereign Transaction created
        trx = SovereignTransaction.objects.filter(reference_number=grievance.appeal_number).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.transaction_type, SovereignTransaction.TransactionType.GRIEVANCE_APPEAL)
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.SUBMITTED)

        # Independent Grievance Committee Member notified
        grv_notifs = Notification.objects.filter(recipient=self.grievance_member)
        self.assertTrue(grv_notifs.filter(title__contains=grievance.appeal_number).exists())

        # University President notified of submission
        pres_notifs = Notification.objects.filter(recipient=self.univ_president)
        self.assertTrue(pres_notifs.filter(title__contains=grievance.appeal_number).exists())

        # 2. Grievance Committee member reviews and files report
        self.client.login(username="grievance_judge", password="password123")
        resp_rev = self.client.post(reverse('accreditation:grievance_review', args=[grievance.pk]), {
            'action': 'save_legal_report',
            'committee_report': 'تم فحص الأدلة وتوصي اللجنة بإعادة تقييم المختبرات ميدانياً.'
        })
        self.assertEqual(resp_rev.status_code, 302)

        grievance.refresh_from_db()
        self.assertEqual(grievance.status, GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW)

        trx.refresh_from_db()
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.UNDER_REVIEW)

        # 3. Board issues final resolution
        self.client.login(username="chairman_user", password="password123")
        resp_res = self.client.post(reverse('accreditation:grievance_review', args=[grievance.pk]), {
            'action': 'resolve_board',
            'final_resolution': 'accept',
            'final_resolution_notes': 'بناء على تقرير لجنة التظلمات، تقرر قبول التظلم وإعادة تقييم معيار المختبرات.'
        })
        self.assertEqual(resp_res.status_code, 302)

        grievance.refresh_from_db()
        self.assertEqual(grievance.status, GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION)
        self.assertEqual(grievance.resolved_by, self.chairman)

        trx.refresh_from_db()
        self.assertEqual(trx.status, SovereignTransaction.TransactionStatus.APPROVED)

        # Appellant and University President receive resolution notifications
        inst_notifs = Notification.objects.filter(recipient=self.inst_officer)
        self.assertTrue(inst_notifs.filter(title__contains='قرار البت في التظلم').exists())
