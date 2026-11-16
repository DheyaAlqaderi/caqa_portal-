from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User, Notification, AuditLog
from apps.institutions.models import Institution, College, AcademicProgram
from apps.standards.models import StandardVersion, StandardCategory, StandardIndicator, AccreditationTrackType
from apps.accreditation.models import (
    AccreditationApplication,
    ApplicationStatus,
    StageChoices,
    SelfStudyReport,
    SelfStudyIndicatorResponse,
    EvidenceDocument,
    DeskReviewEvaluation,
    ReviewTeam,
    ReviewTeamMember,
    IndicatorEvaluationScore,
    ExternalReviewReport,
    SecretariatAssessmentComparisonReport,
    GrievanceAppeal,
)
from apps.site_visits.models import SiteVisitSchedule, FacilityInspection, StakeholderInterview
from apps.decisions.models import (
    CouncilMeeting,
    CouncilMeetingAttendance,
    CouncilAgendaItem,
    CouncilMeetingAttachment,
    CouncilAgendaDiscussion,
    CouncilBallot,
    CouncilBallotVoterRecord,
    CouncilSecretVote,
    CouncilPublicVote,
    CouncilMeetingMinutes,
    CouncilMeetingMinutesVersion,
    CouncilResolution,
    CouncilPolicy,
    AccreditationDecision,
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CouncilMeetingVotingDecisionE2ETest(TestCase):
    """
    Comprehensive End-to-End Automated Test Suite verifying all 25 statutory steps
    and failure scenarios for the Council Meeting, Voting, and Decision Management System
    per Article 6 of Republican Decree No. (210) of 2009.
    """

    def setUp(self):
        self.client = Client()

        # 1. Create Council Leadership, Voting Board Members, Secretary, Expert, Guest, and Unauthorized Users
        self.chairman = User.objects.create_user(
            username='chair_test', password='Password123!',
            first_name='أحمد', last_name='الحبوبي',
            role=User.Roles.COUNCIL_CHAIRMAN,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.vice_chair = User.objects.create_user(
            username='vice_test', password='Password123!',
            first_name='سالم', last_name='النائب',
            role=User.Roles.COUNCIL_VICE_CHAIRMAN,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.sec_gen = User.objects.create_user(
            username='secgen_test', password='Password123!',
            first_name='محمد', last_name='الأمين',
            role=User.Roles.COUNCIL_SECRETARY_GENERAL,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.meeting_sec = User.objects.create_user(
            username='secretary_test', password='Password123!',
            first_name='خالد', last_name='أمين السر',
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )

        # Create 5 additional Board Members (total 7 voting members: Chairman + Vice + 5 Board Members)
        self.board_members = []
        for i in range(1, 6):
            bm = User.objects.create_user(
                username=f'bm_test_{i}', password='Password123!',
                first_name=f'عضو {i}', last_name='مجلس الإدارة',
                role=User.Roles.BOARD_MEMBER,
                approval_status=User.ApprovalStatus.APPROVED, is_active=True
            )
            self.board_members.append(bm)

        # Invited Expert (External Reviewer role) & Technical Admin & Minister
        self.expert_user = User.objects.create_user(
            username='expert_test', password='Password123!',
            first_name='خبير', last_name='أكاديمي',
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.tech_admin = User.objects.create_user(
            username='tech_admin_test', password='Password123!',
            first_name='مهندس', last_name='النظام',
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.minister = User.objects.create_user(
            username='minister_test', password='Password123!',
            first_name='معالي', last_name='الوزير',
            role=User.Roles.MINISTER,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )

        # 2. Create Institution, College, Program, Standards, and Complete 17-Part Accreditation Dossier
        self.institution = Institution.objects.create(
            name='جامعة الاختبار الوطنية',
            code='UNI-TEST-2026',
            institution_type='PUBLIC_UNIVERSITY',
            governorate='أمانة العاصمة - صنعاء',
            decree_number='قرار جمهوري رقم (15) لسنة 2010',
            official_email='info@unitest.edu.ye',
            official_phone='01234567',
            president_name='أ.د. رئيس الجامعة'
        )
        self.college = College.objects.create(
            institution=self.institution,
            name='كلية الطب والعلوم الصحية'
        )
        self.program = AcademicProgram.objects.create(
            college=self.college,
            name='بكالوريوس الطب البشري والجراحة',
            degree_level='BACHELOR'
        )
        self.inst_officer = User.objects.create_user(
            username='inst_officer_test', password='Password123!',
            first_name='مسؤول', last_name='الجودة',
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.institution,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )
        self.uni_president = User.objects.create_user(
            username='uni_pres_test', password='Password123!',
            first_name='رئيس', last_name='الجامعة',
            role=User.Roles.UNIVERSITY_PRESIDENT,
            institution=self.institution,
            approval_status=User.ApprovalStatus.APPROVED, is_active=True
        )

        self.std_version = StandardVersion.objects.create(
            title='معايير الاعتماد البرامجي الطبي الوطنية',
            version_number='2.0',
            track=AccreditationTrackType.MEDICAL_PROGRAMMATIC,
            issue_date=timezone.now().date(),
            status=StandardVersion.VersionStatus.ACTIVE
        )
        self.std_cat = StandardCategory.objects.create(
            version=self.std_version,
            track=AccreditationTrackType.MEDICAL_PROGRAMMATIC,
            code='STD-TEST-1',
            title='الرسالة والأهداف والحوكمة',
            weight_percentage=25,
            order=1
        )
        self.indicator = StandardIndicator.objects.create(
            category=self.std_cat,
            code='IND-1.1',
            title='وضوح رسالة البرنامج الطبي واعتمادها',
            explanation='توفر رسالة واضحة ومعتمدة.',
            is_core_standard=True,
            order=1
        )

        # Create Application & all 17 Dossier components
        self.app = AccreditationApplication.objects.create(
            application_number='APP-2026-9001',
            track=AccreditationTrackType.MEDICAL_PROGRAMMATIC,
            institution=self.institution,
            program=self.program,
            applicant_user=self.inst_officer,
            standard_version=self.std_version,
            current_stage=StageChoices.STAGE_6,
            status=ApplicationStatus.IN_COUNCIL_REVIEW,
            president_endorsed=True,
            president_endorsed_by=self.uni_president,
            president_decree_ref='PRES-2026-101'
        )
        self.ssr = SelfStudyReport.objects.create(
            application=self.app,
            executive_summary='ملخص الدراسة الذاتية الشاملة للبرنامج الطبي.',
            internal_committee_names='أ.د. عميد الكلية، د. رئيس قسم الجودة',
            strengths_overview='بنية تحتية ومعامل سريرية متكاملة.',
            is_locked=True
        )
        SelfStudyIndicatorResponse.objects.create(
            report=self.ssr,
            indicator=self.indicator,
            compliance_level='MET',
            justification='تم اعتماد الرسالة في مجلس الجامعة.'
        )
        EvidenceDocument.objects.create(
            application=self.app,
            indicator=self.indicator,
            code='EV-1.1',
            title='قرار مجلس الجامعة باعتماد الرسالة',
            sha256_hash='a' * 64
        )
        DeskReviewEvaluation.objects.create(
            application=self.app,
            reviewer=self.sec_gen,
            decision='ACCEPTED',
            completeness_percentage=100,
            technical_remarks='ملف مستوفٍ لكافة المتطلبات الشكلية والعلمية.',
            is_completed=True
        )
        self.visit = SiteVisitSchedule.objects.create(
            application=self.app,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            visit_location='الحرم الطبي بصنعاء',
            agenda_details='معاينة المعامل والمستشفى التعليمي',
            status='COMPLETED',
            final_exit_meeting_notes='أشاد الفريق بالتجهيزات الميدانية.'
        )
        FacilityInspection.objects.create(
            visit=self.visit,
            category='LABS',
            facility_name='معمل التشريح السريري',
            inspector=self.expert_user,
            adequacy_rating='EXCELLENT',
            detailed_observations='مجهز بالكامل.'
        )
        StakeholderInterview.objects.create(
            visit=self.visit,
            target_group='FACULTY',
            conducted_by=self.expert_user,
            attendees_count=18,
            interview_date=timezone.now(),
            key_themes_discussed='تطوير المناهج السريرية',
            feedback_summary='ارتياح عالٍ من الكادر الأكاديمي.'
        )
        self.review_team = ReviewTeam.objects.create(
            application=self.app,
            decree_number='DEC-PANEL-77',
            formation_date=timezone.now().date(),
            chairperson=self.expert_user
        )
        ReviewTeamMember.objects.create(
            team=self.review_team,
            user=self.expert_user,
            role_in_team='CHAIRPERSON',
            conflict_of_interest_signed=True
        )
        IndicatorEvaluationScore.objects.create(
            application=self.app,
            indicator=self.indicator,
            evaluator=self.expert_user,
            score_level='FULLY_MET',
            strengths='تطبيق معياري ممتاز.'
        )
        ExternalReviewReport.objects.create(
            application=self.app,
            draft_executive_summary='مسودة التقرير الخارجي للبرنامج الطبي.',
            draft_findings_per_standard='جميع المعايير مستوفاة.',
            institution_reply_text='نشكر اللجنة ونؤكد التزامنا بالتحسين المستمر.',
            team_response_to_reply='تم أخذ رد المؤسسة بعين الاعتبار.',
            final_report_text='التقرير النهائي المعتمد: يوصي الفريق بمنح الاعتماد الكامل.',
            final_recommendation='FULL_ACCREDITATION'
        )
        SecretariatAssessmentComparisonReport.objects.create(
            application=self.app,
            generated_by=self.sec_gen,
            title='تقرير المقارنة التحليلي بين الدراسة الذاتية والتقييم الخارجي',
            secretariat_analytical_summary='تطابق بنسبة 96% بين التقييم الذاتي والخارجي.'
        )

    def test_complete_25_step_council_meeting_voting_minutes_and_decisions_workflow(self):
        """
        Tests the entire lifecycle from meeting creation, all 12 agenda item categories,
        17-part dossier inspection, invitations, RSVP, Article 6 quorum calculation,
        quorum loss on member withdrawal, discussions & reservations, public & secret voting,
        tie-breaking by Chairperson, vote immutability, minutes versioning & approval lock,
        and resolutions/assignments/decisions.
        """
        # STEP 1: Create Council Meeting (Secretary General)
        self.client.force_login(self.sec_gen)
        resp = self.client.post(reverse('decisions:meeting_create'), {
            'meeting_number': 'جلسة مجلس الإدارة رقم (10) لسنة 2026',
            'meeting_type': CouncilMeeting.MeetingType.ORDINARY,
            'meeting_date': '2026-11-15',
            'meeting_time': '09:00',
            'end_time': '13:00',
            'location': 'القاعة الكبرى بمقر المجلس - صنعاء',
            'meeting_link': 'https://meet.caqa.gov.ye/session-10',
            'chairperson_name': self.chairman.get_full_name(),
            'chairperson_user_id': self.chairman.pk,
            'secretary_name': self.meeting_sec.get_full_name(),
            'secretary_user_id': self.meeting_sec.pk,
            'meeting_agenda': 'جدول أعمال الجلسة العاشرة لمجلس الإدارة',
            'quorum_required': 4,
            'use_dynamic_quorum': '1',
            'status': CouncilMeeting.MeetingStatus.UNDER_PREPARATION,
        })
        self.assertEqual(resp.status_code, 302)
        meeting = CouncilMeeting.objects.get(meeting_number='جلسة مجلس الإدارة رقم (10) لسنة 2026')
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.UNDER_PREPARATION)
        self.assertTrue(meeting.use_dynamic_quorum)

        # STEP 2: Add Agenda Items covering all 12 statutory categories
        all_categories = [c[0] for c in CouncilAgendaItem.ItemCategory.choices]
        self.assertEqual(len(all_categories), 12)

        # Item 1: Program Accreditation linked to our 17-Part Application
        resp = self.client.post(reverse('decisions:agenda_item_create', args=[meeting.pk]), {
            'position': 1,
            'item_number': 'البند (1)',
            'title': 'اعتماد برنامج الطب البشري - جامعة الاختبار الوطنية',
            'item_category': CouncilAgendaItem.ItemCategory.PROGRAM_ACCREDITATION,
            'referring_entity': 'الإدارة العامة للاعتماد',
            'presenter_name': self.sec_gen.get_full_name(),
            'description': 'عرض التقرير النهائي لفريق المراجعة الخارجية لبرنامج الطب البشري.',
            'justification': 'استيفاء جميع مراحل التقييم الـ 5.',
            'initial_recommendation': 'منح الاعتماد البرامجي الكامل لمدة 5 سنوات.',
            'required_action': CouncilAgendaItem.RequiredAction.APPROVAL,
            'application_id': self.app.pk,
            # Mark board_member_5 as having a Conflict of Interest on this item
            'conflict_of_interest_members': [self.board_members[4].pk],
        })
        self.assertEqual(resp.status_code, 302)
        item_accred = CouncilAgendaItem.objects.get(meeting=meeting, position=1)

        # Add remaining 11 categories to verify support for all 12 statutory categories
        for idx, cat_code in enumerate(all_categories, start=2):
            if cat_code == CouncilAgendaItem.ItemCategory.PROGRAM_ACCREDITATION:
                continue
            CouncilAgendaItem.objects.create(
                meeting=meeting,
                position=idx,
                item_number=f'البند ({idx})',
                title=f'موضوع تجريبي للفئة {cat_code}',
                item_category=cat_code,
                description=f'تفاصيل البند من الفئة {cat_code}',
                required_action=CouncilAgendaItem.RequiredAction.RECOMMENDATION if idx == 5 else CouncilAgendaItem.RequiredAction.ASSIGNMENT
            )
        self.assertEqual(meeting.agenda_items.count(), 12)

        # STEP 3: Upload Confidential & Non-Confidential Supporting Attachments
        conf_file = SimpleUploadedFile('confidential_report.pdf', b'%PDF-1.4 confidential content')
        pub_file = SimpleUploadedFile('public_agenda.pdf', b'%PDF-1.4 public content')
        self.client.post(reverse('decisions:meeting_upload_attachment', args=[meeting.pk]), {
            'title': 'مذكرة سرية خاصة بأعضاء المجلس',
            'document_type': 'CONFIDENTIAL_BRIEF',
            'agenda_item_id': item_accred.pk,
            'is_confidential': '1',
            'file': conf_file,
        })
        self.client.post(reverse('decisions:meeting_upload_attachment', args=[meeting.pk]), {
            'title': 'مرفق عام للبند الأول',
            'document_type': 'SUPPORTING_DOCUMENT',
            'agenda_item_id': item_accred.pk,
            'is_confidential': '0',
            'file': pub_file,
        })
        self.assertEqual(meeting.attachments.count(), 2)

        # STEP 4: Send Invitations to Council Members & Invite an Expert (Article 6)
        resp = self.client.post(reverse('decisions:meeting_send_invitations', args=[meeting.pk]))
        self.assertEqual(resp.status_code, 302)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.INVITATIONS_SENT)
        # 7 active voting members invited
        voting_attendances = meeting.attendances.filter(attendee_category='VOTING_MEMBER')
        self.assertEqual(voting_attendances.count(), 7)
        for att in voting_attendances:
            self.assertEqual(att.sent_by, self.sec_gen)
            self.assertIsNotNone(att.invitation_sent_at)

        # Invite Expert without voting rights (Article 6) authorized on item_accred
        self.client.post(reverse('decisions:meeting_add_participant', args=[meeting.pk]), {
            'user_id': self.expert_user.pk,
            'attendee_category': CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT,
            'participation_mode': CouncilMeetingAttendance.ParticipationMode.ONLINE,
            'status': CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            'agenda_item_id': item_accred.pk,
            'remarks': 'خبير مدعو لعرض التقرير الفني دون حق تصويت'
        })
        self.assertEqual(meeting.active_voting_members_count(), 7)
        # Majority of 7 voting members is (7 // 2) + 1 = 4
        self.assertEqual(meeting.effective_quorum_required(), 4)
        # Even though the expert is CONFIRMED, confirmed_attendance_count() only counts VOTING_MEMBERs!
        self.assertEqual(meeting.confirmed_attendance_count(), 0)
        self.assertFalse(meeting.is_quorum_met())

        # STEP 5: Verify Quorum Enforcement — Attempting to open a ballot before quorum is met MUST FAIL
        self.client.force_login(self.chairman)
        resp = self.client.post(reverse('decisions:agenda_item_ballot_open', args=[item_accred.pk]), {
            'voting_mode': 'SECRET'
        })
        self.assertEqual(CouncilBallot.objects.filter(meeting=meeting).count(), 0)

        # STEP 6: Record Member Confirmations & Apologies (RSVP) and Verify Read Status
        # 3 members confirm, 1 apologizes -> still 3/4 (quorum not met yet)
        for member in [self.chairman, self.vice_chair, self.board_members[0]]:
            self.client.force_login(member)
            # Opening meeting_detail marks invitation_read=True
            detail_resp = self.client.get(reverse('decisions:meeting_detail', args=[meeting.pk]))
            self.assertEqual(detail_resp.status_code, 200)
            att_rec = CouncilMeetingAttendance.objects.get(meeting=meeting, member=member)
            self.assertTrue(att_rec.invitation_read)

            self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {
                'status': 'CONFIRMED',
                'participation_mode': 'IN_PERSON',
                'remarks': 'حاضر إن شاء الله'
            })

        # Member 2 apologizes
        self.client.force_login(self.board_members[1])
        self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {
            'status': 'APOLOGIZED',
            'remarks': 'مهمة علمية خارجية'
        })
        self.assertEqual(meeting.confirmed_attendance_count(), 3)
        self.assertFalse(meeting.is_quorum_met())

        # Member 3 & Member 5 confirm -> Now 5 voting members confirmed >= 4 required -> Quorum Met!
        for member in [self.board_members[2], self.board_members[4]]:
            self.client.force_login(member)
            self.client.post(reverse('decisions:meeting_rsvp', args=[meeting.pk]), {
                'status': 'CONFIRMED',
                'participation_mode': 'ONLINE'
            })
        self.assertEqual(meeting.confirmed_attendance_count(), 5)
        self.assertTrue(meeting.is_quorum_met())

        # STEP 7: Inspect Complete 17-Part Dossier & Verify Access Control / Confidential Protection
        self.client.force_login(self.board_members[0])
        dossier_resp = self.client.get(reverse('decisions:agenda_item_detail', args=[item_accred.pk]))
        self.assertEqual(dossier_resp.status_code, 200)
        dossier_ctx = dossier_resp.context['dossier']
        # Verify all 17 parts exist in the dossier context
        for part_num in range(1, 18):
            matching_keys = [k for k in dossier_ctx.keys() if k.startswith(f'part_{part_num}_')]
            self.assertTrue(len(matching_keys) >= 1, f"Missing part_{part_num} in 17-part dossier")
        # Board member sees both confidential and public attachments (2)
        self.assertEqual(dossier_resp.context['attachments'].count(), 2)

        # Invited Expert sees the authorized item dossier, but confidential attachment is hidden (only 1 visible)!
        self.client.force_login(self.expert_user)
        expert_dossier_resp = self.client.get(reverse('decisions:agenda_item_detail', args=[item_accred.pk]))
        self.assertEqual(expert_dossier_resp.status_code, 200)
        self.assertEqual(expert_dossier_resp.context['attachments'].count(), 1)

        # Unauthorized Institution Officer is strictly denied access to Council meeting & agenda dossier
        self.client.force_login(self.inst_officer)
        unauth_meeting = self.client.get(reverse('decisions:meeting_detail', args=[meeting.pk]))
        self.assertEqual(unauth_meeting.status_code, 302)
        unauth_dossier = self.client.get(reverse('decisions:agenda_item_detail', args=[item_accred.pk]))
        self.assertEqual(unauth_dossier.status_code, 302)

        # STEP 8: Open Discussions, Record Interventions, Questions, Responses, and Formal Reservations
        self.client.force_login(self.sec_gen)
        self.client.post(reverse('decisions:agenda_item_add_discussion', args=[item_accred.pk]), {
            'intervention_type': CouncilAgendaDiscussion.InterventionType.PRESENTATION,
            'content': 'تم استعراض نتائج الفحص المكتبي والزيارة الميدانية وتقرير المقارنة.',
        })
        self.client.force_login(self.board_members[0])
        self.client.post(reverse('decisions:agenda_item_add_discussion', args=[item_accred.pk]), {
            'intervention_type': CouncilAgendaDiscussion.InterventionType.QUESTION,
            'content': 'ما مدى استيفاء نسبة أعضاء هيئة التدريس إلى الطلاب في المرحلة السريرية؟',
        })
        self.client.force_login(self.vice_chair)
        self.client.post(reverse('decisions:agenda_item_add_discussion', args=[item_accred.pk]), {
            'intervention_type': CouncilAgendaDiscussion.InterventionType.RESERVATION,
            'content': 'أطلب إثبات تحفظي في المحضر بضرورة متابعة تحديث معمل المحاكاة السريرية بعد سنة.',
        })
        item_accred.refresh_from_db()
        self.assertEqual(item_accred.status, CouncilAgendaItem.ItemStatus.UNDER_DISCUSSION)
        self.assertEqual(item_accred.discussions.count(), 3)
        self.assertEqual(item_accred.discussions.filter(intervention_type='RESERVATION').count(), 1)

        # STEP 9: Open Secret Ballot on Item 1 (with Quorum Met)
        self.client.force_login(self.chairman)
        resp = self.client.post(reverse('decisions:agenda_item_ballot_open', args=[item_accred.pk]), {
            'voting_mode': CouncilBallot.VotingMode.SECRET,
            'proposed_decision_text': 'منح الاعتماد الكامل لبرنامج الطب البشري لمدة 5 سنوات'
        })
        self.assertEqual(resp.status_code, 302)
        ballot_secret = CouncilBallot.objects.get(agenda_item=item_accred)
        self.assertEqual(ballot_secret.status, CouncilBallot.BallotStatus.OPEN)

        # STEP 10: Verify Voting Prohibitions:
        # 10a. Invited Expert CANNOT vote (Article 6)
        self.client.force_login(self.expert_user)
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'FULL'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 0)

        # 10b. Technical Admin (not a Board Member) CANNOT vote
        self.client.force_login(self.tech_admin)
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'FULL'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 0)

        # 10c. Apologized/Absent Board Member (board_members[1]) CANNOT vote
        self.client.force_login(self.board_members[1])
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'FULL'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 0)

        # 10d. Conflicted Board Member (board_members[4]) CANNOT vote
        self.client.force_login(self.board_members[4])
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'FULL'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 0)

        # STEP 11: Test Quorum Loss During Session (Member Withdraws -> Quorum Drops to 3/4 -> Voting Blocked!)
        self.client.force_login(self.meeting_sec)
        att_bm2 = CouncilMeetingAttendance.objects.get(meeting=meeting, member=self.board_members[2])
        att_bm4 = CouncilMeetingAttendance.objects.get(meeting=meeting, member=self.board_members[4])
        self.client.post(reverse('decisions:meeting_record_attendance', args=[meeting.pk]), {
            'attendance_id': att_bm2.pk,
            'status': 'ATTENDED',
            'is_currently_present': '0',  # Withdrawn
            'departure_time': '10:30'
        })
        self.client.post(reverse('decisions:meeting_record_attendance', args=[meeting.pk]), {
            'attendance_id': att_bm4.pk,
            'status': 'ATTENDED',
            'is_currently_present': '0',  # Withdrawn
            'departure_time': '10:35'
        })
        self.assertFalse(meeting.is_quorum_met())

        # Chairman attempts to vote while quorum is lost -> Blocked!
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'FULL'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 0)

        # Restore quorum: board_members[2] and board_members[3] are present (now 5 present >= 4 required)
        self.client.force_login(self.meeting_sec)
        self.client.post(reverse('decisions:meeting_record_attendance', args=[meeting.pk]), {
            'attendance_id': att_bm2.pk,
            'status': 'ATTENDED',
            'is_currently_present': '1'
        })
        att_bm3 = CouncilMeetingAttendance.objects.get(meeting=meeting, member=self.board_members[3])
        self.client.post(reverse('decisions:meeting_record_attendance', args=[meeting.pk]), {
            'attendance_id': att_bm3.pk,
            'status': 'ATTENDED',
            'is_currently_present': '1'
        })
        self.assertTrue(meeting.is_quorum_met())

        # STEP 12: Cast Secret Votes & Verify Duplicate Prevention and Vote Immutability
        # Chairman, Vice Chair, BM0 vote FULL; BM2 votes DENIED; BM3 votes ABSTAIN with justification
        for voter in [self.chairman, self.vice_chair, self.board_members[0]]:
            self.client.force_login(voter)
            self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
                'vote_choice': 'FULL'
            })

        # Duplicate vote attempt by Chairman -> Rejected!
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'DENIED'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 3)

        self.client.force_login(self.board_members[2])
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'DENIED'
        })
        self.client.force_login(self.board_members[3])
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_secret.pk]), {
            'vote_choice': 'ABSTAIN',
            'abstain_justification': 'الحاجة لمزيد من البيانات المالية'
        })
        self.assertEqual(ballot_secret.total_votes_cast(), 5)

        # Verify Vote Immutability: even a superuser/admin cannot modify a submitted secret vote!
        secret_vote_obj = ballot_secret.secret_votes.first()
        secret_vote_obj.vote_choice = 'DENIED'
        with self.assertRaises(PermissionDenied):
            secret_vote_obj.save()

        # STEP 13: Close Secret Ballot and Verify Majority Calculation
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot_secret.pk]))
        ballot_secret.refresh_from_db()
        self.assertEqual(ballot_secret.status, CouncilBallot.BallotStatus.CLOSED)
        self.assertEqual(ballot_secret.votes_approve_count, 3)
        self.assertEqual(ballot_secret.votes_reject_count, 1)
        self.assertEqual(ballot_secret.votes_abstain_count, 1)
        self.assertTrue(ballot_secret.majority_achieved)
        self.assertEqual(ballot_secret.final_result, 'APPROVED')

        # STEP 14: Test Public Voting & Article 6 Chairperson Tie-Breaking Rule ("وعند التساوي يرجح الجانب الذي منه رئيس المجلس")
        item_2 = meeting.agenda_items.filter(position=2).first()
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:agenda_item_ballot_open', args=[item_2.pk]), {
            'voting_mode': CouncilBallot.VotingMode.PUBLIC,
            'proposed_decision_text': 'إقرار اللائحة التنظيمية الداخلية'
        })
        ballot_public = CouncilBallot.objects.get(agenda_item=item_2)

        # Create a 2 vs 2 tie (plus 1 abstain):
        # Chairman + Vice Chair vote APPROVE (2); BM0 + BM2 vote REJECT (2); BM3 votes ABSTAIN (1)
        for voter in [self.chairman, self.vice_chair]:
            self.client.force_login(voter)
            self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_public.pk]), {
                'vote_choice': 'APPROVE'
            })
        for voter in [self.board_members[0], self.board_members[2]]:
            self.client.force_login(voter)
            self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_public.pk]), {
                'vote_choice': 'REJECT'
            })
        self.client.force_login(self.board_members[3])
        self.client.post(reverse('decisions:ballot_cast_vote', args=[ballot_public.pk]), {
            'vote_choice': 'ABSTAIN',
            'abstain_justification': 'محايد'
        })

        # Verify Public Vote Immutability
        pub_vote_obj = ballot_public.public_votes.first()
        pub_vote_obj.vote_choice = 'REJECT'
        with self.assertRaises(PermissionDenied):
            pub_vote_obj.save()

        # Close public ballot -> Since Chairman voted APPROVE in PUBLIC mode, Article 6 automatically breaks the tie in favor of APPROVE!
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:ballot_close_and_tally', args=[ballot_public.pk]))
        ballot_public.refresh_from_db()
        self.assertTrue(ballot_public.tie_occurred)
        self.assertTrue(ballot_public.tie_broken_by_chairperson)
        self.assertEqual(ballot_public.chairperson_tie_break_side, 'APPROVE')
        self.assertTrue(ballot_public.majority_achieved)
        self.assertEqual(ballot_public.final_result, 'APPROVED_BY_CHAIR_TIEBREAK')

        # STEP 15: Issue Official Resolutions, Recommendations, Assignments & Accreditation Decision
        self.client.force_login(self.sec_gen)
        # 15a. Issue an ASSIGNMENT with responsible entity & deadline
        self.client.post(reverse('decisions:resolution_create', args=[meeting.pk]), {
            'resolution_type': CouncilResolution.ResolutionType.ASSIGNMENT,
            'agenda_item_id': item_2.pk,
            'ballot_id': ballot_public.pk,
            'resolution_number': 'RES-2026-101',
            'title': 'تكليف الأمانة العامة بتعميم اللائحة التنظيمية',
            'decision_text': 'تكليف الأمانة العامة بإصدار تعميم رسمي باللائحة خلال أسبوعين.',
            'responsible_entity': 'الأمانة العامة للمجلس',
            'responsible_user_id': self.sec_gen.pk,
            'deadline_date': '2026-11-30',
        })
        res_assign = CouncilResolution.objects.get(resolution_number='RES-2026-101')
        self.assertEqual(res_assign.implementation_status, CouncilResolution.ImplementationStatus.ISSUED)

        # Update implementation status to COMPLETED
        self.client.post(reverse('decisions:resolution_update_status', args=[res_assign.pk]), {
            'implementation_status': CouncilResolution.ImplementationStatus.COMPLETED,
            'followup_notes': 'تم التعميم على جميع الإدارات والمؤسسات.'
        })
        res_assign.refresh_from_db()
        self.assertEqual(res_assign.implementation_status, CouncilResolution.ImplementationStatus.COMPLETED)
        self.assertIsNotNone(res_assign.completion_date)

        # 15b. Issue Official Accreditation Decision & Certificate for self.app
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:issue_decision', args=[self.app.pk]), {
            'meeting_id': meeting.pk,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': 'قرار مجلس الاعتماد رقم (100) لسنة 2026',
            'validity_years': 5,
            'start_date': '2026-11-15',
            'legal_justifications': 'استيفاء كافة معايير الاعتماد البرامجي الطبي.',
        })
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, ApplicationStatus.FULL_ACCREDITATION)
        self.assertTrue(AccreditationDecision.objects.filter(application=self.app, meeting=meeting).exists())

        # STEP 16: Generate Meeting Minutes, Modify to Create Version History, Approve & Verify Lock
        self.client.force_login(self.meeting_sec)
        # Version 1 (auto-generated)
        self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'opening_statement': 'افتتحت الجلسة العاشرة بنصاب قانوني مكتمل.',
        })
        minutes = CouncilMeetingMinutes.objects.get(meeting=meeting)
        self.assertEqual(minutes.version_number, 1)

        # Update to Version 2 -> Archives v1 in CouncilMeetingMinutesVersion
        self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'opening_statement': 'افتتحت الجلسة العاشرة بنصاب قانوني مكتمل بحضور 5 أعضاء مصوتين.',
            'modification_reason': 'إضافة عدد الأعضاء الحاضرين في الديباجة',
            'submit_for_approval': '1',
        })
        minutes.refresh_from_db()
        self.assertEqual(minutes.version_number, 2)
        self.assertEqual(minutes.status, CouncilMeetingMinutes.MinutesStatus.PENDING_APPROVAL)
        self.assertEqual(minutes.versions.count(), 1)
        self.assertEqual(minutes.versions.first().modified_by, self.meeting_sec)

        # Chairperson Approves & Signs Minutes -> Locks Minutes & Ratifies Meeting
        self.client.force_login(self.chairman)
        self.client.post(reverse('decisions:meeting_minutes_approve', args=[meeting.pk]))
        minutes.refresh_from_db()
        meeting.refresh_from_db()
        self.assertEqual(minutes.status, CouncilMeetingMinutes.MinutesStatus.APPROVED)
        self.assertEqual(meeting.status, CouncilMeeting.MeetingStatus.MINUTES_RATIFIED)

        # Attempting to modify approved minutes MUST be rejected (remains version 2)
        self.client.force_login(self.meeting_sec)
        self.client.post(reverse('decisions:meeting_minutes_manage', args=[meeting.pk]), {
            'opening_statement': 'محاولة تعديل بعد الاعتماد',
        })
        minutes.refresh_from_db()
        self.assertEqual(minutes.version_number, 2)
        self.assertNotEqual(minutes.opening_statement, 'محاولة تعديل بعد الاعتماد')

        # Verify Printable Minutes & Role Workspace views render cleanly (HTTP 200)
        print_resp = self.client.get(reverse('decisions:meeting_minutes_print', args=[meeting.pk]))
        self.assertEqual(print_resp.status_code, 200)
        ws_resp = self.client.get(reverse('decisions:council_workspace'))
        self.assertEqual(ws_resp.status_code, 200)

        # STEP 17: Verify Notifications & Comprehensive Audit Logs
        self.assertTrue(Notification.objects.filter(recipient=self.uni_president).exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_MEETING_CREATED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_AGENDA_ITEM_CREATED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_MEETING_INVITATIONS_DISPATCHED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_MEETING_RSVP').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_QUORUM_LOST_WARNING').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_AGENDA_DISCUSSION_RECORDED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_BALLOT_OPENED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_BALLOT_VOTE_CAST').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_BALLOT_CLOSED_AND_TALLIED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_RESOLUTION_ISSUED').exists())
        self.assertTrue(AuditLog.objects.filter(action='COUNCIL_MINUTES_APPROVED').exists())
