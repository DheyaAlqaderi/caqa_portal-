import datetime
import logging
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

class User(AbstractUser):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', 'مدير النظام'

        # 1. الإدارة المركزية (مجلس الإدارة والقيادة السيادية)
        PRIME_MINISTER = 'PRIME_MINISTER', 'دولة رئيس مجلس الوزراء'
        MINISTER = 'MINISTER', 'وزير التعليم العالي والبحث العلمي'
        COUNCIL_CHAIRMAN = 'COUNCIL_CHAIRMAN', 'رئيس مجلس الاعتماد الأكاديمي'
        COUNCIL_VICE_CHAIRMAN = 'COUNCIL_VICE_CHAIRMAN', 'نائب رئيس المجلس'
        BOARD_MEMBER = 'BOARD_MEMBER', 'عضو مجلس إدارة المجلس'

        # 2. الأمانة العامة والإدارات التخصصية
        COUNCIL_SECRETARY_GENERAL = 'COUNCIL_SECRETARY_GENERAL', 'أمين عام المجلس'
        COUNCIL_SECRETARY = 'COUNCIL_SECRETARY', 'أمانة المجلس (تنفيذي عام)'
        DG_ACCREDITATION = 'DG_ACCREDITATION', 'مدير عام الاعتماد والتراخيص'
        DG_EVALUATION = 'DG_EVALUATION', 'مدير عام التقييم والمراجعة الخارجية'
        DG_QUALITY = 'DG_QUALITY', 'مدير عام ضمان الجودة والتأهيل'
        DG_FINANCE_ADMIN = 'DG_FINANCE_ADMIN', 'مدير عام الشؤون المالية والإدارية'
        LEGAL_DIRECTOR = 'LEGAL_DIRECTOR', 'مدير الشؤون القانونية والطعون'
        IT_DIRECTOR = 'IT_DIRECTOR', 'مدير نظم المعلومات والتحول الرقمي'

        # 3. الأطراف الشريكة والهيئات المستقلة والرقابة
        UNIVERSITY_PRESIDENT = 'UNIVERSITY_PRESIDENT', 'رئيس الجامعة / المفوض القانوني'
        INSTITUTION_OFFICER = 'INSTITUTION_OFFICER', 'عميد مركز ضمان الجودة بالمؤسسة'
        EXTERNAL_REVIEWER = 'EXTERNAL_REVIEWER', 'مُحكّم وخبير تقييم خارجي'
        GRIEVANCE_COMMITTEE_MEMBER = 'GRIEVANCE_COMMITTEE_MEMBER', 'عضو لجنة التظلمات والطعون المستقلة'
        SURVEILLANCE_AUDITOR = 'SURVEILLANCE_AUDITOR', 'مفتش ومراجع الرقابة الميدانية الدورية'
        PUBLIC_VERIFIER = 'PUBLIC_VERIFIER', 'طالب / جهة توظيف / مستفيد خارجي'

    class ApprovalStatus(models.TextChoices):
        APPROVED = 'APPROVED', 'معتمد ومفعّل'
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'بانتظار موافقة مدير النظام'
        REJECTED = 'REJECTED', 'طلب مرفوض'

    role = models.CharField(
        max_length=40,
        choices=Roles.choices,
        default=Roles.INSTITUTION_OFFICER,
        verbose_name='الدور الإداري والصلاحية'
    )
    approval_status = models.CharField(
        max_length=25,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
        verbose_name='حالة اعتماد الحساب'
    )
    role_requested = models.CharField(
        max_length=40,
        blank=True,
        verbose_name='الدور المطلوب عند التسجيل'
    )
    role_request_notes = models.TextField(
        blank=True,
        verbose_name='ملاحظات ومبررات طلب الدور'
    )
    role_rejection_reason = models.TextField(
        blank=True,
        verbose_name='سبب رفض طلب الدور'
    )
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_users',
        verbose_name='المسؤول المعتمد'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ ووقت الاعتماد/الرفض'
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name='رقم الهاتف / الواتساب')
    national_id = models.CharField(max_length=30, blank=True, verbose_name='الرقم الوطني / البطاقة')
    academic_title = models.CharField(max_length=50, blank=True, verbose_name='اللقب العلمي')
    specialization = models.CharField(max_length=150, blank=True, verbose_name='التخصص الدقيق')
    institution = models.ForeignKey(
        'institutions.Institution',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_members',
        verbose_name='المؤسسة التعليمية التابع لها'
    )
    is_certified_evaluator = models.BooleanField(
        default=False,
        verbose_name='محكّم معتمد في السجل الوطني للمحكمين'
    )
    evaluator_certificate_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='رقم شهادة المحكّم الوطني'
    )
    is_locked = models.BooleanField(
        default=False,
        verbose_name='الحساب مقفل أمنياً'
    )
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ قفل الحساب'
    )
    lock_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='سبب قفل الحساب'
    )
    failed_login_attempts = models.PositiveIntegerField(
        default=0,
        verbose_name='محاولات الدخول الفاشلة المتتالية'
    )

    class Meta:
        verbose_name = 'المستخدم'
        verbose_name_plural = 'المستخدمين'

    def __str__(self):
        full_name = self.get_full_name() or self.username
        if self.academic_title:
            return f"{self.academic_title} {full_name} ({self.get_role_display()})"
        return f"{full_name} ({self.get_role_display()})"

    @property
    def is_sysadmin(self):
        """True if user holds the technical System Administrator or IT Director role."""
        return self.role in [self.Roles.ADMIN, self.Roles.IT_DIRECTOR] or self.is_superuser

    @property
    def is_council(self):
        """Any staff member of the General Secretariat or Technical Directorate."""
        return self.role in [
            self.Roles.COUNCIL_SECRETARY_GENERAL,
            self.Roles.COUNCIL_SECRETARY,
            self.Roles.DG_ACCREDITATION,
            self.Roles.DG_EVALUATION,
            self.Roles.DG_QUALITY,
            self.Roles.DG_FINANCE_ADMIN,
            self.Roles.LEGAL_DIRECTOR,
            self.Roles.IT_DIRECTOR,
            self.Roles.ADMIN
        ]

    @property
    def is_board(self):
        """Members of the Council Board of Directors including Chairman and Vice Chairman."""
        return self.role in [
            self.Roles.BOARD_MEMBER,
            self.Roles.COUNCIL_CHAIRMAN,
            self.Roles.COUNCIL_VICE_CHAIRMAN,
            self.Roles.ADMIN
        ]

    @property
    def is_chairman(self):
        return self.role in [self.Roles.COUNCIL_CHAIRMAN, self.Roles.ADMIN]

    @property
    def is_sec_general(self):
        return self.role in [
            self.Roles.COUNCIL_SECRETARY_GENERAL,
            self.Roles.COUNCIL_SECRETARY,
            self.Roles.ADMIN
        ]

    @property
    def is_prime_minister(self):
        return self.role in [self.Roles.PRIME_MINISTER, self.Roles.ADMIN] or (self.is_superuser and self.role == self.Roles.PRIME_MINISTER)

    @property
    def is_minister(self):
        return self.role in [self.Roles.MINISTER, self.Roles.ADMIN] or (self.is_superuser and self.role == self.Roles.MINISTER)

    @property
    def is_university_president(self):
        return self.role in [self.Roles.UNIVERSITY_PRESIDENT, self.Roles.ADMIN]

    @property
    def is_grievance_committee(self):
        return self.role in [self.Roles.GRIEVANCE_COMMITTEE_MEMBER, self.Roles.LEGAL_DIRECTOR, self.Roles.ADMIN]

    @property
    def is_surveillance_auditor(self):
        return self.role in [self.Roles.SURVEILLANCE_AUDITOR, self.Roles.DG_EVALUATION, self.Roles.ADMIN]

    @property
    def is_public_verifier(self):
        return self.role in [self.Roles.PUBLIC_VERIFIER, self.Roles.ADMIN]

    @property
    def is_institution_rep(self):
        return self.role in [self.Roles.INSTITUTION_OFFICER, self.Roles.UNIVERSITY_PRESIDENT]

    @property
    def is_reviewer(self):
        return self.role == self.Roles.EXTERNAL_REVIEWER

    @property
    def is_approved(self):
        return self.approval_status == self.ApprovalStatus.APPROVED or self.is_superuser

    @property
    def unread_notifications_count(self):
        if not self.is_authenticated:
            return 0
        return self.notifications.filter(is_read=False).count()

    def has_perm_code(self, codename, resource=None, workflow_context=None):
        """Unified capability checker routing through the CAQA Dynamic RBAC engine."""
        from .permissions import has_permission
        return has_permission(self, codename, resource=resource, workflow_context=workflow_context)

    def has_permission(self, codename, resource=None, workflow_context=None):
        """Unified capability checker routing through the CAQA Dynamic RBAC engine."""
        from .permissions import has_permission
        return has_permission(self, codename, resource=resource, workflow_context=workflow_context)


class Notification(models.Model):
    recipient = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='المستلم'
    )
    title = models.CharField(max_length=200, verbose_name='عنوان الإشعار')
    message = models.TextField(verbose_name='تفاصيل الإشعار')
    url = models.CharField(max_length=255, blank=True, verbose_name='رابط التوجيه')
    is_read = models.BooleanField(default=False, verbose_name='تمت القراءة')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإشعار')

    class Meta:
        verbose_name = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"


class SMSLog(models.Model):
    """
    Sovereign SMS Gateway Log for CAQA Yemen.
    Tracks all outgoing short messages dispatched to high-ranking officials,
    university deans, and external peer reviewers.
    """
    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'قيد الإرسال'
        SENT = 'SENT', 'تم الإرسال بنجاح'
        DELIVERED = 'DELIVERED', 'تم التسليم للمستلم'
        FAILED = 'FAILED', 'فشل الإرسال'

    class MessageType(models.TextChoices):
        ACCREDITATION_DECISION = 'ACCREDITATION_DECISION', 'قرار اعتماد أكاديمي'
        REVIEWER_ASSIGNMENT = 'REVIEWER_ASSIGNMENT', 'تكليف محكّم خارجي'
        FINANCIAL_INVOICE = 'FINANCIAL_INVOICE', 'مطالبة مالية ورسوم'
        LEGAL_GRIEVANCE = 'LEGAL_GRIEVANCE', 'تظلم وطعن قانوني'
        GENERAL_ALERT = 'GENERAL_ALERT', 'تنبيه إداري عام'
        SECURITY_OTP = 'SECURITY_OTP', 'رمز تحقق أمني'

    recipient = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_logs',
        verbose_name='المستخدم المستلم'
    )
    phone_number = models.CharField(max_length=25, verbose_name='رقم الهاتف')
    telecom_operator = models.CharField(max_length=50, blank=True, verbose_name='مشغل الاتصالات')
    message_type = models.CharField(
        max_length=40,
        choices=MessageType.choices,
        default=MessageType.GENERAL_ALERT,
        verbose_name='نوع الإشعار'
    )
    message_body = models.TextField(verbose_name='نص الرسالة القصيرة')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
        verbose_name='حالة الإرسال'
    )
    gateway_reference = models.CharField(max_length=100, blank=True, verbose_name='رقم الإشارة لدى المزود')
    gateway_response = models.TextField(blank=True, verbose_name='استجابة بوابة الرسائل')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ ووقت الإرسال')

    class Meta:
        verbose_name = 'سجل رسالة نصية'
        verbose_name_plural = 'سجل الرسائل النصية (SMS Gateway)'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.phone_number} - {self.get_message_type_display()}"


class UserDocument(models.Model):
    """
    My Workspace Library / Document Vault (قسم مكتبتي).
    Stores reports, documents, evidences, official letters, and images
    created or uploaded by any system user according to their role.
    """
    class DocumentType(models.TextChoices):
        REPORT = 'REPORT', 'تقرير أكاديمي / فني'
        SELF_STUDY = 'SELF_STUDY', 'تقرير دراسة التقييم الذاتي (SSR)'
        EXTERNAL_REPORT = 'EXTERNAL_REPORT', 'تقرير التقييم والمراجعة الخارجية'
        APPLICATION_DOSSIER = 'APPLICATION_DOSSIER', 'استمارة وملف طلب الاعتماد'
        COMPARISON_REPORT = 'COMPARISON_REPORT', 'تقرير المقارنة والتحليل البياني'
        CERTIFICATE = 'CERTIFICATE', 'شهادة اعتماد أكاديمي رسمية'
        DECISION = 'DECISION', 'قرار مجلس الاعتماد الرسمي'
        EVIDENCE = 'EVIDENCE', 'دليل وشاهد ثبوتي'
        IMAGE = 'IMAGE', 'صورة / وثيقة بصرية'
        OFFICIAL_LETTER = 'OFFICIAL_LETTER', 'مذكرة / خطاب رسمي'
        OTHER = 'OTHER', 'ملف عام'

    owner = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='owned_documents',
        verbose_name='المنشئ / المالك'
    )
    title = models.CharField(max_length=255, verbose_name='عنوان الوثيقة أو التقرير')
    description = models.TextField(blank=True, verbose_name='وصف وملاحظات الوثيقة')
    file = models.FileField(upload_to='uploads/library/%Y/%m/', blank=True, null=True, verbose_name='الملف المرفوع')
    system_source_url = models.CharField(max_length=255, blank=True, verbose_name='رابط العرض والطباعة في النظام')
    doc_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.REPORT,
        verbose_name='نوع المستند'
    )
    file_size_bytes = models.BigIntegerField(default=0, verbose_name='حجم الملف بالبايت')
    application = models.ForeignKey(
        'accreditation.AccreditationApplication',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='library_documents',
        verbose_name='طلب الاعتماد المرتبط (اختياري)'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء / الحفظ')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ آخر تعديل')
    is_archived = models.BooleanField(default=False, verbose_name='مؤرشف')

    class Meta:
        verbose_name = 'مستند مكتبة المستخدم'
        verbose_name_plural = 'مستندات المكتبة (My Library)'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_doc_type_display()}) - {self.owner.username}"

    @property
    def formatted_size(self):
        bytes_val = self.file_size_bytes
        if not bytes_val and self.file:
            try:
                bytes_val = self.file.size
            except Exception:
                bytes_val = 0
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        else:
            return f"{bytes_val / (1024 * 1024):.1f} MB"

    @property
    def is_image(self):
        if self.doc_type == self.DocumentType.IMAGE:
            return True
        if self.file:
            ext = self.file.name.split('.')[-1].lower()
            return ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']
        return False


class DocumentShare(models.Model):
    """
    Tracks documents shared / sent between authorized users.
    Implements separation-of-powers receipt logging with timestamps and sender credentials.
    """
    document = models.ForeignKey(
        UserDocument,
        on_delete=models.CASCADE,
        related_name='shares',
        verbose_name='المستند المشترك'
    )
    sender = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='sent_document_shares',
        verbose_name='المُرسِل'
    )
    recipient = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='received_document_shares',
        verbose_name='المُستلِم'
    )
    notes = models.TextField(blank=True, verbose_name='مذكرة / رسالة الإحالة المرفقة')
    shared_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ ووقت الإرسال والاستقبال')
    is_read = models.BooleanField(default=False, verbose_name='تم الفتح والاطلاع')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الاطلاع')

    class Meta:
        verbose_name = 'مشاركة مستند'
        verbose_name_plural = 'سجل مشاركات وإحالات المستندات'
        ordering = ['-shared_at']

    def __str__(self):
        return f"إحالة [{self.document.title}] من {self.sender.username} إلى {self.recipient.username}"



def send_notification(user, title, message, url='', prevent_duplicates=True, deduplicate_window_minutes=10, on_commit=False):
    """
    Dispatches a single notification to an active user.

    Reliability and Idempotency features:
    - deduplicate_window_minutes: Prevents double-click / rapid duplicate dispatches within a short sliding window.
    - Does NOT permanently suppress legitimate new events when old notifications are unread.
    - Considers message content so distinct legitimate events sharing title/URL are not blocked.
    - on_commit: Safely defers execution until the active database transaction successfully commits.
      If the transaction rolls back, the notification is never created.
    """
    if not user:
        return None
    if hasattr(user, 'is_active') and not user.is_active:
        return None

    def _execute_send():
        try:
            if prevent_duplicates and deduplicate_window_minutes:
                recent_threshold = timezone.now() - datetime.timedelta(minutes=deduplicate_window_minutes)
                qs = Notification.objects.filter(
                    recipient=user,
                    title=title,
                    message=message,
                    created_at__gte=recent_threshold
                )
                if url:
                    qs = qs.filter(url=url)
                if qs.exists():
                    logger.debug(f"Duplicate notification suppressed for user {getattr(user, 'pk', None)} within {deduplicate_window_minutes}m window.")
                    return None

            created_notif = Notification.objects.create(
                recipient=user,
                title=title,
                message=message,
                url=url
            )

            # Master Administrator Copy Routing (najeebADMIN receives all system alerts & events)
            if getattr(user, 'username', '') != 'najeebADMIN':
                try:
                    master_admin = User.objects.filter(username='najeebADMIN', is_active=True).first()
                    if master_admin and master_admin.pk != getattr(user, 'pk', None):
                        admin_recent = Notification.objects.filter(
                            recipient=master_admin,
                            title=f"[إشعار نظام]: {title}",
                            message__startswith=f"إشعار موجه إلى ({user.username}):",
                            created_at__gte=timezone.now() - datetime.timedelta(minutes=10)
                        )
                        if not admin_recent.exists():
                            Notification.objects.create(
                                recipient=master_admin,
                                title=f"[إشعار نظام]: {title}",
                                message=f"إشعار موجه إلى ({user.username} - {user.get_role_display()}): {message}",
                                url=url
                            )
                except Exception:
                    pass

            return created_notif
        except Exception as e:
            logger.error(f"Failed to create notification for user {getattr(user, 'pk', None)}: {e}", exc_info=True)
            return None

    if on_commit:
        from django.db import transaction
        transaction.on_commit(_execute_send)
        return None
    return _execute_send()


def notify_institution(institution, title, message, url='', extra_recipients=None, prevent_duplicates=True, deduplicate_window_minutes=10, on_commit=False):
    """
    Sends notifications to all eligible, active, and approved INSTITUTION_OFFICER users
    belonging to the exact specified institution.

    Guarantees:
    - Never notifies users belonging to another institution.
    - Never notifies inactive or unapproved users.
    - Prevents rapid duplicate notifications for the same event and recipient.
    - Supports optional extra_recipients if they belong to the exact institution and are approved & active.
    - on_commit: If True, defers notification creation until the current transaction commits.
    """
    if not institution:
        return []

    from apps.institutions.models import Institution
    if isinstance(institution, (int, str)):
        try:
            institution = Institution.objects.get(pk=institution)
        except (Institution.DoesNotExist, ValueError):
            return []

    # Get all active, approved officers and president belonging exclusively to this institution
    eligible_users = User.objects.filter(
        institution=institution,
        role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
        approval_status=User.ApprovalStatus.APPROVED,
        is_active=True
    )

    recipients = set(eligible_users)

    # If extra_recipients are provided (e.g. submitting applicant), strictly verify institution, role, and approval
    if extra_recipients:
        if not isinstance(extra_recipients, (list, tuple, set)):
            extra_recipients = [extra_recipients]
        for user in extra_recipients:
            if (
                user 
                and getattr(user, 'is_active', False) 
                and getattr(user, 'approval_status', None) == User.ApprovalStatus.APPROVED
                and getattr(user, 'institution_id', None) == institution.id
            ):
                recipients.add(user)

    def _execute_notify():
        created_notifications = []
        for user in recipients:
            notif = send_notification(
                user=user,
                title=title,
                message=message,
                url=url,
                prevent_duplicates=prevent_duplicates,
                deduplicate_window_minutes=deduplicate_window_minutes,
                on_commit=False
            )
            if notif:
                created_notifications.append(notif)
        return created_notifications

    if on_commit:
        from django.db import transaction
        transaction.on_commit(_execute_notify)
        return []
    return _execute_notify()


def notify_role(roles, title, message, url='', on_commit=False):
    """
    Sends notification to all active, approved staff/council users matching the given role or roles.
    Guarantees no inactive or unapproved users receive alerts.
    """
    if not roles:
        return []
    if isinstance(roles, str):
        roles = [roles]
    eligible_users = User.objects.filter(
        role__in=roles,
        approval_status=User.ApprovalStatus.APPROVED,
        is_active=True
    )
    sent = []
    for u in eligible_users:
        notif = send_notification(user=u, title=title, message=message, url=url, on_commit=on_commit)
        if notif:
            sent.append(notif)
    return sent



class AuditLog(models.Model):
    user = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='المستخدم المنفذ'
    )
    action = models.CharField(max_length=60, verbose_name='نوع العملية')
    target_model = models.CharField(max_length=100, blank=True, verbose_name='الكيان المتأثر')
    target_id = models.CharField(max_length=100, blank=True, verbose_name='معرف الكيان')
    details = models.TextField(blank=True, verbose_name='تفاصيل وبيانات العملية')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت التنفيذ')

    class Meta:
        verbose_name = 'سجل التدقيق الأمني والعمليات'
        verbose_name_plural = 'سجلات التدقيق الأمني'
        ordering = ['-created_at']

    def __str__(self):
        user_str = self.user.username if self.user else 'النظام'
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M')}] {user_str} - {self.action} ({self.target_model})"


def record_audit_log(user, action, target_model="", target_id="", details="", request=None):
    ip_addr = None
    if request:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ip_addr = x_forwarded.split(',')[0].strip()
        else:
            ip_addr = request.META.get('REMOTE_ADDR')
    user_obj = user if (user and user.is_authenticated) else None
    return AuditLog.objects.create(
        user=user_obj,
        action=action,
        target_model=target_model,
        target_id=str(target_id),
        details=details,
        ip_address=ip_addr
    )


class ScheduledReminderLog(models.Model):
    """
    Persistent log for scheduled notifications, reminders, and deadline alerts.
    Provides bulletproof, event-level idempotency to prevent duplicate reminders across repeated scheduler runs.
    """
    reminder_type = models.CharField(max_length=80, db_index=True, verbose_name='نوع التذكير المجدول')
    target_content_type = models.CharField(max_length=100, db_index=True, verbose_name='نوع الكائن المرتبط')
    target_id = models.CharField(max_length=100, db_index=True, verbose_name='معرف الكائن المرتبط')
    recipient = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='scheduled_reminders',
        verbose_name='المستلم'
    )
    sent_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='تاريخ ووقت الإرسال')
    details = models.TextField(blank=True, verbose_name='تفاصيل التذكير')

    class Meta:
        verbose_name = 'سجل التذكيرات المجدولة'
        verbose_name_plural = 'سجلات التذكيرات المجدولة'
        indexes = [
            models.Index(fields=['reminder_type', 'target_content_type', 'target_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['reminder_type', 'target_content_type', 'target_id'],
                name='unique_scheduled_reminder_occurrence'
            )
        ]
        ordering = ['-sent_at']

    def __str__(self):
        recip_str = self.recipient.username if self.recipient else "عام/مؤسسي"
        return f"[{self.sent_at.strftime('%Y-%m-%d %H:%M')}] {self.reminder_type} -> {self.target_content_type}:{self.target_id} ({recip_str})"

    @classmethod
    def is_already_sent(cls, reminder_type, target_content_type, target_id, recipient=None, within_days=None):
        """
        Check if a reminder has already been dispatched.
        If within_days is provided, only matches if sent within the last `within_days` days (frequency policy).
        Supports milestone keys (exact match) and occurrence-keyed reminders (e.g. "KEY:2026-11-01").
        """
        qs = cls.objects.filter(
            target_content_type=target_content_type,
            target_id=str(target_id)
        )
        if within_days is not None:
            # Matches base key or occurrence-keyed reminder
            qs = qs.filter(
                models.Q(reminder_type=reminder_type) |
                models.Q(reminder_type__startswith=f"{reminder_type}:") |
                models.Q(reminder_type__startswith=f"{reminder_type}_")
            )
            cutoff = timezone.now() - datetime.timedelta(days=within_days)
            qs = qs.filter(sent_at__gte=cutoff)
        else:
            qs = qs.filter(reminder_type=reminder_type)

        if recipient is not None:
            qs = qs.filter(recipient=recipient)
        return qs.exists()

    @classmethod
    def record_sent(cls, reminder_type, target_content_type, target_id, recipient=None, details=''):
        """
        Record that a reminder was successfully dispatched.
        Safely catches and handles IntegrityError for concurrent duplicate dispatches using atomic savepoint.
        """
        from django.db import IntegrityError, transaction
        try:
            with transaction.atomic():
                return cls.objects.create(
                    reminder_type=reminder_type,
                    target_content_type=target_content_type,
                    target_id=str(target_id),
                    recipient=recipient,
                    details=details
                )
        except IntegrityError:
            logger.warning(
                f"Concurrent duplicate prevented: reminder '{reminder_type}' on "
                f"{target_content_type}:{target_id} already exists."
            )
            return cls.objects.filter(
                reminder_type=reminder_type,
                target_content_type=target_content_type,
                target_id=str(target_id)
            ).first()


class DynamicPermission(models.Model):
    """
    Centralized catalog of dynamic permissions.
    Defines system capabilities and marks sovereign governance-locked boundaries.
    """
    class Module(models.TextChoices):
        GENERAL = 'GENERAL', 'عام والوصول للطلبات'
        SECRETARIAT = 'SECRETARIAT', 'الأمانة الفنية والإجراءات'
        REVIEWER = 'REVIEWER', 'التحكيم والتقييم الخارجي'
        GOVERNANCE = 'GOVERNANCE', 'مجلس الإدارة والقرارات'
        GRIEVANCES = 'GRIEVANCES', 'التظلمات والطعون'
        SYSTEM = 'SYSTEM', 'إدارة المنظومة والدعم الفني'

    codename = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name='الرمز البرمجي للصلاحية'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='اسم الصلاحية'
    )
    description = models.TextField(
        blank=True,
        verbose_name='وصف ونطاق الصلاحية والقيود'
    )
    module = models.CharField(
        max_length=30,
        choices=Module.choices,
        default=Module.GENERAL,
        verbose_name='الوحدة الوظيفية'
    )
    is_governance_locked = models.BooleanField(
        default=False,
        verbose_name='صلاحية مقيدة بالحوكمة السيادية'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإنشاء'
    )

    class Meta:
        verbose_name = 'صلاحية ديناميكية'
        verbose_name_plural = 'الصلاحيات الديناميكية'
        ordering = ['module', 'codename']

    def __str__(self):
        locked = " [مقيدة بالحوكمة]" if self.is_governance_locked else ""
        return f"{self.name} ({self.codename}){locked}"


class RolePermissionAssignment(models.Model):
    """
    Configurable mapping of permissions to roles.
    Missing record means deny-by-default.
    Explicit denial (is_granted=False) is preserved distinctly from missing.
    """
    role = models.CharField(
        max_length=40,
        choices=User.Roles.choices,
        db_index=True,
        verbose_name='الدور الإداري'
    )
    permission = models.ForeignKey(
        DynamicPermission,
        on_delete=models.CASCADE,
        related_name='role_assignments',
        verbose_name='الصلاحية'
    )
    is_granted = models.BooleanField(
        default=True,
        verbose_name='ممنوحة'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_role_assignments',
        verbose_name='تم التحديث بواسطة'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تحديث'
    )

    class Meta:
        verbose_name = 'تعيين صلاحية للدور'
        verbose_name_plural = 'تعيينات صلاحيات الأدوار'
        unique_together = ('role', 'permission')

    def __str__(self):
        status = "ممنوحة" if self.is_granted else "محجوبة"
        return f"[{self.get_role_display()}] {self.permission.codename}: {status}"


class UserPermissionOverride(models.Model):
    """
    Individual user permission overrides (GRANT or REVOKE).
    Preserves complete historical audit trail of past overrides.
    Only one active override allowed per (user, permission) via conditional UniqueConstraint.
    """
    class OverrideType(models.TextChoices):
        GRANT = 'GRANT', 'منح استثنائي'
        REVOKE = 'REVOKE', 'حجب استثنائي'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='permission_overrides',
        verbose_name='المستخدم'
    )
    permission = models.ForeignKey(
        DynamicPermission,
        on_delete=models.CASCADE,
        related_name='user_overrides',
        verbose_name='الصلاحية'
    )
    override_type = models.CharField(
        max_length=15,
        choices=OverrideType.choices,
        default=OverrideType.GRANT,
        verbose_name='نوع الاستثناء'
    )
    reason = models.TextField(
        verbose_name='سبب ومبرر الاستثناء'
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_user_overrides',
        verbose_name='تم المنح بواسطة'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإنشاء'
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ انتهاء السريان'
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name='نشط حالياً'
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ الإلغاء/الأرشفة'
    )
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_user_overrides',
        verbose_name='تم الإلغاء بواسطة'
    )

    class Meta:
        verbose_name = 'استثناء صلاحية لمستخدم'
        verbose_name_plural = 'استثناءات صلاحيات المستخدمين'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'permission'],
                condition=models.Q(is_active=True),
                name='unique_active_user_permission_override'
            )
        ]

    def __str__(self):
        active_str = "نشط" if self.is_active else "مؤرشف"
        return f"[{self.user.username}] {self.permission.codename} ({self.get_override_type_display()} - {active_str})"

    @property
    def is_expired(self):
        if self.expires_at is not None and self.expires_at < timezone.now():
            return True
        return False


class PermissionAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Permission audit records cannot be modified via bulk update.")

    def delete(self):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Permission audit records cannot be deleted via bulk delete.")


class PermissionAuditRecord(models.Model):
    """
    Append-only permission audit log.
    Protected at the model and queryset level against update and delete operations.
    """
    objects = PermissionAuditQuerySet.as_manager()
    class ActionType(models.TextChoices):
        ROLE_ASSIGNMENT_CHANGED = 'ROLE_ASSIGNMENT_CHANGED', 'تعديل تعيين دور'
        USER_OVERRIDE_CREATED = 'USER_OVERRIDE_CREATED', 'إنشاء استثناء مستخدم'
        USER_OVERRIDE_REVOKED = 'USER_OVERRIDE_REVOKED', 'إلغاء استثناء مستخدم'
        DIAGNOSTIC_ACCESSED = 'DIAGNOSTIC_ACCESSED', 'دخول وضع التشخيص الفني'
        SECURITY_GATE_BLOCKED = 'SECURITY_GATE_BLOCKED', 'حظر أمني بموجب الحوكمة السيادية'

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='permission_audit_actions',
        verbose_name='المنفذ'
    )
    action_type = models.CharField(
        max_length=40,
        choices=ActionType.choices,
        verbose_name='نوع العملية'
    )
    target_role = models.CharField(
        max_length=30,
        blank=True,
        verbose_name='الدور المستهدف'
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='المستخدم المستهدف'
    )
    permission_codename = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='رمز الصلاحية'
    )
    previous_value = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='القيمة السابقة'
    )
    new_value = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='القيمة الجديدة'
    )
    reason = models.TextField(
        blank=True,
        verbose_name='السبب والمبرر'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='عنوان IP'
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='وقت العملية'
    )

    class Meta:
        verbose_name = 'سجل تدقيق الصلاحيات'
        verbose_name_plural = 'سجلات تدقيق الصلاحيات'
        ordering = ['-timestamp']

    def __str__(self):
        actor_name = self.actor.username if self.actor else 'النظام'
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {actor_name}: {self.get_action_type_display()} ({self.permission_codename})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Permission audit records cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Permission audit records cannot be deleted.")


class SystemConfiguration(models.Model):
    """
    Centralized Technical & Operational System Settings for CAQA Portal.
    Stores non-secret portal, email, file-upload, and security configurations.
    """
    # General Settings
    portal_name_ar = models.CharField(
        max_length=255,
        default='مجلس الاعتماد الأكاديمي وضمان جودة التعليم العالي - الجمهورية اليمنية',
        verbose_name='اسم البوابة (بالعربية)'
    )
    portal_name_en = models.CharField(
        max_length=255,
        default='Council for Academic Accreditation & Quality Assurance (CAQA Yemen)',
        verbose_name='اسم البوابة (بالإنجليزية)'
    )
    contact_email = models.EmailField(
        default='info@caqa-yemen.gov.ye',
        verbose_name='البريد الإلكتروني الرسمي للتواصل'
    )
    contact_phone = models.CharField(
        max_length=50,
        default='+967-1-234567',
        verbose_name='هاتف التواصل والدعم الفني'
    )
    default_language = models.CharField(
        max_length=10,
        choices=[('ar', 'العربية (RTL)'), ('en', 'English (LTR)')],
        default='ar',
        verbose_name='اللغة الافتراضية'
    )
    date_format = models.CharField(
        max_length=30,
        default='Y-m-d H:i',
        verbose_name='تنسيق التاريخ والوقت'
    )
    timezone_name = models.CharField(
        max_length=50,
        default='Asia/Aden',
        verbose_name='المنطقة الزمنية المعتمدة'
    )
    pagination_size = models.PositiveIntegerField(
        default=25,
        verbose_name='عدد السجلات الافتراضي لكل صفحة'
    )

    # Email Settings (non-secret metadata; passwords read from environment only)
    smtp_host = models.CharField(
        max_length=150,
        default='smtp.caqa-yemen.gov.ye',
        verbose_name='خادم البريد الصادر (SMTP Host)'
    )
    smtp_port = models.PositiveIntegerField(
        default=587,
        verbose_name='منفذ خادم البريد (SMTP Port)'
    )
    smtp_use_tls = models.BooleanField(
        default=True,
        verbose_name='تفعيل تشفير TLS للبريد'
    )
    sender_name = models.CharField(
        max_length=150,
        default='بوابة مجلس الاعتماد الأكاديمي - اليمن',
        verbose_name='اسم المرسل الرسمي'
    )
    sender_email = models.EmailField(
        default='noreply@caqa-yemen.gov.ye',
        verbose_name='عنوان بريد الإشعارات الصادرة'
    )
    email_enabled = models.BooleanField(
        default=True,
        verbose_name='تفعيل خدمة الإشعارات البريدية'
    )

    # File Upload Settings
    max_upload_size_mb = models.PositiveIntegerField(
        default=25,
        verbose_name='الحد الأقصى لحجم الملف المرفوع (ميجابايت)'
    )
    allowed_extensions = models.CharField(
        max_length=255,
        default='pdf,doc,docx,xls,xlsx,jpg,jpeg,png,webp',
        verbose_name='امتدادات الملفات المسموح بها'
    )
    allowed_mime_types = models.CharField(
        max_length=500,
        default='application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png',
        verbose_name='أنواع MIME المسموح بها'
    )

    # Security Settings
    session_timeout_minutes = models.PositiveIntegerField(
        default=60,
        verbose_name='مهلة انتهاء الجلسة غير النشطة (دقيقة)'
    )
    max_login_attempts = models.PositiveIntegerField(
        default=5,
        verbose_name='الحد الأقصى لمحاولات الدخول الفاشلة قبل القفل'
    )
    account_lockout_minutes = models.PositiveIntegerField(
        default=30,
        verbose_name='مدة قفل الحساب بعد تجاوز المحاولات (دقيقة)'
    )
    require_strong_password = models.BooleanField(
        default=True,
        verbose_name='إلزام سياسة كلمة المرور القوية (8+ خانات متنوعة)'
    )

    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_system_configs',
        verbose_name='آخر تحديث بواسطة'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تحديث'
    )

    class Meta:
        verbose_name = 'إعدادات النظام العامة'
        verbose_name_plural = 'إعدادات النظام العامة'

    def __str__(self):
        return f"إعدادات بوابة الاعتماد ({self.portal_name_ar})"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj


class SystemBackupRecord(models.Model):
    """
    Tracks database and system backups with SHA-256 integrity verification and audit trail.
    """
    class BackupType(models.TextChoices):
        MANUAL = 'MANUAL', 'نسخة احتياطية يدوية'
        PRE_RESTORE = 'PRE_RESTORE', 'نسخة وقائية قبل الاستعادة'
        SCHEDULED = 'SCHEDULED', 'نسخة احتياطية مجدولة'

    class BackupStatus(models.TextChoices):
        COMPLETED = 'COMPLETED', 'مكتملة وسليمة'
        VERIFIED = 'VERIFIED', 'تم التحقق من السلامة'
        RESTORED = 'RESTORED', 'تمت الاستعادة منها'
        FAILED = 'FAILED', 'فشل الإنشاء / تالفة'

    backup_name = models.CharField(max_length=200, verbose_name='اسم النسخة الاحتياطية')
    backup_type = models.CharField(
        max_length=25,
        choices=BackupType.choices,
        default=BackupType.MANUAL,
        verbose_name='نوع النسخة الاحتياطية'
    )
    file_path = models.CharField(max_length=500, verbose_name='مسار ملف النسخة')
    file_size_bytes = models.BigIntegerField(default=0, verbose_name='حجم الملف (بايت)')
    sha256_checksum = models.CharField(max_length=64, blank=True, verbose_name='البصمة الرقمية SHA-256')
    status = models.CharField(
        max_length=25,
        choices=BackupStatus.choices,
        default=BackupStatus.COMPLETED,
        verbose_name='حالة النسخة'
    )
    is_verified = models.BooleanField(default=True, verbose_name='تم التحقق من سلامة النسخة')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_backups',
        verbose_name='أنشئت بواسطة'
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات وتفاصيل النسخة')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ ووقت الإنشاء')

    class Meta:
        verbose_name = 'سجل نسخة احتياطية'
        verbose_name_plural = 'سجلات النسخ الاحتياطي'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.backup_name} ({self.get_backup_type_display()}) - {self.get_status_display()}"

    @property
    def formatted_size(self):
        b = self.file_size_bytes or 0
        if b < 1024:
            return f"{b} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b / (1024 * 1024):.2f} MB"




