from django.db import models
from django.conf import settings

class SiteVisitSchedule(models.Model):
    class VisitStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'مجدولة ومؤكدة'
        IN_PROGRESS = 'IN_PROGRESS', 'الزيارة جارية حالياً على أرض الواقع'
        COMPLETED = 'COMPLETED', 'اكتملت الزيارة الميدانية'
        POSTPONED = 'POSTPONED', 'مؤجلة'

    application = models.OneToOneField(
        'accreditation.AccreditationApplication',
        on_delete=models.CASCADE,
        related_name='site_visit',
        verbose_name='طلب الاعتماد'
    )
    start_date = models.DateField(verbose_name='تاريخ بدء الزيارة الميدانية')
    end_date = models.DateField(verbose_name='تاريخ اختتام الزيارة الميدانية')
    visit_location = models.CharField(max_length=255, verbose_name='المقر الرئيسي والمنشآت المشمولة بالزيارة')
    agenda_details = models.TextField(verbose_name='البرنامج الزمني والجدول اليومي للزيارة الميدانية')
    logistics_coordinator = models.CharField(max_length=150, blank=True, verbose_name='منسق الزيارة والمسؤول اللوجستي من المؤسسة')
    status = models.CharField(
        max_length=20,
        choices=VisitStatus.choices,
        default=VisitStatus.SCHEDULED,
        verbose_name='حالة الزيارة'
    )
    final_exit_meeting_notes = models.TextField(blank=True, verbose_name='محضر اللقاء الختامي الشفوي مع قيادة المؤسسة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'جدول الزيارة الميدانية'
        verbose_name_plural = 'جداول الزيارات الميدانية'

    def __str__(self):
        return f"زيارة ميدانية لطلب ({self.application.application_number}) من {self.start_date} إلى {self.end_date}"


class FacilityInspection(models.Model):
    class FacilityCategory(models.TextChoices):
        CLASSROOMS = 'CLASSROOMS', 'القاعات والمدرجات الدراسية'
        LABS = 'LABS', 'المعامل والمختبرات والورش التخصصية'
        LIBRARY = 'LIBRARY', 'المكتبة المركزية ومصادر التعلم وقواعد البيانات'
        CLINICAL_TRAINING = 'CLINICAL_TRAINING', 'المستشفيات والمراكز السريرية والتدريب الميداني'
        IT_INFRASTRUCTURE = 'IT_INFRASTRUCTURE', 'البنية التحتية لتكنولوجيا المعلومات والشبكات'
        STUDENT_SERVICES = 'STUDENT_SERVICES', 'المرافق الطلابية والخدمات العامة والسلامة'

    class AdequacyLevel(models.TextChoices):
        EXCELLENT = 'EXCELLENT', 'ممتاز ومطابق لأعلى المعايير'
        ADEQUATE = 'ADEQUATE', 'كافي ومستوفٍ للحد الأدنى المطلوب'
        NEEDS_IMPROVEMENT = 'NEEDS_IMPROVEMENT', 'بحاجة إلى تجهيزات وصيانة إضافية'
        INADEQUATE = 'INADEQUATE', 'غير ملائم ولا يلبي متطلبات البرنامج/المؤسسة'

    visit = models.ForeignKey(
        SiteVisitSchedule,
        on_delete=models.CASCADE,
        related_name='facility_inspections',
        verbose_name='الزيارة الميدانية'
    )
    category = models.CharField(
        max_length=30,
        choices=FacilityCategory.choices,
        verbose_name='نوع المرفق'
    )
    facility_name = models.CharField(max_length=200, verbose_name='اسم المرفق / المعمل / القاعة')
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name='عضو الفريق المعاين'
    )
    capacity_students = models.PositiveIntegerField(default=30, verbose_name='السعة الاستيعابية التقديرية')
    adequacy_rating = models.CharField(
        max_length=25,
        choices=AdequacyLevel.choices,
        default=AdequacyLevel.ADEQUATE,
        verbose_name='مستوى الملاءمة والتجهيز'
    )
    safety_compliance = models.BooleanField(default=True, verbose_name='مستوفي شروط السلامة المهنية والإخلاء')
    detailed_observations = models.TextField(verbose_name='الملاحظات التفصيلية للمعاينة')
    inspection_date = models.DateField(auto_now_add=True, verbose_name='تاريخ المعاينة')

    class Meta:
        verbose_name = 'معاينة مرفق / معمل'
        verbose_name_plural = 'معاينات المرافق والمعامل'

    def __str__(self):
        return f"{self.facility_name} ({self.get_category_display()}) - {self.get_adequacy_rating_display()}"


class StakeholderInterview(models.Model):
    class StakeholderGroup(models.TextChoices):
        LEADERSHIP = 'LEADERSHIP', 'القيادات الأكاديمية ورؤساء الأقسام والعمداء'
        FACULTY = 'FACULTY', 'أعضاء هيئة التدريس والهيئة المعاونة'
        CURRENT_STUDENTS = 'CURRENT_STUDENTS', 'الطلاب المقيدون في مختلف المستويات'
        ADMIN_STAFF = 'ADMIN_STAFF', 'الكادر الإداري والفني والتقني'
        ALUMNI = 'ALUMNI', 'الخريجون من الدفعات السابقة'
        EMPLOYERS = 'EMPLOYERS', 'أرباب العمل وممثلو سوق العمل والجهات التدريبية'

    visit = models.ForeignKey(
        SiteVisitSchedule,
        on_delete=models.CASCADE,
        related_name='interviews',
        verbose_name='الزيارة الميدانية'
    )
    target_group = models.CharField(
        max_length=30,
        choices=StakeholderGroup.choices,
        verbose_name='الفئة المستهدفة في المقابلة'
    )
    conducted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name='المحكّم الذي أدار المقابلة'
    )
    attendees_count = models.PositiveIntegerField(default=10, verbose_name='عدد الحاضرين في جلسة المقابلة')
    interview_date = models.DateTimeField(verbose_name='موعد المقابلة')
    key_themes_discussed = models.TextField(verbose_name='محاور النقاش والأسئلة المطروحة')
    feedback_summary = models.TextField(verbose_name='ملخص إفادات وانطباعات الحاضرين')
    satisfaction_level = models.CharField(
        max_length=30,
        default='عالٍ عموماً مع ملاحظات',
        verbose_name='مستوى الرضا العام للفئة'
    )

    class Meta:
        verbose_name = 'محضر مقابلة أصحاب المصلحة'
        verbose_name_plural = 'محاضر مقابلات أصحاب المصلحة'

    def __str__(self):
        return f"مقابلة: {self.get_target_group_display()} (عدد: {self.attendees_count})"


class AcademicAuditRecord(models.Model):
    class AuditType(models.TextChoices):
        EXAM_PAPERS = 'EXAM_PAPERS', 'عينات من نماذج الاختبارات والسلالم التصحيحية'
        STUDENT_WORK = 'STUDENT_WORK', 'عينات من أعمال ومشاريع الطلاب والتكاليف'
        COURSE_PORTFOLIO = 'COURSE_PORTFOLIO', 'ملفات المقررات الدراسية (Course Files)'
        FACULTY_FILES = 'FACULTY_FILES', 'ملفات أعضاء هيئة التدريس والإنتاج العلمي'
        GRADE_RECORDS = 'GRADE_RECORDS', 'سجلات ومطابقة رصد الدرجات والكنترول'

    class ComplianceLevel(models.TextChoices):
        FULLY_COMPLIANT = 'FULLY_COMPLIANT', 'مطابق تماماً لمعايير نتاجات التعلم والنزاهة'
        MINOR_ISSUES = 'MINOR_ISSUES', 'مطابق بشكل عام مع ملاحظات فنية بسيطة'
        NON_COMPLIANT = 'NON_COMPLIANT', 'غير مطابق أو يفتقر لأدلة القياس والتوثيق'

    visit = models.ForeignKey(
        SiteVisitSchedule,
        on_delete=models.CASCADE,
        related_name='academic_audits',
        verbose_name='الزيارة الميدانية'
    )
    audit_type = models.CharField(
        max_length=30,
        choices=AuditType.choices,
        verbose_name='نوع الفحص الأكاديمي'
    )
    course_or_subject = models.CharField(max_length=200, verbose_name='المقرر أو العينة التي تم فحصها')
    sampling_details = models.CharField(max_length=255, verbose_name='حجم وتفاصيل العينة العشوائية المفحوصة')
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name='المحكّم الفاحص'
    )
    compliance_rating = models.CharField(
        max_length=25,
        choices=ComplianceLevel.choices,
        default=ComplianceLevel.FULLY_COMPLIANT,
        verbose_name='مستوى المطابقة الأكاديمية'
    )
    findings_and_evidence = models.TextField(verbose_name='النتائج والشواهد المرصودة')
    audit_date = models.DateField(auto_now_add=True)

    class Meta:
        verbose_name = 'سجل تدقيق وفحص أكاديمي'
        verbose_name_plural = 'سجلات التدقيق الأكاديمي'

    def __str__(self):
        return f"تدقيق {self.get_audit_type_display()} - {self.course_or_subject}"
