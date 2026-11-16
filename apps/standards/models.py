from django.db import models

class AccreditationTrackType(models.TextChoices):
    INSTITUTIONAL = 'INSTITUTIONAL', 'مسار الاعتماد المؤسسي'
    PROGRAMMATIC = 'PROGRAMMATIC', 'مسار الاعتماد البرامجي'
    MEDICAL_PROGRAMMATIC = 'MEDICAL_PROGRAMMATIC', 'مسار اعتماد برامج الطب البشري (WFME)'

class StandardVersion(models.Model):
    class VersionStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة قيد الإعداد'
        UNDER_REVIEW = 'UNDER_REVIEW', 'قيد المراجعة الفنية'
        APPROVED = 'APPROVED', 'معتمد من المجلس'
        ACTIVE = 'ACTIVE', 'سارٍ ونافذ للتطبيق الرسمي'
        RETIRED = 'RETIRED', 'متقاعد / مستبدل بإصدار أحدث'

    track = models.CharField(
        max_length=25,
        choices=AccreditationTrackType.choices,
        verbose_name='نوع ومسار الاعتماد'
    )
    specialization_or_field = models.CharField(
        max_length=150,
        blank=True,
        verbose_name='التخصص أو المجال (في حال المعايير البرامجية التخصصية كالمعايير الطبية أو الهندسية)'
    )
    title = models.CharField(max_length=255, verbose_name='اسم ودليل المعايير الوطني')
    version_number = models.CharField(max_length=30, default='1.0', verbose_name='رقم الإصدار')
    adoption_decree = models.CharField(max_length=150, blank=True, verbose_name='قرار الاعتماد الرسمي الصادر عن المجلس/الوزارة')
    issue_date = models.DateField(null=True, blank=True, verbose_name='تاريخ إصدار الدليل')
    effective_date = models.DateField(null=True, blank=True, verbose_name='تاريخ بدء السريان والنفاذ')
    status = models.CharField(
        max_length=25,
        choices=VersionStatus.choices,
        default=VersionStatus.ACTIVE,
        verbose_name='حالة الإصدار'
    )
    reference_document = models.FileField(
        upload_to='standards/versions/%Y/',
        blank=True,
        null=True,
        verbose_name='الوثيقة المرجعية الرسمية للدليل (PDF)'
    )
    changelog = models.TextField(blank=True, verbose_name='سجل التعديلات ومبررات التحديث')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إصدار المعايير الوطنية'
        verbose_name_plural = 'إصدارات المعايير الوطنية'
        ordering = ['track', '-version_number']

    def __str__(self):
        spec = f" ({self.specialization_or_field})" if self.specialization_or_field else ""
        return f"{self.title} [إصدار {self.version_number}]{spec} - ({self.get_status_display()})"


class StandardCategory(models.Model):
    version = models.ForeignKey(
        StandardVersion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='categories',
        verbose_name='إصدار المعايير التابع له'
    )
    track = models.CharField(
        max_length=25,
        choices=AccreditationTrackType.choices,
        default=AccreditationTrackType.INSTITUTIONAL,
        verbose_name='المسار الأكاديمي'
    )
    code = models.CharField(max_length=30, verbose_name='رمز المعيار (مثلاً: STD-01)')
    title = models.CharField(max_length=255, verbose_name='عنوان المعيار الرئيسي')
    description = models.TextField(blank=True, verbose_name='وصف المعيار وأهدافه')
    weight_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.00,
        verbose_name='الوزن النسبي (%)'
    )
    order = models.PositiveIntegerField(default=1, verbose_name='الترتيب')
    is_active = models.BooleanField(default=True, verbose_name='مفعل بالدليل الوطني')

    class Meta:
        verbose_name = 'معيار رئيسي'
        verbose_name_plural = 'المعايير الرئيسية'
        ordering = ['track', 'order', 'code']
        unique_together = ('track', 'code')

    def __str__(self):
        return f"[{self.get_track_display()}] {self.code}: {self.title}"


class StandardIndicator(models.Model):
    category = models.ForeignKey(
        StandardCategory,
        on_delete=models.CASCADE,
        related_name='indicators',
        verbose_name='المعيار الرئيسي'
    )
    code = models.CharField(max_length=40, verbose_name='رمز المؤشر (مثلاً: IND-1.1)')
    title = models.CharField(max_length=300, verbose_name='نص المؤشر الفرعي')
    explanation = models.TextField(blank=True, verbose_name='شرح المؤشر ومتطلبات تحققه')
    suggested_evidences = models.TextField(
        blank=True,
        verbose_name='الشواهد والأدلة الإرشادية الواجب إرفاقها'
    )
    is_core_standard = models.BooleanField(
        default=False,
        verbose_name='مؤشر جوهري حاسم (Core Essential) لا يُمنح الاعتماد بدونه'
    )
    order = models.PositiveIntegerField(default=1, verbose_name='الترتيب')

    class Meta:
        verbose_name = 'مؤشر أداء / معيار فرعي'
        verbose_name_plural = 'المؤشرات الفرعية'
        ordering = ['category', 'order', 'code']
        unique_together = ('category', 'code')

    def __str__(self):
        core_tag = " [جوهري]" if self.is_core_standard else ""
        return f"{self.code} - {self.title[:60]}...{core_tag}"


class RubricEvaluationLevel(models.TextChoices):
    NOT_MET = 'NOT_MET', 'غير مستوفى (0)'
    PARTIALLY_MET = 'PARTIALLY_MET', 'مستوفى جزئياً (1)'
    SUBSTANTIALLY_MET = 'SUBSTANTIALLY_MET', 'مستوفى بدرجة كافية (2)'
    FULLY_MET = 'FULLY_MET', 'مستوفى بالكامل ومتميز (3)'
