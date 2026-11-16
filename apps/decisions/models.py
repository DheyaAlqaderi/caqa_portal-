import uuid
import os
from io import BytesIO
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.exceptions import PermissionDenied, ValidationError


class CouncilMeeting(models.Model):
    class MeetingType(models.TextChoices):
        ORDINARY = 'ORDINARY', 'جلسة دورية عادية'
        EXTRAORDINARY = 'EXTRAORDINARY', 'جلسة طارئة / استثنائية'

    class MeetingStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة دعوة'
        UNDER_PREPARATION = 'UNDER_PREPARATION', 'قيد الإعداد والتجهيز'
        INVITATIONS_SENT = 'INVITATIONS_SENT', 'وجهت الدعوة للأعضاء'
        IN_SESSION = 'IN_SESSION', 'منعقدة حالياً'
        TEMPORARILY_SUSPENDED = 'TEMPORARILY_SUSPENDED', 'معلقة مؤقتاً'
        ADJOURNED = 'ADJOURNED', 'مكتملة المداولة والاقتراع'
        COMPLETED = 'COMPLETED', 'مكتملة ومنتهية'
        MINUTES_RATIFIED = 'MINUTES_RATIFIED', 'المحضر مصادق عليه رسمياً'
        CANCELLED = 'CANCELLED', 'ملغاة رسمياً'

    ALLOWED_STATUS_TRANSITIONS = {
        'DRAFT': ['UNDER_PREPARATION', 'INVITATIONS_SENT', 'IN_SESSION', 'CANCELLED'],
        'UNDER_PREPARATION': ['DRAFT', 'INVITATIONS_SENT', 'IN_SESSION', 'CANCELLED'],
        'INVITATIONS_SENT': ['IN_SESSION', 'TEMPORARILY_SUSPENDED', 'CANCELLED'],
        'IN_SESSION': ['TEMPORARILY_SUSPENDED', 'ADJOURNED', 'COMPLETED', 'MINUTES_RATIFIED', 'CANCELLED'],
        'TEMPORARILY_SUSPENDED': ['IN_SESSION', 'ADJOURNED', 'CANCELLED'],
        'ADJOURNED': ['IN_SESSION', 'COMPLETED', 'MINUTES_RATIFIED'],
        'COMPLETED': ['MINUTES_RATIFIED'],
        'MINUTES_RATIFIED': [],
        'CANCELLED': [],
    }

    meeting_number = models.CharField(max_length=50, verbose_name='رقم الجلسة / الاجتماع')
    meeting_type = models.CharField(
        max_length=30,
        choices=MeetingType.choices,
        default=MeetingType.ORDINARY,
        verbose_name='نوع الجلسة'
    )
    meeting_date = models.DateField(verbose_name='تاريخ انعقاد الجلسة')
    meeting_time = models.TimeField(null=True, blank=True, verbose_name='وقت بدء الانعقاد')
    end_time = models.TimeField(null=True, blank=True, verbose_name='وقت انتهاء الجلسة')
    location = models.CharField(max_length=150, default='مقر المجلس الرئيسي - صنعاء', verbose_name='مكان الانعقاد')
    meeting_link = models.URLField(blank=True, verbose_name='رابط الاجتماع المرئي الآمن')
    status = models.CharField(
        max_length=30,
        choices=MeetingStatus.choices,
        default=MeetingStatus.INVITATIONS_SENT,
        verbose_name='حالة الجلسة'
    )
    chairperson_name = models.CharField(max_length=150, verbose_name='رئيس الجلسة (رئيس المجلس)')
    chairperson_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chaired_council_meetings',
        verbose_name='حساب رئيس الجلسة'
    )
    secretary_name = models.CharField(max_length=150, blank=True, verbose_name='اسم أمين سر الجلسة')
    secretary_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='secretaried_council_meetings',
        verbose_name='حساب أمين سر الجلسة'
    )
    attendees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='attended_council_meetings',
        blank=True,
        verbose_name='أعضاء مجلس الإدارة الحاضرون'
    )
    quorum_required = models.PositiveIntegerField(
        default=5,
        verbose_name='الحد الأدنى للنصاب القانوني اللازم لانعقاد الجلسة'
    )
    use_dynamic_quorum = models.BooleanField(
        default=False,
        verbose_name='احتساب النصاب ديناميكياً وفق أغلبية الأعضاء الفعليين (المادة 6)'
    )
    meeting_agenda = models.TextField(verbose_name='جدول أعمال الجلسة')
    minutes_summary = models.TextField(blank=True, verbose_name='محضر وخلاصة مداولات الجلسة')
    cancellation_reason = models.TextField(blank=True, verbose_name='سبب الإلغاء أو التعليق المؤقت')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'جلسة مجلس الإدارة'
        verbose_name_plural = 'جلسات مجلس الإدارة'
        ordering = ['-meeting_date']

    def __str__(self):
        return f"{self.meeting_number} بتاريخ ({self.meeting_date}) - {self.get_meeting_type_display()}"

    def can_transition_to(self, new_status):
        if new_status == self.status:
            return True
        allowed = self.ALLOWED_STATUS_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def transition_status(self, new_status, reason=''):
        if not self.can_transition_to(new_status):
            raise ValidationError(
                f"انتقال حالة غير مسموح به للجلسة من ({self.get_status_display()}) إلى ({new_status})."
            )
        self.status = new_status
        if reason:
            self.cancellation_reason = reason
        self.save()

    def active_voting_members_count(self):
        """
        Returns the total number of voting Council members invited to this meeting,
        or currently appointed & active voting members in the system (Article 6).
        Excludes invited experts and guests.
        """
        invited_voting = self.attendances.filter(attendee_category='VOTING_MEMBER').count()
        if invited_voting > 0:
            return invited_voting
        from apps.accounts.models import User
        return User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
            ],
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        ).count()

    def effective_quorum_required(self):
        """
        According to Article 6 of the Council establishment decree:
        A meeting is valid when a majority (> 50%, i.e., (N // 2) + 1) of its members are present.
        """
        if self.use_dynamic_quorum:
            total = self.active_voting_members_count()
            return (total // 2) + 1 if total > 0 else 1
        return self.quorum_required

    def confirmed_attendance_count(self):
        """
        Returns the number of voting members who either confirmed or actually attended
        and have not withdrawn from the meeting. Strictly excludes guests and experts.
        """
        voting_present = self.attendances.filter(
            attendee_category='VOTING_MEMBER',
            status__in=['CONFIRMED', 'ATTENDED'],
            is_currently_present=True
        ).count()
        if self.attendances.exists():
            return voting_present
        return self.attendees.count()

    def is_quorum_met(self):
        """Validates statutory quorum before opening ballots or finalizing decisions."""
        if self.status == self.MeetingStatus.CANCELLED:
            return False
        return self.confirmed_attendance_count() >= self.effective_quorum_required()


class CouncilMeetingAttendance(models.Model):
    class RSVPStatus(models.TextChoices):
        INVITED = 'INVITED', 'تمت الدعوة'
        CONFIRMED = 'CONFIRMED', 'مؤكد الحضور'
        APOLOGIZED = 'APOLOGIZED', 'معتذر رسمياً'
        ATTENDED = 'ATTENDED', 'حاضر بالجلسة'
        ABSENT = 'ABSENT', 'غائب دون عذر'

    class AttendeeCategory(models.TextChoices):
        VOTING_MEMBER = 'VOTING_MEMBER', 'عضو مجلس إدارة (له حق التصويت)'
        INVITED_EXPERT = 'INVITED_EXPERT', 'خبير أو مختص مدعو (دون حق تصويت - المادة 6)'
        GUEST = 'GUEST', 'ضيف مدعو (دون حق تصويت)'

    class ParticipationMode(models.TextChoices):
        IN_PERSON = 'IN_PERSON', 'حضور فعلي بمقر المجلس'
        ONLINE = 'ONLINE', 'مشاركة مرئية عن بُعد'

    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='attendances',
        verbose_name='جلسة المجلس'
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='council_attendances',
        verbose_name='عضو المجلس / المدعو'
    )
    attendee_category = models.CharField(
        max_length=25,
        choices=AttendeeCategory.choices,
        default=AttendeeCategory.VOTING_MEMBER,
        verbose_name='صفة الحضور والتصويت'
    )
    participation_mode = models.CharField(
        max_length=20,
        choices=ParticipationMode.choices,
        default=ParticipationMode.IN_PERSON,
        verbose_name='آلية المشاركة'
    )
    status = models.CharField(
        max_length=20,
        choices=RSVPStatus.choices,
        default=RSVPStatus.INVITED,
        verbose_name='موقف الحضور'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_meeting_invitations',
        verbose_name='منشئ الدعوة'
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_meeting_invitations',
        verbose_name='مرسل الدعوة'
    )
    invitation_sent_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ وساعة إرسال الدعوة')
    invitation_read = models.BooleanField(default=False, verbose_name='تم الاطلاع على الدعوة')
    invitation_read_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاطلاع على الدعوة')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ وساعة الرد')
    arrival_time = models.TimeField(null=True, blank=True, verbose_name='وقت الوصول للجلسة')
    departure_time = models.TimeField(null=True, blank=True, verbose_name='وقت المغادرة / الانسحاب')
    is_currently_present = models.BooleanField(default=True, verbose_name='متواجد حالياً بالجلسة')
    remarks = models.CharField(max_length=255, blank=True, verbose_name='ملاحظات أو عذر الاعتذار')

    class Meta:
        verbose_name = 'سجل حضور ودعوة عضو المجلس'
        verbose_name_plural = 'سجلات حضور أعضاء المجلس'
        unique_together = ('meeting', 'member')

    def __str__(self):
        return f"{self.member.get_full_name()} - {self.meeting.meeting_number} ({self.get_status_display()})"

    def is_eligible_voter(self):
        """
        Verifies whether this attendee has statutory voting rights in the meeting:
        - Must be a VOTING_MEMBER (not an INVITED_EXPERT or GUEST per Article 6).
        - Must have status CONFIRMED or ATTENDED and be currently present (not withdrawn).
        - User role must be a Board role.
        """
        if self.attendee_category != self.AttendeeCategory.VOTING_MEMBER:
            return False
        if self.status not in [self.RSVPStatus.CONFIRMED, self.RSVPStatus.ATTENDED]:
            return False
        if not self.is_currently_present:
            return False
        from apps.accounts.models import User
        return self.member.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.BOARD_MEMBER,
        ]


class CouncilAgendaItem(models.Model):
    """
    Independent Agenda Item within a Council Meeting supporting all 12 statutory categories
    and distinct required Council actions.
    """
    class ItemCategory(models.TextChoices):
        INSTITUTIONAL_ACCREDITATION = 'INSTITUTIONAL_ACCREDITATION', '1. طلبات الاعتماد المؤسسي'
        PROGRAM_ACCREDITATION = 'PROGRAM_ACCREDITATION', '2. طلبات الاعتماد البرامجي الأكاديمي'
        EXTERNAL_EVALUATION_REPORT = 'EXTERNAL_EVALUATION_REPORT', '3. تقارير التقييم والمراجعة الخارجية'
        ACCREDITATION_COMMITTEE_REPORT = 'ACCREDITATION_COMMITTEE_REPORT', '4. تقارير لجان الاعتماد المختصة'
        REGULATIONS_BYLAWS = 'REGULATIONS_BYLAWS', '5. اللوائح والأنظمة والأدلة'
        STANDARDS_INDICATORS = 'STANDARDS_INDICATORS', '6. معايير ومؤشرات الاعتماد'
        PLANS_STRATEGIES = 'PLANS_STRATEGIES', '7. الخطط والاستراتيجيات'
        FINANCIAL_ADMIN_REPORT = 'FINANCIAL_ADMIN_REPORT', '8. التقارير المالية والإدارية'
        GRIEVANCE_APPEAL = 'GRIEVANCE_APPEAL', '9. التظلمات والطعون'
        COMMITTEE_FORMATION = 'COMMITTEE_FORMATION', '10. تعيين وتشكيل اللجان'
        SURVEILLANCE_FOLLOWUP = 'SURVEILLANCE_FOLLOWUP', '11. تقارير الرقابة والمتابعة الدورية'
        OTHER_TOPIC = 'OTHER_TOPIC', '12. موضوعات أخرى ضمن اختصاص المجلس'

    class RequiredAction(models.TextChoices):
        APPROVAL = 'APPROVAL', 'إقرار واعتماد نهائي'
        RECOMMENDATION = 'RECOMMENDATION', 'رفع توصية لجهة عليا'
        ASSIGNMENT = 'ASSIGNMENT', 'تكليف إدارة أو لجنة مختصة'
        REFERRAL = 'REFERRAL', 'إحالة لمزيد من الدراسة والمراجعة'
        POSTPONEMENT = 'POSTPONEMENT', 'تأجيل البت واستكمال متطلبات'
        DISCUSSION_ONLY = 'DISCUSSION_ONLY', 'مناقشة وإحاطة دون تصويت'

    class ItemStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'مدرج بجدول الأعمال'
        UNDER_DISCUSSION = 'UNDER_DISCUSSION', 'مفتوح للمناقشة والمداولة'
        VOTING_OPEN = 'VOTING_OPEN', 'مفتوح للتصويت'
        VOTING_CLOSED = 'VOTING_CLOSED', 'أغلق التصويت واحتسبت النتيجة'
        DECIDED = 'DECIDED', 'تم البت وإصدار المخرج الرسمي'
        POSTPONED = 'POSTPONED', 'مؤجل لجلسة لاحقة'
        REFERRED = 'REFERRED', 'محال للجنة أو إدارة مختصة'

    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='agenda_items',
        verbose_name='جلسة المجلس'
    )
    item_number = models.CharField(max_length=30, verbose_name='رقم البند')
    position = models.PositiveIntegerField(default=1, verbose_name='ترتيب البند في جدول الأعمال')
    title = models.CharField(max_length=255, verbose_name='عنوان وموضوع البند')
    item_category = models.CharField(
        max_length=40,
        choices=ItemCategory.choices,
        default=ItemCategory.INSTITUTIONAL_ACCREDITATION,
        verbose_name='تصنيف ونوع البند'
    )
    referring_entity = models.CharField(
        max_length=150,
        default='الأمانة العامة للمجلس',
        verbose_name='الجهة أو الإدارة المحيلة'
    )
    presenter_name = models.CharField(max_length=150, blank=True, verbose_name='المسؤول عن العرض / الإدارة العارضة')
    presenter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='presented_agenda_items',
        verbose_name='المتحدث المسؤول'
    )
    description = models.TextField(verbose_name='وصف وتفاصيل الموضوع')
    justification = models.TextField(blank=True, verbose_name='المبررات والمسوغات')
    initial_recommendation = models.TextField(blank=True, verbose_name='التوصية الأولية المرفوعة للمجلس')
    presentation_summary = models.TextField(blank=True, verbose_name='ملخص العرض المقدم أثناء الجلسة')
    required_action = models.CharField(
        max_length=25,
        choices=RequiredAction.choices,
        default=RequiredAction.APPROVAL,
        verbose_name='الإجراء المطلوب من المجلس'
    )
    status = models.CharField(
        max_length=25,
        choices=ItemStatus.choices,
        default=ItemStatus.SCHEDULED,
        verbose_name='حالة البند'
    )
    # Contextual links to domain objects
    application = models.ForeignKey(
        'accreditation.AccreditationApplication',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agenda_items',
        verbose_name='طلب الاعتماد المرتبط'
    )
    policy = models.ForeignKey(
        'CouncilPolicy',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agenda_items',
        verbose_name='اللائحة أو السياسة المرتبطة'
    )
    grievance = models.ForeignKey(
        'accreditation.GrievanceAppeal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agenda_items',
        verbose_name='التظلم المرتبط'
    )
    standard_version = models.ForeignKey(
        'standards.StandardVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agenda_items',
        verbose_name='دليل المعايير المرتبط'
    )
    attachment = models.FileField(
        upload_to='meetings/agenda/%Y/',
        null=True,
        blank=True,
        verbose_name='المرفق الرسمي للبند'
    )
    conflict_of_interest_members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='conflicted_agenda_items',
        verbose_name='أعضاء ذوو تضارب مصالح محظورون من التصويت على البند'
    )
    authorized_experts = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='expert_authorized_agenda_items',
        verbose_name='الخبراء والضيوف المصرح لهم بالاطلاع على هذا البند'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'بند جدول أعمال المجلس'
        verbose_name_plural = 'بنود جدول أعمال المجلس'
        ordering = ['position', 'id']

    def __str__(self):
        return f"بند ({self.item_number}): {self.title}"


class CouncilMeetingAttachment(models.Model):
    """Supporting documents and attachments for a Council Meeting or specific Agenda Item."""
    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='جلسة المجلس'
    )
    agenda_item = models.ForeignKey(
        CouncilAgendaItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments',
        verbose_name='بند جدول الأعمال المرتبط'
    )
    title = models.CharField(max_length=255, verbose_name='عنوان الوثيقة أو المرفق')
    document_type = models.CharField(max_length=60, default='SUPPORTING_DOCUMENT', verbose_name='نوع الوثيقة')
    file = models.FileField(upload_to='meetings/attachments/%Y/', verbose_name='ملف الوثيقة')
    is_confidential = models.BooleanField(
        default=False,
        verbose_name='وثيقة سرية خاصة بأعضاء المجلس فقط (تحجب عن الضيوف)'
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_meeting_attachments',
        verbose_name='المستخدم الرافع للوثيقة'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مرفق جلسة المجلس'
        verbose_name_plural = 'مرفقات ووثائق جلسات المجلس'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} ({self.meeting.meeting_number})"


class CouncilAgendaDiscussion(models.Model):
    """
    Independent record of member discussions, interventions, questions, observations,
    responses, formal reservations, and procedural motions per agenda item.
    """
    class InterventionType(models.TextChoices):
        PRESENTATION = 'PRESENTATION', 'ملخص عرض الموضوع'
        INTERVENTION = 'INTERVENTION', 'مداخلة عضو المجلس'
        QUESTION = 'QUESTION', 'سؤال واستفسار'
        OBSERVATION = 'OBSERVATION', 'ملاحظة فنية / أكاديمية'
        RESPONSE = 'RESPONSE', 'رد وتوضيح'
        RESERVATION = 'RESERVATION', 'تحفظ رسمي مثبت في المحضر'
        RECOMMENDATION = 'RECOMMENDATION', 'توصية مقترحة أثناء النقاش'
        MOTION_POSTPONE = 'MOTION_POSTPONE', 'طلب تأجيل البت في البند'
        MOTION_REFER = 'MOTION_REFER', 'طلب إحالة البند للجنة مختصة'
        MOTION_MORE_INFO = 'MOTION_MORE_INFO', 'طلب استيفاء معلومات إضافية قبل التصويت'

    agenda_item = models.ForeignKey(
        CouncilAgendaItem,
        on_delete=models.CASCADE,
        related_name='discussions',
        verbose_name='بند جدول الأعمال'
    )
    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='council_interventions',
        verbose_name='المتحدث / المتداخل'
    )
    speaker_name = models.CharField(max_length=150, blank=True, verbose_name='اسم المتحدث')
    intervention_type = models.CharField(
        max_length=30,
        choices=InterventionType.choices,
        default=InterventionType.INTERVENTION,
        verbose_name='نوع المداخلة'
    )
    content = models.TextField(verbose_name='نص المداخلة أو الملاحظة أو التحفظ')
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_council_discussions',
        verbose_name='أمين السر الموثق'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مداخلة ونقاش بند جدول الأعمال'
        verbose_name_plural = 'سجل النقاشات والمداخلات والتحفظات'
        ordering = ['created_at', 'id']

    def __str__(self):
        name = self.speaker.get_full_name() if self.speaker else self.speaker_name
        return f"{self.get_intervention_type_display()} - {name} ({self.agenda_item.item_number})"


class CouncilBallot(models.Model):
    """
    Voting Session associated with a specific Agenda Item (and/or Accreditation Application)
    deliberated within an authorized Council Meeting with quorum verification.
    Supports both PUBLIC and SECRET voting modes and enforces Article 6 voting rules.
    """
    class BallotStatus(models.TextChoices):
        OPEN = 'OPEN', 'الاقتراع مفتوح للتصويت'
        CLOSED = 'CLOSED', 'تم إغلاق الاقتراع وفرز الأصوات'
        CANCELLED = 'CANCELLED', 'ملغي لعدم اكتمال النصاب'

    class VotingMode(models.TextChoices):
        PUBLIC = 'PUBLIC', 'تصويت علني موثق بالاسم'
        SECRET = 'SECRET', 'اقتراع سري مشفر ومفصول الهوية'

    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='ballots',
        verbose_name='جلسة المجلس المنعقدة'
    )
    agenda_item = models.ForeignKey(
        CouncilAgendaItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ballots',
        verbose_name='بند جدول الأعمال المرتبط'
    )
    application = models.ForeignKey(
        'accreditation.AccreditationApplication',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ballots',
        verbose_name='طلب الاعتماد المعروض للتصويت'
    )
    title = models.CharField(max_length=255, verbose_name='موضوع التصويت')
    proposed_decision_text = models.TextField(
        blank=True,
        verbose_name='نص مشروع القرار أو التوصية المطروح للتصويت'
    )
    voting_mode = models.CharField(
        max_length=15,
        choices=VotingMode.choices,
        default=VotingMode.SECRET,
        verbose_name='نمط التصويت (علني / سري)'
    )
    status = models.CharField(
        max_length=20,
        choices=BallotStatus.choices,
        default=BallotStatus.OPEN,
        verbose_name='حالة التصويت'
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opened_council_ballots',
        verbose_name='المسؤول الفاتح للتصويت'
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_council_ballots',
        verbose_name='المسؤول المغلق للتصويت'
    )
    opened_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ وساعة فتح التصويت')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ وساعة إغلاق التصويت')

    # Aggregated tallies calculated strictly when voting closes
    present_members_snapshot = models.PositiveIntegerField(default=0, verbose_name='إجمالي الأعضاء الحاضرين')
    eligible_voters_snapshot = models.PositiveIntegerField(default=0, verbose_name='عدد الأعضاء المؤهلين للتصويت')
    votes_approve_count = models.PositiveIntegerField(default=0, verbose_name='عدد الأصوات الموافقة')
    votes_reject_count = models.PositiveIntegerField(default=0, verbose_name='عدد الأصوات الرافضة')
    votes_full_count = models.PositiveIntegerField(default=0, verbose_name='أصوات الاعتماد الكامل')
    votes_conditional_count = models.PositiveIntegerField(default=0, verbose_name='أصوات الاعتماد المشروط')
    votes_denied_count = models.PositiveIntegerField(default=0, verbose_name='أصوات رفض الاعتماد')
    votes_abstain_count = models.PositiveIntegerField(default=0, verbose_name='أصوات الامتناع')
    non_voting_count = models.PositiveIntegerField(default=0, verbose_name='عدد الأعضاء الذين لم يصوتوا')

    # Article 6 Majority & Tie-Break Outcome fields
    majority_achieved = models.BooleanField(default=False, verbose_name='تحققت الأغلبية المطلوبة (المادة 6)')
    tie_occurred = models.BooleanField(default=False, verbose_name='حدث تساوٍ في الأصوات')
    tie_broken_by_chairperson = models.BooleanField(
        default=False,
        verbose_name='تم ترجيح الكفة بجانب رئيس المجلس (المادة 6)'
    )
    chairperson_tie_break_side = models.CharField(
        max_length=25,
        blank=True,
        verbose_name='الجانب المرجح من رئيس المجلس'
    )
    final_result = models.CharField(
        max_length=40,
        blank=True,
        verbose_name='النتيجة النهائية للتصويت'
    )

    class Meta:
        verbose_name = 'جلسة تصويت واقتراع المجلس'
        verbose_name_plural = 'جلسات التصويت والاقتراع لمجلس الإدارة'

    def __str__(self):
        return f"تصويت ({self.title}) [{self.get_voting_mode_display()}] - {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status == self.BallotStatus.OPEN

    def total_votes_cast(self):
        if self.voting_mode == self.VotingMode.PUBLIC:
            return self.public_votes.count()
        return self.secret_votes.count()

    def is_member_conflicted(self, user):
        """Checks if the user has a declared or institutional conflict of interest on this ballot's item."""
        if self.agenda_item and self.agenda_item.conflict_of_interest_members.filter(pk=user.pk).exists():
            return True
        target_app = self.application or (self.agenda_item.application if self.agenda_item else None)
        if target_app and user.institution_id and user.institution_id == target_app.institution_id:
            return True
        if target_app:
            from apps.accreditation.models import ConflictOfInterestDeclaration
            if ConflictOfInterestDeclaration.objects.filter(
                application=target_app, reviewer=user, is_conflict_acknowledged=True
            ).exists():
                return True
        return False

    def eligible_voters_count_live(self):
        """Counts currently present voting members minus any conflicted members."""
        present_voters = self.meeting.attendances.filter(
            attendee_category='VOTING_MEMBER',
            status__in=['CONFIRMED', 'ATTENDED'],
            is_currently_present=True
        ).select_related('member')
        if not present_voters.exists():
            return self.meeting.confirmed_attendance_count()
        count = 0
        for att in present_voters:
            if att.is_eligible_voter() and not self.is_member_conflicted(att.member):
                count += 1
        return count

    def tally_results(self, chairperson_tie_break=None):
        """
        Calculates voting results according to Article 6 of the Council establishment decree:
        - Decisions, recommendations, and proposals are adopted by a majority of the votes of members present.
        - In the event of a tie, the side supported by the Council Chairperson prevails.
        - Preserves full anonymity in SECRET mode and full attribution in PUBLIC mode.
        """
        present_count = self.meeting.confirmed_attendance_count()
        eligible_count = self.eligible_voters_count_live()

        if self.voting_mode == self.VotingMode.PUBLIC:
            qs = self.public_votes.all()
        else:
            qs = self.secret_votes.all()

        full_c = qs.filter(vote_choice='FULL').count()
        cond_c = qs.filter(vote_choice='CONDITIONAL').count()
        approve_std_c = qs.filter(vote_choice='APPROVE').count()
        denied_c = qs.filter(vote_choice='DENIED').count()
        reject_std_c = qs.filter(vote_choice='REJECT').count()
        abstain_c = qs.filter(vote_choice='ABSTAIN').count()

        total_approve = full_c + cond_c + approve_std_c
        total_reject = denied_c + reject_std_c
        total_cast = total_approve + total_reject + abstain_c

        self.present_members_snapshot = max(present_count, total_cast)
        self.eligible_voters_snapshot = max(eligible_count, total_cast)
        self.non_voting_count = max(0, self.eligible_voters_snapshot - total_cast)

        self.votes_full_count = full_c + approve_std_c
        self.votes_conditional_count = cond_c
        self.votes_denied_count = denied_c + reject_std_c
        self.votes_abstain_count = abstain_c

        self.votes_approve_count = total_approve
        self.votes_reject_count = total_reject

        # Article 6 Tie-Breaking and Majority Calculation
        self.tie_occurred = (total_approve == total_reject and total_approve > 0)
        self.tie_broken_by_chairperson = False
        self.chairperson_tie_break_side = ''

        if self.tie_occurred:
            resolved_side = chairperson_tie_break
            if not resolved_side and self.voting_mode == self.VotingMode.PUBLIC:
                # Automatically determine which side the Council Chairperson supported
                from apps.accounts.models import User
                chair_vote = self.public_votes.filter(
                    models.Q(voter=self.meeting.chairperson_user) |
                    models.Q(voter__role=User.Roles.COUNCIL_CHAIRMAN)
                ).first()
                if chair_vote:
                    if chair_vote.vote_choice in ['APPROVE', 'FULL', 'CONDITIONAL']:
                        resolved_side = 'APPROVE'
                    elif chair_vote.vote_choice in ['REJECT', 'DENIED']:
                        resolved_side = 'REJECT'

            if resolved_side in ['APPROVE', 'FULL']:
                self.tie_broken_by_chairperson = True
                self.chairperson_tie_break_side = 'APPROVE'
                self.majority_achieved = True
                self.final_result = 'APPROVED_BY_CHAIR_TIEBREAK'
            elif resolved_side in ['REJECT', 'DENIED']:
                self.tie_broken_by_chairperson = True
                self.chairperson_tie_break_side = 'REJECT'
                self.majority_achieved = False
                self.final_result = 'REJECTED_BY_CHAIR_TIEBREAK'
            else:
                self.majority_achieved = False
                self.final_result = 'TIE_PENDING_CHAIRPERSON'
        else:
            if total_approve > total_reject:
                self.majority_achieved = True
                if cond_c > (full_c + approve_std_c):
                    self.final_result = 'CONDITIONAL_APPROVED'
                else:
                    self.final_result = 'APPROVED'
            elif total_reject > total_approve:
                self.majority_achieved = False
                self.final_result = 'REJECTED'
            else:
                self.majority_achieved = False
                self.final_result = 'NO_DECISION'

        self.status = self.BallotStatus.CLOSED
        self.closed_at = timezone.now()
        self.save()

        if self.agenda_item:
            self.agenda_item.status = CouncilAgendaItem.ItemStatus.VOTING_CLOSED
            self.agenda_item.save()


class CouncilBallotVoterRecord(models.Model):
    """
    Audit proof that an authorized member has cast their ballot.
    STRICT SECURITY NOTE: Stores NO vote choice to preserve ballot secrecy.
    """
    ballot = models.ForeignKey(
        CouncilBallot,
        on_delete=models.CASCADE,
        related_name='voter_records',
        verbose_name='جلسة الاقتراع'
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cast_council_ballots',
        verbose_name='عضو المجلس المقترع'
    )
    voted_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإدلاء بالصوت')

    class Meta:
        verbose_name = 'سجل إثبات مشاركة بالاقتراع'
        verbose_name_plural = 'سجلات إثبات مشاركة أعضاء المجلس بالاقتراع'
        unique_together = ('ballot', 'voter')

    def __str__(self):
        return f"إثبات تصويت: {self.voter.get_full_name()} في ({self.ballot.title})"


class CouncilSecretVote(models.Model):
    """
    Anonymous, unlinked secret vote.
    STRICT SECURITY NOTE: Has NO Foreign Key to voter or User model.
    Only linked to ballot with a cryptographic verification hash.
    Immutable once created.
    """
    class VoteChoice(models.TextChoices):
        APPROVE = 'APPROVE', 'موافقة'
        REJECT = 'REJECT', 'رفض / عدم موافقة'
        FULL = 'FULL', 'منح الاعتماد الكامل'
        CONDITIONAL = 'CONDITIONAL', 'منح الاعتماد المشروط'
        DENIED = 'DENIED', 'رفض منح الاعتماد'
        ABSTAIN = 'ABSTAIN', 'امتناع مسبب'

    ballot = models.ForeignKey(
        CouncilBallot,
        on_delete=models.CASCADE,
        related_name='secret_votes',
        verbose_name='جلسة الاقتراع'
    )
    vote_choice = models.CharField(
        max_length=25,
        choices=VoteChoice.choices,
        verbose_name='خيار التصويت السري'
    )
    abstain_justification = models.TextField(blank=True, verbose_name='المبررات القانونية والأكاديمية للامتناع')
    cast_hash = models.CharField(max_length=64, editable=False, verbose_name='رمز البصمة الرقمية المشفر للاقتراع')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'صوت اقتراع سري'
        verbose_name_plural = 'أصوات الاقتراع السري المشفرة'

    def __str__(self):
        return f"صوت سري رقم ({self.pk}) - {self.get_vote_choice_display()}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("يُحظر قطعياً تعديل الصوت السري بعد الإدلاء به لأي مستخدم أو مسؤول.")
        super().save(*args, **kwargs)


class CouncilPublicVote(models.Model):
    """
    Attributed Public Vote when a ballot is configured in PUBLIC voting mode.
    Immutable once submitted to prevent administrative tampering.
    """
    ballot = models.ForeignKey(
        CouncilBallot,
        on_delete=models.CASCADE,
        related_name='public_votes',
        verbose_name='جلسة التصويت العلني'
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='public_council_votes',
        verbose_name='عضو المجلس المصوت'
    )
    vote_choice = models.CharField(
        max_length=25,
        choices=CouncilSecretVote.VoteChoice.choices,
        verbose_name='خيار التصويت العلني'
    )
    justification = models.TextField(blank=True, verbose_name='ملاحظات أو تسبيب الصوت')
    voted_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت التصويت')

    class Meta:
        verbose_name = 'صوت علني موثق لعضو المجلس'
        verbose_name_plural = 'أصوات التصويت العلني لأعضاء المجلس'
        unique_together = ('ballot', 'voter')

    def __str__(self):
        return f"{self.voter.get_full_name()}: {self.get_vote_choice_display()} ({self.ballot.title})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("يُحظر قطعياً تعديل صوت عضو المجلس بعد الإدلاء به حتى لمدير النظام.")
        super().save(*args, **kwargs)


class CouncilMeetingMinutes(models.Model):
    """
    Official Meeting Minutes with full version history, signatory approvals,
    and PDF export support.
    """
    class MinutesStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة محضر قيد الإعداد'
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'مرفوع للاعتماد والتوقيع'
        APPROVED = 'APPROVED', 'معتمد ومصادق عليه رسمياً'

    meeting = models.OneToOneField(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='official_minutes',
        verbose_name='جلسة المجلس'
    )
    minutes_number = models.CharField(max_length=60, unique=True, verbose_name='رقم المحضر الرسمي')
    version_number = models.PositiveIntegerField(default=1, verbose_name='رقم الإصدار الحالي')
    opening_statement = models.TextField(blank=True, verbose_name='ديباجة افتتاح الجلسة والتحقق من النصاب')
    discussions_record = models.TextField(blank=True, verbose_name='سجل المداولات والمناقشات والتحفظات')
    decisions_record = models.TextField(blank=True, verbose_name='سجل نتائج التصويت والقرارات والتوصيات والتكليفات')
    closing_statement = models.TextField(blank=True, verbose_name='خاتمة المحضر ووقت اختتام الجلسة')
    status = models.CharField(
        max_length=25,
        choices=MinutesStatus.choices,
        default=MinutesStatus.DRAFT,
        verbose_name='حالة المحضر'
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prepared_council_minutes',
        verbose_name='أمين السر المعد للمحضر'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_council_minutes',
        verbose_name='المسؤول المعتمد للمحضر (رئيس المجلس)'
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ وساعة اعتماد المحضر')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'محضر اجتماع مجلس الإدارة'
        verbose_name_plural = 'محاضر اجتماعات مجلس الإدارة'

    def __str__(self):
        return f"محضر ({self.minutes_number}) - الإصدار v{self.version_number} ({self.get_status_display()})"


class CouncilMeetingMinutesVersion(models.Model):
    """Preserves previous versions of meeting minutes and records who modified them and when."""
    minutes = models.ForeignKey(
        CouncilMeetingMinutes,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name='المحضر الرئيسي'
    )
    version_number = models.PositiveIntegerField(verbose_name='رقم الإصدار المؤرشف')
    content_snapshot = models.TextField(verbose_name='النص الكامل للإصدار المؤرشف')
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modified_minutes_versions',
        verbose_name='المستخدم المعدل'
    )
    modification_reason = models.CharField(max_length=255, blank=True, verbose_name='سبب التعديل أو المراجعة')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ وساعة حفظ الإصدار')

    class Meta:
        verbose_name = 'إصدار مؤرشف لمحضر الجلسة'
        verbose_name_plural = 'سجل إصدارات محاضر الجلسات'
        ordering = ['-version_number', '-created_at']

    def __str__(self):
        return f"{self.minutes.minutes_number} - v{self.version_number}"


class CouncilResolution(models.Model):
    """
    Independent Decision, Recommendation, Assignment, Referral, or Postponement record
    issued from a Council Meeting agenda item.
    """
    class ResolutionType(models.TextChoices):
        FINAL_DECISION = 'FINAL_DECISION', 'قرار نهائي نافذ ضمن صلاحيات المجلس'
        RECOMMENDATION = 'RECOMMENDATION', 'توصية مرفوعة لجهة عليا (الوزير / رئاسة الوزراء)'
        ASSIGNMENT = 'ASSIGNMENT', 'تكليف لإدارة تنفيذية أو لجنة متخصصة'
        REFERRAL = 'REFERRAL', 'إحالة لمزيد من الدراسة والمراجعة'
        POSTPONEMENT = 'POSTPONEMENT', 'قرار بتأجيل البت في الموضوع'

    class ImplementationStatus(models.TextChoices):
        ISSUED = 'ISSUED', 'صادر وبانتظار التنفيذ'
        IN_PROGRESS = 'IN_PROGRESS', 'قيد التنفيذ والمتابعة'
        SUBMITTED_TO_AUTHORITY = 'SUBMITTED_TO_AUTHORITY', 'مرفوع للجهة العليا للاعتماد'
        COMPLETED = 'COMPLETED', 'تم التنفيذ والإنجاز'
        OVERDUE = 'OVERDUE', 'متأخر عن الموعد المحدد'

    resolution_number = models.CharField(max_length=60, unique=True, verbose_name='رقم القرار / التوصية / التكليف')
    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='resolutions',
        verbose_name='جلسة المجلس'
    )
    agenda_item = models.ForeignKey(
        CouncilAgendaItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolutions',
        verbose_name='بند جدول الأعمال المرتبط'
    )
    ballot = models.ForeignKey(
        CouncilBallot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolutions',
        verbose_name='نتيجة التصويت المرتبطة'
    )
    accreditation_decision = models.ForeignKey(
        'AccreditationDecision',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolutions',
        verbose_name='قرار الاعتماد الأكاديمي المرتبط'
    )
    resolution_type = models.CharField(
        max_length=30,
        choices=ResolutionType.choices,
        default=ResolutionType.FINAL_DECISION,
        verbose_name='طبيعة المخرج (قرار / توصية / تكليف / إحالة / تأجيل)'
    )
    title = models.CharField(max_length=255, verbose_name='موضوع القرار أو التوصية أو التكليف')
    decision_text = models.TextField(verbose_name='منطوق ونص القرار أو التوصية أو التكليف')
    voting_result_summary = models.CharField(max_length=255, blank=True, verbose_name='ملخص نتيجة التصويت')
    issue_date = models.DateField(default=timezone.now, verbose_name='تاريخ الصدور')
    responsible_entity = models.CharField(max_length=150, blank=True, verbose_name='الجهة المكلفة بالتنفيذ')
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_council_resolutions',
        verbose_name='الموظف / المسؤول المكلف بالمتابعة'
    )
    receiving_entity = models.CharField(max_length=150, blank=True, verbose_name='الجهة المستلمة / المبلغة')
    deadline_date = models.DateField(null=True, blank=True, verbose_name='الموعد النهائي للتنفيذ')
    implementation_status = models.CharField(
        max_length=30,
        choices=ImplementationStatus.choices,
        default=ImplementationStatus.ISSUED,
        verbose_name='حالة التنفيذ والمتابعة'
    )
    completion_date = models.DateField(null=True, blank=True, verbose_name='تاريخ إنجاز التنفيذ')
    followup_notes = models.TextField(blank=True, verbose_name='ملاحظات المتابعة والتنفيذ')
    attachment = models.FileField(
        upload_to='meetings/resolutions/%Y/',
        null=True,
        blank=True,
        verbose_name='مرفق القرار أو التكليف'
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_council_resolutions',
        verbose_name='المسؤول المصدر'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'قرار أو توصية أو تكليف للمجلس'
        verbose_name_plural = 'سجل قرارات وتوصيات وتكليفات المجلس'
        ordering = ['-issue_date', '-id']

    def __str__(self):
        return f"{self.resolution_number}: {self.title} ({self.get_resolution_type_display()})"



class AccreditationDecision(models.Model):
    class DecisionType(models.TextChoices):
        FULL_ACCREDITATION = 'FULL_ACCREDITATION', 'منح الاعتماد الكامل'
        CONDITIONAL_ACCREDITATION = 'CONDITIONAL_ACCREDITATION', 'منح الاعتماد المشروط / المؤقت'
        POSTPONED = 'POSTPONED', 'تأجيل البت لاستكمال متطلبات'
        DENIED = 'DENIED', 'رفض منح الاعتماد'

    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.CASCADE,
        related_name='decisions',
        verbose_name='جلسة المجلس المنعقدة'
    )
    application = models.OneToOneField(
        'accreditation.AccreditationApplication',
        on_delete=models.CASCADE,
        related_name='council_decision',
        verbose_name='طلب الاعتماد المعروض'
    )
    decision_type = models.CharField(
        max_length=35,
        choices=DecisionType.choices,
        verbose_name='القرار النهائي للمجلس'
    )
    decree_number = models.CharField(max_length=100, unique=True, verbose_name='رقم القرار الوزاري / قرار المجلس')
    decision_date = models.DateField(verbose_name='تاريخ صدور القرار')
    validity_years = models.PositiveIntegerField(
        default=5,
        verbose_name='مدة سريان وثيقة الاعتماد (بالسنوات)'
    )
    start_date = models.DateField(null=True, blank=True, verbose_name='تاريخ بدء السريان')
    expiry_date = models.DateField(null=True, blank=True, verbose_name='تاريخ انتهاء السريان')
    legal_justifications = models.TextField(verbose_name='حيثيات ومسوغات القرار وفق التقرير الفني النهائي')
    corrective_requirements = models.TextField(
        blank=True,
        verbose_name='الاشتراطات وخطة التحسين الواجب تنفيذها (خاصة للاعتماد المشروط)'
    )
    votes_in_favor = models.PositiveIntegerField(default=7, verbose_name='عدد الأصوات المؤيدة')
    votes_against = models.PositiveIntegerField(default=0, verbose_name='عدد الأصوات المعارضة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'قرار اعتماد أكاديمي'
        verbose_name_plural = 'قرارات الاعتماد الصادرة عن المجلس'
        ordering = ['-decision_date']

    def __str__(self):
        return f"قرار رقم ({self.decree_number}) - {self.get_decision_type_display()}"


class AccreditationCertificate(models.Model):
    class CertificateStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'سارية ونافذة المفعول'
        EXPIRED = 'EXPIRED', 'منتهية المدة الزمنية'
        SUSPENDED = 'SUSPENDED', 'معلقة مؤقتاً بقرار رسمي'
        REVOKED = 'REVOKED', 'مسحوبة وملغاة نهائياً'
        SUPERSEDED = 'SUPERSEDED', 'مجددة / مستبدلة بشهادة أحدث'

    decision = models.OneToOneField(
        AccreditationDecision,
        on_delete=models.CASCADE,
        related_name='certificate',
        verbose_name='قرار الاعتماد'
    )
    certificate_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='المعرف الرقمي الموثق')
    national_registry_code = models.CharField(max_length=50, unique=True, verbose_name='رقم القيد في السجل الوطني للاعتماد')
    issue_date = models.DateField(verbose_name='تاريخ إصدار الشهادة')
    qr_code_image = models.FileField(upload_to='certificates/qr/%Y/', blank=True, null=True, verbose_name='رمز التحقق السريع QR')
    status = models.CharField(
        max_length=25,
        choices=CertificateStatus.choices,
        default=CertificateStatus.ACTIVE,
        verbose_name='حالة سريان الشهادة في السجل الوطني'
    )
    is_revoked = models.BooleanField(default=False, verbose_name='ملغاة أو مسحوبة')
    revocation_date = models.DateField(null=True, blank=True, verbose_name='تاريخ السحب أو الإلغاء')
    revocation_decree = models.CharField(max_length=150, blank=True, verbose_name='قرار السحب الرسمي')
    revocation_reason = models.TextField(blank=True, verbose_name='سبب إلغاء أو سحب الاعتماد')
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_certificates',
        verbose_name='المسؤول الموثق للسحب'
    )
    printed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ طباعة الوثيقة')

    class Meta:
        verbose_name = 'شهادة اعتماد رسمية'
        verbose_name_plural = 'شهادات الاعتماد الصادرة'

    def __str__(self):
        return f"شهادة اعتماد رقم ({self.national_registry_code}) - {self.get_status_display()}"

    def generate_qr_code(self, verification_url):
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=2,
            )
            qr.add_data(verification_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            file_name = f"qr_{self.certificate_uuid}.png"
            self.qr_code_image.save(file_name, ContentFile(buffer.getvalue()), save=False)
        except Exception:
            pass



class CertificateRevocationRecord(models.Model):
    certificate = models.ForeignKey(
        AccreditationCertificate,
        on_delete=models.CASCADE,
        related_name='revocation_history',
        verbose_name='وثيقة الشهادة'
    )
    action_type = models.CharField(
        max_length=30,
        choices=[
            ('SUSPEND', 'تعليق مؤقت'),
            ('REVOKE', 'سحب نهائي وإلغاء'),
            ('REINSTATE', 'إلغاء التعليق وإعادة التفعيل'),
        ],
        verbose_name='نوع الإجراء القانوني'
    )
    decree_reference = models.CharField(max_length=150, verbose_name='رقم وتاريخ القرار الوزاري / قرار المجلس')
    justification = models.TextField(verbose_name='الأسباب القانونية والحيثيات الفنية')
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name='المستخدم المنفذ'
    )
    action_date = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ وساعة الإجراء')

    class Meta:
        verbose_name = 'سجل سحب أو تعليق شهادة'
        verbose_name_plural = 'سجلات سحب وتعليق الشهادات'
        ordering = ['-action_date']

    def __str__(self):
        return f"{self.get_action_type_display()} - {self.certificate.national_registry_code}"


class BoardNomination(models.Model):
    class NominationStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة ترشيح'
        SUBMITTED_TO_PM = 'SUBMITTED_TO_PM', 'مرفوع لدولة رئيس الوزراء'
        UNDER_REVIEW = 'UNDER_REVIEW', 'قيد دراسة ديوان رئاسة الوزراء'
        RETURNED_FOR_COMPLETION = 'RETURNED_FOR_COMPLETION', 'معاد للاستكمال واستيفاء المتطلبات'
        DECREE_ISSUED = 'DECREE_ISSUED', 'صدر به قرار جمهوري / وزاري'
        REJECTED = 'REJECTED', 'معتذر عنه / غير معتمد'

    class ProposedPosition(models.TextChoices):
        CHAIRMAN = 'CHAIRMAN', 'رئيس مجلس الاعتماد الأكاديمي'
        VICE_CHAIRMAN = 'VICE_CHAIRMAN', 'نائب رئيس المجلس'
        BOARD_MEMBER_PUBLIC = 'BOARD_MEMBER_PUBLIC', 'عضو مجلس إدارة - قطاع الجامعات الحكومية'
        BOARD_MEMBER_PRIVATE = 'BOARD_MEMBER_PRIVATE', 'عضو مجلس إدارة - قطاع الجامعات الأهلية'
        BOARD_MEMBER_EXPERT = 'BOARD_MEMBER_EXPERT', 'عضو مجلس إدارة - خبير جودة أكاديمية'
        BOARD_MEMBER_MEDICAL = 'BOARD_MEMBER_MEDICAL', 'عضو مجلس إدارة - ممثل القطاع الصحي والطبي'
        BOARD_MEMBER_TECH = 'BOARD_MEMBER_TECH', 'عضو مجلس إدارة - ممثل القطاع التقني والهندسي'

    nominee_name = models.CharField(max_length=200, verbose_name='اسم المرشح الرباعي واللقب')
    academic_rank = models.CharField(max_length=100, default='أستاذ دكتور (بروفيسور)', verbose_name='الرتبة العلمية')
    proposed_position = models.CharField(
        max_length=50,
        choices=ProposedPosition.choices,
        default=ProposedPosition.BOARD_MEMBER_EXPERT,
        verbose_name='المنصب / الصفة المرشح لها بمجلس الإدارة'
    )
    specialization = models.CharField(max_length=150, verbose_name='التخصص العلمي الدقيق')
    current_institution = models.CharField(max_length=200, verbose_name='المؤسسة / الجامعة الحالية')
    cv_summary = models.TextField(verbose_name='نبذة عن السيرة الذاتية والخبرات الأكاديمية ومسوغات الترشيح')
    nomination_document = models.FileField(
        upload_to='nominations/%Y/',
        blank=True,
        null=True,
        verbose_name='وثيقة مذكرة الترشيح والسيرة الذاتية المرفقة'
    )
    nomination_letter_ref = models.CharField(max_length=120, blank=True, verbose_name='رقم مذكرة الترشيح المرفوعة لدولة رئيس الوزراء')
    nomination_date = models.DateField(default=timezone.now, verbose_name='تاريخ مذكرة الترشيح')
    status = models.CharField(
        max_length=30,
        choices=NominationStatus.choices,
        default=NominationStatus.SUBMITTED_TO_PM,
        verbose_name='حالة الترشيح'
    )
    republican_decree_number = models.CharField(max_length=120, blank=True, verbose_name='رقم القرار الجمهوري / قرار التعيين الصادر')
    decree_date = models.DateField(null=True, blank=True, verbose_name='تاريخ صدور القرار الجمهوري')
    decree_document = models.FileField(
        upload_to='decrees/%Y/',
        blank=True,
        null=True,
        verbose_name='نسخة وثيقة القرار الجمهوري الرسمية'
    )
    appointment_start_date = models.DateField(null=True, blank=True, verbose_name='تاريخ بدء التعيين الرسمي')
    appointment_end_date = models.DateField(null=True, blank=True, verbose_name='تاريخ انتهاء فترة التعيين')
    term_years = models.PositiveIntegerField(default=4, verbose_name='مدة التعيين القانونية (بالسنوات)')
    appointed_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='board_appointments',
        verbose_name='المستخدم المعين في النظام'
    )
    minister_notes = models.TextField(blank=True, verbose_name='توجيهات وملاحظات معالي الوزير')
    pm_notes = models.TextField(blank=True, verbose_name='توجيهات واعتماد دولة رئيس مجلس الوزراء')
    pm_endorsed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pm_endorsed_nominations',
        verbose_name='المعتمد برئاسة الوزراء'
    )
    pm_endorsed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ اعتماد رئاسة الوزراء')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_board_nominations',
        verbose_name='المستخدم المنشئ'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ترشيح عضوية مجلس الإدارة'
        verbose_name_plural = 'ترشيحات رئاسة وعضوية مجلس الإدارة'
        ordering = ['-nomination_date', '-created_at']

    def __str__(self):
        return f"{self.nominee_name} - {self.get_proposed_position_display()} ({self.get_status_display()})"

    def is_appointment_active(self):
        """Verifies that an appointment has been decreed and has not passed its expiration date."""
        if self.status != self.NominationStatus.DECREE_ISSUED:
            return False
        if self.appointment_end_date and self.appointment_end_date < timezone.now().date():
            return False
        return True


class CouncilPolicy(models.Model):
    class PolicyType(models.TextChoices):
        EXECUTIVE_REGULATION = 'EXECUTIVE_REGULATION', 'لائحة تنفيذية عامة'
        NATIONAL_QUALITY_POLICY = 'NATIONAL_QUALITY_POLICY', 'سياسة وطنية لضمان الجودة'
        ACCREDITATION_STANDARDS = 'ACCREDITATION_STANDARDS', 'دليل معايير اعتماد تخصصي'
        FEES_SCHEDULE = 'FEES_SCHEDULE', 'لائحة الرسوم وأجور الخدمات'
        GOVERNANCE_MANUAL = 'GOVERNANCE_MANUAL', 'دليل الحوكمة ونظام العمل الداخلي'

    class RatificationStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة سياسة/لائحة'
        COUNCIL_APPROVED = 'COUNCIL_APPROVED', 'مقرة من مجلس الإدارة'
        PENDING_RATIFICATION = 'PENDING_RATIFICATION', 'معروضة للمصادقة الوزارية'
        RATIFIED = 'RATIFIED', 'مصادق عليها بقرار وزاري'
        EFFECTIVE = 'EFFECTIVE', 'نافذة ومنشورة رسمياً'
        RETURNED_WITH_REMARKS = 'RETURNED_WITH_REMARKS', 'معادة للمجلس بملاحظات للتعديل'
        REJECTED = 'REJECTED', 'غير مصادق عليها'

    title = models.CharField(max_length=255, verbose_name='عنوان السياسة / اللائحة العامة')
    policy_type = models.CharField(
        max_length=50,
        choices=PolicyType.choices,
        default=PolicyType.EXECUTIVE_REGULATION,
        verbose_name='نوع الوثيقة / اللائحة'
    )
    version_number = models.CharField(max_length=20, default='1.0', verbose_name='رقم الإصدار')
    council_session_ref = models.CharField(max_length=150, verbose_name='مرجع إقرار مجلس الإدارة (رقم وتاريخ الجلسة)')
    submission_date = models.DateField(default=timezone.now, verbose_name='تاريخ الإحالة إلى معالي الوزير')
    summary = models.TextField(verbose_name='خلاصة السياسة والأهداف الاستراتيجية')
    document_file = models.FileField(
        upload_to='policies/%Y/',
        blank=True,
        null=True,
        verbose_name='نسخة وثيقة السياسة / اللائحة (PDF)'
    )
    status = models.CharField(
        max_length=30,
        choices=RatificationStatus.choices,
        default=RatificationStatus.PENDING_RATIFICATION,
        verbose_name='موقف المصادقة الوزارية'
    )
    ministerial_decree_number = models.CharField(max_length=120, blank=True, verbose_name='رقم وتاريخ القرار الوزاري بالمصادقة والنفاذ')
    ratification_date = models.DateField(null=True, blank=True, verbose_name='تاريخ المصادقة الوزارية')
    effective_date = models.DateField(null=True, blank=True, verbose_name='تاريخ بدء العمل والنفاذ الرسمي')
    minister_directive = models.TextField(blank=True, verbose_name='توجيهات وقرار معالي الوزير')
    ratified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ratified_council_policies',
        verbose_name='المصادق (معالي الوزير)'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'سياسة ولائحة المجلس العامة'
        verbose_name_plural = 'السياسات واللوائح العامة للمجلس'
        ordering = ['-submission_date', '-created_at']

    def __str__(self):
        return f"{self.title} v{self.version_number} ({self.get_status_display()})"


class SovereignTransaction(models.Model):
    """
    Centralized Sovereign Transaction and Official Correspondence Engine.
    Provides verifiable sender -> authorized recipient -> document -> audit movements across CAQA.
    """
    class TransactionType(models.TextChoices):
        NOMINATION_MEMO = 'NOMINATION_MEMO', 'مذكرة ترشيح مجلس الإدارة'
        PRESIDENTIAL_DECREE = 'PRESIDENTIAL_DECREE', 'قرار تعيين جمهوري'
        POLICY_RATIFICATION = 'POLICY_RATIFICATION', 'مصادقة على لائحة/سياسة'
        MEETING_INVITATION = 'MEETING_INVITATION', 'دعوة اجتماع مجلس الإدارة'
        ACCREDITATION_DECISION = 'ACCREDITATION_DECISION', 'قرار اعتماد أكاديمي رسمي'
        GRIEVANCE_APPEAL = 'GRIEVANCE_APPEAL', 'عريضة تظلم وطعن قانوني'
        OFFICIAL_MEMO = 'OFFICIAL_MEMO', 'مذكرة مراسلة وزارية/سيادية'
        APPLICATION_SUBMISSION = 'APPLICATION_SUBMISSION', 'تقديم طلب اعتماد جديد'
        PRESIDENT_ENDORSEMENT = 'PRESIDENT_ENDORSEMENT', 'مصادقة وتوقيع رئيس الجامعة'
        APPLICATION_APPROVAL = 'APPLICATION_APPROVAL', 'موافقة أو إرجاع طلب الاعتماد وتحديد الرسوم'
        SELF_STUDY_SUBMISSION = 'SELF_STUDY_SUBMISSION', 'تسليم تقرير التقييم الذاتي والشواهد'
        DESK_REVIEW_RESULT = 'DESK_REVIEW_RESULT', 'نتيجة الفحص المكتبي والاكتمال الشكلي'
        FINANCIAL_CLAIM_CLEARANCE = 'FINANCIAL_CLAIM_CLEARANCE', 'المطالبة المالية وسند الإبراء المالي'
        REVIEW_TEAM_ASSIGNMENT = 'REVIEW_TEAM_ASSIGNMENT', 'تشكيل وتكليف فريق المراجعة الخارجية'
        COI_DECLARATION = 'COI_DECLARATION', 'إقرار الحيادية وعدم تضارب المصالح'
        SITE_VISIT_NOTICE = 'SITE_VISIT_NOTICE', 'خطة وجدول الزيارة الميدانية'
        DRAFT_EXTERNAL_REPORT = 'DRAFT_EXTERNAL_REPORT', 'مسودة تقرير التقييم الخارجي وحق الرد'
        INSTITUTION_REPLY = 'INSTITUTION_REPLY', 'مذكرة رد المؤسسة الرسمي'
        FINAL_EXTERNAL_REPORT = 'FINAL_EXTERNAL_REPORT', 'التقرير النهائي لفريق التقييم الخارجي'
        COMPARISON_REPORT_REFERRAL = 'COMPARISON_REPORT_REFERRAL', 'إحالة تقرير المقارنة التحليلي لمجلس الإدارة'
        SURVEILLANCE_REPORT = 'SURVEILLANCE_REPORT', 'تقرير وخطة التحسين والرقابة الدورية'

    class TransactionStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة معاملة'
        SUBMITTED = 'SUBMITTED', 'مرسلة ومقيدة رسمياً'
        RECEIVED = 'RECEIVED', 'مستلمة بالديوان المختص'
        UNDER_REVIEW = 'UNDER_REVIEW', 'قيد الدراسة والمراجعة'
        RETURNED_FOR_COMPLETION = 'RETURNED_FOR_COMPLETION', 'معادة للاستكمال'
        APPROVED = 'APPROVED', 'معتمدة / مصادق عليها'
        REJECTED = 'REJECTED', 'معتذر عنها / مرفوضة'
        FORWARDED = 'FORWARDED', 'محالة لجهة الاختصاص'
        COMPLETED = 'COMPLETED', 'منجزة ونافذة'
        ARCHIVED = 'ARCHIVED', 'مؤرشفة بالسجل العام'

    reference_number = models.CharField(
        max_length=60,
        unique=True,
        verbose_name='رقم القيد السيادي الموحد'
    )
    transaction_type = models.CharField(
        max_length=40,
        choices=TransactionType.choices,
        verbose_name='نوع المعاملة السيادية'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_sovereign_transactions',
        verbose_name='المستخدم الراسل'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_sovereign_transactions',
        verbose_name='المستخدم المستلم المختص'
    )
    sending_authority = models.CharField(max_length=150, verbose_name='الجهة أو الديوان الراسل')
    receiving_authority = models.CharField(max_length=150, verbose_name='الجهة أو الديوان المستلم')
    subject = models.CharField(max_length=255, verbose_name='موضوع المعاملة')
    description = models.TextField(verbose_name='بيان ومحتوى المعاملة والمرفقات')
    official_document = models.FileField(
        upload_to='transactions/%Y/',
        blank=True,
        null=True,
        verbose_name='الوثيقة أو المذكرة الرسمية المرفقة'
    )
    submission_date = models.DateTimeField(default=timezone.now, verbose_name='تاريخ القيد والإرسال')
    status = models.CharField(
        max_length=35,
        choices=TransactionStatus.choices,
        default=TransactionStatus.SUBMITTED,
        verbose_name='حالة المعاملة'
    )
    action_reason = models.TextField(blank=True, verbose_name='أسباب ومسوغات القرار أو التوجيه')
    
    # Contextual linkages
    meeting = models.ForeignKey(
        CouncilMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name='جلسة المجلس المرتبطة'
    )
    application = models.ForeignKey(
        'accreditation.AccreditationApplication',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name='طلب الاعتماد المرتبط'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'معاملة ومراسلة سيادية موحدة'
        verbose_name_plural = 'سجل المعاملات والمراسلات السيادية الموحدة'
        ordering = ['-submission_date', '-created_at']

    def __str__(self):
        return f"{self.reference_number}: {self.subject} ({self.get_status_display()})"

    def transition_to(self, new_status, actor, reason=''):
        """Performs a controlled, auditable status transition."""
        old_status = self.status
        self.status = new_status
        if reason:
            self.action_reason = reason
        self.save()
        TransactionMovementHistory.objects.create(
            transaction=self,
            from_status=old_status,
            to_status=new_status,
            actor=actor,
            notes=reason
        )

    @classmethod
    def record_lifecycle_movement(
        cls,
        transaction_type,
        subject,
        description,
        sender=None,
        recipient=None,
        sending_authority='',
        receiving_authority='',
        status=None,
        action_reason='',
        from_status='DRAFT',
        application=None,
        meeting=None,
        official_document=None,
        prefix='TX',
    ):
        """
        Records a verifiable transaction and movement history entry in the Central Sovereign Transaction Engine.
        """
        status = status or cls.TransactionStatus.SUBMITTED
        if not sending_authority and sender:
            if getattr(sender, 'institution', None):
                sending_authority = f"{sender.institution.name} ({sender.get_role_display()})"
            else:
                sending_authority = f"مجلس الاعتماد الأكاديمي ({sender.get_role_display()})"
        if not receiving_authority and recipient:
            if getattr(recipient, 'institution', None):
                receiving_authority = f"{recipient.institution.name} ({recipient.get_role_display()})"
            else:
                receiving_authority = f"مجلس الاعتماد الأكاديمي ({recipient.get_role_display()})"

        ref_num = f"{prefix}-{timezone.now().year}-{uuid.uuid4().hex[:8].upper()}"
        while cls.objects.filter(reference_number=ref_num).exists():
            ref_num = f"{prefix}-{timezone.now().year}-{uuid.uuid4().hex[:8].upper()}"

        trx = cls.objects.create(
            reference_number=ref_num,
            transaction_type=transaction_type,
            sender=sender if (sender and getattr(sender, 'is_authenticated', False)) else None,
            recipient=recipient if (recipient and getattr(recipient, 'is_authenticated', False)) else None,
            sending_authority=sending_authority or 'مجلس الاعتماد الأكاديمي',
            receiving_authority=receiving_authority or 'الأمانة العامة لمجلس الاعتماد',
            subject=subject[:255],
            description=description,
            official_document=official_document,
            status=status,
            action_reason=action_reason,
            application=application,
            meeting=meeting,
        )
        TransactionMovementHistory.objects.create(
            transaction=trx,
            from_status=from_status,
            to_status=status,
            actor=sender if (sender and getattr(sender, 'is_authenticated', False)) else None,
            notes=action_reason or description[:255],
        )
        return trx


class TransactionMovementHistory(models.Model):
    transaction = models.ForeignKey(
        SovereignTransaction,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name='المعاملة السيادية'
    )
    from_status = models.CharField(max_length=35, verbose_name='من حالة')
    to_status = models.CharField(max_length=35, verbose_name='إلى حالة')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='المستخدم المنفذ'
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات ومسوغات الإجراء')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ وساعة الإجراء')

    class Meta:
        verbose_name = 'حركة قيد المعاملة السيادية'
        verbose_name_plural = 'سجل حركات وتدرج المعاملات السيادية'
        ordering = ['-timestamp']
