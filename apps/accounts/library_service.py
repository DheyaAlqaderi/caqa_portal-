from django.db.models import Q
from .models import User

def get_authorized_recipients(sender):
    """
    Sovereign Recipient Filter for Document Sharing (قسم مكتبتي).
    Strictly enforces separation of powers and legal governance lines:
    Prevents unauthorized lateral or cross-hierarchical communications (e.g. University influencing Reviewers).
    """
    if not sender or not sender.is_authenticated:
        return User.objects.none()

    base_qs = User.objects.filter(is_active=True, approval_status=User.ApprovalStatus.APPROVED).exclude(pk=sender.pk)

    # 1. Superuser, Council Chairman, Vice Chairman, Secretary General, Admin: Full Governance Reach
    if sender.is_superuser or sender.role in [
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN,
        User.Roles.COUNCIL_SECRETARY_GENERAL,
        User.Roles.ADMIN,
    ]:
        return base_qs.order_by('role', 'first_name')

    # 2. Board Member: Can communicate with Chairman, Vice Chairman, Secretary General, Legal Director, other Board Members
    if sender.role == User.Roles.BOARD_MEMBER:
        return base_qs.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.LEGAL_DIRECTOR,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.ADMIN,
            ]
        ).order_by('role', 'first_name')

    # 3. Minister of Higher Education: Can communicate with Chairman, Secretary General, and Council leadership
    if sender.role == User.Roles.MINISTER:
        return base_qs.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.ADMIN,
            ]
        ).order_by('role', 'first_name')

    # 4. University Representative (INSTITUTION_OFFICER / UNIVERSITY_PRESIDENT):
    # CAN communicate with: Officers & President of their own university, DG Accreditation, DG Evaluation, Secretary General, Secretariat.
    # CANNOT communicate with: External Reviewers (anti-influence gate), Board Members.
    if sender.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]:
        return base_qs.filter(
            Q(institution_id=sender.institution_id, role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]) |
            Q(role__in=[
                User.Roles.DG_ACCREDITATION,
                User.Roles.DG_EVALUATION,
                User.Roles.DG_FINANCE_ADMIN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.ADMIN,
            ])
        ).order_by('role', 'first_name')

    # 5. External Reviewer (EXTERNAL_REVIEWER):
    # CAN communicate with: DG Evaluation, Secretary General, Secretariat, and peer reviewers.
    # CANNOT communicate with: Institution Officers, Board Members.
    if sender.role == User.Roles.EXTERNAL_REVIEWER:
        return base_qs.filter(
            role__in=[
                User.Roles.DG_EVALUATION,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.EXTERNAL_REVIEWER,
                User.Roles.ADMIN,
            ]
        ).order_by('role', 'first_name')

    # 6. Legal Director (LEGAL_DIRECTOR):
    # Communicates with: Chairman, Secretary General, Board Members, DGs.
    if sender.role == User.Roles.LEGAL_DIRECTOR:
        return base_qs.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.DG_ACCREDITATION,
                User.Roles.ADMIN,
            ]
        ).order_by('role', 'first_name')

    # 7. Specialized Director Generals (Accreditation, Evaluation, Quality, Finance, IT)
    directorates = [
        User.Roles.DG_ACCREDITATION,
        User.Roles.DG_EVALUATION,
        User.Roles.DG_QUALITY,
        User.Roles.DG_FINANCE_ADMIN,
        User.Roles.IT_DIRECTOR,
    ]
    if sender.role in directorates:
        # Inter-directorate + Leadership
        allowed_roles = list(directorates) + [
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.ADMIN,
        ]
        # Specific external reach per directorate:
        extra_q = Q()
        if sender.role in [User.Roles.DG_ACCREDITATION, User.Roles.DG_FINANCE_ADMIN]:
            extra_q |= Q(role=User.Roles.INSTITUTION_OFFICER)
        if sender.role == User.Roles.DG_EVALUATION:
            extra_q |= Q(role=User.Roles.EXTERNAL_REVIEWER)

        return base_qs.filter(Q(role__in=allowed_roles) | extra_q).order_by('role', 'first_name')

    # Fallback default: Secretariat and Admin
    return base_qs.filter(
        role__in=[User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN]
    ).order_by('role', 'first_name')


def sync_system_assets_to_library(user=None):
    """
    Auto-aggregates and synchronizes official state decisions, certificates,
    Secretariat comparison reports, and uploaded evidences into UserDocument and DocumentShare.
    Guarantees that every target user finds all their past and present institutional assets
    in 'مكتبتي' (My Library) immediately according to role, institution, and separation of powers.
    """
    from apps.accounts.models import UserDocument, DocumentShare
    from apps.decisions.models import AccreditationCertificate, AccreditationDecision
    from apps.accreditation.models import EvidenceDocument, SecretariatAssessmentComparisonReport

    chairman = User.objects.filter(role=User.Roles.COUNCIL_CHAIRMAN, is_active=True).first() or User.objects.filter(is_superuser=True).first()
    sec_gen = User.objects.filter(role=User.Roles.COUNCIL_SECRETARY_GENERAL, is_active=True).first() or chairman
    minister = User.objects.filter(role=User.Roles.MINISTER, is_active=True).first()

    # 1. Sync Official Certificates
    for cert in AccreditationCertificate.objects.select_related('decision__application__institution', 'decision__application__program').all():
        app = cert.decision.application
        inst = app.institution
        prog_str = f" - {app.program.name}" if app.program else " (اعتماد مؤسسي)"
        title = f"شهادة اعتماد أكاديمي رسمية: {inst.name}{prog_str} [{cert.national_registry_code}]"

        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.CERTIFICATE,
            title=title,
            defaults={
                'owner': chairman or sec_gen,
                'description': f"شهادة اعتماد صادرة بموجب {cert.decision.decree_number} سارية من {cert.decision.start_date} حتى {cert.decision.expiry_date}",
                'system_source_url': f"/decisions/certificate/{cert.pk}/",
                'file': cert.qr_code_image if cert.qr_code_image else None,
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = f"/decisions/certificate/{cert.pk}/"
            doc.save(update_fields=['system_source_url'])

        # Auto-share to university officers of this institution
        officers = User.objects.filter(institution=inst, role=User.Roles.INSTITUTION_OFFICER, is_active=True)
        for off in officers:
            DocumentShare.objects.get_or_create(
                document=doc,
                sender=chairman or sec_gen,
                recipient=off,
                defaults={'notes': f"نسخة رسمية من شهادة الاعتماد الأكاديمي الصادرة لمؤسستكم الموقرة بموجب {cert.decision.decree_number}"}
            )

        # Auto-share to Minister and Secretary General
        if minister and minister != doc.owner:
            DocumentShare.objects.get_or_create(
                document=doc,
                sender=doc.owner,
                recipient=minister,
                defaults={'notes': f"نسخة للعرض والإحاطة لمعالي الوزير - قرار اعتماد {cert.decision.decree_number}"}
            )

    # 2. Sync Official Decisions
    for dec in AccreditationDecision.objects.select_related('application__institution', 'application__program').all():
        app = dec.application
        inst = app.institution
        title = f"{dec.decree_number} - {dec.get_decision_type_display()} ({inst.name})"

        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.DECISION,
            title=title,
            defaults={
                'owner': chairman or sec_gen,
                'description': f"قرار رسمي صادر عن مجلس الإدارة في دورة انعقاده بتاريخ {dec.decision_date}. الحيثيات: {dec.legal_justifications[:150]}",
                'system_source_url': f"/accreditation/{app.pk}/",
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = f"/accreditation/{app.pk}/"
            doc.save(update_fields=['system_source_url'])

        # Share to university officers
        officers = User.objects.filter(institution=inst, role=User.Roles.INSTITUTION_OFFICER, is_active=True)
        for off in officers:
            DocumentShare.objects.get_or_create(
                document=doc,
                sender=chairman or sec_gen,
                recipient=off,
                defaults={'notes': f"القرار الرسمي الصادر عن مجلس الاعتماد الأكاديمي لطلبكم رقم ({app.application_number})"}
            )

    # 3. Sync Secretariat Assessment Comparison Reports
    board_members = User.objects.filter(
        role__in=[
            User.Roles.BOARD_MEMBER,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_EVALUATION,
            User.Roles.DG_ACCREDITATION,
        ],
        is_active=True
    )
    for rep in SecretariatAssessmentComparisonReport.objects.select_related('application__institution', 'generated_by').all():
        app = rep.application
        owner = rep.generated_by or sec_gen
        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.COMPARISON_REPORT,
            title=rep.title,
            defaults={
                'owner': owner,
                'description': f"تقرير تحليلي مقارن أعدته الإدارة العامة للتقييم والمراجعة الخارجية بين التقييم الذاتي والتقييم الخارجي مع الشواهد للطلب ({app.application_number})",
                'system_source_url': f"/accreditation/{app.pk}/comparison-dashboard/",
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = f"/accreditation/{app.pk}/comparison-dashboard/"
            doc.save(update_fields=['system_source_url'])

        # Share with all board members, DG_EVALUATION, DG_ACCREDITATION, and Secretariat
        for bm in board_members:
            if bm != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=bm,
                    defaults={'notes': f"إحالة التقرير المقارن التحليلي (مع الشواهد المرفقة) لمجلس الإدارة للدراسة والبت - {app.institution.name}"}
                )

        # Also sync the Integrated 17-Section Accreditation Dossier (ملف الاعتماد المتكامل - 17 قسماً) from Secretary General to Council Chairman & Board Members
        dossier_owner = sec_gen or owner
        dossier_title = f"ملف الاعتماد المتكامل المعروض على المجلس (17 قسماً) - {app.institution.name} [{app.application_number}]"
        dossier_doc, d_created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.APPLICATION_DOSSIER,
            title=dossier_title,
            defaults={
                'owner': dossier_owner,
                'description': f"ملف الاعتماد الأكاديمي المتكامل (17 قسماً رسمياً) شاملاً التقييم الذاتي والخارجي والشواهد وتقرير المقارنة التحليلي للطلب ({app.application_number})",
                'system_source_url': f"/accreditation/{app.pk}/dossier-17/",
            }
        )
        if not d_created and dossier_doc.system_source_url != f"/accreditation/{app.pk}/dossier-17/":
            dossier_doc.system_source_url = f"/accreditation/{app.pk}/dossier-17/"
            dossier_doc.save(update_fields=['system_source_url'])

        for bm in board_members:
            if bm != dossier_owner:
                DocumentShare.objects.get_or_create(
                    document=dossier_doc,
                    sender=dossier_owner,
                    recipient=bm,
                    defaults={'notes': f"إحالة ملف الاعتماد المتكامل (17 قسماً) مع تقرير المقارنة التحليلي من الأمين العام للمجلس إلى رئيس وأعضاء مجلس الإدارة - {app.application_number}"}
                )

    # 4. Sync Self-Study Reports (SSR - تقارير دراسة التقييم الذاتي: الأصلي والمعدل)
    from apps.accreditation.models import SelfStudyReport
    for ssr in SelfStudyReport.objects.select_related('application__institution', 'application__applicant_user').all():
        app = ssr.application
        inst = app.institution
        owner = app.applicant_user or User.objects.filter(institution=inst, role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT], is_active=True).first() or chairman
        title = f"تقرير دراسة التقييم الذاتي (SSR) - {inst.name} [{app.application_number}]"

        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.SELF_STUDY,
            title=title,
            defaults={
                'owner': owner,
                'description': f"وثيقة تقرير التقييم الذاتي الشامل وفق معايير الجودة الوطنية للطلب ({app.application_number})",
                'system_source_url': f"/accreditation/{app.pk}/self-study/report/",
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = f"/accreditation/{app.pk}/self-study/report/"
            doc.save(update_fields=['system_source_url'])

        # Ensure all SSR documents for this application (both original and modified versions) are shared to stakeholders
        all_ssr_docs = UserDocument.objects.filter(application=app, doc_type=UserDocument.DocumentType.SELF_STUDY)

        # Share to all university officers and university president of same institution
        inst_officers = User.objects.filter(
            institution=inst,
            role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
            is_active=True
        )
        for ssr_doc in all_ssr_docs:
            for off in inst_officers:
                if off != ssr_doc.owner:
                    DocumentShare.objects.get_or_create(
                        document=ssr_doc,
                        sender=ssr_doc.owner,
                        recipient=off,
                        defaults={'notes': f"نسخة مركز الجودة ورئاسة الجامعة لتقرير التقييم الذاتي - {app.application_number}"}
                    )

            # Share to Secretariat leadership (DG_ACCREDITATION, DG_EVALUATION, DG_QUALITY, COUNCIL_SECRETARY_GENERAL)
            sec_leaders = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.DG_EVALUATION,
                    User.Roles.DG_QUALITY,
                ],
                is_active=True
            )
            for sec_u in sec_leaders:
                if sec_u != ssr_doc.owner:
                    DocumentShare.objects.get_or_create(
                        document=ssr_doc,
                        sender=ssr_doc.owner,
                        recipient=sec_u,
                        defaults={'notes': f"نسخة تقرير التقييم الذاتي المسلّم من المؤسسة للطلب ({app.application_number})"}
                    )

            # If review team is assigned, share to external reviewers
            if hasattr(app, 'review_team') and app.review_team:
                for member in app.review_team.members.filter(user__isnull=False):
                    if member.user != ssr_doc.owner:
                        DocumentShare.objects.get_or_create(
                            document=ssr_doc,
                            sender=sec_gen or ssr_doc.owner,
                            recipient=member.user,
                            defaults={'notes': f"إحالة رسمية لدراسة التقييم الذاتي المعتمدة لفريق المراجعة الخارجية - {app.application_number}"}
                        )

    # 5. Sync External Review Reports (تقارير المراجعة والتقييم الميداني الخارجي)
    from apps.accreditation.models import ExternalReviewReport
    for ext_rep in ExternalReviewReport.objects.select_related('application__institution').all():
        app = ext_rep.application
        inst = app.institution
        team_leader = None
        if hasattr(app, 'review_team') and app.review_team:
            leader_member = app.review_team.members.filter(role_in_team__in=['TEAM_LEADER', 'LEAD_REVIEWER', 'CHAIR']).first() or app.review_team.members.first()
            if leader_member:
                team_leader = leader_member.user
        dg_eval = User.objects.filter(role=User.Roles.DG_EVALUATION, is_active=True).first()
        owner = team_leader or dg_eval or sec_gen or chairman
        title = f"تقرير التقييم والمراجعة الميدانية الخارجية - {inst.name} [{app.application_number}]"

        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.EXTERNAL_REPORT,
            title=title,
            defaults={
                'owner': owner,
                'description': f"تقرير المراجعة الخارجية النهائي/المسودة ونتائج المعايير والتوصية الختامية للطلب ({app.application_number})",
                'system_source_url': f"/accreditation/{app.pk}/external-report/",
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = f"/accreditation/{app.pk}/external-report/"
            doc.save(update_fields=['system_source_url'])

        # Share with all review team members
        if hasattr(app, 'review_team') and app.review_team:
            for member in app.review_team.members.filter(user__isnull=False):
                if member.user != owner:
                    DocumentShare.objects.get_or_create(
                        document=doc,
                        sender=owner,
                        recipient=member.user,
                        defaults={'notes': f"نسخة فريق المراجعة الخارجية الميداني - {app.application_number}"}
                    )

        # Share with Secretariat leadership, DG_EVALUATION, and DG_ACCREDITATION
        council_leaders = User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.DG_EVALUATION,
                User.Roles.DG_ACCREDITATION,
                User.Roles.COUNCIL_CHAIRMAN,
            ],
            is_active=True
        )
        for cl in council_leaders:
            if cl != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=cl,
                    defaults={'notes': f"تقرير التقييم الخارجي الميداني المحال لمدير عام التقييم والمراجعة الخارجية والمجلس - {app.application_number}"}
                )

        # If draft sent to institution or final ready, share with university officers and university president
        if ext_rep.draft_sent_to_institution_date or ext_rep.final_submitted_to_council_date:
            inst_officers = User.objects.filter(
                institution=inst,
                role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
                is_active=True
            )
            for off in inst_officers:
                if off != owner:
                    DocumentShare.objects.get_or_create(
                        document=doc,
                        sender=sec_gen or owner,
                        recipient=off,
                        defaults={'notes': f"تقرير وملاحظات المقيم الخارجي للمؤسسة لتعديل التقييم الذاتي وممارسة حق الرد - {app.application_number}"}
                    )

    # 6. Sync Accreditation Application Dossiers (تقارير واستمارات طلبات الاعتماد الرسمية)
    from apps.accreditation.models import AccreditationApplication
    for app in AccreditationApplication.objects.select_related('institution', 'program', 'applicant_user').all():
        inst = app.institution
        owner = app.applicant_user or User.objects.filter(institution=inst, role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT], is_active=True).first() or chairman
        prog_str = f" - {app.program.name}" if app.program else " (اعتماد مؤسسي)"
        title = f"استمارة وملف طلب الاعتماد: {inst.name}{prog_str} [{app.application_number}]"

        doc, created = UserDocument.objects.get_or_create(
            application=app,
            doc_type=UserDocument.DocumentType.APPLICATION_DOSSIER,
            title=title,
            defaults={
                'owner': owner,
                'description': f"تقرير وملف طلب الاعتماد الأكاديمي الرسمي المتضمن البيانات الأساسية وتوقيع رئيس الجامعة وقرار مدير عام الاعتماد ({app.get_current_stage_display()})",
                'system_source_url': f"/accreditation/{app.pk}/report/",
            }
        )
        if not created and doc.system_source_url != f"/accreditation/{app.pk}/report/":
            doc.system_source_url = f"/accreditation/{app.pk}/report/"
            doc.save(update_fields=['system_source_url'])

        # Share to University President and other university officers of the institution
        inst_officers = User.objects.filter(
            institution=inst,
            role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
            is_active=True
        )
        for off in inst_officers:
            if off != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=off,
                    defaults={'notes': f"نسخة رسمية من تقرير طلب الاعتماد الأكاديمي للمؤسسة ({app.application_number})"}
                )

        # Share to DG_ACCREDITATION, DG_FINANCE_ADMIN, and COUNCIL_SECRETARY_GENERAL
        sec_reviewers = User.objects.filter(
            role__in=[User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.DG_ACCREDITATION, User.Roles.DG_FINANCE_ADMIN],
            is_active=True
        )
        for s_user in sec_reviewers:
            if s_user != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=s_user,
                    defaults={'notes': f"نسخة رسمية من تقرير طلب الاعتماد الأكاديمي المرسل من المؤسسة للدراسة والاعتماد - {app.application_number}"}
                )

    # 7. Sync Uploaded Evidence Documents
    for ev in EvidenceDocument.objects.select_related('application__institution', 'application__applicant_user', 'indicator').all():
        app = ev.application
        owner = app.applicant_user or User.objects.filter(institution=app.institution, is_active=True).first() or chairman
        is_img = False
        if ev.document_file:
            ext = ev.document_file.name.split('.')[-1].lower()
            is_img = ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']
        doc_t = UserDocument.DocumentType.IMAGE if is_img else UserDocument.DocumentType.EVIDENCE

        ev_doc, _ = UserDocument.objects.get_or_create(
            application=app,
            title=f"شاهد [{ev.code}]: {ev.title}",
            defaults={
                'owner': owner,
                'doc_type': doc_t,
                'description': ev.description or f"شاهد ثبوتي لمؤشر معيار الجودة ({ev.indicator.code if ev.indicator else ''})",
                'file': ev.document_file,
                'file_size_bytes': ev.file_size_bytes or 0,
            }
        )
        # Share evidence with DG_EVALUATION, DG_ACCREDITATION, and Board when in evaluation or council review
        ev_recipients = User.objects.filter(
            role__in=[
                User.Roles.DG_EVALUATION,
                User.Roles.DG_ACCREDITATION,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
            ],
            is_active=True
        )
        for ev_rec in ev_recipients:
            if ev_rec != owner:
                DocumentShare.objects.get_or_create(
                    document=ev_doc,
                    sender=owner,
                    recipient=ev_rec,
                    defaults={'notes': f"شاهد مرفق لطلب الاعتماد ({app.application_number}) - المؤشر ({ev.indicator.code if ev.indicator else 'عام'})"}
                )

    # 8. Sync Council Policies & General Regulations (اللوائح والسياسات العامة للمجلس)
    from apps.decisions.models import CouncilPolicy, BoardNomination
    for policy in CouncilPolicy.objects.select_related('ratified_by').all():
        owner = chairman or sec_gen
        title = f"لائحة / سياسة عامة: {policy.title} [{policy.get_policy_type_display()}]"
        doc, created = UserDocument.objects.get_or_create(
            title=title,
            doc_type=UserDocument.DocumentType.OFFICIAL_LETTER,
            defaults={
                'owner': owner,
                'description': f"وثيقة ولائحة مجلس الإدارة ({policy.council_session_ref}) - موقف المصادقة: {policy.get_status_display()}",
                'system_source_url': "/decisions/minister/policies/",
                'file': policy.document_file if policy.document_file else None,
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = "/decisions/minister/policies/"
            doc.save(update_fields=['system_source_url'])

        # Share to Minister, Chairman, Board Members, Secretary General
        pol_stakeholders = User.objects.filter(
            role__in=[User.Roles.MINISTER, User.Roles.COUNCIL_CHAIRMAN, User.Roles.BOARD_MEMBER, User.Roles.COUNCIL_SECRETARY_GENERAL],
            is_active=True
        )
        for st in pol_stakeholders:
            if st != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=st,
                    defaults={'notes': f"نسخة للاطلاع والمتابعة للائحة/سياسة المجلس العامة ({policy.title})"}
                )

    # 9. Sync Board Nominations (مذكرات الترشيح لمجلس الوزراء والقرار الجمهوري)
    for nom in BoardNomination.objects.all():
        owner = minister or chairman
        title = f"مذكرة ترشيح: {nom.nominee_name} [{nom.get_proposed_position_display()}]"
        doc, created = UserDocument.objects.get_or_create(
            title=title,
            doc_type=UserDocument.DocumentType.OFFICIAL_LETTER,
            defaults={
                'owner': owner,
                'description': f"مذكرة ترشيح صادرة لدولة رئيس الوزراء لشغل منصب ({nom.get_proposed_position_display()}) - الحالة: {nom.get_status_display()}",
                'system_source_url': "/decisions/minister/nominations/",
            }
        )
        if not created and not doc.system_source_url:
            doc.system_source_url = "/decisions/minister/nominations/"
            doc.save(update_fields=['system_source_url'])

        # Share to Minister and Chairman
        if chairman and chairman != owner:
            DocumentShare.objects.get_or_create(
                document=doc,
                sender=owner,
                recipient=chairman,
                defaults={'notes': f"مذكرة ترشيح لقيادة/عضوية المجلس ({nom.nominee_name})"}
            )

    # 10. Sync Grievances & Appeals (عرائض الطعون والتظلمات الرسمية)
    from apps.accreditation.models import GrievanceAppeal, DeskReviewEvaluation
    legal_dir = User.objects.filter(role=User.Roles.LEGAL_DIRECTOR, is_active=True).first()
    for grv in GrievanceAppeal.objects.select_related('application__institution', 'appellant_user').all():
        app = grv.application
        owner = grv.appellant_user or User.objects.filter(institution=app.institution, is_active=True).first() or chairman
        title = f"عريضة تظلم وطعن رسمي: {app.institution.name} [{app.application_number}]"
        doc, created = UserDocument.objects.get_or_create(
            application=app,
            title=title,
            doc_type=UserDocument.DocumentType.OFFICIAL_LETTER,
            defaults={
                'owner': owner,
                'description': f"عريضة تظلم رسمية رقم ({grv.appeal_number}) - الحالة: {grv.get_status_display()}",
                'system_source_url': f"/accreditation/grievances/{grv.pk}/review/",
                'file': grv.supporting_document if grv.supporting_document else None,
            }
        )
        if not created and doc.system_source_url != f"/accreditation/grievances/{grv.pk}/review/":
            doc.system_source_url = f"/accreditation/grievances/{grv.pk}/review/"
            doc.save(update_fields=['system_source_url'])

        # Share with Legal Director, Grievance Committee, Chairman, Board Members, and Secretary General
        grievance_recipients = list(User.objects.filter(
            role__in=[
                User.Roles.LEGAL_DIRECTOR,
                User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
            ],
            is_active=True
        ))
        for gr_u in grievance_recipients:
            if gr_u and gr_u != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=gr_u,
                    defaults={'notes': f"إحالة عريضة تظلم رسمية من مؤسسة ({app.institution.name}) للدراسة والبت القانوني"}
                )

    # 11. Sync Surveillance & Continuous Improvement Plans & Reports (خطط التحسين وتقارير الرقابة)
    from apps.surveillance.models import ContinuousImprovementPlan, AnnualMonitoringReport, SurveillanceVisit
    dg_quality = User.objects.filter(role=User.Roles.DG_QUALITY, is_active=True).first()

    for plan in ContinuousImprovementPlan.objects.select_related('decision__application__institution', 'submitted_by').all():
        inst = plan.decision.application.institution
        owner = plan.submitted_by or User.objects.filter(institution=inst, is_active=True).first() or chairman
        title = f"خطة التحسين المستمر: {inst.name} [{plan.plan_title[:40]}]"
        doc, created = UserDocument.objects.get_or_create(
            application=plan.decision.application,
            title=title,
            doc_type=UserDocument.DocumentType.REPORT,
            defaults={
                'owner': owner,
                'description': f"خطة التطوير والتحسين المستمر المؤسسية - الحالة: {plan.get_status_display()}",
                'system_source_url': f"/surveillance/manage/{plan.decision_id}/",
            }
        )
        if not created and doc.system_source_url != f"/surveillance/manage/{plan.decision_id}/":
            doc.system_source_url = f"/surveillance/manage/{plan.decision_id}/"
            doc.save(update_fields=['system_source_url'])

        # Share to DG Quality, Secretary General, Council Secretary, and Board
        for qu in [dg_quality, sec_gen, chairman]:
            if qu and qu != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=qu,
                    defaults={'notes': f"متابعة خطة التحسين المستمر المرفوعة من ({inst.name})"}
                )

    for rep in AnnualMonitoringReport.objects.select_related('decision__application__institution', 'submitted_by').all():
        inst = rep.decision.application.institution
        owner = rep.submitted_by or User.objects.filter(institution=inst, is_active=True).first() or chairman
        title = f"التقرير الرقابي السنوي: {inst.name} [{rep.reporting_period}]"
        doc, created = UserDocument.objects.get_or_create(
            application=rep.decision.application,
            title=title,
            doc_type=UserDocument.DocumentType.REPORT,
            defaults={
                'owner': owner,
                'description': f"تقرير المتابعة والرقابة الدورية السنوية لفترة ({rep.reporting_period}) - موقف المراجعة: {rep.get_review_status_display()}",
                'system_source_url': f"/surveillance/manage/{rep.decision_id}/",
                'file': rep.report_file if rep.report_file else None,
            }
        )
        if not created and doc.system_source_url != f"/surveillance/manage/{rep.decision_id}/":
            doc.system_source_url = f"/surveillance/manage/{rep.decision_id}/"
            doc.save(update_fields=['system_source_url'])

        for qu in [dg_quality, sec_gen, chairman]:
            if qu and qu != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=qu,
                    defaults={'notes': f"التقرير السنوي لمتابعة الجودة والامتثال - {inst.name}"}
                )

    for visit in SurveillanceVisit.objects.select_related('decision__application__institution').all():
        inst = visit.decision.application.institution
        owner = dg_quality or sec_gen or chairman
        title = f"تقرير زيارة الرقابة الميدانية: {inst.name} [{visit.get_visit_type_display()}]"
        doc, created = UserDocument.objects.get_or_create(
            application=visit.decision.application,
            title=title,
            doc_type=UserDocument.DocumentType.REPORT,
            defaults={
                'owner': owner,
                'description': f"تقرير لجنة النزول والزيارة الميدانية الرقابية - الحالة: {visit.get_status_display()}",
                'system_source_url': f"/surveillance/manage/{visit.decision_id}/",
            }
        )
        if not created and doc.system_source_url != f"/surveillance/manage/{visit.decision_id}/":
            doc.system_source_url = f"/surveillance/manage/{visit.decision_id}/"
            doc.save(update_fields=['system_source_url'])

        # Share to university officers & president
        inst_officers = User.objects.filter(
            institution=inst,
            role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT],
            is_active=True
        )
        for off in inst_officers:
            if off != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=off,
                    defaults={'notes': f"إشعار وتقرير لجنة الزيارة الميدانية الرقابية والتفتيشية لجامعتكم"}
                )

    # 12. Sync Desk Review Evaluations (تقارير الفحص المكتبي الشكلي والموضوعي - DeskReviewEvaluation)
    for dr in DeskReviewEvaluation.objects.filter(is_completed=True).select_related('application__institution', 'reviewer'):
        app = dr.application
        inst = app.institution
        owner = dr.reviewer or sec_gen or chairman
        title = f"تقرير الفحص المكتبي الشكلي والموضوعي: {inst.name} [{app.application_number}]"
        doc, created = UserDocument.objects.get_or_create(
            application=app,
            title=title,
            doc_type=UserDocument.DocumentType.REPORT,
            defaults={
                'owner': owner,
                'description': f"نتيجة الفحص المكتبي الشكلي والموضوعي ({dr.get_decision_display()}) بنسبة استيفاء ({dr.completeness_percentage}%) - ملاحظات: {(dr.technical_remarks or '')[:150]}",
                'system_source_url': f"/accreditation/{app.pk}/desk-review/",
            }
        )
        if not created and doc.system_source_url != f"/accreditation/{app.pk}/desk-review/":
            doc.system_source_url = f"/accreditation/{app.pk}/desk-review/"
            doc.save(update_fields=['system_source_url'])

        dr_recipients = list(User.objects.filter(
            Q(institution=inst, role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]) |
            Q(role__in=[
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.DG_ACCREDITATION,
                User.Roles.DG_EVALUATION,
                User.Roles.DG_FINANCE_ADMIN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
            ]),
            is_active=True
        ))
        for rec in dr_recipients:
            if rec != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=rec,
                    defaults={'notes': f"نسخة من تقرير الفحص المكتبي الشكلي والموضوعي للطلب ({app.application_number})"}
                )

    # 13. Sync Financial Invoices & Clearance Certificates (المطالبات المالية وسندات المخالصة المالية)
    from apps.operations.models import Invoice
    dg_fin = User.objects.filter(role=User.Roles.DG_FINANCE_ADMIN, is_active=True).first()
    for inv in Invoice.objects.select_related('application__institution').all():
        app = inv.application
        if not app:
            continue
        inst = app.institution
        owner = dg_fin or sec_gen or chairman
        status_label = "مسددة ومعتمدة مالياً (FINANCIAL_CLEARED)" if inv.status == Invoice.PaymentStatus.PAID else inv.get_status_display()
        title = f"المطالبة المالية وسند السداد [{inv.invoice_number}] - {inst.name}"
        doc, created = UserDocument.objects.get_or_create(
            application=app,
            title=title,
            doc_type=UserDocument.DocumentType.OFFICIAL_LETTER,
            defaults={
                'owner': owner,
                'description': f"المطالبة المالية رقم ({inv.invoice_number}) بمبلغ ({inv.total_amount} ريال) - الحالة: {status_label}",
                'system_source_url': f"/operations/invoices/{inv.pk}/",
                'file': inv.proof_of_payment if inv.proof_of_payment else None,
            }
        )
        if not created:
            updated_fields = []
            if doc.system_source_url != f"/operations/invoices/{inv.pk}/":
                doc.system_source_url = f"/operations/invoices/{inv.pk}/"
                updated_fields.append('system_source_url')
            new_desc = f"المطالبة المالية رقم ({inv.invoice_number}) بمبلغ ({inv.total_amount} ريال) - الحالة: {status_label}"
            if doc.description != new_desc:
                doc.description = new_desc
                updated_fields.append('description')
            if updated_fields:
                doc.save(update_fields=updated_fields)

        fin_recipients = list(User.objects.filter(
            Q(institution=inst, role__in=[User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]) |
            Q(role__in=[
                User.Roles.DG_FINANCE_ADMIN,
                User.Roles.DG_ACCREDITATION,
                User.Roles.DG_EVALUATION,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
            ]),
            is_active=True
        ))
        for rec in fin_recipients:
            if rec != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=rec,
                    defaults={'notes': f"نسخة المطالبة المالية وسند المخالصة للطلب ({app.application_number}) - ({status_label})"}
                )

    # 14. Sync Council Meeting Minutes (محاضر جلسات مجلس الإدارة - CouncilMeetingMinutes)
    from apps.decisions.models import CouncilMeetingMinutes
    for mins in CouncilMeetingMinutes.objects.select_related('meeting', 'prepared_by', 'approved_by').all():
        owner = mins.prepared_by or mins.approved_by or sec_gen or chairman
        title = f"محضر جلسة مجلس الإدارة [{mins.minutes_number}] - {mins.meeting.meeting_number}"
        doc, created = UserDocument.objects.get_or_create(
            title=title,
            doc_type=UserDocument.DocumentType.REPORT,
            defaults={
                'owner': owner,
                'description': f"محضر الجلسة ({mins.meeting.meeting_number}) الإصدار (v{mins.version_number}) - الحالة: {mins.get_status_display()}",
                'system_source_url': f"/decisions/meetings/{mins.meeting_id}/minutes/print/",
            }
        )
        if not created and doc.system_source_url != f"/decisions/meetings/{mins.meeting_id}/minutes/print/":
            doc.system_source_url = f"/decisions/meetings/{mins.meeting_id}/minutes/print/"
            doc.save(update_fields=['system_source_url'])

        mins_recipients = list(User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
            ],
            is_active=True
        ))
        for rec in mins_recipients:
            if rec != owner:
                DocumentShare.objects.get_or_create(
                    document=doc,
                    sender=owner,
                    recipient=rec,
                    defaults={'notes': f"نسخة رسمية من محضر الجلسة ({mins.meeting.meeting_number}) متضمناً الحضور والمداخلات والتحفظات والقرارات"}
                )



