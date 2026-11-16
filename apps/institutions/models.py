from django.db import models

class Institution(models.Model):
    class InstitutionType(models.TextChoices):
        PUBLIC_UNIVERSITY = 'PUBLIC_UNIVERSITY', 'جامعة حكومية'
        PRIVATE_UNIVERSITY = 'PRIVATE_UNIVERSITY', 'جامعة أهلية / خاصة'
        UNIVERSITY_COLLEGE = 'UNIVERSITY_COLLEGE', 'كلية جامعية مجتمعية'
        HIGHER_INSTITUTE = 'HIGHER_INSTITUTE', 'معهد عالي'

    name = models.CharField(max_length=255, verbose_name='اسم المؤسسة التعليمية')
    name_en = models.CharField(max_length=255, blank=True, verbose_name='اسم المؤسسة بالإنجليزية')
    code = models.CharField(max_length=50, unique=True, verbose_name='الرمز التعريفي للمؤسسة')
    institution_type = models.CharField(
        max_length=30,
        choices=InstitutionType.choices,
        default=InstitutionType.PUBLIC_UNIVERSITY,
        verbose_name='نوع المؤسسة'
    )
    decree_number = models.CharField(max_length=100, blank=True, verbose_name='رقم وتاريخ قرار الإنشاء الجمهوري/الوزاري')
    establishment_year = models.PositiveIntegerField(null=True, blank=True, verbose_name='سنة التأسيس')
    governorate = models.CharField(max_length=100, verbose_name='المحافظة')
    city = models.CharField(max_length=100, blank=True, verbose_name='المدينة')
    address = models.TextField(blank=True, verbose_name='العنوان والمقر الرئيسي')
    website = models.URLField(blank=True, verbose_name='الموقع الإلكتروني الرسمي')
    official_email = models.EmailField(verbose_name='البريد الإلكتروني الرسمي')
    official_phone = models.CharField(max_length=50, verbose_name='الهاتف الرسمي')
    president_name = models.CharField(max_length=150, verbose_name='اسم رئيس الجامعة / عميد المؤسسة')
    quality_center_dean = models.CharField(max_length=150, blank=True, verbose_name='عميد / مدير مركز التطوير وضمان الجودة')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ التسجيل بالبوابة')

    class Meta:
        verbose_name = 'مؤسسة تعليم عالي'
        verbose_name_plural = 'مؤسسات التعليم العالي'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_institution_type_display()})"

    @property
    def license_number(self):
        """Safe alias for decree_number to ensure template and backward compatibility."""
        return self.decree_number


class College(models.Model):
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='colleges',
        verbose_name='المؤسسة التابعة لها'
    )
    name = models.CharField(max_length=255, verbose_name='اسم الكلية')
    establishment_year = models.PositiveIntegerField(null=True, blank=True, verbose_name='سنة التأسيس')
    dean_name = models.CharField(max_length=150, blank=True, verbose_name='اسم عميد الكلية')
    email = models.EmailField(blank=True, verbose_name='البريد الإلكتروني للكلية')
    phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف الكلية')

    class Meta:
        verbose_name = 'كلية'
        verbose_name_plural = 'الكليات'
        ordering = ['institution', 'name']
        unique_together = ('institution', 'name')

    def __str__(self):
        return f"{self.name} - {self.institution.name}"


class Department(models.Model):
    college = models.ForeignKey(
        College,
        on_delete=models.CASCADE,
        related_name='departments',
        verbose_name='الكلية التابع لها'
    )
    name = models.CharField(max_length=255, verbose_name='اسم القسم الأكاديمي')
    head_name = models.CharField(max_length=150, blank=True, verbose_name='رئيس القسم')
    establishment_year = models.PositiveIntegerField(null=True, blank=True, verbose_name='سنة التأسيس')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'قسم أكاديمي'
        verbose_name_plural = 'الأقسام الأكاديمية'
        ordering = ['college__institution', 'college', 'name']
        unique_together = ('college', 'name')

    def __str__(self):
        return f"قسم {self.name} - {self.college.name}"


class AcademicProgram(models.Model):
    class DegreeLevel(models.TextChoices):
        DIPLOMA = 'DIPLOMA', 'دبلوم عالي'
        BACHELOR = 'BACHELOR', 'بكالوريوس'
        MASTER = 'MASTER', 'ماجستير'
        PHD = 'PHD', 'دكتوراه'

    class StudySystem(models.TextChoices):
        CREDIT_HOURS = 'CREDIT_HOURS', 'نظام الساعات المعتمدة'
        SEMESTER = 'SEMESTER', 'نظام الفصول الدراسية'
        YEARLY = 'YEARLY', 'النظام السنوي التقليدي'

    college = models.ForeignKey(
        College,
        on_delete=models.CASCADE,
        related_name='programs',
        verbose_name='الكلية'
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='programs',
        verbose_name='القسم الأكاديمي (اختياري)'
    )
    name = models.CharField(max_length=255, verbose_name='اسم البرنامج الأكاديمي')
    code = models.CharField(max_length=50, blank=True, verbose_name='رمز البرنامج')
    degree_level = models.CharField(
        max_length=20,
        choices=DegreeLevel.choices,
        default=DegreeLevel.BACHELOR,
        verbose_name='المستوى والدرجة الممنوحة'
    )
    study_system = models.CharField(
        max_length=20,
        choices=StudySystem.choices,
        default=StudySystem.CREDIT_HOURS,
        verbose_name='نظام الدراسة'
    )
    study_duration_years = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=4.0,
        verbose_name='مدة الدراسة المقررة (بالسنوات)'
    )
    total_credit_hours = models.PositiveIntegerField(default=130, verbose_name='إجمالي الساعات المعتمدة')
    department_head = models.CharField(max_length=150, blank=True, verbose_name='رئيس القسم الأكاديمي')
    ministry_approval_decree = models.CharField(max_length=150, blank=True, verbose_name='رقم وتاريخ قرار فتح البرنامج من الوزارة')
    graduates_count_last_year = models.PositiveIntegerField(default=0, verbose_name='عدد خريجي آخر دفعة')
    active_students_count = models.PositiveIntegerField(default=0, verbose_name='عدد الطلاب المقيدين حالياً')

    class Meta:
        verbose_name = 'برنامج أكاديمي'
        verbose_name_plural = 'البرامج الأكاديمية'
        ordering = ['college__institution', 'college', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_degree_level_display()}) - {self.college.name}"
