from django.db import models
from django.conf import settings
from apps.standards.models import AccreditationTrackType, StandardIndicator, RubricEvaluationLevel

class StageChoices(models.IntegerChoices):
    STAGE_1 = 1, 'المرحلة 1: التهيئة والدراسة الذاتية ورفع الشواهد'
    STAGE_2 = 2, 'المرحلة 2: الفحص المكتبي الأولي واستيفاء الشروط'
    STAGE_3 = 3, 'المرحلة 3: تشكيل لجان المراجعة والتقييم الخارجي'
    STAGE_4 = 4, 'المرحلة 4: الزيارة الميدانية والمعاينة الواقعية'
    STAGE_5 = 5, 'المرحلة 5: مسودة التقرير، حق الرد، والتقرير النهائي'
    STAGE_6 = 6, 'المرحلة 6: مداولات المجلس وقرار الاعتماد والشهادة'
    STAGE_7 = 7, 'المرحلة 7: المتابعة السنوية الدورية والتحسين المستمر'

class ApplicationStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'مسودة قيد الإعداد'
    PENDING_REVIEW = 'PENDING_REVIEW', 'تم التقديم وينتظر مراجعة المجلس وتحديد التكلفة'
    PRESIDENT_ENDORSED = 'PRESIDENT_ENDORSED', 'معتمد ومصادق عليه من رئيس الجامعة'
    ACCEPTED_PENDING_SELF_EVALUATION = 'ACCEPTED_PENDING_SELF_EVALUATION', 'تم قبول الطلب وتحديد التكلفة'
    SELF_EVALUATION_IN_PROGRESS = 'SELF_EVALUATION_IN_PROGRESS', 'التقييم الذاتي قيد الإعداد'
    SELF_EVALUATION_SUBMITTED = 'SELF_EVALUATION_SUBMITTED', 'تم تسليم التقييم الذاتي رسمياً'
    REJECTED = 'REJECTED', 'طلب اعتماد مرفوض'
    SUBMITTED = 'SUBMITTED', 'تم التقديم رسمياً للأمانة'
    DESK_UNDER_REVIEW = 'DESK_UNDER_REVIEW', 'قيد الفحص المكتبي'
    DESK_DEFICIENCY = 'DESK_DEFICIENCY', 'نقص وثائق مطلوب استكماله'
    DESK_ACCEPTED = 'DESK_ACCEPTED', 'مستوفي للشروط والأهلية'
    FINANCIAL_CLEARED = 'FINANCIAL_CLEARED', 'مستوفي السداد والإبراء المالي'
    PANEL_ASSIGNED = 'PANEL_ASSIGNED', 'تم تشكيل لجنة التقييم الخارجي'
    SITE_VISIT_SCHEDULED = 'SITE_VISIT_SCHEDULED', 'الزيارة الميدانية مجدولة'
    SITE_VISIT_COMPLETED = 'SITE_VISIT_COMPLETED', 'اكتملت الزيارة الميدانية'
    DRAFT_REPORT_ISSUED = 'DRAFT_REPORT_ISSUED', 'صدرت مسودة تقرير المراجعة'
    WAITING_INSTITUTION_RESPONSE = 'WAITING_INSTITUTION_RESPONSE', 'بانتظار رد المؤسسة (حق الرد)'
    RESPONSE_SUBMITTED = 'RESPONSE_SUBMITTED', 'تم استلام رد المؤسسة'
    FINAL_REPORT_READY = 'FINAL_REPORT_READY', 'التقرير النهائي معتمد من المحكمين'
    IN_COUNCIL_REVIEW = 'IN_COUNCIL_REVIEW', 'معروض على مجلس الإدارة'
    FULL_ACCREDITATION = 'FULL_ACCREDITATION', 'حاصل على الاعتماد الكامل (5 سنوات)'
    CONDITIONAL_ACCREDITATION = 'CONDITIONAL_ACCREDITATION', 'حاصل على الاعتماد المشروط'
    DENIED = 'DENIED', 'تأجيل أو رفض الاعتماد'


class AccreditationApplication(models.Model):
    application_number = models.CharField(max_length=50, unique=True, verbose_name='رقم الطلب الرسمي')
    track = models.CharField(
        max_length=30,
        choices=AccreditationTrackType.choices,
        verbose_name='نوع ومسار الاعتماد'
    )
    institution = models.ForeignKey(
        'institutions.Institution',
        on_delete=models.CASCADE,
        related_name='accreditation_applications',
        verbose_name='المؤسسة المتقدمة'
    )
    program = models.ForeignKey(
        'institutions.AcademicProgram',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='program_applications',
        verbose_name='البرنامج الأكاديمي المعني (في حال الاعتماد البرامجي أو الطبي)'
    )
    applicant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_applications',
        verbose_name='المسؤول مقدم الطلب'
    )
    standard_version = models.ForeignKey(
        'standards.StandardVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='applications',
        verbose_name='إصدار المعايير المطبق على الطلب'
    )
    academic_year = models.CharField(max_length=20, default='2025/2026', verbose_name='العام الأكاديمي')
    current_stage = models.IntegerField(
        choices=StageChoices.choices,
        default=StageChoices.STAGE_1,
        verbose_name='المرحلة الحالية من دورة العمل'
    )
    status = models.CharField(
        max_length=40,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.DRAFT,
        verbose_name='حالة الطلب التفصيلية'
    )
    submission_date = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التقديم الرسمي')
    
    # Pricing & Acceptance by Council Board
    cost_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='تكلفة الاعتماد المعتمدة (ريال يمني/دولار)')
    cost_currency = models.CharField(max_length=15, default='YER', verbose_name='العملة')
    cost_breakdown_notes = models.TextField(blank=True, verbose_name='تفاصيل وبنود تكلفة الاعتماد')
    council_approval_notes = models.TextField(blank=True, verbose_name='رسالة وتوجيهات المجلس للمؤسسة عند القبول')
    
    # Rejection by Council Board
    rejection_reason = models.TextField(blank=True, verbose_name='سبب رفض الطلب الرسمي')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_applications',
        verbose_name='المسؤول المراجع بالمجلس'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ مراجعة وقرار الطلب')

    # University President Sovereign Endorsement
    president_endorsed = models.BooleanField(default=False, verbose_name='معتمد وموقع من رئيس الجامعة')
    president_endorsed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='endorsed_applications',
        verbose_name='رئيس الجامعة المعتمد'
    )
    president_endorsed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ اعتماد رئيس الجامعة')
    president_decree_ref = models.CharField(max_length=150, blank=True, verbose_name='قرار / تفويض رئيس الجامعة')

    # Contact & Additional Details
    contact_person_name = models.CharField(max_length=150, blank=True, verbose_name='اسم مسؤول التواصل')
    contact_phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف مسؤول التواصل')
    contact_email = models.EmailField(blank=True, verbose_name='البريد الإلكتروني لمسؤول التواصل')
    notes = models.TextField(blank=True, verbose_name='ملاحظات وبيانات إضافية')
    initial_license_document = models.FileField(upload_to='applications/licenses/%Y/', blank=True, null=True, verbose_name='وثيقة الترخيص أو قرار الإنشاء')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ إنشاء الطلب')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        verbose_name = 'طلب اعتماد'
        verbose_name_plural = 'طلبات الاعتماد'
        ordering = ['-created_at']

    def __str__(self):
        target = f"{self.program.name} ({self.institution.name})" if self.program else self.institution.name
        return f"[{self.application_number}] {self.get_track_display()} - {target}"

    @property
    def is_programmatic(self):
        return self.track in [AccreditationTrackType.PROGRAMMATIC, AccreditationTrackType.MEDICAL_PROGRAMMATIC]

    @property
    def is_medical(self):
        return self.track == AccreditationTrackType.MEDICAL_PROGRAMMATIC

    @property
    def is_institutional(self):
        return self.track == AccreditationTrackType.INSTITUTIONAL

    @property
    def establishment_decree_number(self):
        """Safe property returning the institution's establishment decree number if present."""
        if self.institution and self.institution.decree_number:
            return self.institution.decree_number
        return ""

    @property
    def license_file(self):
        """Safe property alias for initial_license_document."""
        return self.initial_license_document

    @property
    def can_start_self_study(self):
        allowed_statuses = [
            ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION,
            ApplicationStatus.SELF_EVALUATION_IN_PROGRESS,
            ApplicationStatus.SELF_EVALUATION_SUBMITTED,
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.DESK_UNDER_REVIEW,
            ApplicationStatus.DESK_DEFICIENCY,
            ApplicationStatus.DESK_ACCEPTED,
        ]
        return self.status in allowed_statuses


class SelfStudyReport(models.Model):
    application = models.OneToOneField(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='self_study_report',
        verbose_name='طلب الاعتماد المرتبط'
    )
    executive_summary = models.TextField(verbose_name='الملخص التنفيذي للدراسة الذاتية')
    historical_background = models.TextField(blank=True, verbose_name='الخلفية التاريخية والتعريفية')
    internal_committee_names = models.TextField(verbose_name='أعضاء لجنة التقييم الذاتي الداخلية ورتبهم')
    methodology = models.TextField(blank=True, verbose_name='المنهجية المتبعة وآليات جمع وتحليل البيانات')
    strengths_overview = models.TextField(blank=True, verbose_name='أبرز نقاط القوة بحسب التقييم الداخلي')
    weaknesses_and_challenges = models.TextField(blank=True, verbose_name='التحديات ومواطن التحسين المطلوبة')
    is_locked = models.BooleanField(default=False, verbose_name='مغلق بعد التسليم النهائي')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تقرير الدراسة الذاتية (SSR)'
        verbose_name_plural = 'تقارير الدراسة الذاتية'

    def __str__(self):
        return f"دراسة ذاتية لطلب: {self.application.application_number}"


class SelfStudyIndicatorResponse(models.Model):
    class ComplianceLevel(models.TextChoices):
        MET = 'MET', 'مستوفى بالكامل'
        PARTIALLY_MET = 'PARTIALLY_MET', 'مستوفى جزئياً'
        NOT_MET = 'NOT_MET', 'غير مستوفى'
        INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE', 'غير متاح له دليل كافٍ'

    report = models.ForeignKey(
        SelfStudyReport,
        on_delete=models.CASCADE,
        related_name='indicator_responses',
        verbose_name='تقرير الدراسة الذاتية'
    )
    indicator = models.ForeignKey(
        StandardIndicator,
        on_delete=models.CASCADE,
        related_name='self_study_responses',
        verbose_name='المؤشر'
    )
    compliance_level = models.CharField(
        max_length=30,
        choices=ComplianceLevel.choices,
        default=ComplianceLevel.MET,
        verbose_name='مستوى تحقق المتطلب'
    )
    justification = models.TextField(blank=True, verbose_name='التبرير وشرح واقع المؤسسة')
    strengths = models.TextField(blank=True, verbose_name='نقاط القوة')
    gaps_and_weaknesses = models.TextField(blank=True, verbose_name='جوانب القصور والفجوات')
    corrective_actions = models.TextField(blank=True, verbose_name='الإجراءات التصحيحية وخطط التحسين')
    responsible_party = models.CharField(max_length=150, blank=True, verbose_name='المسؤول عن التنفيذ')
    target_completion_date = models.DateField(null=True, blank=True, verbose_name='الموعد المستهدف للتحسين')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تقييم مؤشر في الدراسة الذاتية'
        verbose_name_plural = 'تقييمات مؤشرات الدراسة الذاتية'
        unique_together = ('report', 'indicator')

    def __str__(self):
        return f"{self.indicator.code} - {self.get_compliance_level_display()}"


class EvidenceDocument(models.Model):
    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='evidences',
        verbose_name='طلب الاعتماد'
    )
    indicator = models.ForeignKey(
        StandardIndicator,
        on_delete=models.CASCADE,
        related_name='uploaded_evidences',
        verbose_name='المؤشر المرتبط بالشاهد'
    )
    code = models.CharField(max_length=50, verbose_name='رمز الشاهد / الوثيقة')
    title = models.CharField(max_length=255, verbose_name='عنوان الشاهد والدليل الثبوتي')
    description = models.TextField(blank=True, verbose_name='شرح الدليل ومحتواه')
    document_file = models.FileField(upload_to='evidences/%Y/%m/', blank=True, null=True, verbose_name='الملف المرفق')
    sha256_hash = models.CharField(max_length=64, blank=True, verbose_name='البصمة الرقمية للتحقق SHA-256')
    file_size_bytes = models.BigIntegerField(default=0, verbose_name='حجم الملف (بايت)')
    mime_type = models.CharField(max_length=100, blank=True, verbose_name='نوع الملف')
    is_verified = models.BooleanField(default=True, verbose_name='متحقق من سلامة البصمة')
    external_url = models.URLField(blank=True, verbose_name='رابط إلكتروني خارجي (إن وجد)')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الرفع')

    class Meta:
        verbose_name = 'وثيقة شاهد / دليل ثبوتي'
        verbose_name_plural = 'شواهد وأدلة الاعتماد'
        ordering = ['indicator__category__order', 'indicator__order', 'code']

    def save(self, *args, **kwargs):
        if self.document_file and not self.sha256_hash:
            try:
                import hashlib
                hasher = hashlib.sha256()
                for chunk in self.document_file.chunks():
                    hasher.update(chunk)
                self.sha256_hash = hasher.hexdigest()
                self.file_size_bytes = self.document_file.size
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.code}] {self.title} - مؤشر ({self.indicator.code})"


class DeskReviewEvaluation(models.Model):
    class DeskDecision(models.TextChoices):
        ACCEPTED = 'ACCEPTED', 'استيفاء الشروط والموافقة على الانتقال للتقييم الميداني'
        NEEDS_COMPLETION = 'NEEDS_COMPLETION', 'وجود نواقص واستيفاءات مطلوبة قبل الاستمرار'
        REJECTED = 'REJECTED', 'عدم استيفاء شروط الأهلية والحد الأدنى ورفض الطلب'

    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='desk_reviews',
        verbose_name='طلب الاعتماد'
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='conducted_desk_reviews',
        verbose_name='عضو الفريق الفني للمجلس'
    )
    decision = models.CharField(
        max_length=25,
        choices=DeskDecision.choices,
        default=DeskDecision.NEEDS_COMPLETION,
        verbose_name='قرار الفحص المكتبي الأولي'
    )
    formal_criteria_met = models.BooleanField(default=True, verbose_name='استيفاء المعايير الشكلية والتنظيمية')
    completeness_percentage = models.PositiveIntegerField(default=75, verbose_name='نسبة اكتمال الوثائق والأدلة (%)')
    technical_remarks = models.TextField(verbose_name='ملاحظات الفحص المكتبي الموضوعية')
    deficiencies_requested = models.TextField(blank=True, verbose_name='قائمة النواقص المطلوب من المؤسسة استكمالها')
    institution_feedback = models.TextField(blank=True, verbose_name='إفادة وتوضيح المؤسسة حول استكمال النواقص')
    is_completed = models.BooleanField(default=False, verbose_name='تم إنجاز واعتماد الفحص')
    reviewed_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ المراجعة')

    class Meta:
        verbose_name = 'فحص مكتبي أولي'
        verbose_name_plural = 'الفحوصات المكتبية الأولية'

    def __str__(self):
        return f"فحص مكتبي ({self.application.application_number}) - {self.get_decision_display()}"


class ReviewTeam(models.Model):
    application = models.OneToOneField(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='review_team',
        verbose_name='طلب الاعتماد'
    )
    decree_number = models.CharField(max_length=100, verbose_name='رقم وتاريخ قرار تشكيل اللجنة الصادر من الأمانة العامة')
    formation_date = models.DateField(verbose_name='تاريخ التشكيل الرسمي')
    chairperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='chaired_panels',
        verbose_name='رئيس فريق المراجعة والتقييم'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'لجنة المراجعة والتقييم الخارجي'
        verbose_name_plural = 'لجان المراجعة والتقييم الخارجي'

    def __str__(self):
        return f"لجنة المراجعة الخارجية لطلب ({self.application.application_number})"


class ReviewTeamMember(models.Model):
    class PanelRole(models.TextChoices):
        CHAIRPERSON = 'CHAIRPERSON', 'رئيس الفريق'
        QUALITY_EXPERT = 'QUALITY_EXPERT', 'خبير ومحكّم ضمان جودة'
        SUBJECT_SPECIALIST = 'SUBJECT_SPECIALIST', 'خبير ومحكّم في التخصص الدقيق'
        RAPPORTEUR = 'RAPPORTEUR', 'مقرر الفريق'

    team = models.ForeignKey(
        ReviewTeam,
        on_delete=models.CASCADE,
        related_name='members',
        verbose_name='فريق المراجعة'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='team_memberships',
        verbose_name='المحكّم / الخبير'
    )
    role_in_team = models.CharField(
        max_length=30,
        choices=PanelRole.choices,
        default=PanelRole.QUALITY_EXPERT,
        verbose_name='المهمة داخل الفريق'
    )
    conflict_of_interest_signed = models.BooleanField(
        default=False,
        verbose_name='تم توقيع إقرار النزاهة وعدم تعارض المصالح'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'عضو لجنة التقييم الخارجي'
        verbose_name_plural = 'أعضاء لجنة التقييم الخارجي'
        unique_together = ('team', 'user')

    def __str__(self):
        return f"{self.user} - {self.get_role_in_team_display()}"


class IndicatorEvaluationScore(models.Model):
    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='indicator_scores',
        verbose_name='طلب الاعتماد'
    )
    indicator = models.ForeignKey(
        StandardIndicator,
        on_delete=models.CASCADE,
        related_name='scores',
        verbose_name='المؤشر'
    )
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='given_scores',
        verbose_name='المحكّم المقيم'
    )
    score_level = models.CharField(
        max_length=25,
        choices=RubricEvaluationLevel.choices,
        default=RubricEvaluationLevel.SUBSTANTIALLY_MET,
        verbose_name='درجة الاستيفاء وفق سلم التقدير'
    )
    strengths = models.TextField(blank=True, verbose_name='نقاط القوة المرصودة')
    weaknesses = models.TextField(blank=True, verbose_name='نقاط الضعف وفرص التحسين')
    evidence_verification_notes = models.TextField(blank=True, verbose_name='ملاحظات التحقق الميداني من الأدلة')
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تقييم مؤشر'
        verbose_name_plural = 'تقييمات المؤشرات'
        unique_together = ('application', 'indicator', 'evaluator')

    def __str__(self):
        return f"{self.indicator.code} - {self.get_score_level_display()} بواسطة ({self.evaluator.username})"


class ExternalReviewReport(models.Model):
    class FinalRecommendation(models.TextChoices):
        FULL_ACCREDITATION = 'FULL_ACCREDITATION', 'التوصية بمنح الاعتماد الكامل (5 سنوات)'
        CONDITIONAL_ACCREDITATION = 'CONDITIONAL_ACCREDITATION', 'التوصية بمنح الاعتماد المشروط مع خطة تصحيحية'
        POSTPONE_OR_DENY = 'POSTPONE_OR_DENY', 'التوصية بتأجيل أو حجب الاعتماد لعدم استيفاء المتطلبات الأساسية'

    application = models.OneToOneField(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='external_report',
        verbose_name='طلب الاعتماد'
    )
    # Draft Phase
    draft_executive_summary = models.TextField(verbose_name='الملخص التنفيذي لمسودة التقرير')
    draft_findings_per_standard = models.TextField(verbose_name='نتائج تقييم المعايير ونقاط القوة والضعف (مسودة)')
    draft_report_file = models.FileField(upload_to='reports/drafts/%Y/', blank=True, null=True, verbose_name='ملف مسودة التقرير الكامل')
    draft_sent_to_institution_date = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ إرسال المسودة للمؤسسة')
    response_deadline = models.DateField(null=True, blank=True, verbose_name='الموعد النهائي لحق الرد للمؤسسة')

    # Right to Reply Phase
    institution_reply_text = models.TextField(blank=True, verbose_name='رد وتوضيحات المؤسسة (حق الرد حول الأخطاء المادية)')
    institution_reply_file = models.FileField(upload_to='reports/replies/%Y/', blank=True, null=True, verbose_name='مرفقات رد المؤسسة')
    institution_reply_date = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ تسليم رد المؤسسة')

    # Final Report Phase
    team_response_to_reply = models.TextField(blank=True, verbose_name='موقف ومناقشة لجنة المحكمين حيال رد المؤسسة')
    final_report_text = models.TextField(blank=True, verbose_name='نص التقرير النهائي المعتمد')
    final_report_file = models.FileField(upload_to='reports/final/%Y/', blank=True, null=True, verbose_name='ملف التقرير النهائي النهائي المعتمد')
    final_recommendation = models.CharField(
        max_length=35,
        choices=FinalRecommendation.choices,
        default=FinalRecommendation.FULL_ACCREDITATION,
        verbose_name='التوصية الختامية لفريق التقييم الخارجي'
    )
    final_submitted_to_council_date = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الرفع النهائي للأمانة والمجلس')

    class Meta:
        verbose_name = 'تقرير المراجعة الخارجية والردود'
        verbose_name_plural = 'تقارير المراجعة الخارجية والردود'

    def __str__(self):
        return f"تقرير المراجعة الخارجية لطلب: {self.application.application_number}"


class DeskReviewChecklistItem(models.Model):
    class ItemStatus(models.TextChoices):
        MET = 'MET', 'مستوفى ومكتمل'
        DEFICIENT = 'DEFICIENT', 'ناقص / به ملاحظات'
        NOT_APPLICABLE = 'NOT_APPLICABLE', 'لا ينطبق'

    desk_review = models.ForeignKey(
        DeskReviewEvaluation,
        on_delete=models.CASCADE,
        related_name='checklist_items',
        verbose_name='الفحص المكتبي'
    )
    item_title = models.CharField(max_length=255, verbose_name='بند التحقق الشكلي / القانوني')
    regulatory_reference = models.CharField(max_length=150, blank=True, verbose_name='المرجع اللائحي أو القانوني')
    is_mandatory = models.BooleanField(default=True, verbose_name='متطلب إلزامي شرطي')
    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.MET,
        verbose_name='حالة الاستيفاء'
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات الفاحص الفني')
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'بند فحص مكتبي'
        verbose_name_plural = 'بنود الفحص المكتبي التفصيلية'

    def __str__(self):
        return f"{self.item_title} ({self.get_status_display()})"


class ApplicationStatusHistory(models.Model):
    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='status_history',
        verbose_name='طلب الاعتماد'
    )
    from_stage = models.IntegerField(choices=StageChoices.choices, verbose_name='من مرحلة')
    to_stage = models.IntegerField(choices=StageChoices.choices, verbose_name='إلى مرحلة')
    from_status = models.CharField(max_length=35, choices=ApplicationStatus.choices, verbose_name='من حالة')
    to_status = models.CharField(max_length=35, choices=ApplicationStatus.choices, verbose_name='إلى حالة')
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='المستخدم المنفذ'
    )
    reason = models.TextField(blank=True, verbose_name='سبب ومبررات الانتقال')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ ووقت الانتقال')

    class Meta:
        verbose_name = 'سجل انتقال حالة الطلب'
        verbose_name_plural = 'سجلات انتقالات حالات الطلبات'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M')}] {self.application.application_number}: {self.from_status} -> {self.to_status}"


class ConflictOfInterestDeclaration(models.Model):
    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='coi_declarations',
        verbose_name='طلب الاعتماد'
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coi_declarations',
        verbose_name='المحكّم المصرح'
    )
    has_taught_in_institution = models.BooleanField(
        default=False,
        verbose_name='هل سبق لك التدريس أو العمل بالمؤسسة/البرنامج خلال آخر 5 سنوات؟'
    )
    has_relatives_or_graduates = models.BooleanField(
        default=False,
        verbose_name='هل لديك أقارب حتى الدرجة الرابعة أو طلاب أشرفت عليهم بالبرنامج؟'
    )
    has_financial_or_consulting = models.BooleanField(
        default=False,
        verbose_name='هل لديك مصالح مالية، استشارات، أو شراكات بحثية مع المؤسسة؟'
    )
    other_conflict_details = models.TextField(
        blank=True,
        verbose_name='أي مبررات أو روابط أخرى قد تؤثر على الحيدة والموضوعية'
    )
    is_conflict_acknowledged = models.BooleanField(
        default=False,
        verbose_name='يوجد تعارض مصالح فعلي يستوجب الاعتذار عن التحكيم'
    )
    signature_statement = models.CharField(
        max_length=255,
        default='أقر أنا المحكّم المذكور بصحة ما ورد والتزامي بالنزاهة والحياد التام وفق لوائح المجلس.',
        verbose_name='نص الإقرار والتعهد'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP أثناء التوقيع')
    signed_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ وساعة التوقيع')

    class Meta:
        verbose_name = 'إقرار تعارض المصالح والنزاهة'
        verbose_name_plural = 'إقرارات تعارض المصالح والنزاهة'
        unique_together = ('application', 'reviewer')

    def __str__(self):
        status = "تعارض قائم (معتذر)" if self.is_conflict_acknowledged else "مستوفٍ وخالٍ من التعارض"
        return f"إقرار نزاهة: {self.reviewer.get_full_name() or self.reviewer.username} ({status})"


class GrievanceAppeal(models.Model):
    class AppealStatus(models.TextChoices):
        SUBMITTED = 'SUBMITTED', 'تظلم مقدم قيد القيد'
        UNDER_COMMITTEE_REVIEW = 'UNDER_COMMITTEE_REVIEW', 'قيد دراسة وفحص لجنة التظلمات المستقلة'
        ACCEPTED_RECONSIDERATION = 'ACCEPTED_RECONSIDERATION', 'قبول التظلم وإعادة النظر في التقييم'
        DECISION_MODIFIED = 'DECISION_MODIFIED', 'قبول التظلم مع تعديل قرار الاعتماد'
        RETURNED_ADDITIONAL_REVIEW = 'RETURNED_ADDITIONAL_REVIEW', 'معاد لفريق المحكمين لمراجعة تكميلية'
        REJECTED_DECISION_UPHELD = 'REJECTED_DECISION_UPHELD', 'رفض التظلم وتأييد قرار المجلس السابق'

    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='grievances',
        verbose_name='طلب الاعتماد المتظلم منه'
    )
    appellant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name='مقدم التظلم (ممثل المؤسسة)'
    )
    appeal_number = models.CharField(max_length=60, unique=True, verbose_name='رقم قيد التظلم الرسمي')
    submission_date = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ قيد التظلم')
    grounds_of_appeal = models.TextField(verbose_name='أسباب وحيثيات التظلم (الأخطاء الإجرائية أو الموضوعية المدعاة)')
    supporting_document = models.FileField(
        upload_to='appeals/%Y/',
        blank=True,
        null=True,
        verbose_name='المذكرة القانونية والمستندات الثبوتية المؤيدة للتظلم'
    )
    status = models.CharField(
        max_length=30,
        choices=AppealStatus.choices,
        default=AppealStatus.SUBMITTED,
        verbose_name='حالة نظر التظلم'
    )
    committee_report = models.TextField(blank=True, verbose_name='تقرير وتوصية لجنة التظلمات المحايدة')
    committee_chair_report = models.FileField(
        upload_to='appeals/reports/%Y/',
        blank=True,
        null=True,
        verbose_name='وثيقة تقرير لجنة التظلمات المستقلة'
    )
    final_resolution_notes = models.TextField(blank=True, verbose_name='القرار النهائي للبت في التظلم')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_grievances',
        verbose_name='المعتمد لقرار البت بالتظلم'
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الفصل في التظلم')

    class Meta:
        verbose_name = 'تظلم واعتراض رسمي'
        verbose_name_plural = 'التظلمات والاعتراضات الرسمية'
        ordering = ['-submission_date']

    def __str__(self):
        return f"تظلم ({self.appeal_number}) - {self.application.institution.name}"


class SecretariatAssessmentComparisonReport(models.Model):
    application = models.ForeignKey(
        AccreditationApplication,
        on_delete=models.CASCADE,
        related_name='comparison_reports',
        verbose_name='طلب الاعتماد المرتبط'
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='generated_comparisons',
        verbose_name='الموظف / المسؤول معد المقارنة'
    )
    title = models.CharField(max_length=255, verbose_name='عنوان تقرير المقارنة التحليلي')
    comparison_data_json = models.JSONField(
        default=dict,
        verbose_name='بيانات المقارنة ومصفوفة الدرجات التفصيلية (JSON)'
    )
    secretariat_analytical_summary = models.TextField(
        blank=True,
        verbose_name='الملخص التحليلي للأمانة الفنية والفروقات المرصودة'
    )
    attached_to_council_briefing = models.BooleanField(
        default=True,
        verbose_name='مرفق رسمياً ضمن المذكرة المرفوعة للمجلس'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء والتوثيق')

    class Meta:
        verbose_name = 'تقرير مقارنة التقييم الذاتي بالمراجعة الخارجية'
        verbose_name_plural = 'تقارير مقارنة التقييم الذاتي بالمراجعة الخارجية'
        ordering = ['-created_at']

    def __str__(self):
        return f"مقارنة تحليلي للطلب ({self.application.application_number}) - {self.created_at.strftime('%Y-%m-%d')}"


