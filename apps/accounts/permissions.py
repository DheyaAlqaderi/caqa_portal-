import logging
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import (
    User,
    DynamicPermission,
    RolePermissionAssignment,
    UserPermissionOverride,
    PermissionAuditRecord,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. PERMISSION CATALOG DEFINITION
# ------------------------------------------------------------------------------

PERMISSION_CATALOG = [
    # General Access
    {
        'codename': 'can_view_application',
        'name': 'استعراض طلبات الاعتماد',
        'description': 'استعراض بيانات وملفات طلبات الاعتماد الأكاديمي ضمن النطاق المصرح به.',
        'module': DynamicPermission.Module.GENERAL,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_submit_application',
        'name': 'تقديم طلب اعتماد أولي',
        'description': 'إنشاء وتقديم طلب اعتماد أكاديمي رسمي نيابة عن المؤسسة التعليمية التابع لها حصراً.',
        'module': DynamicPermission.Module.GENERAL,
        'is_governance_locked': True,  # Strictly limited to INSTITUTION_OFFICER
    },
    {
        'codename': 'can_edit_self_study',
        'name': 'تحرير الدراسة الذاتية والشواهد',
        'description': 'تحرير بنود ومؤشرات الدراسة الذاتية وإرفاق شواهد الجودة للمؤسسة التابع لها.',
        'module': DynamicPermission.Module.GENERAL,
        'is_governance_locked': True,  # Strictly limited to INSTITUTION_OFFICER
    },

    # Secretariat & Administrative Processing
    {
        'codename': 'can_conduct_desk_review',
        'name': 'إجراء الفحص المكتبي واستيفاء الشروط',
        'description': 'مراجعة ملف الطلب شكلياً ومكتبياً والتحقق من الاستيفاء الإداري.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_request_corrections',
        'name': 'طلب استيفاء نواقص من المؤسسة',
        'description': 'توجيه طلب استيفاء وثائق أو متطلبات ناقصة للمؤسسة التعليمية أثناء الفحص.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_view_finance',
        'name': 'استعراض الفواتير والعمليات المالية',
        'description': 'الاطلاع على الفواتير وسندات السداد ورسوم الاعتماد المقررة.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_verify_payment',
        'name': 'التحقق المالي وتأكيد سداد الفواتير',
        'description': 'مراجعة سند السداد البنكي واعتماد تحصيل الرسوم المالية للطلب.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_nominate_reviewers',
        'name': 'ترشيح وتأليف فريق التحكيم الخارجي',
        'description': 'ترشيح رئيس وأعضاء فريق المراجعة والتقييم الخارجي المستقل.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_schedule_site_visit',
        'name': 'جدولة وإدارة الزيارة الميدانية',
        'description': 'تخطيط وتنسيق جدول الزيارة الميدانية ومواعيد المقابلات والتفتيش الأكاديمي.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_generate_comparison',
        'name': 'إعداد التقرير المقارن التحليلي',
        'description': 'استخراج ومقارنة تقييم المؤسسة الذاتي مع تقييم فريق المراجعة الخارجي وإعداد التحليل.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_issue_financial_clearance',
        'name': 'إصدار إبراء الذمة المالية وسند التحصيل',
        'description': 'التأكيد المالي النهائي لسداد رسوم الاعتماد وإصدار وثيقة الإبراء المالي للطلب.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': True,  # Strictly limited to Finance, Sec General, and Admin
    },
    {
        'codename': 'can_manage_evaluator_registry',
        'name': 'إدارة وتحديث السجل الوطني للمحكمين',
        'description': 'مراجعة طلبات قيد المحكمين وتأهيلهم واعتماد شهادات التحكيم الوطني وتحديث السجل.',
        'module': DynamicPermission.Module.SECRETARIAT,
        'is_governance_locked': False,
    },

    # Reviewer Operations
    {
        'codename': 'can_declare_coi',
        'name': 'تسجيل إقرار النزاهة وتعارض المصالح',
        'description': 'إقرار المحكم الخارجي بالحياد وخلو تعارض المصالح أو الإفصاح عن أي علاقة سابقة.',
        'module': DynamicPermission.Module.REVIEWER,
        'is_governance_locked': True,  # Strictly limited to EXTERNAL_REVIEWER
    },
    {
        'codename': 'can_submit_evaluation',
        'name': 'رصد درجات المؤشرات وأدلة الفحص',
        'description': 'تقييم مؤشرات المعايير وإدخال الدرجات وملاحظات التحكيم للبرنامج المكلف به.',
        'module': DynamicPermission.Module.REVIEWER,
        'is_governance_locked': True,  # Strictly limited to EXTERNAL_REVIEWER
    },
    {
        'codename': 'can_draft_external_report',
        'name': 'تحرير مسودة تقرير المراجعة الخارجية',
        'description': 'صياغة وإعداد مسودة تقرير التقييم الخارجي الشامل وملاحظات الفريق.',
        'module': DynamicPermission.Module.REVIEWER,
        'is_governance_locked': True,  # Strictly limited to EXTERNAL_REVIEWER
    },
    {
        'codename': 'can_respond_to_external_report',
        'name': 'تقديم رد المؤسسة على مسودة التقرير',
        'description': 'رفع ملاحظات ورد المؤسسة التعليمية على مسودة تقرير المراجعة الخارجية خلال المهلة.',
        'module': DynamicPermission.Module.REVIEWER,
        'is_governance_locked': True,  # Strictly limited to INSTITUTION_OFFICER
    },
    {
        'codename': 'can_finalize_external_report',
        'name': 'اعتماد ورفع التقرير النهائي للمحكمين',
        'description': 'المصادقة على التقرير النهائي لفريق المراجعة الخارجية وإحالته رسمياً للأمانة.',
        'module': DynamicPermission.Module.REVIEWER,
        'is_governance_locked': True,  # Strictly limited to EXTERNAL_REVIEWER
    },

    # Council Governance
    {
        'codename': 'can_approve_review_team',
        'name': 'اعتماد تشكيل فريق التحكيم الخارجي',
        'description': 'المصادقة الرسمية على تشكيل فريق المراجعين الخارجيين وإصدار قرار التكليف.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_view_board_materials',
        'name': 'استعراض ملفات ومداولات مجلس الإدارة',
        'description': 'الاطلاع على الملفات والتقارير المقارنة المحالة لاجتماعات مجلس الإدارة.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_participate_in_meeting',
        'name': 'حضور جلسات المجلس والمشاركة بالمداولة',
        'description': 'المشاركة القانونية في جلسات المجلس الرسمية لمناقشة قرارات الاعتماد.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to BOARD_MEMBER
    },
    {
        'codename': 'can_record_individual_vote',
        'name': 'تسجيل التصويت الفردي لعضو المجلس',
        'description': 'الإدلاء بالصوت الفردي لعضو المجلس على طلب الاعتماد داخل جلسة رسمية مكتملة النصاب.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to BOARD_MEMBER
    },
    {
        'codename': 'can_record_meeting_minutes',
        'name': 'توثيق محضر وقرار اجتماع المجلس',
        'description': 'تدوين وقائع جلسة المجلس الرسمية ونتائج فرز الأصوات والقرارات المتخذة.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_finalize_collective_decision',
        'name': 'المصادقة على قرار الاعتماد النهائي الجماعي',
        'description': 'إصدار قرار الاعتماد الأكاديمي النهائي الجماعي بموجب نصاب وأغلبية نظامية معتمدة.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to BOARD_MEMBER
    },
    {
        'codename': 'can_manage_certificates',
        'name': 'إدارة وإصدار شهادات الاعتماد الرسمية',
        'description': 'توليد وتوثيق وطباعة شهادات الاعتماد الأكاديمي الصادرة بموجب قرارات المجلس.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_sign_council_decrees',
        'name': 'التوقيع الرئاسي والسيادي على القرارات والشهادات',
        'description': 'التوقيع النهائي والختم السيادي على قرارات الاعتماد وشهادات السجل الوطني.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to COUNCIL_CHAIRMAN, COUNCIL_VICE_CHAIRMAN, ADMIN
    },

    # Grievances & Appeals
    {
        'codename': 'can_submit_grievance',
        'name': 'تقديم طعن/تظلم على قرار الاعتماد',
        'description': 'رفع طلب تظلم رسمي من المؤسسة التعليمية على قرار رفض أو مشروط خلال المهلة النظامية.',
        'module': DynamicPermission.Module.GRIEVANCES,
        'is_governance_locked': True,  # Strictly limited to INSTITUTION_OFFICER
    },
    {
        'codename': 'can_review_grievance_legal_terms',
        'name': 'الفحص القانوني الشكلي لعرائض التظلمات',
        'description': 'فحص استيفاء المواعيد والشروط القانونية للطعون والتظلمات وإعداد المذكرة التفسيرية.',
        'module': DynamicPermission.Module.GRIEVANCES,
        'is_governance_locked': True,  # Strictly limited to LEGAL_DIRECTOR, COUNCIL_SECRETARY_GENERAL, COUNCIL_SECRETARY, ADMIN
    },
    {
        'codename': 'can_review_grievance_committee',
        'name': 'فحص التظلم وإعداد التقرير الفني المستقل',
        'description': 'فحص عريضة الطعن والأدلة وإعداد تقرير فني مسبب للجنة المستقلة.',
        'module': DynamicPermission.Module.GRIEVANCES,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_decide_grievance',
        'name': 'البت النهائي في نتيجة التظلم الأكاديمي',
        'description': 'إصدار الحكم النهائي في التظلم من قبل مجلس الإدارة بكامل هيئته القانونية.',
        'module': DynamicPermission.Module.GRIEVANCES,
        'is_governance_locked': True,  # Strictly limited to BOARD_MEMBER
    },

    # Ministerial & Sovereign Oversight
    {
        'codename': 'can_view_national_strategic_dashboard',
        'name': 'الإشراف العام واستعراض المؤشرات الاستراتيجية الوطنية',
        'description': 'الاطلاع على لوحة المؤشرات الوطنية الشاملة للتعليم العالي ومؤسساته في الجمهورية.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_nominate_board_members',
        'name': 'ترشيح رئيس وأعضاء مجلس إدارة مجلس الاعتماد الأكاديمي',
        'description': 'إعداد ورفع قوائم ترشيح قيادة وأعضاء مجلس الإدارة لرئاسة مجلس الوزراء.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to MINISTER
    },
    {
        'codename': 'can_ratify_council_policies',
        'name': 'المصادقة والاعتماد النهائي للسياسات واللوائح العامة',
        'description': 'المصادقة الوزارية النهائية وإصدار القرارات التنفيذية للوائح وسياسات المجلس.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': True,  # Strictly limited to MINISTER
    },
    {
        'codename': 'can_view_all_registry_reports',
        'name': 'استعراض التقارير السيادية لمؤسسات وبرامج التعليم العالي',
        'description': 'الاطلاع الشامل على كافة تقارير الجودة والقرارات وسجل المؤسسات بالجمهورية.',
        'module': DynamicPermission.Module.GOVERNANCE,
        'is_governance_locked': False,
    },

    # System Administration & Diagnostics
    {
        'codename': 'can_manage_user_accounts',
        'name': 'اعتماد وإدارة حسابات المستخدمين',
        'description': 'مراجعة طلبات التسجيل الجديدة وتفعيل الحسابات وضبط الأدوار المصرح بها.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_manage_permissions',
        'name': 'إدارة مصفوفة الصلاحيات والاستثناءات',
        'description': 'ضبط تعيينات الأدوار والاستثناءات الفردية غير المقيدة بالحوكمة السيادية.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': True,  # Strictly limited to ADMIN
    },
    {
        'codename': 'can_view_technical_audit',
        'name': 'الفحص والتشخيص التقني المقيد (للقراءة فقط)',
        'description': 'استعراض مؤشرات الأداء والتشخيص الفني وحالة النظام للأغراض التقنية دون صلاحية تعديل.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': True,  # Strictly limited to ADMIN
    },
    {
        'codename': 'can_manage_reference_data',
        'name': 'إدارة البيانات المرجعية والهيكل المؤسسي تقنياً',
        'description': 'إدارة السجلات المرجعية للمؤسسات والكليات والأقسام والبرامج والتصنيفات مع الحفاظ على عزل البيانات.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_manage_system_settings',
        'name': 'إدارة الإعدادات العامة للنظام والأمان والبريد',
        'description': 'ضبط إعدادات البوابة، خادم البريد SMTP، سياسات رفع الملفات، وإعدادات الجلسات والأمان.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': True,  # Strictly limited to ADMIN & IT_DIRECTOR
    },
    {
        'codename': 'can_monitor_notifications',
        'name': 'مراقبة الإشعارات والبريد وإعادة الإرسال الآمن',
        'description': 'متابعة حالة تسليم الإشعارات والرسائل النصية والبريد وإعادة محاولة الإرسال الفاشل بأمان.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_manage_files_storage',
        'name': 'إدارة ومراقبة الملفات ومساحة التخزين',
        'description': 'فحص بيانات الملفات المرفوعة، سعة التخزين، وكشف الملفات المفقودة أو اليتيمة دون الإخلال بسرية الوثائق.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': True,  # Strictly limited to ADMIN & IT_DIRECTOR
    },
    {
        'codename': 'can_monitor_workflows',
        'name': 'مراقبة سير العمليات والمسارات التشغيلية (للقراءة فقط)',
        'description': 'متابعة التقدم التقني والزمني لمسارات الاعتماد واللجان والقرارات دون صلاحية التدخل أو الاعتماد الأكاديمي.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': False,
    },
    {
        'codename': 'can_manage_backups',
        'name': 'إدارة النسخ الاحتياطي والاستعادة المحمية',
        'description': 'إنشاء النسخ الاحتياطية لقاعدة البيانات، التحقق من سلامتها ببصمة SHA-256، وتنفيذ الاستعادة المحمية.',
        'module': DynamicPermission.Module.SYSTEM,
        'is_governance_locked': True,  # Strictly limited to ADMIN
    },
]

# ------------------------------------------------------------------------------
# 2. DEFAULT LEAST-PRIVILEGE ROLE MAPPING
# ------------------------------------------------------------------------------

DEFAULT_ROLE_PERMISSIONS = {
    User.Roles.ADMIN: [
        'can_manage_user_accounts',
        'can_manage_permissions',
        'can_view_technical_audit',
        'can_view_all_registry_reports',
        'can_manage_reference_data',
        'can_manage_system_settings',
        'can_monitor_notifications',
        'can_manage_files_storage',
        'can_monitor_workflows',
        'can_manage_backups',
    ],
    # 1. Central Administration (Council Board & Sovereign Leadership)
    User.Roles.PRIME_MINISTER: [
        'can_view_application',
        'can_view_board_materials',
        'can_view_national_strategic_dashboard',
        'can_view_all_registry_reports',
    ],
    User.Roles.MINISTER: [
        'can_view_application',
        'can_view_board_materials',
        'can_view_national_strategic_dashboard',
        'can_nominate_board_members',
        'can_ratify_council_policies',
        'can_view_all_registry_reports',
    ],
    User.Roles.COUNCIL_CHAIRMAN: [
        'can_view_application',
        'can_view_board_materials',
        'can_participate_in_meeting',
        'can_finalize_collective_decision',
        'can_manage_certificates',
        'can_sign_council_decrees',
        'can_decide_grievance',
        'can_view_all_registry_reports',
        'can_view_national_strategic_dashboard',
    ],
    User.Roles.COUNCIL_VICE_CHAIRMAN: [
        'can_view_application',
        'can_view_board_materials',
        'can_participate_in_meeting',
        'can_finalize_collective_decision',
        'can_sign_council_decrees',
        'can_decide_grievance',
        'can_view_all_registry_reports',
    ],
    User.Roles.BOARD_MEMBER: [
        'can_view_application',
        'can_approve_review_team',
        'can_view_board_materials',
        'can_participate_in_meeting',
        'can_record_individual_vote',
        'can_finalize_collective_decision',
        'can_review_grievance_committee',
        'can_decide_grievance',
    ],

    # 2. General Secretariat & Specialized Directorates
    User.Roles.COUNCIL_SECRETARY_GENERAL: [
        'can_view_application',
        'can_conduct_desk_review',
        'can_request_corrections',
        'can_view_finance',
        'can_verify_payment',
        'can_issue_financial_clearance',
        'can_nominate_reviewers',
        'can_approve_review_team',
        'can_schedule_site_visit',
        'can_generate_comparison',
        'can_view_board_materials',
        'can_record_meeting_minutes',
        'can_manage_certificates',
        'can_view_all_registry_reports',
    ],
    User.Roles.COUNCIL_SECRETARY: [
        'can_view_application',
        'can_conduct_desk_review',
        'can_request_corrections',
        'can_view_finance',
        'can_verify_payment',
        'can_issue_financial_clearance',
        'can_nominate_reviewers',
        'can_schedule_site_visit',
        'can_generate_comparison',
        'can_view_board_materials',
        'can_record_meeting_minutes',
        'can_manage_certificates',
    ],
    User.Roles.DG_ACCREDITATION: [
        'can_view_application',
        'can_conduct_desk_review',
        'can_request_corrections',
        'can_view_all_registry_reports',
    ],
    User.Roles.DG_EVALUATION: [
        'can_view_application',
        'can_nominate_reviewers',
        'can_schedule_site_visit',
        'can_generate_comparison',
        'can_view_board_materials',
    ],
    User.Roles.DG_QUALITY: [
        'can_view_application',
        'can_manage_evaluator_registry',
        'can_view_all_registry_reports',
    ],
    User.Roles.DG_FINANCE_ADMIN: [
        'can_view_application',
        'can_view_finance',
        'can_verify_payment',
        'can_issue_financial_clearance',
    ],
    User.Roles.LEGAL_DIRECTOR: [
        'can_view_application',
        'can_review_grievance_legal_terms',
        'can_review_grievance_committee',
        'can_view_board_materials',
    ],
    User.Roles.IT_DIRECTOR: [
        'can_view_application',
        'can_view_technical_audit',
        'can_manage_user_accounts',
        'can_view_all_registry_reports',
        'can_manage_reference_data',
        'can_manage_system_settings',
        'can_monitor_notifications',
        'can_manage_files_storage',
        'can_monitor_workflows',
    ],

    # 3. External Stakeholders, Autonomous Bodies & Oversight
    User.Roles.EXTERNAL_REVIEWER: [
        'can_view_application',
        'can_declare_coi',
        'can_submit_evaluation',
        'can_draft_external_report',
        'can_finalize_external_report',
    ],
    User.Roles.INSTITUTION_OFFICER: [
        'can_view_application',
        'can_submit_application',
        'can_edit_self_study',
        'can_view_finance',
        'can_respond_to_external_report',
        'can_submit_grievance',
    ],
    User.Roles.UNIVERSITY_PRESIDENT: [
        'can_view_application',
        'can_submit_application',
        'can_view_finance',
        'can_submit_grievance',
        'can_respond_to_external_report',
    ],
    User.Roles.GRIEVANCE_COMMITTEE_MEMBER: [
        'can_view_application',
        'can_review_grievance_committee',
        'can_view_board_materials',
    ],
    User.Roles.SURVEILLANCE_AUDITOR: [
        'can_view_application',
        'can_view_all_registry_reports',
    ],
    User.Roles.PUBLIC_VERIFIER: [
        'can_view_all_registry_reports',
    ],
}

# ------------------------------------------------------------------------------
# 3. NON-OVERRIDABLE GOVERNANCE RESTRICTIONS (HARD GATES)
# ------------------------------------------------------------------------------

GOVERNANCE_LOCKED_PERMISSIONS = {
    # Ministerial Sovereign Gates: strictly limited to MINISTER
    'can_nominate_board_members': [User.Roles.MINISTER],
    'can_ratify_council_policies': [User.Roles.MINISTER],

    # Academic Decision Gates: strictly limited to Board Members & Leadership
    'can_record_individual_vote': [User.Roles.BOARD_MEMBER],
    'can_finalize_collective_decision': [
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN,
        User.Roles.BOARD_MEMBER
    ],
    'can_decide_grievance': [
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN,
        User.Roles.BOARD_MEMBER
    ],
    'can_participate_in_meeting': [
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN,
        User.Roles.BOARD_MEMBER
    ],
    'can_sign_council_decrees': [
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN
    ],

    # Financial Clearance Gate: strictly limited to Finance Director, Sec General, and Admin
    'can_issue_financial_clearance': [
        User.Roles.DG_FINANCE_ADMIN,
        User.Roles.COUNCIL_SECRETARY_GENERAL,
        User.Roles.COUNCIL_SECRETARY,
        User.Roles.ADMIN
    ],

    # Legal Review Gate: strictly limited to Legal Director, Sec General, and Admin
    'can_review_grievance_legal_terms': [
        User.Roles.LEGAL_DIRECTOR,
        User.Roles.COUNCIL_SECRETARY_GENERAL,
        User.Roles.COUNCIL_SECRETARY,
        User.Roles.ADMIN
    ],

    # Institutional Representation: strictly limited to institutional leadership and officers
    'can_submit_application': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
    'can_edit_self_study': [User.Roles.INSTITUTION_OFFICER],
    'can_respond_to_external_report': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
    'can_submit_grievance': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],

    # Reviewer Operational Gate (Zero Conflict of Interest - No Board or Secretariat can act as Reviewer)
    'can_declare_coi': [User.Roles.EXTERNAL_REVIEWER],
    'can_submit_evaluation': [User.Roles.EXTERNAL_REVIEWER],
    'can_draft_external_report': [User.Roles.EXTERNAL_REVIEWER],
    'can_finalize_external_report': [User.Roles.EXTERNAL_REVIEWER],

    # Technical Admin Governance Gates: strictly limited to ADMIN / IT_DIRECTOR
    'can_manage_permissions': [User.Roles.ADMIN],
    'can_view_technical_audit': [User.Roles.ADMIN, User.Roles.IT_DIRECTOR],
    'can_manage_system_settings': [User.Roles.ADMIN, User.Roles.IT_DIRECTOR],
    'can_manage_files_storage': [User.Roles.ADMIN, User.Roles.IT_DIRECTOR],
    'can_manage_backups': [User.Roles.ADMIN],
}

# ------------------------------------------------------------------------------
# 4. AUDIT & LOGGING SERVICE
# ------------------------------------------------------------------------------

def record_permission_audit(
    actor,
    action_type,
    target_role="",
    target_user=None,
    permission_codename="",
    previous_value="",
    new_value="",
    reason="",
    request=None
):
    """
    Centralized factory for creating immutable permission audit records.
    Safely captures IP address and request metadata.
    """
    ip_addr = None
    if request:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ip_addr = x_forwarded.split(',')[0].strip()
        else:
            ip_addr = request.META.get('REMOTE_ADDR')

    actor_obj = actor if (actor and actor.is_authenticated) else None

    return PermissionAuditRecord.objects.create(
        actor=actor_obj,
        action_type=action_type,
        target_role=target_role,
        target_user=target_user,
        permission_codename=permission_codename,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        ip_address=ip_addr,
    )


# ------------------------------------------------------------------------------
# 5. USER OVERRIDE MUTATION SERVICE (TRANSACTIONAL ROTATION)
# ------------------------------------------------------------------------------

def rotate_user_override(user, permission, override_type, reason, granted_by, expires_at=None, request=None):
    """
    Safely applies a new user permission override using transactional rotation.
    1. Runs inside transaction.atomic() to ensure database integrity.
    2. Archives any existing active override (sets is_active=False, records revoked_at and revoked_by).
    3. Creates the new active override.
    4. Creates an immutable PermissionAuditRecord.
    Never overwrites or deletes old records.
    """
    if not reason or not reason.strip():
        raise ValueError("A mandatory administrative reason is required for creating a permission override.")

    if isinstance(permission, str):
        permission = DynamicPermission.objects.get(codename=permission)

    # Check Governance Lock: Overrides cannot bypass Level 1 Hard Gates
    if permission.codename in GOVERNANCE_LOCKED_PERMISSIONS:
        allowed_roles = GOVERNANCE_LOCKED_PERMISSIONS[permission.codename]
        if user.role not in allowed_roles:
            record_permission_audit(
                actor=granted_by,
                action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                target_user=user,
                permission_codename=permission.codename,
                previous_value="",
                new_value=override_type,
                reason=f"Blocked attempt to create override: {permission.codename} is governance-locked to {allowed_roles}",
                request=request
            )
            raise PermissionDenied(f"Cannot grant {permission.codename} to role {user.role}: protected by sovereign governance.")

    # Anti-Self-Escalation Check: User cannot grant or override their own permissions
    if granted_by and granted_by.pk == user.pk:
        record_permission_audit(
            actor=granted_by,
            action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
            target_user=user,
            permission_codename=permission.codename,
            reason="Blocked self-escalation attempt: user cannot modify own permission overrides.",
            request=request
        )
        raise PermissionDenied("Anti-self-escalation: You cannot grant or modify permission overrides for yourself.")

    with transaction.atomic():
        # Archive previous active override
        active_overrides = UserPermissionOverride.objects.filter(
            user=user,
            permission=permission,
            is_active=True
        )
        prev_value = ""
        now = timezone.now()
        for old in active_overrides:
            prev_value = f"{old.override_type} (Active since {old.created_at.strftime('%Y-%m-%d')})"
            old.is_active = False
            old.revoked_at = now
            old.revoked_by = granted_by
            old.save(update_fields=['is_active', 'revoked_at', 'revoked_by'])

            record_permission_audit(
                actor=granted_by,
                action_type=PermissionAuditRecord.ActionType.USER_OVERRIDE_REVOKED,
                target_user=user,
                permission_codename=permission.codename,
                previous_value=old.override_type,
                new_value="ARCHIVED",
                reason=f"Superseded by new override: {reason}",
                request=request
            )

        # Create new active override
        new_override = UserPermissionOverride.objects.create(
            user=user,
            permission=permission,
            override_type=override_type,
            reason=reason.strip(),
            granted_by=granted_by,
            expires_at=expires_at,
            is_active=True
        )

        record_permission_audit(
            actor=granted_by,
            action_type=PermissionAuditRecord.ActionType.USER_OVERRIDE_CREATED,
            target_user=user,
            permission_codename=permission.codename,
            previous_value=prev_value or "None",
            new_value=override_type,
            reason=reason.strip(),
            request=request
        )

        return new_override


def revoke_user_override(override_id, revoked_by, reason="", request=None):
    """
    Deactivates an active user override and archives it.
    """
    with transaction.atomic():
        override = UserPermissionOverride.objects.select_for_update().get(pk=override_id, is_active=True)
        
        # Anti-self-escalation check
        if revoked_by and revoked_by.pk == override.user_id:
            raise PermissionDenied("Anti-self-escalation: You cannot revoke overrides for your own account.")

        override.is_active = False
        override.revoked_at = timezone.now()
        override.revoked_by = revoked_by
        override.save(update_fields=['is_active', 'revoked_at', 'revoked_by'])

        record_permission_audit(
            actor=revoked_by,
            action_type=PermissionAuditRecord.ActionType.USER_OVERRIDE_REVOKED,
            target_user=override.user,
            permission_codename=override.permission.codename,
            previous_value=override.override_type,
            new_value="REVOKED",
            reason=reason or "Administrative deactivation",
            request=request
        )
        return override


# ------------------------------------------------------------------------------
# 6. IDEMPOTENT PERMISSION SEEDING SERVICE
# ------------------------------------------------------------------------------

def seed_default_permissions(stdout=None, dry_run=False):
    """
    Idempotent seeding service.
    1. Creates missing permission catalog entries.
    2. Creates missing default role-permission assignments only (get_or_create).
    3. Never overwrites existing administrator-customized assignments.
    4. Records created entries in the permission audit log.
    """
    created_perms_count = 0
    created_assignments_count = 0

    for perm_data in PERMISSION_CATALOG:
        codename = perm_data['codename']
        if dry_run:
            exists = DynamicPermission.objects.filter(codename=codename).exists()
            if not exists and stdout:
                stdout.write(f"[Dry-Run] Would create permission: {codename}")
            continue

        perm, created = DynamicPermission.objects.get_or_create(
            codename=codename,
            defaults={
                'name': perm_data['name'],
                'description': perm_data['description'],
                'module': perm_data['module'],
                'is_governance_locked': perm_data['is_governance_locked'],
            }
        )
        if created:
            created_perms_count += 1
            record_permission_audit(
                actor=None,
                action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
                permission_codename=codename,
                previous_value="None",
                new_value="CATALOG_INITIALIZED",
                reason="System catalog seeding",
            )

    # Seed Default Role Assignments
    for role, codenames in DEFAULT_ROLE_PERMISSIONS.items():
        for codename in codenames:
            if dry_run:
                exists = RolePermissionAssignment.objects.filter(role=role, permission__codename=codename).exists()
                if not exists and stdout:
                    stdout.write(f"[Dry-Run] Would assign {codename} to role {role}")
                continue

            try:
                perm_obj = DynamicPermission.objects.get(codename=codename)
            except DynamicPermission.DoesNotExist:
                continue

            # Only create if completely missing; do not overwrite is_granted if admin changed it
            assignment, created = RolePermissionAssignment.objects.get_or_create(
                role=role,
                permission=perm_obj,
                defaults={'is_granted': True}
            )
            if created:
                created_assignments_count += 1
                record_permission_audit(
                    actor=None,
                    action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
                    target_role=role,
                    permission_codename=codename,
                    previous_value="Unassigned",
                    new_value="Granted",
                    reason="Initial default role assignment",
                )

    if stdout:
        stdout.write(
            f"Permission seeding completed: {created_perms_count} permissions created, "
            f"{created_assignments_count} default assignments created."
        )

    return {
        'permissions_created': created_perms_count,
        'assignments_created': created_assignments_count,
    }


# ------------------------------------------------------------------------------
# 7. SENSITIVE DATA REDACTION FOR TECHNICAL DIAGNOSTICS
# ------------------------------------------------------------------------------

def redact_sensitive_diagnostics(data):
    """
    Recursively scrubs passwords, session secrets, API tokens, encryption keys,
    and confidential identifiers from technical diagnostic output.
    Operates server-side before rendering.
    """
    SENSITIVE_KEYS = {
        'password', 'secret', 'token', 'key', 'sessionid', 'csrftoken',
        'auth', 'authorization', 'api_key', 'private', 'signature',
        'national_id', 'ssn', 'credential', 'cookie', 'secret_key'
    }

    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in SENSITIVE_KEYS):
                scrubbed[k] = "******** [REDACTED_BY_SECURITY_POLICY] ********"
            else:
                scrubbed[k] = redact_sensitive_diagnostics(v)
        return scrubbed
    elif isinstance(data, (list, tuple)):
        return [redact_sensitive_diagnostics(item) for item in data]
    return data


# ------------------------------------------------------------------------------
# 8. CENTRALIZED AUTHORIZATION PIPELINE (THE 7 DETERMINISTIC LEVELS)
# ------------------------------------------------------------------------------

def has_permission(user, permission_codename: str, resource=None, request=None, workflow_context=None, raise_exception=False) -> bool:
    """
    Deterministic 7-Level Authorization Pipeline.
    Evaluates:
      Level 0: Authentication & Account Active/Approval status
      Level 1: Sovereign Non-Overridable Governance Gates
      Level 2: Active User-Specific Overrides (GRANT / REVOKE)
      Level 3: Role Permission Assignments (is_granted=True, Deny by Default)
      Level 4: Resource Ownership & Scope (Tenant isolation, Reviewer panel)
      Level 5: Conflict-of-Interest Clearance (COI recusal)
      Level 6: Workflow & Governance Preconditions (Quorum, transition guards)
      Level 7: ALLOW

    Returns True if authorized, False otherwise.
    If raise_exception=True and unauthorized, raises PermissionDenied.
    """

    def _deny(reason="Permission denied"):
        logger.debug(f"Auth Denied: user={getattr(user, 'username', 'anon')} perm={permission_codename} reason={reason}")
        if raise_exception:
            raise PermissionDenied(reason)
        return False

    # --------------------------------------------------------------------------
    # Level 0: Authentication and Account Validity
    # --------------------------------------------------------------------------
    if not user or not user.is_authenticated:
        return _deny("User is not authenticated.")

    if not getattr(user, 'is_active', False):
        return _deny("User account is inactive.")

    # Account approval check: unless superuser performing system technical operations
    is_approved = getattr(user, 'is_approved', False)
    if not is_approved:
        return _deny("User account is pending approval or rejected.")

    # --------------------------------------------------------------------------
    # Level 1: Non-Overridable Governance Gates
    # --------------------------------------------------------------------------
    # Check Governance Locks: Neither role assignments nor user overrides can grant locked permissions
    if permission_codename in GOVERNANCE_LOCKED_PERMISSIONS:
        allowed_roles = GOVERNANCE_LOCKED_PERMISSIONS[permission_codename]
        if user.role not in allowed_roles:
            record_permission_audit(
                actor=user,
                action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                target_user=user,
                permission_codename=permission_codename,
                reason=f"Security Gate Blocked: {user.role} attempted to exercise {permission_codename} (restricted to {allowed_roles})",
                request=request
            )
            return _deny(f"Governance Restriction: {permission_codename} is reserved strictly for {allowed_roles}.")

    # Anti-Self-Escalation Check:
    # If the action is managing permissions or users, user cannot modify their own permissions or role
    if permission_codename in ['can_manage_permissions', 'can_manage_user_accounts']:
        target = workflow_context.get('target_user') if workflow_context else None
        if target and target.pk == user.pk:
            record_permission_audit(
                actor=user,
                action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                target_user=user,
                permission_codename=permission_codename,
                reason="Security Gate Blocked: Self-escalation attempt detected.",
                request=request
            )
            return _deny("Anti-Self-Escalation: You cannot modify your own role or permission configuration.")

    # --------------------------------------------------------------------------
    # Level 2: Active User-Specific Overrides
    # --------------------------------------------------------------------------
    has_active_grant_override = False
    now = timezone.now()

    override = UserPermissionOverride.objects.filter(
        user=user,
        permission__codename=permission_codename,
        is_active=True
    ).order_by('-created_at').first()

    if override:
        if override.override_type == UserPermissionOverride.OverrideType.REVOKE:
            # Active REVOKE immediately blocks the permission
            return _deny(f"Permission explicitly revoked by administrative override for user {user.username}.")
        elif override.override_type == UserPermissionOverride.OverrideType.GRANT:
            # Check expiration
            if override.expires_at is None or override.expires_at >= now:
                # Active and valid GRANT override: bypasses Level 3 Role check
                has_active_grant_override = True
            else:
                # Expired override: ignore it, fall through to Level 3
                has_active_grant_override = False

    # --------------------------------------------------------------------------
    # Level 3: Role Permission Assignment
    # --------------------------------------------------------------------------
    if not has_active_grant_override:
        assignment = RolePermissionAssignment.objects.filter(
            role=user.role,
            permission__codename=permission_codename
        ).first()

        if not assignment:
            # Deny by default if no assignment exists
            return _deny(f"No role permission assignment found for role {user.role} and permission {permission_codename} (Deny-by-default).")

        if not assignment.is_granted:
            # Explicit denial on role
            return _deny(f"Permission {permission_codename} is explicitly denied for role {user.role}.")

    # --------------------------------------------------------------------------
    # Level 4: Resource Ownership and Assignment Scope
    # --------------------------------------------------------------------------
    if resource is not None:
        # 1. Institution Isolation (Multi-tenant check)
        if user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]:
            res_inst_id = getattr(resource, 'institution_id', None)
            if res_inst_id is None:
                # Check related application or institution attribute
                if hasattr(resource, 'application') and resource.application:
                    res_inst_id = resource.application.institution_id
                elif hasattr(resource, 'institution') and resource.institution:
                    res_inst_id = resource.institution.id

            if res_inst_id is not None and user.institution_id != res_inst_id:
                record_permission_audit(
                    actor=user,
                    action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                    target_user=user,
                    permission_codename=permission_codename,
                    reason=f"Tenant Isolation Blocked: User from institution {user.institution_id} attempted access to institution {res_inst_id} resource.",
                    request=request
                )
                return _deny("Tenant Isolation: You cannot access resources belonging to another educational institution.")

        # 2. Reviewer Panel Assignment Scope
        if user.role == User.Roles.EXTERNAL_REVIEWER and not user.is_staff:
            app_obj = resource
            if not hasattr(app_obj, 'review_team') and hasattr(resource, 'application'):
                app_obj = resource.application

            if hasattr(app_obj, 'review_team') and app_obj.review_team:
                team = app_obj.review_team
                is_chair = team.chairperson_id == user.id
                is_member = team.members.filter(user=user).exists()
                if not (is_chair or is_member):
                    return _deny("Reviewer Scope: You are not assigned to the review panel for this application.")
            elif hasattr(app_obj, 'review_team') and not app_obj.review_team:
                # No review team formed yet
                if permission_codename in ['can_submit_evaluation', 'can_draft_external_report', 'can_finalize_external_report']:
                    return _deny("Reviewer Scope: No review team has been assigned to this application.")

    # --------------------------------------------------------------------------
    # Level 5: Conflict-of-Interest (COI) Clearance
    # --------------------------------------------------------------------------
    if user.role == User.Roles.EXTERNAL_REVIEWER and resource is not None:
        app_obj = resource if hasattr(resource, 'coi_declarations') else getattr(resource, 'application', None)
        if app_obj and hasattr(app_obj, 'coi_declarations'):
            coi = app_obj.coi_declarations.filter(reviewer=user).first()
            if not coi:
                if permission_codename in ['can_submit_evaluation', 'can_draft_external_report', 'can_finalize_external_report']:
                    return _deny("COI Restriction: You must sign the Conflict of Interest Declaration before evaluating.")
            else:
                has_conflict = (
                    coi.is_conflict_acknowledged or
                    coi.has_taught_in_institution or
                    coi.has_relatives_or_graduates or
                    coi.has_financial_or_consulting
                )
                if has_conflict and permission_codename in ['can_submit_evaluation', 'can_draft_external_report', 'can_finalize_external_report']:
                    record_permission_audit(
                        actor=user,
                        action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                        target_user=user,
                        permission_codename=permission_codename,
                        reason=f"COI Gate Blocked: Reviewer {user.username} has declared/acknowledged a conflict of interest on application {app_obj.pk}.",
                        request=request
                    )
                    return _deny("Conflict of Interest: Access denied due to declared or unhandled conflict of interest.")

    # Grievance Independence Check: Original evaluator cannot review grievance
    if permission_codename == 'can_review_grievance_committee' and resource is not None:
        app_obj = getattr(resource, 'application', None)
        if app_obj and hasattr(app_obj, 'review_team') and app_obj.review_team:
            team = app_obj.review_team
            is_evaluator = (team.chairperson_id == user.id) or team.members.filter(user=user).exists()
            if is_evaluator:
                return _deny("Grievance Independence: An original evaluator cannot review the grievance for this application.")

    # --------------------------------------------------------------------------
    # Level 6: Workflow and Governance Preconditions
    # --------------------------------------------------------------------------
    if permission_codename == 'can_finalize_collective_decision' and (resource is not None or workflow_context is not None):
        meeting = workflow_context.get('meeting') if workflow_context else getattr(resource, 'meeting', None)
        if not meeting:
            return _deny("Council Governance: Finalizing an accreditation decision requires an official Council Meeting.")

    if permission_codename == 'can_conduct_desk_review' and resource is not None:
        # Check if application status allows desk review
        status = getattr(resource, 'status', None)
        from apps.accreditation.models import ApplicationStatus
        if status not in [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.DESK_UNDER_REVIEW,
            ApplicationStatus.DESK_DEFICIENCY,
            ApplicationStatus.DESK_ACCEPTED
        ]:
            return _deny(f"Workflow Condition: Application status ({status}) does not permit desk review operations.")

    # --------------------------------------------------------------------------
    # Level 7: ALLOW
    # --------------------------------------------------------------------------
    return True


# ------------------------------------------------------------------------------
# 9. REUSABLE VIEW DECORATOR
# ------------------------------------------------------------------------------

def permission_required_custom(permission_codename, resource_getter=None, raise_exception=True):
    """
    View decorator enforcing centralized permission evaluation.
    resource_getter: callable(request, *args, **kwargs) -> resource or None
    """
    def decorator(view_func):
        from functools import wraps
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            resource = None
            if resource_getter and callable(resource_getter):
                resource = resource_getter(request, *args, **kwargs)

            has_perm = has_permission(
                user=request.user,
                permission_codename=permission_codename,
                resource=resource,
                request=request,
                raise_exception=raise_exception
            )
            if not has_perm:
                raise PermissionDenied(f"Access Denied: Missing required permission {permission_codename}.")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
