import os
import sys
import django

# Setup Django Environment
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caqa_core.settings')
django.setup()

from django.utils import timezone
from apps.accounts.models import User
from apps.institutions.models import Institution, College, AcademicProgram
from apps.standards.models import StandardCategory, StandardIndicator, AccreditationTrackType, RubricEvaluationLevel
from apps.accreditation.models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    SelfStudyReport,
    EvidenceDocument,
    DeskReviewEvaluation,
    ReviewTeam,
    ReviewTeamMember,
    IndicatorEvaluationScore,
    ExternalReviewReport,
)
from apps.site_visits.models import (
    SiteVisitSchedule,
    FacilityInspection,
    StakeholderInterview,
    AcademicAuditRecord,
)
from apps.decisions.models import (
    CouncilMeeting,
    AccreditationDecision,
    AccreditationCertificate,
)
from apps.surveillance.models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
)

def run_seed():
    print("=== CAQA Yemen Seeding Started ===")

    # 1. Create Default Users & Roles
    pwd = "caqa123456"

    council_sec, _ = User.objects.get_or_create(
        username="council_sec",
        defaults={
            'first_name': "أحمد",
            'last_name': "المتوكل",
            'academic_title': "د.",
            'role': User.Roles.COUNCIL_SECRETARY,
            'is_staff': True,
            'is_superuser': True,
            'email': "secretary@caqa-yemen.gov.ye",
            'specialization': "إدارة التعليم العالي وضمان الجودة",
        }
    )
    council_sec.set_password(pwd)
    council_sec.save()

    reviewer_lead, _ = User.objects.get_or_create(
        username="reviewer_lead",
        defaults={
            'first_name': "علي",
            'last_name': "الخولاني",
            'academic_title': "أ.د.",
            'role': User.Roles.EXTERNAL_REVIEWER,
            'is_certified_evaluator': True,
            'evaluator_certificate_number': "YE-CAQA-REV-2023-014",
            'specialization': "التعليم الطبي وضمان الجودة البرامجية",
            'email': "kholani.eval@caqa-yemen.gov.ye",
        }
    )
    reviewer_lead.set_password(pwd)
    reviewer_lead.save()

    board_member, _ = User.objects.get_or_create(
        username="board_member",
        defaults={
            'first_name': "خالد",
            'last_name': "الحكيمي",
            'academic_title': "أ.د.",
            'role': User.Roles.BOARD_MEMBER,
            'is_staff': True,
            'email': "board.member@caqa-yemen.gov.ye",
            'specialization': "تخطيط استراتيجي وسياسات التعليم العالي",
        }
    )
    board_member.set_password(pwd)
    board_member.save()

    print("[OK] Users & Reviewers created.")

    # 2. Create Institutions, Colleges, and Programs
    # Sana'a University
    sanaa_univ, _ = Institution.objects.get_or_create(
        code="UNIV-SANAA-01",
        defaults={
            'name': "جامعة صنعاء",
            'institution_type': Institution.InstitutionType.PUBLIC_UNIVERSITY,
            'decree_number': "قرار جمهوري رقم (12) لسنة 1970م",
            'establishment_year': 1970,
            'governorate': "صنعاء",
            'city': "أمانة العاصمة",
            'address': "مذبح - صنعاء",
            'website': "https://su.edu.ye",
            'official_email': "info@su.edu.ye",
            'official_phone': "+967-1-464450",
            'president_name': "أ.د. القاسم محمد عباس",
            'quality_center_dean': "أ.د. هدى العماد",
        }
    )

    sanaa_quality_user, _ = User.objects.get_or_create(
        username="sanaa_quality",
        defaults={
            'first_name': "هدى",
            'last_name': "العماد",
            'academic_title': "أ.د.",
            'role': User.Roles.INSTITUTION_OFFICER,
            'institution': sanaa_univ,
            'email': "quality@su.edu.ye",
            'specialization': "تقويم وتطوير المناهج وضمان الجودة",
        }
    )
    sanaa_quality_user.set_password(pwd)
    sanaa_quality_user.save()

    med_college, _ = College.objects.get_or_create(
        institution=sanaa_univ,
        name="كلية الطب والعلوم الصحية",
        defaults={'establishment_year': 1981, 'dean_name': "أ.د. محمد الشهاري"}
    )
    med_program, _ = AcademicProgram.objects.get_or_create(
        college=med_college,
        name="بكالوريوس الطب والجراحة (MBBS)",
        defaults={
            'code': "MED-MBBS-01",
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
            'study_system': AcademicProgram.StudySystem.CREDIT_HOURS,
            'study_duration_years': 6.0,
            'total_credit_hours': 240,
            'department_head': "أ.د. أحمد المخلافي",
            'graduates_count_last_year': 185,
            'active_students_count': 1200,
        }
    )

    eng_college, _ = College.objects.get_or_create(
        institution=sanaa_univ,
        name="كلية الهندسة",
        defaults={'establishment_year': 1983, 'dean_name': "أ.د. فاروق الحكيمي"}
    )
    cs_program, _ = AcademicProgram.objects.get_or_create(
        college=eng_college,
        name="بكالوريوس هندسة الحاسوب والتحكم",
        defaults={
            'code': "ENG-COMP-01",
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
            'study_system': AcademicProgram.StudySystem.CREDIT_HOURS,
            'study_duration_years': 5.0,
            'total_credit_hours': 165,
            'department_head': "د. عبدالحكيم الشامي",
        }
    )

    # University of Science and Technology (UST)
    ust_univ, _ = Institution.objects.get_or_create(
        code="UNIV-UST-02",
        defaults={
            'name': "جامعة العلوم والتكنولوجيا",
            'institution_type': Institution.InstitutionType.PRIVATE_UNIVERSITY,
            'decree_number': "قرار وزاري رقم (2) لسنة 1994م",
            'establishment_year': 1994,
            'governorate': "صنعاء",
            'city': "صنعاء",
            'address': "شارع الستين الغربي",
            'website': "https://ust.edu.ye",
            'official_email': "info@ust.edu.ye",
            'official_phone': "+967-1-373237",
            'president_name': "أ.د. عادل المتوكل",
            'quality_center_dean': "أ.د. أمين الكستبان",
        }
    )

    ust_quality_user, _ = User.objects.get_or_create(
        username="ust_quality",
        defaults={
            'first_name': "أمين",
            'last_name': "الكستبان",
            'academic_title': "أ.د.",
            'role': User.Roles.INSTITUTION_OFFICER,
            'institution': ust_univ,
            'email': "quality@ust.edu.ye",
            'specialization': "إدارة الجودة الشاملة والاعتماد المؤسسي",
        }
    )
    ust_quality_user.set_password(pwd)
    ust_quality_user.save()

    ust_med_college, _ = College.objects.get_or_create(
        institution=ust_univ,
        name="كلية الصيدلة",
        defaults={'establishment_year': 1998, 'dean_name': "أ.د. منير الوصابي"}
    )
    pharmd_prog, _ = AcademicProgram.objects.get_or_create(
        college=ust_med_college,
        name="دكتور صيدلة (PharmD)",
        defaults={
            'code': "PHARM-UST-01",
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
            'study_system': AcademicProgram.StudySystem.CREDIT_HOURS,
            'study_duration_years': 5.5,
            'total_credit_hours': 198,
        }
    )

    # Aden University
    aden_univ, _ = Institution.objects.get_or_create(
        code="UNIV-ADEN-03",
        defaults={
            'name': "جامعة عدن",
            'institution_type': Institution.InstitutionType.PUBLIC_UNIVERSITY,
            'establishment_year': 1975,
            'governorate': "عدن",
            'city': "خور مكسر",
            'address': "خور مكسر - عدن",
            'website': "https://aden-univ.net",
            'official_email': "info@aden-univ.net",
            'official_phone': "+967-2-234444",
            'president_name': "أ.د. الخضر ناصر لصور",
            'quality_center_dean': "أ.د. نبيل المشوشي",
        }
    )
    aden_pharm_col, _ = College.objects.get_or_create(
        institution=aden_univ,
        name="كلية الصيدلة",
        defaults={'establishment_year': 1995, 'dean_name': "د. خالد السويدي"}
    )
    aden_pharm_prog, _ = AcademicProgram.objects.get_or_create(
        college=aden_pharm_col,
        name="بكالوريوس الصيدلة السريرية",
        defaults={
            'code': "PHARM-ADEN-01",
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
            'study_system': AcademicProgram.StudySystem.SEMESTER,
            'study_duration_years': 5.0,
            'total_credit_hours': 180,
        }
    )

    print("[OK] Universities, Colleges, and Programs created.")

    # 3. Create Standards & Indicators for BOTH Tracks Separately
    # Track A: Institutional Standards (8 Standards)
    inst_standards_data = [
        ("INST-STD-01", "الرسالة والرؤية والأهداف المؤسسية", 10.0, 1, [
            ("INST-IND-1.1", "وجود رسالة ورؤية واضحة وموثقة للجامعة معتمدة ومشاركة مع أصحاب المصلحة.", "وثيقة الخطة الإستراتيجية ومحاضر اعتماد مجلس الجامعة.", True),
            ("INST-IND-1.2", "اتساق الأهداف الإستراتيجية مع متطلبات التنمية الوطنية في اليمن.", "مؤشرات قياس الأداء KPI وتقارير المواءمة.", False),
        ]),
        ("INST-STD-02", "الحوكمة والقيادة والإدارة الرشيدة", 15.0, 2, [
            ("INST-IND-2.1", "وجود هيكل تنظيمي ولوائح إدارية وأكاديمية نافذة تحدد الصلاحيات والمسؤوليات بوضوح.", "الهيكل التنظيمي المعتمد والدليل الإجرائي واللوائح.", True),
            ("INST-IND-2.2", "التزام القيادة بالنزاهة والشفافية وتطبيق نظم المساءلة والمشاركة.", "محاضر اجتماعات المجالس وسياسات مكافحة الفساد.", False),
        ]),
        ("INST-STD-03", "البرامج الأكاديمية والخطط الدراسية", 15.0, 3, [
            ("INST-IND-3.1", "استناد كافة البرامج للترخيص الرسمي من وزارة التعليم العالي ومطابقتها للمعايير الوطنية.", "قرارات الترخيص ووثائق مواصفات البرامج والمقررات.", True),
            ("INST-IND-3.2", "تطبيق آليات دورية للمراجعة والتطوير المستمر للمناهج والخطط الدراسية.", "تقارير المراجعة الدورية للمناهج ومحاضر لجان التطوير.", False),
        ]),
        ("INST-STD-04", "أعضاء هيئة التدريس والكادر المعاون", 15.0, 4, [
            ("INST-IND-4.1", "كفاية أعداد وتخصصات أعضاء هيئة التدريس المتفرغين ونسبتهم إلى الطلاب.", "سجلات الكادر التدريسي، العقود، وملفات الرتب الأكاديمية.", True),
            ("INST-IND-4.2", "وجود سياسات شفافة للتوظيف والترقيات والتدريب والتطوير المهني المستمر.", "لائحة الترقيات الأكاديمية وخطة التطوير التدريبي السنوية.", False),
        ]),
        ("INST-STD-05", "شؤون الطلاب والخدمات المساندة", 10.0, 5, [
            ("INST-IND-5.1", "سياسات قبول واضحة ومعلنة ونظم تسجيل وإرشاد أكاديمي ونفسي فعالة.", "دليل قبول وتسجيل الطلاب وسجلات الإرشاد الأكاديمي.", True),
            ("INST-IND-5.2", "توفير بيئة طلابية داعمة وأنشطة لا صفية وخدمات رعاية صحية واجتماعية.", "تقارير الأنشطة الطلابية وعيادات الرعاية ومرافق الرياضة.", False),
        ]),
        ("INST-STD-06", "المرافق والمصادر التعليمية والتقنية", 15.0, 6, [
            ("INST-IND-6.1", "كفاية القاعات والمختبرات والمكتبة المركزية ومصادر التعلم الإلكترونية.", "سجلات الجرد الهندسي للمباني والمختبرات واشتراكات قواعد البيانات.", True),
            ("INST-IND-6.2", "استيفاء شروط السلامة العامة والأمن البيئي وتسهيلات ذوي الاحتياجات الخاصة.", "شهادات السلامة المدنية وخطط الإخلاء وتجهيزات الوصول.", False),
        ]),
        ("INST-STD-07", "البحث العلمي والتطوير والابتكار", 10.0, 7, [
            ("INST-IND-7.1", "تخصيص ميزانية بحثية وإصدار مجلات علمية محكمة وتبني خطة بحثية معتمدة.", "الخطة البحثية للجامعة ومجلات الجامعة والتمويل البحثي.", False),
        ]),
        ("INST-STD-08", "المسؤولية المجتمعية والنزاهة المالية", 10.0, 8, [
            ("INST-IND-8.1", "وجود نظام مالي ومحاسبي محكم ومدقق سنوياً من جهة محاسبية قانونية مستقلة.", "التقارير المالية السنوية المدققة من مكاتب المحاسبة القانونية.", True),
            ("INST-IND-8.2", "مساهمة الجامعة الفعالة في خدمة المجتمع المحلي والمبادرات التنموية.", "تقارير برامج التوعية والشراكات المجتمعية والتدريب المستمر.", False),
        ]),
    ]

    for code, title, weight, order, indicators in inst_standards_data:
        cat, _ = StandardCategory.objects.get_or_create(
            track=AccreditationTrackType.INSTITUTIONAL,
            code=code,
            defaults={
                'title': title,
                'weight_percentage': weight,
                'order': order,
            }
        )
        for ind_code, ind_title, suggested_ev, is_core in indicators:
            StandardIndicator.objects.get_or_create(
                category=cat,
                code=ind_code,
                defaults={
                    'title': ind_title,
                    'suggested_evidences': suggested_ev,
                    'is_core_standard': is_core,
                }
            )

    # Track B: Programmatic Standards (8 Standards)
    prog_standards_data = [
        ("PROG-STD-01", "رسالة البرنامج وأهدافه ومخرجات التعلم المستهدفة (ILOs)", 15.0, 1, [
            ("PROG-IND-1.1", "تحديد مخرجات تعلم مستهدفة (ILOs) واضحة وقابلة للقياس متوافقة مع الإطار الوطني للمؤهلات.", "وثيقة مواصفات البرنامج ومصفوفة مواءمة مخرجات التعلم.", True),
            ("PROG-IND-1.2", "مواءمة مخرجات البرنامج التخصصية مع المعايير المرجعية الوطنية والدولية.", "تقارير المقارنة المرجعية (Benchmarking) مع كليات نظيرة.", False),
        ]),
        ("PROG-STD-02", "تصميم الخطة والمناهج الدراسية وتوصيف المقررات", 15.0, 2, [
            ("PROG-IND-2.1", "شمولية وحداثة الخطة الدراسية وتوصيف المقررات وفق نماذج المجلس المعتمدة.", "ملفات توصيف المقررات (Course Specifications) وكتب المقررات.", True),
            ("PROG-IND-2.2", "تكامل وتدرج المقررات والتوازن بين المعارف النظرية والتطبيقات العملية والمهارية.", "الخريطة المنهجية وجداول المتطلبات السابقة والتوزيع الفصلي.", False),
        ]),
        ("PROG-STD-03", "استراتيجيات التدريس والتعلم والتقويم الأكاديمي", 15.0, 3, [
            ("PROG-IND-3.1", "تنوع طرائق التدريس المتمحورة حول الطالب (التعلم القائم على حل المشكلات، الحالات السريرية...).", "نماذج الأنشطة الصفية وتقارير استراتيجيات التدريس المطبقة.", True),
            ("PROG-IND-3.2", "عدالة وموثوقية أساليب تقويم الطلاب واتساق أسئلة الاختبارات مع نتاجات التعلم المستهدفة.", "نماذج الاختبارات مع نماذج الإجابة والسلالم التصحيحية (Rubrics).", True),
        ]),
        ("PROG-STD-04", "كفاءة هيئة التدريس التخصصية للبرنامج", 15.0, 4, [
            ("PROG-IND-4.1", "ملاءمة تخصصات أعضاء هيئة التدريس للمقررات التي يدرسونها ونصابهم التدريسي.", "جداول العبء التدريسي وسير الكادر الذاتية وقرارات التكليف.", True),
            ("PROG-IND-4.2", "تقييم أداء أعضاء هيئة التدريس بصورة دورية بواسطة الطلاب ورؤساء الأقسام.", "استبانات تقييم الطلاب لأعضاء هيئة التدريس وتقارير الأداء السنوي.", False),
        ]),
        ("PROG-STD-05", "قبول الطلاب والإرشاد والتحصيل الأكاديمي", 10.0, 5, [
            ("PROG-IND-5.1", "التزام البرنامج بشروط القبول ومعدلات الثانوية المعتمدة من الوزارة والطاقة الاستيعابية.", "كشوفات الطلاب المقبولين وسجلات المفاضلة واختبارات القبول.", True),
            ("PROG-IND-5.2", "وجود نظام إرشاد أكاديمي فاعل لمتابعة الطلاب المتعثرين والموهوبين وتوثيق ذلك.", "سجلات الإرشاد الأكاديمي بالقسم وملفات التدخلات العلاجية.", False),
        ]),
        ("PROG-STD-06", "المعامل التخصصية والتدريب السريري والميداني", 15.0, 6, [
            ("PROG-IND-6.1", "توفير معامل تخصصية مجهزة بأحدث التقنيات تتناسب مع أعداد الطلاب ومجالات البرنامج.", "سجلات جرد معامل البرنامج، كراسات التجارب العملية، وأدلة السلامة.", True),
            ("PROG-IND-6.2", "تأمين مواقع تدريب سريري/ميداني معتمدة (مستشفيات، مصانع، مراكز أبحاث) بإشراف أكاديمي مباشر.", "اتفاقيات التدريب الميداني والسريري، سجلات التدريب اليومي Logbooks.", True),
        ]),
        ("PROG-STD-07", "بيئة ومصادر التعلم المتخصصة", 5.0, 7, [
            ("PROG-IND-7.1", "توفر المراجع الحديثة والدوريات التخصصية وقواعد البيانات الرقمية ذات العلاقة بالبرنامج.", "فهارس الكتب التخصصية والاشتراكات في المكتبات الرقمية العالمية.", False),
        ]),
        ("PROG-STD-08", "قياس مخرجات التعلم ورضا أرباب العمل والخريجين", 10.0, 8, [
            ("PROG-IND-8.1", "قياس دوري وموثق لمدى تحقق نواتج التعلم المستهدفة للبرنامج (Program ILOs).", "تقارير القياس السنوية لمخرجات البرنامج وتحليل الفجوات.", True),
            ("PROG-IND-8.2", "استطلاع آراء الخريجين وأرباب العمل حول كفاءة الخريجين ونسب توظيفهم.", "دراسات التتبع للخريجين واستبانات رضا أرباب العمل والمؤسسات المشغلة.", False),
        ]),
    ]

    for code, title, weight, order, indicators in prog_standards_data:
        cat, _ = StandardCategory.objects.get_or_create(
            track=AccreditationTrackType.PROGRAMMATIC,
            code=code,
            defaults={
                'title': title,
                'weight_percentage': weight,
                'order': order,
            }
        )
        for ind_code, ind_title, suggested_ev, is_core in indicators:
            StandardIndicator.objects.get_or_create(
                category=cat,
                code=ind_code,
                defaults={
                    'title': ind_title,
                    'suggested_evidences': suggested_ev,
                    'is_core_standard': is_core,
                }
            )

    print("[OK] National Standards for both tracks created.")

    # 4. Create Sample Live Applications Across the 7 Stages
    # App 1: Programmatic Accreditation - Sana'a University Medicine (Completed Full Accreditation Stage 7)
    app1, _ = AccreditationApplication.objects.get_or_create(
        application_number="CAQA-PROG-2026-0001",
        defaults={
            'track': AccreditationTrackType.PROGRAMMATIC,
            'institution': sanaa_univ,
            'program': med_program,
            'applicant_user': sanaa_quality_user,
            'academic_year': "2025/2026",
            'current_stage': StageChoices.STAGE_7,
            'status': ApplicationStatus.FULL_ACCREDITATION,
            'submission_date': timezone.now() - timezone.timedelta(days=120),
        }
    )
    ssr1, _ = SelfStudyReport.objects.get_or_create(
        application=app1,
        defaults={
            'executive_summary': "أعدت كلية الطب والعلوم الصحية بجامعة صنعاء هذه الدراسة الذاتية الشاملة لبرنامج الطب والجراحة استناداً لمعايير مجلس الاعتماد الوطني والمعايير الدولية للاتحاد العالمي للتعليم الطبي (WFME). تم تدقيق كافة مخرجات التعلم، والمعامل السريرية، ومستشفيات التدريب المعتمدة.",
            'internal_committee_names': "أ.د. محمد الشهاري (عميد الكلية)، أ.د. هدى العماد (عميد الجودة)، أ.د. مطهر العريقي (منسق المعايير السريرية).",
            'is_locked': True,
        }
    )
    # Evidences for App 1
    ind_sample = StandardIndicator.objects.filter(category__track=AccreditationTrackType.PROGRAMMATIC).first()
    if ind_sample:
        EvidenceDocument.objects.get_or_create(
            application=app1,
            code="DOC-MED-01",
            defaults={
                'indicator': ind_sample,
                'title': "وثيقة توصيف برنامج الطب والجراحة ومصفوفة نتاجات التعلم (WFME Standard)",
                'description': "تتضمن مواصفات البرنامج الكاملة ومطابقة المقررات مع متطلبات المعيار الوطني.",
            }
        )

    # Desk Review for App 1
    DeskReviewEvaluation.objects.get_or_create(
        application=app1,
        defaults={
            'reviewer': council_sec,
            'decision': DeskReviewEvaluation.DeskDecision.ACCEPTED,
            'formal_criteria_met': True,
            'completeness_percentage': 95,
            'technical_remarks': "استوفت كلية الطب كافة المتطلبات الشكلية والموضوعية، وتم توفير كافة شواهد المختبرات والمستشفيات المعتمدة.",
            'is_completed': True,
        }
    )

    # Review Team for App 1
    team1, _ = ReviewTeam.objects.get_or_create(
        application=app1,
        defaults={
            'decree_number': "قرار الأمانة العامة رقم (2026/08)",
            'formation_date': timezone.now().date() - timezone.timedelta(days=90),
            'chairperson': reviewer_lead,
        }
    )
    ReviewTeamMember.objects.get_or_create(
        team=team1,
        user=reviewer_lead,
        defaults={'role_in_team': ReviewTeamMember.PanelRole.CHAIRPERSON, 'conflict_of_interest_signed': True}
    )

    # Site Visit for App 1
    visit1, _ = SiteVisitSchedule.objects.get_or_create(
        application=app1,
        defaults={
            'start_date': timezone.now().date() - timezone.timedelta(days=60),
            'end_date': timezone.now().date() - timezone.timedelta(days=55),
            'visit_location': "كلية الطب - مستشفى الكويت الجامعي - مستشفى الثورة",
            'agenda_details': "تمت المعاينة الميدانية لمعامل التشريح، ومختبرات المهارات السريرية، وقاعات التدريس، ومستشفى التدريب، ومقابلة الطلاب وهيئة التدريس.",
            'status': SiteVisitSchedule.VisitStatus.COMPLETED,
            'final_exit_meeting_notes': "أثنى الفريق على الكفاءة العالية للكادر التدريسي والبنية التحتية المتطورة لمركز المهارات السريرية.",
        }
    )
    FacilityInspection.objects.get_or_create(
        visit=visit1,
        facility_name="مركز المهارات السريرية والمحاكاة الطبية (Skills Lab)",
        defaults={
            'category': FacilityInspection.FacilityCategory.LABS,
            'inspector': reviewer_lead,
            'capacity_students': 45,
            'adequacy_rating': FacilityInspection.AdequacyLevel.EXCELLENT,
            'safety_compliance': True,
            'detailed_observations': "يحتوي المركز على أجهزة محاكاة سريرية متطورة ومطابقة لأحدث المعايير الطبية الدولية.",
        }
    )
    StakeholderInterview.objects.get_or_create(
        visit=visit1,
        target_group=StakeholderInterview.StakeholderGroup.CURRENT_STUDENTS,
        defaults={
            'conducted_by': reviewer_lead,
            'attendees_count': 25,
            'interview_date': timezone.now() - timezone.timedelta(days=58),
            'key_themes_discussed': "الرضا عن جودة التدريب السريري، أساليب التقييم، وتوفر المصادر.",
            'feedback_summary': "عبر الطلاب عن رضا مرتفع عن المتابعة السريرية من أساتذة الكلية في المستشفيات الجامعية.",
        }
    )

    # External Report for App 1
    ExternalReviewReport.objects.get_or_create(
        application=app1,
        defaults={
            'draft_executive_summary': "أظهر تقييم برنامج الطب والجراحة استيفاءً نموذجياً لمعايير الاعتماد البرامجي الوطنية.",
            'draft_findings_per_standard': "استيفاء كامل للمجالات الثمانية مع ممارسات نوعية في التعليم المرتكز على حل المعضلات الطبية.",
            'draft_sent_to_institution_date': timezone.now() - timezone.timedelta(days=45),
            'institution_reply_text': "تثمن الجامعة جهود فريق المحكمين، وتؤكد صحة كافة المعطيات الواردة في المسودة.",
            'institution_reply_date': timezone.now() - timezone.timedelta(days=35),
            'final_report_text': "يوصي فريق التقييم الخارجي بالإجماع بمنح برنامج الطب والجراحة بجامعة صنعاء الاعتماد البرامجي الكامل لمدة خمس سنوات.",
            'final_recommendation': ExternalReviewReport.FinalRecommendation.FULL_ACCREDITATION,
            'final_submitted_to_council_date': timezone.now() - timezone.timedelta(days=30),
        }
    )

    # Council Meeting & Decision for App 1
    meeting1, _ = CouncilMeeting.objects.get_or_create(
        meeting_number="الجلسة رقم (03) لسنة 2026م",
        defaults={
            'meeting_date': timezone.now().date() - timezone.timedelta(days=20),
            'chairperson_name': "أ.د. رئيس مجلس الاعتماد الأكاديمي",
            'meeting_agenda': "مناقشة التقرير النهائي للاعتماد البرامجي لكلية الطب بجامعة صنعاء.",
            'minutes_summary': "وافق أعضاء المجلس بالإجماع على التقرير الفني وقرروا منح الاعتماد الكامل لمدة 5 سنوات.",
        }
    )
    meeting1.attendees.add(board_member)

    decision1, _ = AccreditationDecision.objects.get_or_create(
        application=app1,
        defaults={
            'meeting': meeting1,
            'decision_type': AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            'decree_number': "قرار المجلس رقم (18) لسنة 2026م",
            'decision_date': timezone.now().date() - timezone.timedelta(days=20),
            'validity_years': 5,
            'start_date': timezone.now().date() - timezone.timedelta(days=20),
            'expiry_date': timezone.now().date().replace(year=timezone.now().year + 5),
            'legal_justifications': "بناءً على قانون التعليم العالي وتقرير فريق المراجعة الخارجية المعتمد، واستيفاء كافة المعايير الوطنية للتعليم الطبي بنسبة 94%.",
            'votes_in_favor': 9,
            'votes_against': 0,
        }
    )

    # Certificate with QR Code for App 1
    cert1, cert1_created = AccreditationCertificate.objects.get_or_create(
        decision=decision1,
        defaults={
            'national_registry_code': "YEM-CAQA-PROG-2026-0001",
            'issue_date': timezone.now().date() - timezone.timedelta(days=20),
            'printed_at': timezone.now(),
        }
    )
    # Generate QR verification
    cert1.generate_qr_code(f"http://127.0.0.1:8000/decisions/verify/{cert1.certificate_uuid}/")
    cert1.save()

    # Improvement plan for Stage 7
    ContinuousImprovementPlan.objects.get_or_create(
        decision=decision1,
        defaults={
            'plan_title': "خطة التحسين المستمر لبرنامج الطب والجراحة 2026 - 2031",
            'implementation_timeframe': "5 سنوات",
            'corrective_actions_matrix': "التوسع في أجهزة المحاكاة الرقمية، وزيادة أبحاث الطلاب في المجلات المصنفة دولياً.",
            'is_approved_by_council': True,
        }
    )

    # App 2: Institutional Accreditation - UST (Currently at Stage 4: Site Visit In Progress)
    app2, _ = AccreditationApplication.objects.get_or_create(
        application_number="CAQA-INST-2026-0002",
        defaults={
            'track': AccreditationTrackType.INSTITUTIONAL,
            'institution': ust_univ,
            'applicant_user': ust_quality_user,
            'academic_year': "2025/2026",
            'current_stage': StageChoices.STAGE_4,
            'status': ApplicationStatus.SITE_VISIT_SCHEDULED,
            'submission_date': timezone.now() - timezone.timedelta(days=45),
        }
    )
    SelfStudyReport.objects.get_or_create(
        application=app2,
        defaults={
            'executive_summary': "تقرير الدراسة الذاتية المؤسسية لجامعة العلوم والتكنولوجيا ويشمل تقييم الحوكمة، البنية الجامعية، كفاءة الكليات، والموارد المالية.",
            'internal_committee_names': "أ.د. عادل المتوكل (رئيس الجامعة)، أ.د. أمين الكستبان (عميد الجودة).",
            'is_locked': True,
        }
    )
    DeskReviewEvaluation.objects.get_or_create(
        application=app2,
        defaults={
            'reviewer': council_sec,
            'decision': DeskReviewEvaluation.DeskDecision.ACCEPTED,
            'formal_criteria_met': True,
            'completeness_percentage': 90,
            'technical_remarks': "استوفت الجامعة المعايير الشكلية والموضوعية وتم استيفاء كافة الوثائق المطلوبة.",
            'is_completed': True,
        }
    )
    team2, _ = ReviewTeam.objects.get_or_create(
        application=app2,
        defaults={
            'decree_number': "قرار أمين عام المجلس رقم (2026/14)",
            'formation_date': timezone.now().date() - timezone.timedelta(days=15),
            'chairperson': reviewer_lead,
        }
    )
    SiteVisitSchedule.objects.get_or_create(
        application=app2,
        defaults={
            'start_date': timezone.now().date(),
            'end_date': timezone.now().date() + timezone.timedelta(days=4),
            'visit_location': "المقر الرئيسي لجامعة العلوم والتكنولوجيا - صنعاء",
            'agenda_details': "فحص المباني، القاعات المركزية، المستشفى الجامعي، مراكز الحاسوب ومقابلة ممثلي المجتمع والطلاب.",
            'status': SiteVisitSchedule.VisitStatus.IN_PROGRESS,
        }
    )

    # App 3: Programmatic Accreditation - Aden University Clinical Pharmacy (At Stage 2: Desk Review)
    app3, _ = AccreditationApplication.objects.get_or_create(
        application_number="CAQA-PROG-2026-0003",
        defaults={
            'track': AccreditationTrackType.PROGRAMMATIC,
            'institution': aden_univ,
            'program': aden_pharm_prog,
            'applicant_user': council_sec,
            'academic_year': "2025/2026",
            'current_stage': StageChoices.STAGE_2,
            'status': ApplicationStatus.DESK_UNDER_REVIEW,
            'submission_date': timezone.now() - timezone.timedelta(days=10),
        }
    )
    SelfStudyReport.objects.get_or_create(
        application=app3,
        defaults={
            'executive_summary': "الدراسة الذاتية لبرنامج بكالوريوس الصيدلة السريرية بكلية الصيدلة - جامعة عدن.",
            'internal_committee_names': "د. خالد السويدي (عميد الكلية)، د. منى باحبيب (رئيسة قسم الصيدلة السريرية).",
            'is_locked': True,
        }
    )
    DeskReviewEvaluation.objects.get_or_create(
        application=app3,
        defaults={
            'reviewer': council_sec,
            'decision': DeskReviewEvaluation.DeskDecision.NEEDS_COMPLETION,
            'formal_criteria_met': False,
            'completeness_percentage': 65,
            'deficiencies_requested': "مطلوب استكمال اتفاقيات التدريب السريري بمستشفيات عدن المعتمدة، وتحديث توصيف مقررات الفصل التاسع والعاشر.",
            'technical_remarks': "الملف بحاجة لاستكمال النواقص المحددة قبل الانتقال للزيارة الميدانية.",
            'is_completed': False,
        }
    )

    print("[OK] Live accreditation applications created.")

    # 8. Standard Versions and Linking
    from apps.standards.models import StandardVersion
    v_inst, _ = StandardVersion.objects.get_or_create(
        track=AccreditationTrackType.INSTITUTIONAL,
        version_number="2.0",
        defaults={
            'title': "الدليل الوطني لمعايير الاعتماد المؤسسي لمؤسسات التعليم العالي في الجمهورية اليمنية",
            'adoption_decree': "قرار مجلس الإدارة رقم (14) لسنة 2024م",
            'status': StandardVersion.VersionStatus.ACTIVE,
            'effective_date': timezone.now().date(),
            'changelog': "تحديث معايير الحوكمة والتحول الرقمي والبنية التحتية والمختبرات وفق المعايير الإقليمية والدولية.",
        }
    )
    StandardCategory.objects.filter(track=AccreditationTrackType.INSTITUTIONAL, version__isnull=True).update(version=v_inst)

    v_prog, _ = StandardVersion.objects.get_or_create(
        track=AccreditationTrackType.PROGRAMMATIC,
        version_number="2.0",
        defaults={
            'title': "الدليل الوطني لمعايير الاعتماد البرامجي في الجمهورية اليمنية",
            'adoption_decree': "قرار مجلس الإدارة رقم (15) لسنة 2024م",
            'status': StandardVersion.VersionStatus.ACTIVE,
            'effective_date': timezone.now().date(),
            'changelog': "تحديث مصفوفات نتاجات التعلم والتدريب السريري والميداني ومؤشرات الكفاءة المهنية.",
        }
    )
    StandardCategory.objects.filter(track=AccreditationTrackType.PROGRAMMATIC, version__isnull=True).update(version=v_prog)
    print("[OK] Standard Versions linked to Categories.")

    # 9. Operations: Training & Fees
    from apps.operations.models import TrainingProgram, FeeSchedule
    TrainingProgram.objects.get_or_create(
        title="البرنامج الوطني لتأهيل وتدريب مقيمي ومحكمي ضمان الجودة الأكاديمية (الدفعة الرابعة)",
        defaults={
            'track': AccreditationTrackType.INSTITUTIONAL,
            'trainer_name': "أ.د. رئيس مجلس الاعتماد ونخبة من خبراء الجودة الدوليين",
            'start_date': timezone.now().date() + timezone.timedelta(days=14),
            'end_date': timezone.now().date() + timezone.timedelta(days=18),
            'location_or_online': "المقر الرئيسي للمجلس - قاعة المؤتمرات الكبرى",
            'target_audience': "أساتذة الجامعات والخبراء المرشحون للانضمام للسجل الوطني للمحكمين",
            'is_active': True,
        }
    )
    TrainingProgram.objects.get_or_create(
        title="ورشة عمل بناء وإدارة بنك الشواهد والأدلة الرقمية وتوصيف البرامج وفق معايير المجلس",
        defaults={
            'track': AccreditationTrackType.PROGRAMMATIC,
            'trainer_name': "د. أحمد المتوكل - أمانة المجلس الفنية",
            'start_date': timezone.now().date() + timezone.timedelta(days=7),
            'end_date': timezone.now().date() + timezone.timedelta(days=9),
            'location_or_online': "عبر تقنية الاتصال المرئي (Online Webinar)",
            'target_audience': "عمداء مراكز التطوير وضمان الجودة ومسؤولو البرامج الأكاديمية بالجامعات",
            'is_active': True,
        }
    )

    FeeSchedule.objects.get_or_create(
        service_name="رسوم مراجعة وفحص طلب الاعتماد المؤسسي الكامل لمؤسسات التعليم العالي",
        defaults={
            'track': AccreditationTrackType.INSTITUTIONAL,
            'regulatory_reference': "لائحة الرسوم والخدمات المقرة بقرار وزير التعليم العالي رقم (8) لسنة 2023م",
            'amount_yer': 1500000.00,
            'is_active': True,
        }
    )
    FeeSchedule.objects.get_or_create(
        service_name="رسوم مراجعة وتقييم طلب الاعتماد البرامجي التخصصي",
        defaults={
            'track': AccreditationTrackType.PROGRAMMATIC,
            'regulatory_reference': "لائحة الرسوم والخدمات المقرة بقرار وزير التعليم العالي رقم (8) لسنة 2023م",
            'amount_yer': 900000.00,
            'is_active': True,
        }
    )
    print("[OK] Training programs and Fee Schedules initialized.")

    print("=== Complete! ===")

if __name__ == '__main__':
    run_seed()
