from django.db import models
from django.conf import settings
from apps.standards.models import AccreditationTrackType

class TrainingProgram(models.Model):
    title = models.CharField(max_length=255, verbose_name='عنوان البرنامج التدريبي أو ورشة العمل')
    track = models.CharField(
        max_length=25,
        choices=AccreditationTrackType.choices,
        blank=True,
        null=True,
        verbose_name='المسار الأكاديمي المستهدف'
    )
    trainer_name = models.CharField(max_length=150, verbose_name='المدرب أو الخبير المحاضر')
    start_date = models.DateField(verbose_name='تاريخ بدء التدريب')
    end_date = models.DateField(verbose_name='تاريخ ختام التدريب')
    location_or_online = models.CharField(max_length=200, default='مقر المجلس - قاعة التدريب', verbose_name='مكان الانعقاد أو الرابط الافتراضي')
    target_audience = models.CharField(max_length=200, verbose_name='الفئة المستهدفة (عمداء جودة، مقيمون، منسقو برامج)')
    materials_url = models.URLField(blank=True, verbose_name='رابط المواد والحقائب التدريبية')
    is_active = models.BooleanField(default=True, verbose_name='متاح للتسجيل والمشاركة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'برنامج تدريب وورشة عمل'
        verbose_name_plural = 'برامج التدريب والتأهيل'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.title} ({self.start_date})"


class TrainingParticipant(models.Model):
    program = models.ForeignKey(
        TrainingProgram,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name='البرنامج التدريبي'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attended_training_programs',
        verbose_name='المشارك'
    )
    attendance_rate = models.PositiveIntegerField(default=100, verbose_name='نسبة الحضور (%)')
    certificate_issued = models.BooleanField(default=False, verbose_name='صدرت شهادة مشاركة رسمية')
    registration_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مشارك في برنامج تدريبي'
        verbose_name_plural = 'المشاركون في برامج التدريب'
        unique_together = ('program', 'user')

    def __str__(self):
        return f"{self.user} - {self.program.title}"


class SupportTicket(models.Model):
    class TicketCategory(models.TextChoices):
        TECHNICAL = 'TECHNICAL', 'دعم فني واستخدام المنصة'
        PROCEDURAL = 'PROCEDURAL', 'استفسار إجرائي ولائحي'
        STANDARDS = 'STANDARDS', 'استفسار حول المعايير والشواهد'
        FINANCIAL = 'FINANCIAL', 'استفسار مالي أو رسوم'
        QUALITY_COMPLAINT = 'QUALITY_COMPLAINT', 'بلاغ أو شكوى جودة أكاديمية (طالب/جمهور)'
        VERIFICATION_REQUEST = 'VERIFICATION_REQUEST', 'طلب تحقق رسمي ومصادقة على اعتماد مؤهل (أرباب عمل)'

    class TicketStatus(models.TextChoices):
        OPEN = 'OPEN', 'مفتوحة / جديدة'
        IN_PROGRESS = 'IN_PROGRESS', 'قيد المعالجة من الفريق الفني'
        RESOLVED = 'RESOLVED', 'تم الرد والحل'
        CLOSED = 'CLOSED', 'مغلقة'

    institution = models.ForeignKey(
        'institutions.Institution',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='support_tickets',
        verbose_name='المؤسسة التعليمية المعنية'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_support_tickets',
        verbose_name='المستخدم مقدم التذكرة'
    )
    ticket_number = models.CharField(max_length=50, unique=True, verbose_name='رقم التذكرة')
    target_institution_name = models.CharField(max_length=200, blank=True, verbose_name='اسم الجامعة أو الكلية المشكو في حقها / المستفسر عنها')
    verification_code = models.CharField(max_length=100, blank=True, verbose_name='رقم الشهادة / كود التحقق المطلوب مطابقتها')
    category = models.CharField(
        max_length=25,
        choices=TicketCategory.choices,
        default=TicketCategory.TECHNICAL,
        verbose_name='تصنيف الطلب'
    )
    subject = models.CharField(max_length=255, verbose_name='عنوان الاستفسار أو المشكلة')
    message = models.TextField(verbose_name='تفاصيل الاستفسار أو الطلب')
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
        verbose_name='حالة التذكرة'
    )
    response_notes = models.TextField(blank=True, verbose_name='رد فريق الدعم الفني للمجلس')
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_support_tickets',
        verbose_name='الموظف المجيب'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإغلاق والحل')

    class Meta:
        verbose_name = 'طلب دعم فني واستفسار'
        verbose_name_plural = 'طلبات الدعم الفني والاستفسارات'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.ticket_number}] {self.subject} ({self.get_status_display()})"


class FeeSchedule(models.Model):
    service_name = models.CharField(max_length=255, verbose_name='اسم الخدمة أو مسار الاعتماد')
    track = models.CharField(
        max_length=25,
        choices=AccreditationTrackType.choices,
        verbose_name='نوع ومسار الاعتماد'
    )
    regulatory_reference = models.CharField(max_length=200, verbose_name='السند القانوني ولائحة الرسوم الوزارية المعتمدة')
    amount_yer = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='الرسم القانوني المعتمد (ريال يمني)')
    is_active = models.BooleanField(default=True, verbose_name='ساري المفعول')
    notes = models.TextField(blank=True, verbose_name='ملاحظات تنظيمية')

    class Meta:
        verbose_name = 'لائحة رسوم معتمدة'
        verbose_name_plural = 'لوائح الرسوم المعتمدة'

    def __str__(self):
        return f"{self.service_name} ({self.amount_yer:,.0f} ر.ي)"


class Invoice(models.Model):
    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'بانتظار السداد'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'مسدد جزئياً'
        PAID = 'PAID', 'مسدد بالكامل'
        EXEMPTED = 'EXEMPTED', 'معفى بقرار وزاري'

    invoice_number = models.CharField(max_length=50, unique=True, verbose_name='رقم المطالبة المالية')
    application = models.ForeignKey(
        'accreditation.AccreditationApplication',
        on_delete=models.CASCADE,
        related_name='invoices',
        verbose_name='طلب الاعتماد المرتبط'
    )
    fee_schedule = models.ForeignKey(
        FeeSchedule,
        on_delete=models.PROTECT,
        verbose_name='بند الرسوم المعتمد'
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='إجمالي المبلغ المطلوب (ر.ي)')
    status = models.CharField(
        max_length=25,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        verbose_name='حالة السداد'
    )
    payment_reference = models.CharField(max_length=150, blank=True, verbose_name='رقم وتاريخ إشعار التوريد البنكي')
    proof_of_payment = models.FileField(
        upload_to='invoices/receipts/%Y/',
        blank=True,
        null=True,
        verbose_name='سند التوريد البنكي الرسمي'
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_invoices',
        verbose_name='المسؤول المالي المراجع'
    )
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ إصدار المطالبة')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ تأكيد السداد')

    class Meta:
        verbose_name = 'مطالبة وسداد مالي'
        verbose_name_plural = 'المطالبات والرسوم المالية'
        ordering = ['-issued_at']

    def __str__(self):
        return f"مطالبة ({self.invoice_number}) - {self.application.institution.name} ({self.get_status_display()})"

    @property
    def amount_due(self):
        return self.total_amount
