from apps.accounts.models import User
from apps.accreditation.models import StageChoices, ApplicationStatus

def get_contextual_guidance(user, application):
    """
    Contextual Action Engine for CAQA Yemen.
    Determines role-tailored step-by-step instructions, urgency status, next required actions,
    and continuous improvement tips based on the exact user role and application stage.
    """
    if not user or not application:
        return None

    role = getattr(user, 'role', '')
    stage = application.current_stage
    status = application.status

    # Base metadata
    role_label = user.get_role_display() if hasattr(user, 'get_role_display') else 'مستخدم النظام'
    stage_label = application.get_current_stage_display()

    guidance = {
        'role_title': role_label,
        'role_code': role,
        'current_stage_title': stage_label,
        'stage_number': 1,
        'is_my_turn': False,
        'urgency_level': 'INFORMATIONAL',  # 'ACTION_REQUIRED', 'WAITING', 'COMPLETED', 'INFORMATIONAL'
        'headline': '',
        'tasks': [],
        'improvement_tip': '',
        'legal_reference': 'القرار الجمهوري رقم (210) لسنة 2009 ولائحته التنفيذية',
        'primary_btn': None,  # {'url': '...', 'label': '...', 'icon': '...', 'class': '...'}
    }

    # Map stage number
    stage_map = {
        StageChoices.STAGE_1: 1,
        StageChoices.STAGE_2: 2,
        StageChoices.STAGE_3: 3,
        StageChoices.STAGE_4: 4,
        StageChoices.STAGE_5: 5,
        StageChoices.STAGE_6: 6,
        StageChoices.STAGE_7: 7,
    }
    guidance['stage_number'] = stage_map.get(stage, 1)

    # -------------------------------------------------------------------------
    # STAGE 1: الاستلام والقيد المبدئي (Application Intake & Initial Filing)
    # -------------------------------------------------------------------------
    if stage == StageChoices.STAGE_1:
        if role in [User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب إجراء فوري: فحص الأهلية المبدئية والتراخيص وتحديد التكلفة الرسمية'
            guidance['tasks'] = [
                {'text': 'التحقق من سريان قرار إنشاء الجامعة وترخيص البرنامج الأكاديمي الصادر عن وزارة التعليم العالي.', 'done': bool(application.establishment_decree_number)},
                {'text': 'مطابقة الشروط الشكلية والمستندات التأسيسية المرفقة بطلب الاعتماد.', 'done': False},
                {'text': 'اعتماد قبول الطلب رسمياً وتحديد تكلفة ومصروفات الاعتماد لإصدار أمر السداد للجامعة.', 'done': status != ApplicationStatus.PENDING_REVIEW},
            ]
            guidance['improvement_tip'] = 'يساهم الفحص المكتبي المبدئي الدقيق في حماية معايير الجودة ومنع إهدار موارد الجامعات في برامج غير مرخصة قانوناً.'
            guidance['primary_btn'] = {
                'url': f"/accreditation/board-review/{application.pk}/",
                'label': 'فحص واعتماد الطلب وتحديد التكلفة',
                'icon': 'fa-solid fa-clipboard-check',
                'class': 'btn-primary'
            }
        elif role == User.Roles.INSTITUTION_OFFICER:
            if status == ApplicationStatus.DRAFT:
                guidance['is_my_turn'] = True
                guidance['urgency_level'] = 'ACTION_REQUIRED'
                guidance['headline'] = 'مطلوب منك: استكمال بيانات المسودة وإرسال الطلب رسمياً للمجلس'
                guidance['tasks'] = [
                    {'text': 'التأكد من صحة بيانات الكلية والبرنامج والسنوات الأكاديمية.', 'done': True},
                    {'text': 'إرفاق قرار إنشاء المؤسسة والترخيص الوزاري المعتمد.', 'done': bool(application.establishment_decree_number)},
                    {'text': 'الضغط على زر تقديم الطلب رسمياً لإحالته للأمانة العامة لمجلس الاعتماد.', 'done': False},
                ]
                guidance['primary_btn'] = {
                    'url': f"#draftSubmit",
                    'label': 'إرسال الطلب رسمياً للمجلس',
                    'icon': 'fa-solid fa-paper-plane',
                    'class': 'btn-success'
                }
            else:
                guidance['is_my_turn'] = False
                guidance['urgency_level'] = 'WAITING'
                guidance['headline'] = 'طلبك قيد الفحص لدى الإدارة العامة للاعتماد والتراخيص'
                guidance['tasks'] = [
                    {'text': 'تم تقديم الطلب بنجاح وهو الآن قيد التدقيق لدى أمانة المجلس.', 'done': True},
                    {'text': 'بانتظار إشعار اعتماد الأهلية وتحديد التكلفة المالية للبدء في إعداد التقييم الذاتي.', 'done': False},
                ]
                guidance['improvement_tip'] = 'ابدأ مبكراً بتشكيل فرق العمل الداخلية بالجامعة وتجهيز وثائق ومصفوفات خطة التحسين وضمان الجودة.'

    # -------------------------------------------------------------------------
    # STAGE 2: إعداد وتقديم التقييم الذاتي والشواهد (Self-Study Report & Evidences)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_2:
        if role == User.Roles.INSTITUTION_OFFICER:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب منك: تعبئة دراسة التقييم الذاتي (SSR) ورفع وثائق الشواهد والأدلة'
            guidance['tasks'] = [
                {'text': 'تعبئة استجابة الجامعة لكافة المعايير الوطنية والمؤشرات التفصيلية المعتمدة.', 'done': False},
                {'text': 'رفع وثائق الأدلة والشواهد الثبوتية لكل مؤشر (ملفات PDF واللوائح المعتمدة).', 'done': application.evidences.exists()},
                {'text': 'صياغة التقرير التنفيذي للدراسة الذاتية وخطة التحسين الداخلي وإرساله رسمياً للمجلس.', 'done': False},
            ]
            guidance['improvement_tip'] = 'الدراسة الذاتية ليست مجرد تقرير، بل أداة تطوير مؤسسي مستمر لتحديد نقاط القوة ومجالات التحسين (SWOT Analysis).'
            guidance['primary_btn'] = {
                'url': f"/accreditation/{application.pk}/self-study/indicators/",
                'label': 'تعبئة مؤشرات التقييم الذاتي ورفع الشواهد',
                'icon': 'fa-solid fa-list-check',
                'class': 'btn-success'
            }
        elif role in [User.Roles.DG_QUALITY, User.Roles.COUNCIL_SECRETARY_GENERAL]:
            guidance['is_my_turn'] = False
            guidance['urgency_level'] = 'INFORMATIONAL'
            guidance['headline'] = 'متابعة الدعم الفني: الجامعة تُعد دراسة التقييم الذاتي'
            guidance['tasks'] = [
                {'text': 'تقديم الأدلة الإرشادية لمركز الجودة بالجامعة للالتزام بنماذج التقييم الوطني.', 'done': True},
                {'text': 'متابعة التزام الجامعة بالجدول الزمني المحدد لرفع ملف التقييم الذاتي.', 'done': False},
            ]
            guidance['improvement_tip'] = 'التأكد من مطابقة مؤشرات الجامعة لدليل المعايير الأكاديمية الوطنية NARS.'
        else:
            guidance['is_my_turn'] = False
            guidance['urgency_level'] = 'WAITING'
            guidance['headline'] = 'الملف في عهدة المؤسسة التعليمية لاستكمال الدراسة الذاتية'
            guidance['tasks'] = [
                {'text': 'حظر تدخل لجان التحكيم أو مجلس الإدارة في رصد الدرجات أو التعديل (مبدأ النزاهة وحياد الحوكمة).', 'done': True},
                {'text': 'بانتظار تسليم الجامعة لملف الشواهد كاملاً للانتقال لمرحلة الفحص المكتبي.', 'done': False},
            ]

    # -------------------------------------------------------------------------
    # STAGE 3: الفحص والتدقيق المكتبي (Desk Review & Evidentiary Audit)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_3:
        if role in [User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب إجراء فوري: تدقيق الشواهد وإصدار نتيجة الفحص المكتبي'
            guidance['tasks'] = [
                {'text': 'فحص كفاية وموثوقية الأدلة المرفوعة من المؤسسة لكل معيار ومؤشر.', 'done': False},
                {'text': 'تحديد النواقص والملاحظات الواجب استيفاؤها من الجامعة (إن وجدت).', 'done': False},
                {'text': 'إصدار قرار الفحص المكتبي: (مستوفٍ ومقبول / يتطلب استيفاء نواقص / مرفوض).', 'done': False},
            ]
            guidance['improvement_tip'] = 'الفحص المكتبي يضمن جاهزية البرنامج للزيارة الميدانية وتوفير نفقات التقييم غير المجدي.'
            guidance['primary_btn'] = {
                'url': f"/accreditation/{application.pk}/desk-review/",
                'label': 'إجراء واعتماد الفحص المكتبي',
                'icon': 'fa-solid fa-file-circle-check',
                'class': 'btn-primary'
            }
        elif role == User.Roles.DG_FINANCE_ADMIN:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'متابعة سداد الرسوم المالية وتكاليف الزيارة الميدانية'
            guidance['tasks'] = [
                {'text': 'إصدار فاتورة رسوم الفحص والدراسة وتكاليف لجنة الخبراء الميدانية.', 'done': False},
                {'text': 'التحقق من إيداع المبالغ في الحساب البنكي الرسمي للمجلس وإصدار إفادة السداد.', 'done': False},
            ]
            guidance['primary_btn'] = {
                'url': "/operations/invoices/",
                'label': 'إدارة الفواتير والتحصيل المالي',
                'icon': 'fa-solid fa-file-invoice-dollar',
                'class': 'btn-success'
            }
        elif role == User.Roles.INSTITUTION_OFFICER:
            if status == ApplicationStatus.DESK_DEFICIENCY:
                guidance['is_my_turn'] = True
                guidance['urgency_level'] = 'ACTION_REQUIRED'
                guidance['headline'] = 'تنبيه عاجل: يتطلب الطلب استيفاء نواقص في الشواهد والأدلة'
                guidance['tasks'] = [
                    {'text': 'الاطلاع على قائمة الملاحظات والنواقص الصادرة عن الفاحص المكتبي.', 'done': True},
                    {'text': 'رفع الوثائق والشواهد التكميلية المطلوبة لإعادة فحصها.', 'done': False},
                ]
                guidance['primary_btn'] = {
                    'url': f"/accreditation/{application.pk}/self-study/indicators/",
                    'label': 'استيفاء ورفع الشواهد التكميلية',
                    'icon': 'fa-solid fa-cloud-arrow-up',
                    'class': 'btn-warning'
                }
            else:
                guidance['is_my_turn'] = False
                guidance['urgency_level'] = 'WAITING'
                guidance['headline'] = 'الملف قيد الفحص والتدقيق المكتبي لدى الإدارة المختصة'
                guidance['tasks'] = [
                    {'text': 'يقوم الفاحص المكتبي بمطابقة شواهد التقييم الذاتي مع متطلبات المعايير الوطنية.', 'done': True},
                    {'text': 'ستتلقى إشعاراً فورياً بنتيجة الفحص أو بأي وثائق تكميلية مطلوبة.', 'done': False},
                ]

    # -------------------------------------------------------------------------
    # STAGE 4: التقييم والمراجعة الميدانية الخارجية (External Review & Site Visit)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_4:
        if role in [User.Roles.DG_EVALUATION, User.Roles.COUNCIL_SECRETARY_GENERAL]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب إجراء فوري: تشكيل لجنة الخبراء وجدولة الزيارة الميدانية'
            guidance['tasks'] = [
                {'text': 'اختيار رئيس وأعضاء فريق المراجعة الخارجية من السجل الوطني للمحكمين المعتمدين.', 'done': hasattr(application, 'review_team') and application.review_team is not None},
                {'text': 'التأكد من عدم وجود أي تعارض مصالح للمحكمين مع المؤسسة التعليمية.', 'done': False},
                {'text': 'إقرار خطة وجدول الزيارة الميدانية وإشعار الجامعة وفريق التحكيم.', 'done': False},
            ]
            guidance['primary_btn'] = {
                'url': f"/accreditation/{application.pk}/assign-team/",
                'label': 'تشكيل وتكليف لجنة التقييم الخارجي',
                'icon': 'fa-solid fa-user-plus',
                'class': 'btn-primary'
            }
        elif role == User.Roles.EXTERNAL_REVIEWER:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            coi_signed = hasattr(application, 'conflict_declarations') and application.conflict_declarations.filter(reviewer=user).exists()
            if not coi_signed:
                guidance['headline'] = 'مطلوب إجراء فوري: توقيع إقرار النزاهة وعدم تعارض المصالح (COI)'
                guidance['tasks'] = [
                    {'text': 'قراءة نصوص وضوابط النزاهة وحيادية التقييم الأكاديمي المعتمدة.', 'done': False},
                    {'text': 'توقيع إقرار عدم تعارض المصالح إلكترونياً لفتح صلاحية استعراض الشواهد.', 'done': False},
                ]
                guidance['primary_btn'] = {
                    'url': f"/accreditation/{application.pk}/coi-declare/",
                    'label': 'توقيع إقرار النزاهة وعدم تعارض المصالح',
                    'icon': 'fa-solid fa-signature',
                    'class': 'btn-warning'
                }
            else:
                guidance['headline'] = 'مطلوب منك: رصد درجات التقييم المستقل وإعداد تقرير المراجعة الخارجية'
                guidance['tasks'] = [
                    {'text': 'فحص الأدلة والشواهد الميدانية ومقابلة القيادات والطلبة وهيئة التدريس.', 'done': False},
                    {'text': 'رصد درجات الروباركس لكل مؤشر بدقة واستقلالية تامة.', 'done': False},
                    {'text': 'صياغة التقرير الخارجي النهائي وتحديد التوصيات وفرص التحسين.', 'done': False},
                ]
                guidance['primary_btn'] = {
                    'url': f"/accreditation/{application.pk}/evaluation/rubric/",
                    'label': 'رصد درجات التحكيم الميداني المستقل',
                    'icon': 'fa-solid fa-star-half-stroke',
                    'class': 'btn-success'
                }
        elif role == User.Roles.INSTITUTION_OFFICER:
            guidance['is_my_turn'] = False
            guidance['urgency_level'] = 'INFORMATIONAL'
            guidance['headline'] = 'البرنامج في مرحلة المراجعة الخارجية والتقييم الميداني'
            guidance['tasks'] = [
                {'text': 'تسهيل مهام لجنة الخبراء والمحكمين الميدانيين وتوفير القاعات والمعامل.', 'done': True},
                {'text': 'تجهيز مسؤولي المعايير للمقابلات الفنية وإتاحة الاطلاع على الوثائق الأصلية.', 'done': False},
                {'text': 'استلام مسودة تقرير المراجعة الخارجية لإبداء أي توضيحات جوهرية.', 'done': False},
            ]
            guidance['improvement_tip'] = 'التعامل مع ملاحظات المراجعين الخارجيين كفرص حقيقية لتطوير جودة البرامج وبناء خطة تحسين فاعلة.'

    # -------------------------------------------------------------------------
    # STAGE 5: التقرير المقارن وإعداد جدول أعمال المجلس (Assessment Comparison)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_5:
        if role in [User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب إجراء فوري: إعداد التقرير المقارن وإحالته لمجلس الإدارة'
            guidance['tasks'] = [
                {'text': 'استعراض لوحة التحليل البياني والفجوات بين التقييم الذاتي والتقييم الخارجي.', 'done': False},
                {'text': 'كتابة الملخص التحليلي للأمانة الفنية وتوصيات استيفاء المعايير الوطنية.', 'done': False},
                {'text': 'حفظ وتوثيق التقرير المقارن وإدراجه في جدول أعمال جلسة المجلس القادمة.', 'done': False},
            ]
            guidance['primary_btn'] = {
                'url': f"/accreditation/{application.pk}/comparison-dashboard/",
                'label': 'إعداد واعتماد التقرير المقارن التحليلي',
                'icon': 'fa-solid fa-code-compare',
                'class': 'btn-info'
            }
        elif role in [User.Roles.BOARD_MEMBER, User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_VICE_CHAIRMAN]:
            guidance['is_my_turn'] = False
            guidance['urgency_level'] = 'INFORMATIONAL'
            guidance['headline'] = 'دراسة التقرير المقارن قبل انعقاد جلسة المجلس'
            guidance['tasks'] = [
                {'text': 'الاطلاع على تقرير الفجوات التحليلي وتوصيات المراجعين الخارجيين المستقلين.', 'done': False},
                {'text': 'التحضير لجلسة المداولة والتصويت الرسمي على قرار الاعتماد.', 'done': False},
            ]
            guidance['primary_btn'] = {
                'url': f"/accreditation/{application.pk}/comparison-dashboard/",
                'label': 'استعراض لوحة التقرير المقارن',
                'icon': 'fa-solid fa-chart-line',
                'class': 'btn-outline-primary'
            }
        elif role == User.Roles.LEGAL_DIRECTOR:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'المراجعة القانونية لملف الاعتماد ومسودة القرار'
            guidance['tasks'] = [
                {'text': 'التأكد من سلامة واستيفاء الإجراءات القانونية والمواعيد المنصوص عليها باللائحة.', 'done': False},
                {'text': 'صياغة الملاحظات والتحفظات القانونية إن وجدت لرفعها لمجلس الإدارة.', 'done': False},
            ]

    # -------------------------------------------------------------------------
    # STAGE 6: المداولة وإصدار قرار الاعتماد والشهادة (Council Deliberation & Decrees)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_6:
        if role in [User.Roles.BOARD_MEMBER, User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_VICE_CHAIRMAN, User.Roles.ADMIN]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مطلوب إجراء فوري: مداولة المجلس والتصويت وإصدار قرار الاعتماد'
            guidance['tasks'] = [
                {'text': 'عقد الجلسة الرسمية لمجلس الإدارة ومداولة نتائج التقييم بالأغلبية القانونية.', 'done': False},
                {'text': 'التصويت الفردي السري أو العلني على منح الاعتماد (كامل / مشروط / رفض).', 'done': False},
                {'text': 'إصدار القرار الرسمي، ورقم القيد الوطني، وتوليد وثيقة شهادة الاعتماد (QR).', 'done': hasattr(application, 'council_decision')},
            ]
            guidance['primary_btn'] = {
                'url': f"/decisions/issue-decision/{application.pk}/",
                'label': 'جلسة التصويت وإصدار قرار الاعتماد والشهادة',
                'icon': 'fa-solid fa-stamp',
                'class': 'btn-danger'
            }
        elif role == User.Roles.INSTITUTION_OFFICER:
            if status in [ApplicationStatus.FULL_ACCREDITATION, ApplicationStatus.CONDITIONAL_ACCREDITATION]:
                guidance['is_my_turn'] = False
                guidance['urgency_level'] = 'COMPLETED'
                guidance['headline'] = 'تهانينا! صدر قرار مجلس الاعتماد الأكاديمي رسمياً'
                guidance['tasks'] = [
                    {'text': 'تم منح الاعتماد الأكاديمي بموجب قرار مجلس الإدارة الرسمي.', 'done': True},
                    {'text': 'يمكنك استلام وطباعة وثيقة الشهادة الرسمية وتحميلها برمز التحقق (QR).', 'done': False},
                    {'text': 'البدء في إعداد ومواءمة خطة التحسين المستمر وفق توصيات المجلس.', 'done': False},
                ]
                if hasattr(application, 'council_decision') and hasattr(application.council_decision, 'certificate'):
                    guidance['primary_btn'] = {
                        'url': f"/decisions/certificate/{application.council_decision.certificate.pk}/",
                        'label': 'استعراض وتحميل شهادة الاعتماد الرسمية',
                        'icon': 'fa-solid fa-award',
                        'class': 'btn-warning'
                    }
            elif status == ApplicationStatus.DENIED:
                guidance['is_my_turn'] = True
                guidance['urgency_level'] = 'ACTION_REQUIRED'
                guidance['headline'] = 'صدر قرار المجلس برفض/تأجيل الاعتماد - متاح قيد تظلم قانوني'
                guidance['tasks'] = [
                    {'text': 'الاطلاع على الحيثيات والأسباب القانونية والفنية لقرار المجلس.', 'done': True},
                    {'text': 'يحق للجامعة قيد تظلم رسمي إلى لجنة التظلمات المستقلة خلال 30 يوماً.', 'done': False},
                ]
                guidance['primary_btn'] = {
                    'url': f"/accreditation/{application.pk}/grievance/new/",
                    'label': 'قيد تظلم وطعن رسمي في قرار المجلس',
                    'icon': 'fa-solid fa-scale-unbalanced-flip',
                    'class': 'btn-danger'
                }

    # -------------------------------------------------------------------------
    # STAGE 7: المتابعة الدورية وخطة التحسين والتطوير المستمر (Continuous Improvement)
    # -------------------------------------------------------------------------
    elif stage == StageChoices.STAGE_7:
        if role == User.Roles.INSTITUTION_OFFICER:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'مرحلة استدامة الجودة: تنفيذ خطة التحسين ورفع تقارير المتابعة السنوية'
            guidance['tasks'] = [
                {'text': 'إعداد مصفوفة خطة التحسين لمعالجة التوصيات والاشتراطات الصادرة مع قرار الاعتماد.', 'done': False},
                {'text': 'تنفيذ الإجراءات التصحيحية ورصد مؤشرات الأداء السنوية بالجامعة.', 'done': False},
                {'text': 'رفع تقرير المتابعة الدورية السنوي عبر البوابة لضمان استمرار سريان الشهادة.', 'done': False},
            ]
            guidance['improvement_tip'] = 'الاعتماد الأكاديمي ليس نهاية المطاف، بل انطلاقة لثقافة التحسين المستمر وضمان عدم تراجع جودة المخرجات.'
            guidance['primary_btn'] = {
                'url': f"/surveillance/",
                'label': 'متابعة خطة التحسين والرقابة الدورية',
                'icon': 'fa-solid fa-clock-rotate-left',
                'class': 'btn-success'
            }
        elif role in [User.Roles.DG_QUALITY, User.Roles.COUNCIL_SECRETARY_GENERAL]:
            guidance['is_my_turn'] = True
            guidance['urgency_level'] = 'ACTION_REQUIRED'
            guidance['headline'] = 'الإشراف على الرقابة الدورية وتقارير التحسين السنوية للمؤسسة'
            guidance['tasks'] = [
                {'text': 'جدولة مواعيد استحقاق تقارير الرقابة والمتابعة السنوية للبرنامج.', 'done': True},
                {'text': 'تقييم مدى التزام الجامعة بخطة التحسين ومعالجة التوصيات التصحيحية.', 'done': False},
            ]
            guidance['primary_btn'] = {
                'url': "/surveillance/",
                'label': 'لوحة الرقابة والمتابعة الدورية',
                'icon': 'fa-solid fa-sliders',
                'class': 'btn-primary'
            }
        else:
            guidance['is_my_turn'] = False
            guidance['urgency_level'] = 'COMPLETED'
            guidance['headline'] = 'الملف في مرحلة المتابعة الدورية والتحسين المستمر بعد نيل الاعتماد'
            guidance['tasks'] = [
                {'text': 'الشهادة مسجلة في السجل الوطني العام وسارية المفعول وفق المدة المحددة بالقرار.', 'done': True},
                {'text': 'المتابعة السنوية خاضعة لإدارة ضمان الجودة والأمانة العامة.', 'done': True},
            ]

    return guidance
