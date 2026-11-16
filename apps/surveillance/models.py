from django.db import models
from django.conf import settings
from django.utils import timezone


class ContinuousImprovementPlan(models.Model):
    class PlanStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة قيد الإعداد'
        SUBMITTED = 'SUBMITTED', 'تم التقديم وبانتظار المراجعة الفنية'
        UNDER_REVIEW = 'UNDER_REVIEW', 'قيد الفحص والمراجعة الفنية من الأمانة'
        NEEDS_REVISION = 'NEEDS_REVISION', 'معاد للمؤسسة للتعديل أو استكمال الشواهد'
        RESUBMITTED = 'RESUBMITTED', 'معاد تسليمه بعد التعديل'
        TECHNICALLY_REVIEWED = 'TECHNICALLY_REVIEWED', 'تمت المراجعة الفنية ومستوفٍ'
        REFERRED_TO_COUNCIL = 'REFERRED_TO_COUNCIL', 'مرفوع لمجلس الإدارة للاعتماد والبت'
        APPROVED_BY_COUNCIL = 'APPROVED_BY_COUNCIL', 'معتمد رسمياً من مجلس الإدارة'
        FOLLOWUP_REQUIRED = 'FOLLOWUP_REQUIRED', 'يتطلب متابعة استطلاعية ميدانية'
        COMPLETED = 'COMPLETED', 'مكتمل ومغلق'

    decision = models.OneToOneField(
        'decisions.AccreditationDecision',
        on_delete=models.CASCADE,
        related_name='improvement_plan',
        verbose_name='قرار الاعتماد المرتبط'
    )
    plan_title = models.CharField(max_length=255, verbose_name='عنوان خطة التحسين المستمر')
    status = models.CharField(
        max_length=35,
        choices=PlanStatus.choices,
        default=PlanStatus.DRAFT,
        verbose_name='حالة خطة التحسين'
    )
    submission_date = models.DateField(auto_now_add=True, verbose_name='تاريخ تسليم الخطة')
    implementation_timeframe = models.CharField(max_length=100, verbose_name='الفترة الزمنية لتنفيذ الخطة')
    corrective_actions_matrix = models.TextField(verbose_name='مصفوفة معالجة الملاحظات ونقاط التحسين')
    budget_allocated = models.CharField(max_length=100, blank=True, verbose_name='الميزانية التقديرية للتحسين')
    is_approved_by_council = models.BooleanField(default=False, verbose_name='معتمدة رسمياً من المجلس')
    approval_notes = models.TextField(blank=True, verbose_name='ملاحظات وتوجيهات المجلس على الخطة')

    # Secretariat Review Fields
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_improvement_plans',
        verbose_name='مقدم الخطة'
    )
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ ووقت التقديم')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_improvement_plans',
        verbose_name='المراجع الفني (الأمانة)'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ ووقت المراجعة الفنية')
    secretariat_review_notes = models.TextField(blank=True, verbose_name='ملاحظات ومخرجات المراجعة الفنية للأمانة')

    # Council Decision Fields
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decided_improvement_plans',
        verbose_name='المسؤول المعتمد بقرار المجلس'
    )
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ قرار المجلس')

    class Meta:
        verbose_name = 'خطة تحسين مستمر'
        verbose_name_plural = 'خطط التحسين المستمر'

    def __str__(self):
        return f"خطة تحسين: {self.plan_title} ({self.get_status_display()})"

    @property
    def is_editable_by_institution(self):
        """Institution can edit only while in DRAFT or NEEDS_REVISION states."""
        return self.status in [self.PlanStatus.DRAFT, self.PlanStatus.NEEDS_REVISION]


class AnnualMonitoringReport(models.Model):
    class ReviewStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة قيد الإعداد'
        SUBMITTED = 'SUBMITTED', 'مقدم وبانتظار المراجعة'
        UNDER_REVIEW = 'UNDER_REVIEW', 'قيد المراجعة الفنية من الأمانة'
        NEEDS_CORRECTION = 'NEEDS_CORRECTION', 'ملاحظات ومعاد للمؤسسة للتعديل والتوضيح'
        RESUBMITTED = 'RESUBMITTED', 'معاد تسليمه بعد التعديل'
        TECHNICALLY_ACCEPTED = 'TECHNICALLY_ACCEPTED', 'مقبول فنياً من الأمانة ومرفوع للمجلس'
        REFERRED_TO_COUNCIL = 'REFERRED_TO_COUNCIL', 'معروض على مجلس الإدارة'
        SATISFACTORY = 'SATISFACTORY', 'مستوفٍ ومعتمد من المجلس (استمرار سريان الاعتماد)'
        TRIGGER_SITE_AUDIT = 'TRIGGER_SITE_AUDIT', 'يتطلب تنفيذ زيارة استطلاعية تحققية'
        ACTION_REQUIRED = 'ACTION_REQUIRED', 'توجيه إنذار أو اشتراطات تصحيحية من المجلس'

    decision = models.ForeignKey(
        'decisions.AccreditationDecision',
        on_delete=models.CASCADE,
        related_name='annual_reports',
        verbose_name='وثيقة الاعتماد'
    )
    year_number = models.PositiveIntegerField(default=1, verbose_name='رقم سنة المتابعة (1، 2، 3، 4)')
    reporting_period = models.CharField(max_length=50, verbose_name='فترة التقرير (مثلاً 2026 / 2027)')
    submission_date = models.DateField(auto_now_add=True, verbose_name='تاريخ الرفع')
    progress_summary = models.TextField(verbose_name='ملخص التقدم المحرز في تنفيذ توصيات الاعتماد')
    quality_improvements_achieved = models.TextField(verbose_name='أبرز التحسينات المضافة على البنية والعمليات الأكاديمية')
    report_file = models.FileField(upload_to='surveillance/reports/%Y/', blank=True, null=True, verbose_name='ملف التقرير السنوي المرفق')
    review_status = models.CharField(
        max_length=30,
        choices=ReviewStatus.choices,
        default=ReviewStatus.UNDER_REVIEW,
        verbose_name='حالة تقييم المجلس للتقرير'
    )
    council_feedback_comments = models.TextField(blank=True, verbose_name='ملاحظات ومخرجات مراجعة المجلس')

    # Secretariat Follow-up Fields
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_annual_reports',
        verbose_name='مقدم التقرير'
    )
    secretariat_review_comments = models.TextField(blank=True, verbose_name='ملاحظات المراجعة الفنية للأمانة')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_annual_reports',
        verbose_name='المراجع الفني (الأمانة)'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ المراجعة الفنية')
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ قرار المجلس')

    class Meta:
        verbose_name = 'تقرير متابعة سنوي'
        verbose_name_plural = 'تقارير المتابعة السنوية'
        ordering = ['decision', 'year_number']

    def __str__(self):
        return f"تقرير المتابعة السنوي ({self.year_number}) - {self.reporting_period} ({self.get_review_status_display()})"

    @property
    def is_editable_by_institution(self):
        """Institution can edit only while in DRAFT or NEEDS_CORRECTION states."""
        return self.review_status in [self.ReviewStatus.DRAFT, self.ReviewStatus.NEEDS_CORRECTION]


class SurveillanceVisit(models.Model):
    class VisitReason(models.TextChoices):
        ROUTINE = 'ROUTINE', 'زيارة متابعة دورية عادية'
        CONDITIONAL_FOLLOWUP = 'CONDITIONAL_FOLLOWUP', 'زيارة استطلاعية للتحقق من إزالة شروط الاعتماد المشروط'
        EXCEPTIONAL = 'EXCEPTIONAL', 'زيارة استطلاعية استثنائية طارئة'

    class ComplianceStatus(models.TextChoices):
        MAINTAINED = 'MAINTAINED', 'محافظ على معايير الجودة والاعتماد'
        CONDITIONAL_COMPLIED = 'CONDITIONAL_COMPLIED', 'تم استيفاء الشروط والترقية للاعتماد الكامل'
        WARNING_ISSUED = 'WARNING_ISSUED', 'وجود تراجع ملحوظ وتوجيه إنذار لتصحيح المسار'
        REVOCATION_RECOMMENDED = 'REVOCATION_RECOMMENDED', 'قصور فادح والتوصية بسحب/تعليق وثيقة الاعتماد'

    class VisitStatus(models.TextChoices):
        ASSIGNED = 'ASSIGNED', 'مكلف ومجدول'
        IN_PROGRESS = 'IN_PROGRESS', 'قيد المعاينة الميدانية'
        REPORT_SUBMITTED = 'REPORT_SUBMITTED', 'تم تسليم تقرير المحكمين للأمانة'
        COMPLETED = 'COMPLETED', 'مكتمل ومعتمد بقرار المجلس'

    decision = models.ForeignKey(
        'decisions.AccreditationDecision',
        on_delete=models.CASCADE,
        related_name='surveillance_visits',
        verbose_name='وثيقة الاعتماد الميداني'
    )
    visit_type = models.CharField(
        max_length=30,
        choices=VisitReason.choices,
        default=VisitReason.ROUTINE,
        verbose_name='نوع الزيارة الاستطلاعية'
    )
    status = models.CharField(
        max_length=30,
        choices=VisitStatus.choices,
        default=VisitStatus.ASSIGNED,
        verbose_name='حالة الزيارة والتكليف'
    )
    visit_date = models.DateField(verbose_name='تاريخ الزيارة')
    scope_and_deliverables = models.TextField(blank=True, verbose_name='نطاق التكليف والمخرجات المطلوبة من المحكمين')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='initiated_surveillance_visits',
        verbose_name='المسؤول المكلف (الأمانة)'
    )
    auditors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='surveillance_audits',
        verbose_name='المحكمون والخبراء المكلفون بالزيارة'
    )
    coi_declared_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='surveillance_coi_declarations',
        verbose_name='المحكمون الذين وقعوا إقرار النزاهة والحياد'
    )

    # Reviewer deliverables & report
    field_audit_report = models.TextField(verbose_name='تقرير ونتائج المعاينة الميدانية الاستطلاعية')
    findings_verified_progress = models.TextField(blank=True, verbose_name='التقدم المحرز الذي تم التحقق منه واقعياً')
    remaining_gaps = models.TextField(blank=True, verbose_name='الفجوات ونقاط القصور المتبقية')
    supporting_evidence_notes = models.TextField(blank=True, verbose_name='ملاحظات التحقق من الأدلة والشواهد الميدانية')
    compliance_result = models.CharField(
        max_length=35,
        choices=ComplianceStatus.choices,
        default=ComplianceStatus.MAINTAINED,
        verbose_name='نتيجة الزيارة الاستطلاعية'
    )
    recommendations_to_council = models.TextField(verbose_name='التوصيات المرفوعة إلى مجلس الإدارة')
    secretariat_review_notes = models.TextField(blank=True, verbose_name='مراجعة الأمانة لتقرير المحكمين')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='تاريخ إنشاء التكليف')

    class Meta:
        verbose_name = 'زيارة استطلاعية ومتابعة'
        verbose_name_plural = 'الزيارات الاستطلاعية والمتابعة'
        ordering = ['-visit_date']

    def __str__(self):
        return f"زيارة استطلاعية ({self.get_visit_type_display()}) بتاريخ {self.visit_date} ({self.get_status_display()})"


class CorrectiveActionItem(models.Model):
    class ActionStatus(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'لم يبدأ بعد'
        IN_PROGRESS = 'IN_PROGRESS', 'قيد التنفيذ'
        SUBMITTED_FOR_REVIEW = 'SUBMITTED_FOR_REVIEW', 'مرفوع للمراجعة الفنية'
        VERIFIED_AND_ACCEPTED = 'VERIFIED_AND_ACCEPTED', 'تم التحقق والقبول بنجاح'
        OVERDUE = 'OVERDUE', 'متأخر عن الموعد المحدد'

    plan = models.ForeignKey(
        ContinuousImprovementPlan,
        on_delete=models.CASCADE,
        related_name='action_items',
        verbose_name='خطة التحسين المستمر'
    )
    deficiency_title = models.CharField(max_length=255, verbose_name='الملاحظة أو القصور المطلوب معالجته')
    corrective_activity = models.TextField(verbose_name='الإجراء التصحيحي / النشاط التطويري')
    responsible_person = models.CharField(max_length=150, verbose_name='المسؤول المباشر عن التنفيذ')
    department = models.CharField(max_length=150, blank=True, verbose_name='الجهة / القسم المسؤول عن التنفيذ')
    due_date = models.DateField(verbose_name='تاريخ الاستحقاق والإنجاز')
    kpi_measure = models.CharField(max_length=255, verbose_name='مؤشر قياس التحقق من الإنجاز')
    evidence_document = models.FileField(
        upload_to='surveillance/corrective_evidence/%Y/',
        blank=True,
        null=True,
        verbose_name='الشاهد أو الوثيقة الثبوتية للمعالجة'
    )
    status = models.CharField(
        max_length=30,
        choices=ActionStatus.choices,
        default=ActionStatus.IN_PROGRESS,
        verbose_name='حالة الإجراء'
    )
    secretariat_verification_notes = models.TextField(blank=True, verbose_name='ملاحظات تحقق الأمانة')
    council_verification_notes = models.TextField(blank=True, verbose_name='ملاحظات تحقق المجلس')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'بند إجراء تصحيحي'
        verbose_name_plural = 'بنود الإجراءات التصحيحية'
        ordering = ['due_date']

    def __str__(self):
        return f"{self.deficiency_title} ({self.get_status_display()})"


class ImprovementPlanEvidence(models.Model):
    plan = models.ForeignKey(
        ContinuousImprovementPlan,
        on_delete=models.CASCADE,
        related_name='evidences',
        verbose_name='خطة التحسين المستمر'
    )
    action_item = models.ForeignKey(
        CorrectiveActionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evidences',
        verbose_name='بند الإجراء التصحيحي المرتبط'
    )
    annual_report = models.ForeignKey(
        AnnualMonitoringReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evidences',
        verbose_name='تقرير المتابعة السنوي المرتبط'
    )
    title = models.CharField(max_length=255, verbose_name='عنوان الوثيقة / الشاهد')
    description = models.TextField(blank=True, verbose_name='شرح محتوى الشاهد')
    evidence_file = models.FileField(upload_to='surveillance/evidences/%Y/', verbose_name='ملف الشاهد المرفق')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_surveillance_evidences',
        verbose_name='المستخدم الرافع'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الرفع')

    class Meta:
        verbose_name = 'شاهد ووثيقة خطة التحسين'
        verbose_name_plural = 'شواهد ووثائق خطط التحسين'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} ({self.plan.plan_title})"
