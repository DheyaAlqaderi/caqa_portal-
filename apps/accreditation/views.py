import hashlib
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.http import Http404, FileResponse, HttpResponseForbidden
from django.core.exceptions import ValidationError

from .models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    SelfStudyReport,
    SelfStudyIndicatorResponse,
    EvidenceDocument,
    DeskReviewEvaluation,
    DeskReviewChecklistItem,
    ReviewTeam,
    ReviewTeamMember,
    IndicatorEvaluationScore,
    ExternalReviewReport,
    ApplicationStatusHistory,
    ConflictOfInterestDeclaration,
    GrievanceAppeal,
    SecretariatAssessmentComparisonReport,
)
from .workflow import WorkflowEngine
from apps.standards.models import (
    StandardCategory,
    StandardIndicator,
    AccreditationTrackType,
    RubricEvaluationLevel,
    StandardVersion,
)
from apps.institutions.models import Institution, AcademicProgram
from apps.accounts.models import User, record_audit_log, send_notification, notify_institution, notify_role
from apps.operations.models import Invoice, FeeSchedule
from apps.operations.services import notify_invoice_issued

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'png', 'jpg', 'jpeg', 'zip'}
FORBIDDEN_EXTENSIONS = {'exe', 'bat', 'sh', 'cmd', 'js', 'php', 'py', 'vbs', 'msi', 'scr'}

def _verify_tenant_access(request, application):
    """Prevents cross-institution access (Horizontal privilege escalation)."""
    if request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]:
        if request.user.institution_id and application.institution_id != request.user.institution_id:
            return False
    return True

def _verify_reviewer_access(request, application):
    """Ensures reviewer is explicitly assigned to this specific panel."""
    if request.user.role == User.Roles.EXTERNAL_REVIEWER and not request.user.is_staff:
        if not hasattr(application, 'review_team'):
            return False
        is_chair = application.review_team.chairperson_id == request.user.id
        is_member = application.review_team.members.filter(user=request.user).exists()
        return is_chair or is_member
    return True

def _verify_reviewer_coi_clean(request, application):
    """Ensures an external reviewer has signed a ConflictOfInterestDeclaration without conflict before accessing dossier/evidence."""
    if request.user.role == User.Roles.EXTERNAL_REVIEWER and not request.user.is_staff:
        coi = ConflictOfInterestDeclaration.objects.filter(
            application=application,
            reviewer=request.user
        ).first()
        if not coi or coi.is_conflict_acknowledged:
            return False
    return True

@login_required
def institutional_list(request):
    applications = AccreditationApplication.objects.filter(
        track=AccreditationTrackType.INSTITUTIONAL
    ).select_related('institution', 'applicant_user').order_by('-created_at')
    
    if request.user.is_institution_rep and request.user.institution:
        applications = applications.filter(institution=request.user.institution)

    context = {
        'applications': applications,
        'track_title': 'طلبات الاعتماد المؤسسي للجامعات والكليات',
        'track_type': AccreditationTrackType.INSTITUTIONAL,
    }
    return render(request, 'accreditation/application_list.html', context)

@login_required
def programmatic_list(request):
    applications = AccreditationApplication.objects.filter(
        track=AccreditationTrackType.PROGRAMMATIC
    ).select_related('institution', 'program', 'applicant_user').order_by('-created_at')

    if request.user.is_institution_rep and request.user.institution:
        applications = applications.filter(institution=request.user.institution)

    context = {
        'applications': applications,
        'track_title': 'طلبات الاعتماد البرامجي التخصصي',
        'track_type': AccreditationTrackType.PROGRAMMATIC,
    }
    return render(request, 'accreditation/application_list.html', context)

@login_required
def application_create(request):
    # Strict role check: Council Board, Secretariat Leadership, and Minister are prohibited from submitting applications
    if request.user.is_council or request.user.is_board or request.user.is_minister:
        return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو قيادات الأمانة الفنية بإنشاء أو تقديم طلبات الاعتماد نيابة عن المؤسسات التعليمية.")

    if request.user.role == User.Roles.EXTERNAL_REVIEWER:
        return HttpResponseForbidden("غير مصرح للمحكمين الخارجيين بتقديم طلبات الاعتماد.")

    is_inst_officer = (request.user.role == User.Roles.INSTITUTION_OFFICER)
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN

    if not (is_inst_officer or is_admin):
        messages.error(request, "غير مصرح لك: تقديم طلبات الاعتماد مخصص لممثلي الجامعات المعتمدين فقط.")
        return redirect('core_dashboard')

    if is_inst_officer and not request.user.institution:
        messages.error(request, "حسابك غير مرتبط بأي مؤسسة تعليمية معتمدة في النظام.")
        return redirect('core_dashboard')

    track = request.GET.get('track', AccreditationTrackType.INSTITUTIONAL)
    
    if request.method == 'POST':
        selected_track = request.POST.get('track')
        program_id = request.POST.get('program')
        academic_year = request.POST.get('academic_year', '2025/2026')
        contact_name = request.POST.get('contact_person_name', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        notes = request.POST.get('notes', '').strip()
        license_file = request.FILES.get('initial_license_document')
        
        # If institution officer, strictly force their own institution
        if is_inst_officer:
            institution = request.user.institution
        else:
            institution_id = request.POST.get('institution')
            institution = get_object_or_404(Institution, pk=institution_id)

        program = None
        if selected_track in [AccreditationTrackType.PROGRAMMATIC, AccreditationTrackType.MEDICAL_PROGRAMMATIC] and program_id:
            program = get_object_or_404(AcademicProgram, pk=program_id)
        
        count = AccreditationApplication.objects.count() + 1
        if selected_track == AccreditationTrackType.INSTITUTIONAL:
            prefix = 'INST'
        elif selected_track == AccreditationTrackType.MEDICAL_PROGRAMMATIC:
            prefix = 'MED'
        else:
            prefix = 'PROG'
        app_number = f"CAQA-{prefix}-2026-{count:04d}"

        # Get active standard version for this track
        active_version = StandardVersion.objects.filter(
            track=selected_track, status=StandardVersion.VersionStatus.ACTIVE
        ).first()

        is_submitting_official = 'submit_official' in request.POST or 'submit_now' in request.POST
        initial_status = ApplicationStatus.PENDING_REVIEW if is_submitting_official else ApplicationStatus.DRAFT

        with transaction.atomic():
            app = AccreditationApplication.objects.create(
                application_number=app_number,
                track=selected_track,
                institution=institution,
                program=program,
                standard_version=active_version,
                applicant_user=request.user,
                academic_year=academic_year,
                current_stage=StageChoices.STAGE_1,
                status=initial_status,
                submission_date=timezone.now() if is_submitting_official else None,
                contact_person_name=contact_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                notes=notes,
                initial_license_document=license_file,
            )

            SelfStudyReport.objects.create(
                application=app,
                executive_summary="يجري حالياً إعداد الملخص التنفيذي للدراسة الذاتية من قبل اللجان الداخلية للمؤسسة...",
                internal_committee_names=f"عميد مركز ضمان الجودة د. {institution.quality_center_dean or request.user.get_full_name()}",
            )

            action_name = 'APPLICATION_SUBMITTED_FOR_REVIEW' if is_submitting_official else 'APPLICATION_DRAFT_CREATED'
            record_audit_log(
                user=request.user,
                action=action_name,
                target_model='AccreditationApplication',
                target_id=app.pk,
                details=f"إنشاء طلب اعتماد ({app.application_number}) بحالة ({app.get_status_display()}) لمؤسسة ({institution.name})",
                request=request
            )

            if is_submitting_official:
                # Sync Application Report copy to My Library (مكتبتي) for University President, DG Accreditation, and Institution Officer
                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                # 1. Notify DG of Accreditation and CAQA Secretariat staff with direct link to Application Report
                staff_users = User.objects.filter(
                    role__in=[
                        User.Roles.DG_ACCREDITATION,
                        User.Roles.COUNCIL_SECRETARY_GENERAL,
                        User.Roles.COUNCIL_SECRETARY,
                        User.Roles.ADMIN
                    ],
                    is_active=True,
                    approval_status=User.ApprovalStatus.APPROVED
                )
                for st in staff_users:
                    send_notification(
                        user=st,
                        title="إشعار + نسخة من تقرير طلب الاعتماد الجديد",
                        message=f"قدمت مؤسسة ({institution.name}) طلب اعتماد جديد برقم ({app.application_number}) في مسار ({app.get_track_display()}). تم إرفاق نسخة من تقرير طلب الاعتماد في مكتبتكم، اضغط للانتقال مباشرة إلى تقرير الطلب ومراجعة توقيع رئيس الجامعة وتحديد التكلفة.",
                        url=f"/accreditation/{app.pk}/report/"
                    )

                # 2. Notify University President with direct link to Application Report
                presidents = User.objects.filter(
                    role=User.Roles.UNIVERSITY_PRESIDENT,
                    institution=institution,
                    is_active=True
                )
                if not presidents.exists():
                    presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
                for pres in presidents:
                    send_notification(
                        user=pres,
                        title="إشعار + نسخة من تقرير طلب الاعتماد للتوقيع والاعتماد",
                        message=f"قام مسؤول الجودة برفع طلب اعتماد جديد برقم ({app.application_number}) لمؤسستكم ({institution.name}) مع نسخة في مكتبتكم. اضغط للانتقال مباشرة إلى تقرير طلب الاعتماد للتوقيع والاعتماد الرسمي.",
                        url=f"/accreditation/{app.pk}/report/"
                    )

                # 3. Notify submitting institution officers of official submission receipt
                notify_institution(
                    institution=institution,
                    title="تم إرسال طلب الاعتماد ونسخة التقرير لرئيس الجامعة ومدير عام الاعتماد",
                    message=f"تم استلام طلب الاعتماد رقم ({app.application_number}) لمؤسستكم ({institution.name}) وإرسال إشعار ونسخة من تقرير الطلب إلى رئيس الجامعة للتوقيع، وإلى مدير عام الاعتماد والتراخيص بالأمانة العامة لدراسة الطلب وتحديد التكلفة.",
                    url=f"/accreditation/{app.pk}/report/",
                    extra_recipients=app.applicant_user
                )
                messages.success(request, f"تم تقديم طلب الاعتماد رسمياً برقم قيد ({app.application_number}) وإرسال إشعار ونسخة من تقرير الطلب لرئيس الجامعة ومدير عام الاعتماد.")
            else:
                messages.success(request, f"تم حفظ مسودة طلب الاعتماد بنجاح برقم ({app.application_number}). يمكنك مراجعته وإرساله للمجلس في أي وقت.")

        return redirect('accreditation:application_detail', pk=app.pk)

    if request.user.is_institution_rep and request.user.institution:
        institutions = Institution.objects.filter(pk=request.user.institution.pk)
        programs = AcademicProgram.objects.filter(college__institution=request.user.institution)
    else:
        institutions = Institution.objects.all()
        programs = AcademicProgram.objects.select_related('college__institution').all()

    context = {
        'default_track': track,
        'institutions': institutions,
        'programs': programs,
        'tracks': AccreditationTrackType.choices,
    }
    return render(request, 'accreditation/application_create.html', context)

@login_required
def application_detail(request, pk):
    application = get_object_or_404(
        AccreditationApplication.objects.select_related(
            'institution', 'program', 'applicant_user', 'standard_version'
        ),
        pk=pk
    )
    
    # Enforce Object-level permissions
    if not _verify_tenant_access(request, application):
        messages.error(request, "وصول محجوب: لا يحق لك الاطلاع على طلبات اعتماد خاصة بمؤسسة تعليمية أخرى.")
        return redirect('core_dashboard')

    if not _verify_reviewer_access(request, application):
        messages.error(request, "غير مصرح لك: لست عضواً في لجنة المحكمين المكلفة بهذا الملف.")
        return redirect('core_dashboard')

    ssr, _ = SelfStudyReport.objects.get_or_create(
        application=application,
        defaults={'executive_summary': 'تقرير الدراسة الذاتية قيد الإعداد', 'internal_committee_names': 'لجنة الجودة'}
    )
    
    evidences = application.evidences.select_related('indicator__category').all()
    desk_review = application.desk_reviews.last()
    review_team = getattr(application, 'review_team', None)
    site_visit = getattr(application, 'site_visit', None)
    external_report = getattr(application, 'external_report', None)
    council_decision = getattr(application, 'council_decision', None)
    status_history = application.status_history.select_related('changed_by').all()[:8]
    grievances = application.grievances.all()

    # Reviewer COI check for badge/warning (strictly hidden from institutions)
    reviewer_coi = None
    if request.user.is_reviewer and not request.user.is_institution_rep:
        reviewer_coi = ConflictOfInterestDeclaration.objects.filter(application=application, reviewer=request.user).first()
        if reviewer_coi and reviewer_coi.is_conflict_acknowledged:
            # Hide evaluation evidences and reports on application_detail when reviewer has declared a conflict
            evidences = application.evidences.none()
            external_report = None

    from .guidance_engine import get_contextual_guidance
    guidance = get_contextual_guidance(request.user, application)
    latest_invoice = application.invoices.order_by('-issued_at').first()

    context = {
        'app': application,
        'ssr': ssr,
        'evidences_count': evidences.count(),
        'desk_review': desk_review,
        'review_team': review_team,
        'site_visit': site_visit,
        'external_report': external_report,
        'council_decision': council_decision,
        'status_history': status_history,
        'grievances': grievances,
        'reviewer_coi': reviewer_coi,
        'stages': StageChoices.choices,
        'guidance': guidance,
        'latest_invoice': latest_invoice,
    }
    return render(request, 'accreditation/application_detail.html', context)

@login_required
def self_study_edit(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)

    # Council Board & Secretariat are strictly forbidden from editing or submitting SSR
    if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER]:
        if request.method == 'POST':
            return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية بتعبئة أو تعديل أو تسليم الدراسة الذاتية للمؤسسة.")
        messages.info(request, "تم توجيهك إلى العرض الرسمي لتقرير الدراسة الذاتية؛ استمارات التعديل مخصصة للمؤسسة فقط.")
        return redirect('accreditation:self_study_report_view', pk=application.pk)

    if request.user.role == User.Roles.EXTERNAL_REVIEWER:
        if request.method == 'POST':
            return HttpResponseForbidden("المحكمون الخارجيون غير مخولين بتعديل الدراسة الذاتية للمؤسسة.")
        return redirect('accreditation:self_study_report_view', pk=application.pk)

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لهذا الطلب.")
        return redirect('core_dashboard')

    is_owner_officer = (
        request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]
        and request.user.institution_id == application.institution_id
    )
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    if not (is_owner_officer or is_admin):
        if request.method == 'POST':
            return HttpResponseForbidden("غير مصرح لك بتعديل دراسة هذه المؤسسة.")
        messages.error(request, "غير مصرح لك بتعديل دراسة هذه المؤسسة.")
        return redirect('accreditation:application_detail', pk=application.pk)

    ssr, _ = SelfStudyReport.objects.get_or_create(application=application)

    if request.method == 'POST':
        if ssr.is_locked and not is_admin:
            messages.error(request, "تقرير الدراسة الذاتية مغلق رسمياً بعد التسليم ولا يمكن تعديله إلا بطلب استكمال رسمي.")
            return redirect('accreditation:application_detail', pk=application.pk)

        ssr.executive_summary = request.POST.get('executive_summary', ssr.executive_summary)
        ssr.historical_background = request.POST.get('historical_background', ssr.historical_background)
        ssr.internal_committee_names = request.POST.get('internal_committee_names', ssr.internal_committee_names)
        ssr.methodology = request.POST.get('methodology', ssr.methodology)
        ssr.strengths_overview = request.POST.get('strengths_overview', ssr.strengths_overview)
        ssr.weaknesses_and_challenges = request.POST.get('weaknesses_and_challenges', ssr.weaknesses_and_challenges)
        
        if 'submit_ssr_officially' in request.POST or 'submit_self_study_official' in request.POST:
            is_external_modification = application.status in [
                ApplicationStatus.DRAFT_REPORT_ISSUED,
                ApplicationStatus.WAITING_INSTITUTION_RESPONSE,
                ApplicationStatus.RESPONSE_SUBMITTED,
                ApplicationStatus.SITE_VISIT_COMPLETED,
            ]
            if is_external_modification:
                # Modified in response to External Reviewer's modification report
                ssr.is_locked = True
                ssr.save()
                try:
                    from apps.accounts.models import UserDocument
                    mod_title = f"تقرير دراسة التقييم الذاتي (النسخة المعدلة بعد ملاحظات المقيم الخارجي) - {application.institution.name} [{application.application_number}]"
                    UserDocument.objects.update_or_create(
                        application=application,
                        doc_type=UserDocument.DocumentType.SELF_STUDY,
                        title=mod_title,
                        defaults={
                            'owner': request.user,
                            'description': f"النسخة المعدلة لتقرير التقييم الذاتي من المؤسسة استجابةً لملاحظات المقيم الخارجي ({application.application_number}) - الملخص: {ssr.executive_summary[:200]}",
                            'system_source_url': f"/accreditation/{application.pk}/self-study/report/",
                        }
                    )
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                from apps.site_visits.services import get_panel_reviewers
                for rev in get_panel_reviewers(application):
                    send_notification(
                        user=rev,
                        title=f"تم تعديل وإرسال التقييم الذاتي بناءً على ملاحظاتكم: {application.application_number}",
                        message=f"قامت مؤسسة ({application.institution.name}) بتعديل تقرير التقييم الذاتي للطلب ({application.application_number}) استجابةً لتقرير ملاحظاتكم. اضغط لفتح تقرير التقييم الذاتي المعدل.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                for st in User.objects.filter(role__in=[User.Roles.DG_EVALUATION, User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY_GENERAL], is_active=True):
                    send_notification(
                        user=st,
                        title=f"تم إرسال التقييم الذاتي المعدل بعد ملاحظات المقيم الخارجي: {application.application_number}",
                        message=f"أرسلت مؤسسة ({application.institution.name}) النسخة المعدلة من تقرير التقييم الذاتي للطلب ({application.application_number}) وتم حفظها في مكتبتكم بجانب النسخة الأصلية.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                messages.success(request, "تم اعتماد وإرسال النسخة المعدلة من تقرير الدراسة الذاتية وحفظها في المكتبة بجانب النسخة الأصلية.")
                return redirect('accreditation:self_study_report_view', pk=application.pk)

            target_st = (
                ApplicationStatus.SELF_EVALUATION_SUBMITTED
                if application.status in [
                    ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION,
                    getattr(ApplicationStatus, 'APPROVED_FOR_SELF_STUDY', 'APPROVED_FOR_SELF_STUDY'),
                    ApplicationStatus.SELF_EVALUATION_IN_PROGRESS,
                    ApplicationStatus.DESK_DEFICIENCY,
                ]
                else ApplicationStatus.SUBMITTED
            )
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=target_st,
                    user=request.user,
                    reason="تسليم التقرير رسمياً وإغلاقه للانتقال للفحص المكتبي الأولي",
                    request=request
                )
                ssr.is_locked = True
                ssr.save()
                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass
                record_audit_log(
                    user=request.user,
                    action='SELF_EVALUATION_SUBMITTED',
                    target_model='SelfStudyReport',
                    target_id=ssr.pk,
                    details=f"تسليم تقرير الدراسة والتقييم الذاتي للطلب ({application.application_number})",
                    request=request
                )
                staff_users = User.objects.filter(
                    role__in=[
                        User.Roles.COUNCIL_SECRETARY,
                        User.Roles.COUNCIL_SECRETARY_GENERAL,
                        User.Roles.DG_ACCREDITATION,
                        User.Roles.DG_EVALUATION,
                        User.Roles.ADMIN,
                    ],
                    is_active=True,
                )
                for st in staff_users:
                    send_notification(
                        user=st,
                        title="تم استلام تقرير التقييم الذاتي",
                        message=f"تم إرسال تقرير التقييم الذاتي من مؤسسة ({application.institution.name}) لطلب ({application.application_number}). اضغط للانتقال مباشرة وفتح تقرير التقييم الذاتي للبدء بالفحص المكتبي.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                    if st.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY_GENERAL]:
                        send_notification(
                            user=st,
                            title=f"تم إرسال التقييم الذاتي من المؤسسة والشواهد لإجراء الفحص المكتبي: {application.application_number}",
                            message=f"قامت مؤسسة ({application.institution.name}) بإرسال تقرير التقييم الذاتي والشواهد المرفقة للطلب ({application.application_number}). اضغط للانتقال مباشرة لإجراء الفحص المكتبي الشكلي والموضوعي (DeskReviewEvaluation).",
                            url=f"/accreditation/{application.pk}/desk-review/"
                        )
                messages.success(request, "تم تسليم تقرير الدراسة الذاتية رسمياً إلى مدير عام الاعتماد والأمانة الفنية بنجاح.")
            except ValidationError as e:
                messages.error(request, f"تعذر التسليم: {e.message}")
        else:
            messages.success(request, "تم حفظ مسودة الدراسة الذاتية بنجاح.")

        ssr.save()
        return redirect('accreditation:application_detail', pk=application.pk)

    return render(request, 'accreditation/self_study_form.html', {'app': application, 'ssr': ssr})

@login_required
def evidence_manage(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)
    
    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لهذا الطلب.")
        return redirect('core_dashboard')

    indicators = StandardIndicator.objects.filter(category__track=application.track).select_related('category').order_by('category__order', 'order')

    is_owner_officer = (
        request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]
        and request.user.institution_id == application.institution_id
    )
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    is_restricted = request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER]
    can_upload = (not is_restricted) and (is_owner_officer or is_admin)

    if request.method == 'POST':
        # Strict role check: Council Board & Secretariat cannot upload evidence for institution
        if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER]:
            return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية برفع شواهد نيابة عن المؤسسة التعليمية.")

        if request.user.role == User.Roles.EXTERNAL_REVIEWER:
            return HttpResponseForbidden("غير مصرح للمحكمين الخارجيين برفع شواهد نيابة عن المؤسسة.")

        if not can_upload:
            return HttpResponseForbidden("غير مصرح لك برفع شواهد لهذا الطلب.")

        if hasattr(application, 'self_study_report') and application.self_study_report.is_locked and not is_admin:
            messages.error(request, "بنك الشواهد مغلق رسمياً بعد تسليم تقرير التقييم الذاتي ولا يمكن الإضافة إلا بطلب استكمال رسمي.")
            return redirect('accreditation:evidence_manage', pk=application.pk)

        indicator_id = request.POST.get('indicator')
        code = request.POST.get('code', '').strip()
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        external_url = request.POST.get('external_url', '').strip()
        doc_file = request.FILES.get('document_file')

        # Security check: File extension validation
        if doc_file:
            ext = doc_file.name.split('.')[-1].lower() if '.' in doc_file.name else ''
            if ext in FORBIDDEN_EXTENSIONS or (ext not in ALLOWED_EXTENSIONS):
                messages.error(request, f"الملف المرفق بصيغة غير مقبولة أمنياً (.{ext}). الصيغ المسموحة: PDF, Word, Excel, صور, ZIP.")
                return redirect('accreditation:evidence_manage', pk=application.pk)

            # Security check: Duplicate file detection using SHA-256
            hasher = hashlib.sha256()
            for chunk in doc_file.chunks():
                hasher.update(chunk)
            file_hash = hasher.hexdigest()

            if EvidenceDocument.objects.filter(application=application, sha256_hash=file_hash).exists():
                messages.warning(request, "تنبيه: هذا الملف تم رفعه مسبقاً بنفس المحتوى الرقمي لهذا الطلب.")

        indicator = get_object_or_404(StandardIndicator.objects.select_related('category'), pk=indicator_id)
        allowed_tracks = [application.track]
        if application.track == AccreditationTrackType.MEDICAL_PROGRAMMATIC:
            allowed_tracks.append(AccreditationTrackType.PROGRAMMATIC)
        if indicator.category.track not in allowed_tracks:
            messages.error(request, "لا يمكن ربط وثيقة الشاهد بمؤشر ينتمي إلى مسار اعتماد مختلف عن مسار الطلب.")
            return redirect('accreditation:evidence_manage', pk=application.pk)

        evidence = EvidenceDocument.objects.create(
            application=application,
            indicator=indicator,
            code=code or f"EV-{application.evidences.count()+1:03d}",
            title=title,
            description=description,
            external_url=external_url,
            document_file=doc_file,
        )

        record_audit_log(
            user=request.user,
            action='EVIDENCE_UPLOADED',
            target_model='EvidenceDocument',
            target_id=evidence.pk,
            details=f"رفع شاهد جديد: ({evidence.title}) مرتبط بمؤشر ({indicator.code})",
            request=request
        )

        # Synchronize uploaded evidence into My Library (مكتبتي)
        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        # Notify Council Secretary / Desk Reviewer & DG Accreditation of uploaded evidence
        desk_reviewers = User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.DG_ACCREDITATION,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
            ],
            is_active=True,
        )
        for dr_u in desk_reviewers:
            send_notification(
                user=dr_u,
                title=f"رفع شاهد جديد من المؤسسة لإجراء الفحص المكتبي: {application.application_number}",
                message=f"قامت مؤسسة ({application.institution.name}) برفع وثيقة الشاهد ({evidence.code}: {evidence.title}) مرتبطة بالمؤشر ({indicator.code}) للطلب ({application.application_number}).",
                url=f"/accreditation/{application.pk}/desk-review/"
            )

        messages.success(request, f"تمت إضافة وثيقة الشاهد: ({title}) وربطها بالمؤشر ({indicator.code}) وحفظها بمكتبتك بنجاح.")
        return redirect('accreditation:evidence_manage', pk=application.pk)

    evidences = application.evidences.select_related('indicator__category').order_by('-uploaded_at')
    context = {
        'app': application,
        'indicators': indicators,
        'evidences': evidences,
        'can_upload_evidence': can_upload,
    }
    return render(request, 'accreditation/evidence_manage.html', context)

@login_required
def evidence_download(request, pk):
    """Secure evidence download enforcing RBAC and COI checks."""
    evidence = get_object_or_404(EvidenceDocument.objects.select_related('application'), pk=pk)
    app = evidence.application

    if not _verify_tenant_access(request, app):
        raise Http404("غير مصرح بالوصول إلى المستند.")
    if not _verify_reviewer_access(request, app):
        raise Http404("غير مصرح بالوصول إلى المستند.")
    if not _verify_reviewer_coi_clean(request, app):
        raise Http404("يجب توقيع إقرار الحيادية وخلو تضارب المصالح أولاً للوصول إلى وثائق الشواهد.")

    if not evidence.document_file or not os.path.exists(evidence.document_file.path):
        raise Http404("الملف غير متوفر على خادم التخزين.")

    record_audit_log(
        user=request.user,
        action='EVIDENCE_DOWNLOADED',
        target_model='EvidenceDocument',
        target_id=evidence.pk,
        details=f"تنزيل وثيقة الشاهد: {evidence.title}",
        request=request
    )
    return FileResponse(open(evidence.document_file.path, 'rb'), as_attachment=True, filename=os.path.basename(evidence.document_file.path))

@login_required
def desk_review_process(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)
    
    can_desk_review = (
        request.user.role in [
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_conduct_desk_review')
        or request.user.is_superuser
    )
    if not can_desk_review:
        messages.error(request, "غير مصرح لك: إجراء الفحص المكتبي واستيفاء الشروط خاص بالإدارة العامة للاعتماد والتراخيص وأمانة المجلس فقط.")
        return redirect('accreditation:application_detail', pk=application.pk)

    desk_review, _ = DeskReviewEvaluation.objects.get_or_create(
        application=application,
        defaults={'reviewer': request.user}
    )

    # Initialize standard checklist items if not existing
    default_items = [
        ("الترخيص الوزاري وقرارات الإنشاء الرسمية النافذة", "قانون التعليم العالي رقم (13) لسنة 2005 ولائحته التنفيذية", True),
        ("توصيف البرنامج الأكاديمي ومصفوفة نتاجات التعلم المعتمدة", "الدليل الوطني لضمان الجودة والاعتماد الأكاديمي", True),
        ("تقرير الدراسة الذاتية وقرارات لجان الجودة الداخلية", "دليل إجراءات الاعتماد الوطني", True),
        ("سجلات وبيانات أعضاء هيئة التدريس ونصابهم الأكاديمي", "معايير الاعتماد - معيار أعضاء هيئة التدريس", True),
        ("بنك الشواهد والأدلة الرقمية الثبوتية الداعمة للمؤشرات", "دليل إعداد بنك الشواهد", True),
        ("ملاءمة المرافق والقاعات والمعامل السريرية والورش", "معايير البنية التحتية ومصادر التعلم", True),
    ]
    if desk_review.checklist_items.count() == 0:
        for title, ref, mandatory in default_items:
            DeskReviewChecklistItem.objects.create(
                desk_review=desk_review,
                item_title=title,
                regulatory_reference=ref,
                is_mandatory=mandatory,
                status=DeskReviewChecklistItem.ItemStatus.MET
            )

    if request.method == 'POST':
        decision = request.POST.get('decision')
        completeness = request.POST.get('completeness_percentage', 80)
        formal_met = 'formal_criteria_met' in request.POST
        technical_remarks = request.POST.get('technical_remarks', '')
        deficiencies = request.POST.get('deficiencies_requested', '')

        desk_review.decision = decision
        desk_review.completeness_percentage = int(completeness)
        desk_review.formal_criteria_met = formal_met
        desk_review.technical_remarks = technical_remarks
        desk_review.deficiencies_requested = deficiencies
        desk_review.reviewer = request.user
        desk_review.is_completed = True
        desk_review.save()

        # Update checklist items status
        for item in desk_review.checklist_items.all():
            item_status = request.POST.get(f"item_status_{item.id}")
            item_notes = request.POST.get(f"item_notes_{item.id}", '')
            if item_status:
                item.status = item_status
                item.notes = item_notes
                item.save()

        # If application is in SUBMITTED or SELF_EVALUATION_SUBMITTED, move to DESK_UNDER_REVIEW first
        if application.status in [ApplicationStatus.SUBMITTED, ApplicationStatus.SELF_EVALUATION_SUBMITTED]:
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.DESK_UNDER_REVIEW,
                    user=request.user,
                    reason="بدء إجراءات الفحص المكتبي الأولي",
                    request=request
                )
            except ValidationError:
                application.status = ApplicationStatus.DESK_UNDER_REVIEW
                application.save(update_fields=['status'])

        # Execute workflow transition
        if decision == 'UNDER_REVIEW':
            target_status = ApplicationStatus.DESK_UNDER_REVIEW
        elif decision == DeskReviewEvaluation.DeskDecision.ACCEPTED:
            target_status = ApplicationStatus.DESK_ACCEPTED
        elif decision == DeskReviewEvaluation.DeskDecision.NEEDS_COMPLETION:
            target_status = ApplicationStatus.DESK_DEFICIENCY
        else:
            target_status = ApplicationStatus.DENIED

        try:
            if application.status != target_status:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=target_status,
                    user=request.user,
                    reason=f"قرار الفحص المكتبي: {desk_review.get_decision_display()}",
                    request=request
                )
            messages.success(request, f"تم بنجاح حفظ واعتماد نتيجة الفحص المكتبي ({desk_review.get_decision_display()}).")

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            app_url = f"/accreditation/{application.pk}/"
            if target_status == ApplicationStatus.DESK_ACCEPTED:
                # Notify Institution & University President
                notify_institution(
                    institution=application.institution,
                    title="اجتياز الفحص المكتبي بنجاح",
                    message=f"اجتاز طلب الاعتماد رقم ({application.application_number}) مرحلة الفحص والتدقيق المكتبي الشكلي والموضوعي بنجاح، وتمت إحالته لإجراءات التقييم الميداني والمالي.",
                    url=app_url,
                    extra_recipients=application.applicant_user
                )
                for pres in User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, institution=application.institution, is_active=True):
                    send_notification(
                        user=pres,
                        title="اجتياز الفحص المكتبي الشكلي والموضوعي بنجاح",
                        message=f"اجتاز طلب الاعتماد رقم ({application.application_number}) مرحلة الفحص المكتبي بنسبة استيفاء ({desk_review.completeness_percentage}%).",
                        url=f"/accreditation/{application.pk}/desk-review/"
                    )
                # Notify Finance, Evaluation, and Secretary General
                notify_role(
                    [User.Roles.DG_FINANCE_ADMIN],
                    title="طلب معتمد مكتبياً لمتابعة الرسوم المالية",
                    message=f"اجتاز الطلب ({application.application_number}) لمؤسسة ({application.institution.name}) الفحص المكتبي، يرجى متابعة استحقاق الرسوم وتأكيد السداد المالي (FINANCIAL_CLEARED).",
                    url="/operations/invoices/"
                )
                notify_role(
                    [User.Roles.DG_EVALUATION, User.Roles.COUNCIL_SECRETARY_GENERAL],
                    title="طلب مستوفٍ للفحص المكتبي لتشكيل فريق المراجعة",
                    message=f"الطلب ({application.application_number}) لمؤسسة ({application.institution.name}) جاهز لتشكيل وتكليف لجنة التقييم والمراجعة الخارجية.",
                    url=f"/accreditation/{application.pk}/review-team/"
                )
                # If invoice is already PAID, automatically record/transition to FINANCIAL_CLEARED
                if application.invoices.filter(status='PAID').exists():
                    try:
                        WorkflowEngine.execute_transition(
                            application=application,
                            target_status=ApplicationStatus.FINANCIAL_CLEARED,
                            user=request.user,
                            reason="تأكيد السداد المالي المسبق واستيفاء الفحص المكتبي (FINANCIAL_CLEARED)",
                            request=request
                        )
                    except Exception:
                        pass
            elif target_status == ApplicationStatus.DESK_DEFICIENCY:
                # Re-open SSR so the institution can complete missing items and resubmit
                if hasattr(application, 'self_study_report'):
                    application.self_study_report.is_locked = False
                    application.self_study_report.save(update_fields=['is_locked'])
                notify_institution(
                    institution=application.institution,
                    title="إشعار استيفاء نواقص في الفحص المكتبي",
                    message=f"يتطلب طلب الاعتماد رقم ({application.application_number}) استيفاء بعض النواقص والوثائق التكميلية بحسب ملاحظات الفاحص المكتبي: ({deficiencies}). تم إعادة فتح التقرير لاستكمال النواقص.",
                    url=app_url,
                    extra_recipients=application.applicant_user
                )
                for pres in User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, institution=application.institution, is_active=True):
                    send_notification(
                        user=pres,
                        title="إشعار استيفاء نواقص في الفحص المكتبي",
                        message=f"يتطلب طلب الاعتماد رقم ({application.application_number}) استيفاء نواقص الفحص المكتبي: ({deficiencies}).",
                        url=f"/accreditation/{application.pk}/desk-review/"
                    )
        except ValidationError as e:
            messages.error(request, f"تنبيه سير العمل: {e.message}")

        return redirect('accreditation:application_detail', pk=application.pk)

    return render(request, 'accreditation/desk_review_form.html', {
        'app': application,
        'review': desk_review,
        'checklist_items': desk_review.checklist_items.all(),
    })

@login_required
def assign_review_team(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)

    can_assign = (
        request.user.role in [
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_nominate_reviewers')
        or request.user.is_superuser
    )
    if not can_assign:
        messages.error(request, "غير مصرح لك: تشكيل وتكليف لجان التقييم والمراجعة الخارجية خاص بالإدارة العامة للتقييم والمراجعة وأمانة المجلس فقط.")
        return redirect('accreditation:application_detail', pk=application.pk)

    if request.method == 'POST':
        existing_team = getattr(application, 'review_team', None)
        chair_id = request.POST.get('chairperson')
        if chair_id:
            chair_user = get_object_or_404(User, pk=chair_id)
        elif existing_team and existing_team.chairperson:
            chair_user = existing_team.chairperson
        else:
            chair_user = request.user

        # Validate chairperson is active and an authorized external reviewer (or admin)
        if not chair_user.is_active or chair_user.role not in [User.Roles.EXTERNAL_REVIEWER, User.Roles.ADMIN]:
            messages.error(request, "لا يمكن تكليف مستخدم غير نشط أو غير معتمد في السجل الوطني للمحكمين الخارجيين.")
            return redirect('accreditation:assign_review_team', pk=application.pk)

        member_ids = list(request.POST.getlist('member_ids') or request.POST.getlist('members'))
        replacement_id = request.POST.get('replacement_user_id') or request.POST.get('new_reviewer_id')
        if replacement_id and replacement_id not in member_ids:
            member_ids.append(replacement_id)

        valid_members = []
        for m_id in member_ids:
            m_user = User.objects.filter(pk=m_id).first()
            if not m_user or not m_user.is_active or m_user.role not in [User.Roles.EXTERNAL_REVIEWER, User.Roles.ADMIN]:
                messages.error(request, "أحد الأعضاء المختارين غير نشط أو ليس محكماً خارجياً معتمداً.")
                return redirect('accreditation:assign_review_team', pk=application.pk)
            if m_user not in valid_members:
                valid_members.append(m_user)

        team, created = ReviewTeam.objects.get_or_create(
            application=application,
            defaults={
                'decree_number': request.POST.get('decree_number') or f"قرار أمين عام المجلس رقم (2026/{application.pk:02d})",
                'formation_date': timezone.now().date(),
                'chairperson': chair_user,
            }
        )
        team.decree_number = request.POST.get('decree_number') or team.decree_number

        # Support replacing a conflicted/apologizing reviewer if replace_member_id is passed
        replace_id = request.POST.get('replace_member_id')
        if replace_id:
            ReviewTeamMember.objects.filter(team=team, user_id=replace_id).delete()
            ConflictOfInterestDeclaration.objects.filter(application=application, reviewer_id=replace_id).delete()
            if str(team.chairperson_id) == str(replace_id) and valid_members:
                chair_user = valid_members[0]
            record_audit_log(
                user=request.user,
                action='REVIEWER_REPLACED_DUE_TO_COI',
                target_model='ReviewTeam',
                target_id=team.pk,
                details=f"استبدال المحكم المتعارض/المعتذر رقم ({replace_id}) في لجنة المراجعة للطلب ({application.application_number})",
                request=request
            )

        team.chairperson = chair_user
        team.save()

        # Add team members without duplicates
        for m_user in valid_members:
            ReviewTeamMember.objects.get_or_create(
                team=team,
                user=m_user,
                defaults={
                    'role_in_team': request.POST.get(f'role_{m_user.id}', ReviewTeamMember.PanelRole.QUALITY_EXPERT),
                }
            )

        if application.status != ApplicationStatus.PANEL_ASSIGNED:
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.PANEL_ASSIGNED,
                    user=request.user,
                    reason=f"تكليف لجنة المراجعة بقرار رقم ({team.decree_number}) برئاسة ({team.chairperson.get_full_name()})",
                    request=request
                )
                messages.success(request, "تم اعتماد تشكيل لجنة المراجعة والتقييم الخارجي بنجاح.")
            except ValidationError as e:
                messages.error(request, f"تنبيه سير العمل: {e.message}")
        else:
            messages.success(request, "تم تحديث تشكيل وأعضاء لجنة المراجعة والتقييم الخارجي بنجاح.")

        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        # Trigger Scenarios 22 & 23: Reviewer team assignment & individual invitations
        from apps.site_visits.services import notify_reviewer_team_assigned
        notify_reviewer_team_assigned(team)

        return redirect('accreditation:application_detail', pk=application.pk)

    team = getattr(application, 'review_team', None)
    # In accordance with governance separation of powers, evaluators must strictly be qualified external reviewers
    evaluators = User.objects.filter(role__in=[User.Roles.EXTERNAL_REVIEWER, User.Roles.ADMIN], is_active=True)
    return render(request, 'accreditation/review_team_form.html', {
        'app': application,
        'team': team,
        'evaluators': evaluators,
    })

@login_required
def coi_declare(request, pk):
    """Conflict of interest declaration for external reviewers before evaluation."""
    application = get_object_or_404(AccreditationApplication, pk=pk)

    if not (request.user.is_reviewer or request.user.is_staff):
        messages.error(request, "إقرار النزاهة وعدم تعارض المصالح مخصص حصراً للمحكمين والخبراء المكلفين.")
        return redirect('accreditation:application_detail', pk=application.pk)

    coi, _ = ConflictOfInterestDeclaration.objects.get_or_create(
        application=application,
        reviewer=request.user
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'decline' or 'decline_assignment' in request.POST:
            decline_reason = request.POST.get('decline_reason', '').strip()
            record_audit_log(
                user=request.user,
                action='REVIEWER_ASSIGNMENT_DECLINED',
                target_model='AccreditationApplication',
                target_id=application.pk,
                details=f"اعتذار المحكم ({request.user.get_full_name() or request.user.username}) عن مهمة التحكيم. السبب: {decline_reason}",
                request=request
            )
            # Scenario 25: Reviewer declines assignment
            from apps.site_visits.services import notify_reviewer_declined
            notify_reviewer_declined(request.user, application, reason=decline_reason)
            messages.info(request, "تم تسجيل اعتذارك عن مهمة التحكيم وإشعار أمانة المجلس لاتخاذ اللازم.")
            return redirect('core_dashboard')

        coi.has_taught_in_institution = 'has_taught' in request.POST
        coi.has_relatives_or_graduates = 'has_relatives' in request.POST
        coi.has_financial_or_consulting = 'has_financial' in request.POST
        coi.other_conflict_details = request.POST.get('other_conflict_details', '')
        coi.is_conflict_acknowledged = 'is_conflict_acknowledged' in request.POST

        # Capture IP
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        coi.ip_address = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')
        coi.save()

        record_audit_log(
            user=request.user,
            action='COI_DECLARED',
            target_model='ConflictOfInterestDeclaration',
            target_id=coi.pk,
            details=f"توقيع إقرار النزاهة وتعارض المصالح. وجود تعارض: {coi.is_conflict_acknowledged}",
            request=request
        )

        from apps.site_visits.services import notify_conflict_of_interest_declared, notify_reviewer_accepted

        if coi.is_conflict_acknowledged:
            # Scenario 26: Conflict of interest disclosed (confidential, to Secretariat only)
            notify_conflict_of_interest_declared(request.user, application, has_conflict=True)
            messages.warning(request, "تم تسجيل إفادتك بوجود تعارض مصالح. سيتم إشعار أمانة المجلس لاستبدالك في اللجنة حفاظاً على النزاهة.")
            return redirect('accreditation:application_detail', pk=application.pk)
        else:
            # Scenario 24: Reviewer accepts assignment with clean COI
            notify_reviewer_accepted(request.user, application)
            notify_conflict_of_interest_declared(request.user, application, has_conflict=False)
            from apps.site_visits.services import notify_self_study_delivered_to_reviewer
            notify_self_study_delivered_to_reviewer(request.user, application)
            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass
            messages.success(request, "تم توقيع إقرار النزاهة وخلو تعارض المصالح بنجاح. تم تسليمكم ملف الدراسة الذاتية والشواهد ويمكنكم الآن المتابعة لتقييم المؤشرات.")
            return redirect('accreditation:external_rubrics_evaluation', pk=application.pk)

    return render(request, 'accreditation/coi_declare.html', {'app': application, 'coi': coi})

@login_required
def external_rubrics_evaluation(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)

    if not (request.user.is_reviewer or request.user.is_staff):
        messages.error(request, "غير مصرح لك: استمارة ومصفوفة تقييم المعايير والمؤشرات (Rubrics) مخصصة فقط لأعضاء فريق المحكمين والخبراء المكلفين.")
        return redirect('accreditation:application_detail', pk=application.pk)

    if not _verify_reviewer_access(request, application):
        messages.error(request, "غير مصرح لك: لست عضواً مكلفاً بتحكيم هذا الطلب.")
        return redirect('core_dashboard')

    # COI Guard: Reviewer must sign COI without conflict before evaluating
    coi = ConflictOfInterestDeclaration.objects.filter(application=application, reviewer=request.user).first()
    if not coi and not request.user.is_superuser:
        messages.warning(request, "يجب توقيع إقرار النزاهة وعدم تعارض المصالح أولاً قبل الاطلاع على مصفوفة التقييم.")
        return redirect('accreditation:coi_declare', pk=application.pk)
    if coi and coi.is_conflict_acknowledged and not request.user.is_superuser:
        messages.error(request, "ممنوع من التقييم: لقد أقررت بوجود تعارض مصالح رسمي يمنعك من تحكيم هذا الملف.")
        return redirect('accreditation:application_detail', pk=application.pk)

    indicators = StandardIndicator.objects.filter(category__track=application.track).select_related('category').order_by('category__order', 'order')

    if request.method == 'POST':
        for ind in indicators:
            score_val = request.POST.get(f"score_{ind.id}")
            strengths = request.POST.get(f"strengths_{ind.id}", '')
            weaknesses = request.POST.get(f"weaknesses_{ind.id}", '')
            verif_notes = request.POST.get(f"verif_{ind.id}", '')

            if score_val:
                IndicatorEvaluationScore.objects.update_or_create(
                    application=application,
                    indicator=ind,
                    evaluator=request.user,
                    defaults={
                        'score_level': score_val,
                        'strengths': strengths,
                        'weaknesses': weaknesses,
                        'evidence_verification_notes': verif_notes,
                    }
                )
        record_audit_log(
            user=request.user,
            action='RUBRICS_SCORED',
            target_model='IndicatorEvaluationScore',
            target_id=application.pk,
            details=f"حفظ تقييمات سلالم التقدير لمؤشرات الطلب ({application.application_number})",
            request=request
        )
        ExternalReviewReport.objects.get_or_create(
            application=application,
            defaults={
                'draft_executive_summary': f"تم رصد تقييم المؤشرات المعيارية للطلب ({application.application_number}) من قبل المقيم الخارجي ({request.user.get_full_name() or request.user.username}).",
                'draft_findings_per_standard': "تم استكمال تقييم المؤشرات المعيارية في مصفوفة التقييم الخارجي.",
            }
        )
        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        dg_eval_users = User.objects.filter(
            role__in=[User.Roles.DG_EVALUATION, User.Roles.COUNCIL_SECRETARY_GENERAL],
            is_active=True,
        )
        for dg_u in dg_eval_users:
            send_notification(
                user=dg_u,
                title=f"تم حفظ وإرسال تقييم المؤشرات الخارجي: {application.application_number}",
                message=f"قام المقيم الخارجي ({request.user.get_full_name() or request.user.username}) برصد وحفظ درجات تقييم المؤشرات الخارجية للطلب ({application.application_number}) وتمت مزامنة التقرير في مكتبتكم.",
                url=f"/accreditation/{application.pk}/external-report/"
            )

        if 'submit_to_external_report' in request.POST:
            messages.success(request, "تم حفظ تقييمات المعايير وإشعار مدير عام التقييم والمراجعة الخارجية. يمكنك الآن استكمال تقرير المراجعة الخارجي.")
            return redirect('accreditation:external_report_manage', pk=application.pk)

        messages.success(request, "تم حفظ ومطابقة تقييمات المعايير والشواهد وإشعار مدير عام التقييم والمراجعة الخارجية بنجاح.")
        return redirect('accreditation:application_detail', pk=application.pk)

    existing_scores = {
        s.indicator_id: s for s in IndicatorEvaluationScore.objects.filter(application=application, evaluator=request.user)
    }

    context = {
        'app': application,
        'indicators': indicators,
        'existing_scores': existing_scores,
        'score_levels': RubricEvaluationLevel.choices,
    }
    return render(request, 'accreditation/rubrics_evaluation.html', context)

@login_required
def external_report_manage(request, pk):
    application = get_object_or_404(AccreditationApplication, pk=pk)
    
    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لهذا الطلب.")
        return redirect('core_dashboard')

    report, _ = ExternalReviewReport.objects.get_or_create(
        application=application,
        defaults={
            'draft_executive_summary': 'مسودة تقرير المراجعة الخارجية قيد الإعداد...',
            'draft_findings_per_standard': 'نتائج تقييم المعايير التفصيلية...',
        }
    )

    is_locked_final = application.status in [
        ApplicationStatus.FINAL_REPORT_READY,
        ApplicationStatus.IN_COUNCIL_REVIEW,
        ApplicationStatus.FULL_ACCREDITATION,
        ApplicationStatus.CONDITIONAL_ACCREDITATION,
        ApplicationStatus.DENIED,
    ]

    if request.method == 'POST':
        if is_locked_final and not request.user.is_superuser:
            return HttpResponseForbidden("التقرير الخارجي النهائي معتمد ومقفل رسمياً ولا يمكن تعديله.")

        action = request.POST.get('action')
        
        if action in ['save_draft', 'send_modification_report']:
            if not (request.user.is_reviewer or request.user.is_staff):
                messages.error(request, "غير مصرح لك: صياغة مسودة التقرير وتقرير الملاحظات والتعديل خاص بفريق المحكمين والخبراء فقط.")
                return redirect('accreditation:external_report_manage', pk=application.pk)

            report.draft_executive_summary = request.POST.get('draft_executive_summary', '')
            report.draft_findings_per_standard = request.POST.get('draft_findings_per_standard', '')
            report.draft_sent_to_institution_date = timezone.now()
            from datetime import timedelta, datetime
            explicit_deadline = request.POST.get('response_deadline', '').strip()
            deadline_days_str = request.POST.get('response_deadline_days', '15').strip()
            if explicit_deadline:
                try:
                    report.response_deadline = datetime.strptime(explicit_deadline, '%Y-%m-%d').date()
                except ValueError:
                    report.response_deadline = (timezone.now() + timedelta(days=15)).date()
            else:
                try:
                    days_val = max(1, int(deadline_days_str))
                except ValueError:
                    days_val = 15
                report.response_deadline = (timezone.now() + timedelta(days=days_val)).date()
            report.save()

            # Preserve a snapshot of the Original Self-Study Report in My Library before unlocking SSR for modification
            try:
                from apps.accounts.models import UserDocument
                ssr_obj = getattr(application, 'self_study_report', None)
                if ssr_obj:
                    orig_title = f"تقرير دراسة التقييم الذاتي (النسخة الأصلية الأولية) - {application.institution.name} [{application.application_number}]"
                    UserDocument.objects.get_or_create(
                        application=application,
                        doc_type=UserDocument.DocumentType.SELF_STUDY,
                        title=orig_title,
                        defaults={
                            'owner': application.applicant_user or request.user,
                            'description': f"النسخة الأصلية الأولية لتقرير التقييم الذاتي قبل تعديل المؤسسة بناءً على ملاحظات المقيم الخارجي ({application.application_number}) - الملخص: {(ssr_obj.executive_summary or '')[:200]}",
                            'system_source_url': f"/accreditation/{application.pk}/self-study/report/",
                        }
                    )
                    # Unlock Self-Study Report so the institution can modify its Self-Study Report
                    ssr_obj.is_locked = False
                    ssr_obj.save(update_fields=['is_locked'])
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            if application.status in [ApplicationStatus.PANEL_ASSIGNED, ApplicationStatus.SITE_VISIT_SCHEDULED]:
                application.status = ApplicationStatus.SITE_VISIT_COMPLETED
                application.save(update_fields=['status'])
            if application.status == ApplicationStatus.SITE_VISIT_COMPLETED:
                try:
                    WorkflowEngine.execute_transition(
                        application=application,
                        target_status=ApplicationStatus.DRAFT_REPORT_ISSUED,
                        user=request.user,
                        reason="إصدار تقرير ملاحظات ومسودة المراجعة الخارجية للمؤسسة لتعديل التقييم الذاتي والرد",
                        request=request
                    )
                except ValidationError:
                    application.status = ApplicationStatus.DRAFT_REPORT_ISSUED
                    application.save(update_fields=['status'])

            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.WAITING_INSTITUTION_RESPONSE,
                    user=request.user,
                    reason="إصدار تقرير ملاحظات المقيم الخارجي وإحالته للمؤسسة لتعديل التقييم الذاتي وممارسة حق الرد",
                    request=request
                )
                messages.success(request, "تم إرسال تقرير ملاحظات المقيم الخارجي ومسودة التقرير إلى المؤسسة وفتح التقييم الذاتي للتعديل وحق الرد.")
            except ValidationError as e:
                messages.warning(request, f"{e.message}")

            # Notify Institution Officers & University President of Modification Report & Right to Reply
            deadline_str = report.response_deadline.strftime('%Y-%m-%d') if report.response_deadline else "خلال المهلة المحددة"
            presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, institution=application.institution, is_active=True)
            extra_list = [u for u in ([application.applicant_user] + list(presidents)) if u]
            notify_institution(
                institution=application.institution,
                title="تقرير ملاحظات وطلب تعديل التقييم الذاتي من المقيم الخارجي (حق الرد)",
                message=(
                    f"أرسل المقيم الخارجي تقرير ملاحظاته ومسودة تقرير التقييم للطلب "
                    f"({application.application_number}) الخاص بمؤسستكم ({application.institution.name}). "
                    f"تم فتح التقييم الذاتي للتعديل؛ يرجى الاطلاع على تقرير المقيم الخارجي وتعديل التقييم الذاتي أو تسجيل رد المؤسسة قبل تاريخ ({deadline_str})."
                ),
                url=f"/accreditation/{application.pk}/external-report/",
                extra_recipients=extra_list
            )

            # Also notify DG_EVALUATION & Secretariat users
            secretariat_users = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_EVALUATION,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.ADMIN,
                ],
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED
            )
            for sec in secretariat_users:
                send_notification(
                    user=sec,
                    title=f"إحالة تقرير ملاحظات المقيم الخارجي للمؤسسة: {application.application_number}",
                    message=(
                        f"أحال المقيم الخارجي تقرير الملاحظات ومسودة المراجعة للطلب ({application.application_number}) "
                        f"إلى مؤسسة ({application.institution.name}) لتعديل التقييم الذاتي وممارسة حق الرد حتى ({deadline_str})."
                    ),
                    url=f"/accreditation/{application.pk}/external-report/"
                )
        
        elif action == 'submit_institution_reply':
            if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER]:
                return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية أو المحكمين بتقديم رد المؤسسة الرسمي.")

            is_owner_officer = (
                request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]
                and request.user.institution_id == application.institution_id
            )
            is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
            if not (is_owner_officer or is_admin):
                return HttpResponseForbidden("ممارسة حق الرد مخصص لممثل المؤسسة التعليمية فقط.")

            report.institution_reply_text = request.POST.get('institution_reply_text', '')
            if request.FILES.get('institution_reply_file'):
                report.institution_reply_file = request.FILES.get('institution_reply_file')
            report.institution_reply_date = timezone.now()
            report.save()

            # Save Modified Self-Study Report snapshot in My Library alongside Original Self-Study Report
            try:
                from apps.accounts.models import UserDocument
                ssr_obj = getattr(application, 'self_study_report', None)
                if ssr_obj:
                    if request.POST.get('modified_executive_summary'):
                        ssr_obj.executive_summary = request.POST.get('modified_executive_summary')
                    ssr_obj.is_locked = True
                    ssr_obj.save()
                    mod_title = f"تقرير دراسة التقييم الذاتي (النسخة المعدلة بعد ملاحظات المقيم الخارجي) - {application.institution.name} [{application.application_number}]"
                    UserDocument.objects.update_or_create(
                        application=application,
                        doc_type=UserDocument.DocumentType.SELF_STUDY,
                        title=mod_title,
                        defaults={
                            'owner': request.user,
                            'description': f"النسخة المعدلة لتقرير التقييم الذاتي ورد المؤسسة على ملاحظات المقيم الخارجي للطلب ({application.application_number}) - الإيضاحات: {report.institution_reply_text[:200]}",
                            'system_source_url': f"/accreditation/{application.pk}/self-study/report/",
                        }
                    )
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.RESPONSE_SUBMITTED,
                    user=request.user,
                    reason="تسليم مذكرة رد المؤسسة والتقييم الذاتي المعدل حيال ملاحظات المقيم الخارجي",
                    request=request
                )
                messages.success(request, "تم استلام رد المؤسسة واعتماد التقييم الذاتي المعدل وتوجيهه للمقيم الخارجي ومدير عام التقييم.")
            except ValidationError as e:
                messages.warning(request, f"{e.message}")

            # Notify Review Team and Secretariat of Institution Reply
            from apps.site_visits.services import get_panel_reviewers
            for rev in get_panel_reviewers(application):
                send_notification(
                    user=rev,
                    title=f"استلام رد المؤسسة والتقييم الذاتي المعدل: {application.application_number}",
                    message=(
                        f"قدمت مؤسسة ({application.institution.name}) ردها الرسمي وتعديلات التقييم الذاتي "
                        f"بناءً على ملاحظاتكم للطلب ({application.application_number}). "
                        f"يرجى مراجعة الردود واعتماد التقرير النهائي وإرساله لمدير عام التقييم والمراجعة الخارجية."
                    ),
                    url=f"/accreditation/{application.pk}/external-report/"
                )

            secretariat_users = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_EVALUATION,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.ADMIN,
                ],
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED
            )
            for sec in secretariat_users:
                send_notification(
                    user=sec,
                    title=f"استلام رد المؤسسة والتقييم الذاتي المعدل: {application.application_number}",
                    message=(
                        f"قدمت مؤسسة ({application.institution.name}) ردها الرسمي والنسخة المعدلة من التقييم الذاتي "
                        f"على ملاحظات المقيم الخارجي للطلب ({application.application_number}) وتم حفظها في مكتبتكم."
                    ),
                    url=f"/accreditation/{application.pk}/external-report/"
                )
        
        elif action in ['finalize_report', 'send_to_dg_evaluation']:
            if not (request.user.is_reviewer or request.user.is_staff):
                messages.error(request, "غير مصرح لك: اعتماد وإرسال تقرير التقييم الخارجي النهائي لمدير عام التقييم والمجلس خاص بفريق المحكمين فقط.")
                return redirect('accreditation:external_report_manage', pk=application.pk)

            report.team_response_to_reply = request.POST.get('team_response_to_reply', '')
            report.final_report_text = request.POST.get('final_report_text', '')
            report.final_recommendation = request.POST.get('final_recommendation', ExternalReviewReport.FinalRecommendation.FULL_ACCREDITATION)
            report.final_submitted_to_council_date = timezone.now()
            report.save()
            
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.FINAL_REPORT_READY,
                    user=request.user,
                    reason=f"اعتماد وإرسال تقرير التقييم الخارجي النهائي لمدير عام التقييم والمراجعة الخارجية بتوصية: {report.get_final_recommendation_display()}",
                    request=request
                )
                messages.success(request, "تم حفظ وإرسال تقرير التقييم الخارجي النهائي رسمياً إلى مدير عام التقييم والمراجعة الخارجية وحفظه في المكتبة.")
            except ValidationError as e:
                messages.warning(request, f"{e.message}")

            # Sync External Evaluation Report + Original SSR + Modified SSR into DG_EVALUATION's My Library
            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            # Notify DG_EVALUATION & Secretariat of Final External Evaluation Report Submission
            secretariat_users = User.objects.filter(
                role__in=[
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.ADMIN,
                ],
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED
            )
            for sec in secretariat_users:
                send_notification(
                    user=sec,
                    title=f"تم إرسال التقييم الخارجي النهائي من المقيم الخارجي: {application.application_number}",
                    message=(
                        f"قام المقيم الخارجي بحفظ وإرسال تقرير التقييم الخارجي النهائي للطلب "
                        f"({application.application_number}) الخاص بـ ({application.institution.name}) "
                        f"بتوصية ({report.get_final_recommendation_display()}). "
                        f"تم حفظ تقرير التقييم الخارجي في مكتبتكم بجانب تقرير التقييم الذاتي (الأصلي والمعدل). اضغط لفتح تقرير التقييم الخارجي."
                    ),
                    url=f"/accreditation/{application.pk}/external-report/"
                )

        return redirect('accreditation:application_detail', pk=application.pk)

    return render(request, 'accreditation/external_report.html', {'app': application, 'report': report, 'is_locked_final': is_locked_final})

@login_required
def grievance_create(request, pk):
    """Submit a formal grievance/appeal within the regulatory window."""
    application = get_object_or_404(AccreditationApplication, pk=pk)

    # Council Board, Secretariat, Reviewers, and Minister cannot submit grievances on behalf of institutions
    if request.user.is_council or request.user.is_board or request.user.is_minister or request.user.role == User.Roles.EXTERNAL_REVIEWER:
        return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية أو المحكمين بتقديم تظلم رسمي نيابة عن المؤسسة.")

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بتقديم تظلم على هذا الطلب.")
        return redirect('core_dashboard')

    is_owner_officer = (request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and request.user.institution_id == application.institution_id)
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    if not (is_owner_officer or is_admin):
        return HttpResponseForbidden("تقديم التظلمات الرسمية متاح فقط لرئيس الجامعة وممثل المؤسسة التعليمية المعتمد.")

    if request.method == 'POST':
        grounds = request.POST.get('grounds_of_appeal', '').strip()
        doc_file = request.FILES.get('supporting_document')
        appeal_num = f"GRV-2026-{GrievanceAppeal.objects.count()+1:03d}"

        with transaction.atomic():
            appeal = GrievanceAppeal.objects.create(
                application=application,
                appellant_user=request.user,
                appeal_number=appeal_num,
                grounds_of_appeal=grounds,
                supporting_document=doc_file,
                status=GrievanceAppeal.AppealStatus.SUBMITTED
            )

            # Central Sovereign Transaction Engine
            from apps.decisions.models import SovereignTransaction
            SovereignTransaction.objects.create(
                reference_number=appeal.appeal_number,
                transaction_type=SovereignTransaction.TransactionType.GRIEVANCE_APPEAL,
                sender=request.user,
                sending_authority=application.institution.name,
                receiving_authority="لجنة التظلمات والطعون المستقلة",
                subject=f"تظلم رسمي مقدم من {application.institution.name} على الطلب {application.application_number}",
                description=grounds[:500],
                status=SovereignTransaction.TransactionStatus.SUBMITTED,
                application=application,
                official_document=doc_file
            )

            record_audit_log(
                user=request.user,
                action='GRIEVANCE_SUBMITTED',
                target_model='GrievanceAppeal',
                target_id=appeal.pk,
                details=f"قيد تظلم رسمي رقم ({appeal.appeal_number}) على الطلب ({application.application_number})",
                request=request
            )

        # Notify Grievance Committee, Legal Directorate & Council Leadership
        legal_officers = User.objects.filter(
            role__in=[
                User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
                User.Roles.LEGAL_DIRECTOR,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.ADMIN
            ],
            is_active=True
        )
        for officer in legal_officers:
            send_notification(
                user=officer,
                title=f"قيد تظلم رسمي جديد: {appeal.appeal_number}",
                message=(
                    f"قيدت مؤسسة ({application.institution.name}) تظلماً رسمياً برقم ({appeal.appeal_number}) "
                    f"على طلب الاعتماد ({application.application_number}). يرجى فحص الشروط الشكلية وإعداد المطالعة القانونية."
                ),
                url=f"/accreditation/grievances/{appeal.pk}/review/"
            )

        # Notify University President & Institution Officer
        notify_institution(
            institution=application.institution,
            title=f"تم قيد التظلم الرسمي: {appeal.appeal_number}",
            message=f"تم بنجاح قيد تظلم المؤسسة برقم ({appeal.appeal_number}) وإحالته إلى لجنة التظلمات المستقلة لدراسته.",
            url=f"/accreditation/{application.pk}/"
        )

        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        # Dispatch instant SMS notification to Legal Directorate
        try:
            from apps.accounts.sms_service import notify_grievance_sms
            notify_grievance_sms(appeal)
        except Exception:
            pass

        messages.success(request, f"تم قيد تظلمك رسمياً برقم ({appeal.appeal_number}) وإحالته إلى لجنة التظلمات المستقلة لدراسته والبت فيه.")
        return redirect('accreditation:application_detail', pk=application.pk)

    return render(request, 'accreditation/grievance_form.html', {'app': application})

@login_required
def grievance_review(request, pk):
    """
    Review and process formal grievance:
    - Legal Director / Grievance Committee Member conducts examination and submits report.
    - Council Board / Committee issues final resolution on the appeal.
    """
    grievance = get_object_or_404(GrievanceAppeal.objects.select_related('application__institution', 'appellant_user'), pk=pk)
    
    can_review_legal = (
        request.user.role in [
            User.Roles.LEGAL_DIRECTOR,
            User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_review_grievance_legal_terms')
        or request.user.is_superuser
    )
    can_resolve_board = (
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.BOARD_MEMBER,
            User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_finalize_collective_decision')
        or request.user.is_superuser
    )

    if not (can_review_legal or can_resolve_board):
        messages.error(request, "غير مصرح لك: فحص ونظر التظلمات مقتصر على لجنة التظلمات المستقلة ومجلس إدارة المجلس.")
        return redirect('core_dashboard')

    # Committee Independence Guard: Any reviewer who participated in the original evaluation cannot review/adjudicate the grievance
    if hasattr(grievance.application, 'review_team') and not request.user.is_superuser:
        rt = grievance.application.review_team
        if rt.chairperson_id == request.user.id or rt.members.filter(user=request.user).exists():
            return HttpResponseForbidden("غير مصرح لك: يمتنع قانوناً على من شارك في تقييم الطلب الأصلي المشاركة في فحص أو البت في التظلم المرفوع ضده (مبدأ حياد واستقلالية لجنة التظلمات).")

    if request.method == 'POST':
        action = request.POST.get('action')
        from apps.decisions.models import SovereignTransaction

        if action == 'save_legal_report' and can_review_legal:
            legal_report = request.POST.get('committee_report', '').strip()
            chair_report_file = request.FILES.get('committee_chair_report')

            grievance.committee_report = legal_report
            if chair_report_file:
                grievance.committee_chair_report = chair_report_file
            grievance.status = GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW
            grievance.save()

            # Update Sovereign Transaction
            sov_trx = SovereignTransaction.objects.filter(reference_number=grievance.appeal_number).first()
            if sov_trx:
                sov_trx.transition_to(
                    SovereignTransaction.TransactionStatus.UNDER_REVIEW,
                    request.user,
                    reason=f"إعداد تقرير فحص التظلم والمطالعة القانونية بواسطة {request.user.get_full_name()}"
                )

            record_audit_log(
                user=request.user,
                action='GRIEVANCE_LEGAL_REVIEWED',
                target_model='GrievanceAppeal',
                target_id=grievance.pk,
                details=f"تسجيل تقرير فحص التظلم والمطالعة القانونية للتظلم رقم ({grievance.appeal_number})",
                request=request
            )

            # Notify Council Chairman, Vice Chairman, Board Members & Secretary General
            board_users = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                ],
                is_active=True
            )
            for b_u in board_users:
                send_notification(
                    user=b_u,
                    title=f"إحالة تقرير لجنة فحص التظلمات والمطالعة القانونية: {grievance.appeal_number}",
                    message=f"رفعت الشؤون القانونية ولجنة التظلمات تقرير فحص التظلم رقم ({grievance.appeal_number}) للطلب ({grievance.application.application_number}) للعرض والبت من مجلس الإدارة.",
                    url=f"/accreditation/grievances/{grievance.pk}/review/"
                )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            messages.success(request, "تم تسجيل تقرير فحص التظلم والمطالعة القانونية وإحالته لمجلس الإدارة للبت فيه.")
            return redirect('accreditation:application_detail', pk=grievance.application_id)

        elif action == 'resolve_board' and can_resolve_board:
            resolution = request.POST.get('final_resolution', '')
            notes = request.POST.get('final_resolution_notes', '').strip()

            if resolution == 'accept':
                grievance.status = GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION
                trx_status = SovereignTransaction.TransactionStatus.APPROVED
            elif resolution == 'modify':
                grievance.status = GrievanceAppeal.AppealStatus.DECISION_MODIFIED
                trx_status = SovereignTransaction.TransactionStatus.APPROVED
            elif resolution == 'return_review':
                grievance.status = GrievanceAppeal.AppealStatus.RETURNED_ADDITIONAL_REVIEW
                trx_status = SovereignTransaction.TransactionStatus.RETURNED_FOR_COMPLETION
            else:
                grievance.status = GrievanceAppeal.AppealStatus.REJECTED_DECISION_UPHELD
                trx_status = SovereignTransaction.TransactionStatus.REJECTED

            grievance.final_resolution_notes = notes
            grievance.resolved_by = request.user
            grievance.resolved_at = timezone.now()
            grievance.save()

            # Update Sovereign Transaction
            sov_trx = SovereignTransaction.objects.filter(reference_number=grievance.appeal_number).first()
            if sov_trx:
                sov_trx.transition_to(
                    trx_status,
                    request.user,
                    reason=f"صدور قرار البت في التظلم: {grievance.get_status_display()}"
                )

            record_audit_log(
                user=request.user,
                action='GRIEVANCE_RESOLVED',
                target_model='GrievanceAppeal',
                target_id=grievance.pk,
                details=f"صدور قرار البت في التظلم ({grievance.appeal_number}): {grievance.get_status_display()}",
                request=request
            )

            # Direct notification to Institution Officer & University President
            notify_institution(
                institution=grievance.application.institution,
                title=f"قرار البت في التظلم: {grievance.appeal_number}",
                message=(
                    f"أصدر مجلس الإدارة قراره النهائي حيال التظلم رقم ({grievance.appeal_number}): "
                    f"[{grievance.get_status_display()}]. ملاحظات القرار: {notes[:200]}"
                ),
                url=f"/accreditation/applications/{grievance.application_id}/"
            )

            if grievance.appellant_user:
                send_notification(
                    user=grievance.appellant_user,
                    title=f"قرار البت في التظلم: {grievance.appeal_number}",
                    message=f"أصدر مجلس الإدارة قراره النهائي حيال تظلمكم: [{grievance.get_status_display()}].",
                    url=f"/accreditation/applications/{grievance.application_id}/"
                )

            messages.success(request, f"تم بنجاح اعتماد قرار المجلس حيال التظلم ({grievance.get_status_display()}).")
            return redirect('accreditation:application_detail', pk=grievance.application_id)

    return render(request, 'accreditation/grievance_review.html', {
        'grievance': grievance,
        'app': grievance.application,
        'can_review_legal': can_review_legal,
        'can_resolve_board': can_resolve_board,
    })

@login_required
def grievances_list(request):
    """
    Central Legal Docket & Grievance Registry:
    Authorized for Legal Director, Secretariat Leadership, and Council Board Members.
    Institutions can view their own grievances.
    """
    is_staff_or_council = (
        request.user.role in [
            User.Roles.LEGAL_DIRECTOR,
            User.Roles.GRIEVANCE_COMMITTEE_MEMBER,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.BOARD_MEMBER,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_review_grievance_legal_terms')
        or request.user.is_superuser
    )

    if is_staff_or_council:
        grievances = GrievanceAppeal.objects.select_related(
            'application__institution', 'application__program', 'appellant_user'
        ).order_by('-submission_date')
    elif request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and request.user.institution_id:
        grievances = GrievanceAppeal.objects.filter(
            application__institution_id=request.user.institution_id
        ).select_related('application__institution', 'application__program', 'appellant_user').order_by('-submission_date')
    else:
        messages.error(request, "غير مصرح لك باستعراض سجل التظلمات والطعون القانونية.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status')
    if status_filter:
        grievances = grievances.filter(status=status_filter)

    total_count = grievances.count()
    submitted_count = grievances.filter(status=GrievanceAppeal.AppealStatus.SUBMITTED).count()
    under_review_count = grievances.filter(status=GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW).count()
    resolved_count = grievances.filter(status__in=[
        GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION,
        GrievanceAppeal.AppealStatus.REJECTED_DECISION_UPHELD
    ]).count()

    return render(request, 'accreditation/grievances_list.html', {
        'grievances': grievances,
        'total_count': total_count,
        'submitted_count': submitted_count,
        'under_review_count': under_review_count,
        'resolved_count': resolved_count,
        'statuses': GrievanceAppeal.AppealStatus.choices,
        'is_legal_or_board': is_staff_or_council,
        'current_status': status_filter or '',
    })

@login_required
def application_timeline(request, pk):
    """View full status transition history & audit trail for an application."""
    application = get_object_or_404(AccreditationApplication, pk=pk)
    
    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لهذا السجل.")
        return redirect('core_dashboard')

    history = application.status_history.select_related('changed_by').all().order_by('-created_at')
    return render(request, 'accreditation/timeline.html', {'app': application, 'history': history})


@login_required
def application_submit_draft(request, pk):
    """Allows institution officer to officially submit a draft application to CAQA."""
    application = get_object_or_404(AccreditationApplication, pk=pk)

    # Strict role check: Council Board & Secretariat are prohibited from submitting applications
    if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER]:
        return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية بتقديم مسودة طلب الاعتماد نيابة عن المؤسسة.")

    if request.user.role == User.Roles.EXTERNAL_REVIEWER:
        return HttpResponseForbidden("غير مصرح للمحكمين الخارجيين بتقديم طلب الاعتماد.")
    
    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بتقديم هذا الطلب.")
        return redirect('core_dashboard')

    is_owner_officer = (request.user.role == User.Roles.INSTITUTION_OFFICER and request.user.institution_id == application.institution_id)
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    if not (is_owner_officer or is_admin):
        return HttpResponseForbidden("تقديم الطلبات مخصص لممثل المؤسسة التعليمية المعتمد.")

    if application.status != ApplicationStatus.DRAFT:
        messages.info(request, "الطلب تم تقديمه مسبقاً ولا يزال قيد المعالجة.")
        return redirect('accreditation:application_detail', pk=application.pk)

    try:
        WorkflowEngine.execute_transition(
            application=application,
            target_status=ApplicationStatus.PENDING_REVIEW,
            user=request.user,
            reason="تقديم رسمي للمجلس للمراجعة وتحديد التكلفة",
            request=request
        )
        
        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        # 1. Notify authorized CAQA Secretariat and DG of Accreditation with direct link to Application Report
        staff_users = User.objects.filter(
            role__in=[
                User.Roles.DG_ACCREDITATION,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.ADMIN
            ],
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED
        )
        for st in staff_users:
            send_notification(
                user=st,
                title="إشعار + نسخة من تقرير طلب الاعتماد الجديد",
                message=f"قدمت مؤسسة ({application.institution.name}) طلب اعتماد جديد برقم ({application.application_number}) في مسار ({application.get_track_display()}). تم إرفاق نسخة من تقرير طلب الاعتماد في مكتبتكم، اضغط للانتقال مباشرة إلى تقرير الطلب ومراجعة توقيع رئيس الجامعة وتحديد التكلفة.",
                url=f"/accreditation/{application.pk}/report/"
            )

        # 2. Notify University President with direct link to Application Report
        presidents = User.objects.filter(
            role=User.Roles.UNIVERSITY_PRESIDENT,
            institution=application.institution,
            is_active=True
        )
        if not presidents.exists():
            presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
        for pres in presidents:
            send_notification(
                user=pres,
                title="إشعار + نسخة من تقرير طلب الاعتماد للتوقيع والاعتماد",
                message=f"تم رفع طلب اعتماد جديد برقم ({application.application_number}) لمؤسستكم ({application.institution.name}) مع نسخة في مكتبتكم. اضغط للانتقال مباشرة إلى تقرير طلب الاعتماد للتوقيع والاعتماد الرسمي.",
                url=f"/accreditation/{application.pk}/report/"
            )

        # 3. Notify submitting institution officers
        notify_institution(
            institution=application.institution,
            title="تم إرسال طلب الاعتماد ونسخة التقرير لرئيس الجامعة ومدير عام الاعتماد",
            message=f"تم بنجاح إرسال طلب الاعتماد رقم ({application.application_number}) لمؤسستكم ({application.institution.name})، وإرسال إشعار ونسخة من تقرير الطلب لرئيس الجامعة للتوقيع، ولمدير عام الاعتماد والتراخيص بالأمانة العامة لدراسة الطلب وتحديد التكلفة.",
            url=f"/accreditation/{application.pk}/report/",
            extra_recipients=application.applicant_user
        )

        messages.success(request, f"تم بنجاح إرسال طلب الاعتماد رقم ({application.application_number}) ونسخة التقرير إلى مدير عام الاعتماد ورئيس الجامعة للدراسة والمراجعة وتحديد التكلفة.")
    except ValidationError as e:
        messages.error(request, f"تعذر تقديم الطلب: {e.message}")

    return redirect('accreditation:application_detail', pk=application.pk)

@login_required
def university_president_endorse(request, pk):
    """
    Empowers the University President (رئيس الجامعة / المفوض القانوني)
    to formally review, endorse, and sign the accreditation application.
    """
    application = get_object_or_404(AccreditationApplication, pk=pk)

    can_endorse = (
        request.user.is_superuser or
        request.user.role == User.Roles.ADMIN or
        (
            request.user.role == User.Roles.UNIVERSITY_PRESIDENT and
            (not request.user.institution_id or request.user.institution_id == application.institution_id)
        )
    )
    if not can_endorse:
        if request.method == 'POST':
            return HttpResponseForbidden("غير مصرح لك: اعتماد وتفويض طلب الاعتماد مخصص حصراً لرئيس الجامعة أو المفوض القانوني.")
        messages.error(request, "غير مصرح لك: اعتماد وتفويض طلب الاعتماد مخصص لرئيس الجامعة أو المفوض القانوني.")
        return redirect('accreditation:application_detail', pk=pk)

    if request.method == 'POST':
        decree_ref = request.POST.get('president_decree_ref', '').strip()
        notes = request.POST.get('president_notes', '').strip()

        with transaction.atomic():
            application.president_endorsed = True
            application.president_endorsed_by = request.user
            application.president_endorsed_at = timezone.now()
            if decree_ref:
                application.president_decree_ref = decree_ref
            if notes:
                application.notes = (application.notes or '') + f"\n[توقيع واعتماد رئيس الجامعة {timezone.now().strftime('%Y-%m-%d')}]: {notes}"
            application.save()

            ApplicationStatusHistory.objects.create(
                application=application,
                from_stage=application.current_stage,
                to_stage=application.current_stage,
                from_status=application.status,
                to_status=ApplicationStatus.PRESIDENT_ENDORSED,
                changed_by=request.user,
                reason=f"توقيع ومصادقة رئيس الجامعة ({decree_ref or 'مباشر'})"
            )

            try:
                from apps.decisions.models import SovereignTransaction
                SovereignTransaction.record_lifecycle_movement(
                    transaction_type=SovereignTransaction.TransactionType.PRESIDENT_ENDORSEMENT,
                    subject=f"مصادقة وتوقيع رئيس الجامعة على طلب الاعتماد ({application.application_number})",
                    description=f"مصادقة رئيس جامعة ({application.institution.name}) على طلب الاعتماد رقم ({application.application_number}). مرجع القرار: {decree_ref or 'مباشر'}",
                    sender=request.user,
                    sending_authority=f"رئاسة {application.institution.name}",
                    receiving_authority="الإدارة العامة للاعتماد والتراخيص - الأمانة العامة",
                    status=SovereignTransaction.TransactionStatus.APPROVED,
                    action_reason=notes or "توقيع ومصادقة رئيس الجامعة الرسمية",
                    from_status=application.status,
                    application=application,
                    prefix='END',
                )
            except Exception:
                pass

            record_audit_log(
                user=request.user,
                action='APPLICATION_PRESIDENTIAL_ENDORSEMENT',
                target_model='AccreditationApplication',
                target_id=application.pk,
                details=f"توقيع واعتماد طلب الاعتماد الرسمي ({application.application_number}) من قِبل رئيس الجامعة ({request.user.get_full_name()}) بقرار تفويض ({decree_ref or 'مباشر'})",
                request=request
            )

            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()

            # Dispatch notification to DG of Accreditation and CAQA Secretariat
            dg_users = User.objects.filter(
                role__in=[
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED
            )
            for dg in dg_users:
                send_notification(
                    user=dg,
                    title="تم توقيع واعتماد تقرير طلب الاعتماد من رئيس الجامعة",
                    message=f"قام رئيس جامعة ({application.institution.name})، ({request.user.get_full_name()})، بتوقيع واعتماد تقرير طلب الاعتماد رقم ({application.application_number}) رسمياً (مرجع التفويض: {decree_ref or 'مباشر'}). الطلب مكتمل وجاهز للدراسة وتحديد التكلفة وطلب التقييم الذاتي.",
                    url=f"/accreditation/board-review/{application.pk}/"
                )

            # Also notify institution officers
            notify_institution(
                institution=application.institution,
                title="تم اعتماد وتوقيع طلب الاعتماد من رئيس الجامعة",
                message=f"قام رئيس الجامعة بتوقيع واعتماد طلب الاعتماد رقم ({application.application_number}) رسمياً. الطلب معروض الآن على مدير عام الاعتماد والتراخيص بالأمانة العامة للموافقة وتحديد التكلفة.",
                url=f"/accreditation/{application.pk}/",
                extra_recipients=application.applicant_user
            )

        messages.success(request, f"تم توقيع واعتماد طلب الاعتماد ({application.application_number}) رسمياً من قِبل رئيس الجامعة بنجاح.")
        return redirect('accreditation:application_detail', pk=pk)

    return redirect('accreditation:application_detail', pk=pk)


@login_required
def board_applications_list(request):
    """Central CAQA Dashboard page to list and manage all applications from institutions."""
    if not (request.user.is_council or request.user.is_board or request.user.is_staff):
        messages.error(request, "غير مصرح لك: إدارة ومراجعة طلبات الاعتماد مخصصة لمسؤولي وأعضاء المجلس.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status', '')
    track_filter = request.GET.get('track', '')
    search_q = request.GET.get('q', '').strip()

    applications = AccreditationApplication.objects.select_related(
        'institution', 'program', 'applicant_user', 'standard_version'
    ).all().order_by('-created_at')

    if status_filter:
        applications = applications.filter(status=status_filter)
    if track_filter:
        applications = applications.filter(track=track_filter)
    if search_q:
        applications = applications.filter(
            models.Q(application_number__icontains=search_q) |
            models.Q(institution__name__icontains=search_q) |
            models.Q(program__name__icontains=search_q)
        )

    pending_review_count = AccreditationApplication.objects.filter(status=ApplicationStatus.PENDING_REVIEW).count()
    accepted_pending_ssr_count = AccreditationApplication.objects.filter(status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION).count()
    rejected_count = AccreditationApplication.objects.filter(status=ApplicationStatus.REJECTED).count()

    context = {
        'applications': applications,
        'status_filter': status_filter,
        'track_filter': track_filter,
        'search_q': search_q,
        'pending_review_count': pending_review_count,
        'accepted_pending_ssr_count': accepted_pending_ssr_count,
        'rejected_count': rejected_count,
        'status_choices': ApplicationStatus.choices,
        'track_choices': AccreditationTrackType.choices,
    }
    return render(request, 'accreditation/board_applications_list.html', context)


@login_required
def board_application_review(request, pk):
    """Central CAQA Board Review Page: review application data, accept with fee or reject with mandatory reason."""
    can_review = (
        request.user.is_superuser or
        request.user.is_council or
        request.user.is_board or
        request.user.is_staff or
        request.user.role in [
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.BOARD_MEMBER,
            User.Roles.ADMIN
        ]
    )
    if not can_review:
        messages.error(request, "غير مصرح لك: مراجعة طلبات الاعتماد مخصصة لمدير عام الاعتماد والتراخيص ومسؤولي الأمانة والمجلس فقط.")
        return redirect('core_dashboard')

    application = get_object_or_404(
        AccreditationApplication.objects.select_related(
            'institution', 'program', 'applicant_user', 'standard_version', 'president_endorsed_by'
        ),
        pk=pk
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'accept_application':
            cost_str = request.POST.get('cost_amount', '').strip()
            currency = request.POST.get('cost_currency', 'YER').strip()
            cost_notes = request.POST.get('cost_breakdown_notes', '').strip()
            approval_notes = request.POST.get('council_approval_notes', '').strip()

            if not cost_str:
                messages.error(request, "يرجى إدخال تكلفة الاعتماد المعتمدة؛ لا يمكن قبول الطلب دون تحديد التكلفة المالية.")
                return redirect('accreditation:board_application_review', pk=application.pk)

            try:
                cost_val = float(cost_str)
                if cost_val <= 0:
                    messages.error(request, "يجب أن تكون التكلفة قيمة رقمية موجبة.")
                    return redirect('accreditation:board_application_review', pk=application.pk)
            except ValueError:
                messages.error(request, "يرجى إدخال مبلغ صحيح لتكلفة الاعتماد.")
                return redirect('accreditation:board_application_review', pk=application.pk)

            application.cost_amount = cost_val
            application.cost_currency = currency
            application.cost_breakdown_notes = cost_notes
            application.council_approval_notes = approval_notes
            application.reviewed_by = request.user
            application.reviewed_at = timezone.now()
            application.status = ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION
            application.save()

            # Create or update Invoice in operations module
            fee_schedule = FeeSchedule.objects.filter(track=application.track).first()
            if not fee_schedule:
                fee_schedule = FeeSchedule.objects.first()
            if not fee_schedule:
                fee_schedule = FeeSchedule.objects.create(
                    service_name=f"رسوم اعتماد {application.get_track_display()}",
                    track=application.track,
                    regulatory_reference="قرار مجلس الإدارة واللائحة المالية",
                    amount_yer=cost_val,
                    notes="لائحة رسوم الاعتماد المعتمدة"
                )
            inv, _ = Invoice.objects.get_or_create(
                application=application,
                defaults={
                    'invoice_number': f"INV-2026-{application.pk:04d}",
                    'fee_schedule': fee_schedule,
                    'total_amount': cost_val,
                    'status': Invoice.PaymentStatus.UNPAID
                }
            )
            inv.total_amount = cost_val
            inv.save()
            notify_invoice_issued(inv)

            ApplicationStatusHistory.objects.create(
                application=application,
                from_stage=StageChoices.STAGE_1,
                to_stage=StageChoices.STAGE_1,
                from_status=ApplicationStatus.PENDING_REVIEW,
                to_status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION,
                changed_by=request.user,
                reason=f"قبول الطلب وتحديد التكلفة بمبلغ ({cost_val:,.2f} {currency}) والمطالبة بالتقييم الذاتي"
            )

            record_audit_log(
                user=request.user,
                action='APPLICATION_ACCEPTED_WITH_COST',
                target_model='AccreditationApplication',
                target_id=application.pk,
                details=f"قبول طلب الاعتماد ({application.application_number}) وتحديد التكلفة بمبلغ ({cost_val:,.2f} {currency}) من قِبل ({request.user.get_full_name()})",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            # 1. Notify University President with direct link to the two action paths (Payment & Self-Study)
            presidents = User.objects.filter(
                role=User.Roles.UNIVERSITY_PRESIDENT,
                institution=application.institution,
                is_active=True
            )
            if not presidents.exists():
                presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
            for pres in presidents:
                send_notification(
                    user=pres,
                    title="الموافقة على طلب الاعتماد وتحديد التكلفة - قرار القبول المبدئي وفتح التقييم الذاتي",
                    message=(
                        f"تفيدكم أمانة المجلس بموافقة مدير عام الاعتماد والتراخيص مبدئياً على طلب الاعتماد رقم ({application.application_number}) "
                        f"لجامعتكم ({application.institution.name}) وتحديد التكلفة بمبلغ ({cost_val:,.2f} {currency}) وفتح التقييم الذاتي. "
                        f"اضغط للانتقال مباشرة إلى مساري العمل: (1) التسديد المالي للفاتورة رقم ({inv.invoice_number}) و (2) إعداد التقييم الذاتي."
                    ),
                    url=f"/accreditation/{application.pk}/#approved-paths"
                )

            # 2. Notify Institution Officer & applicant with direct link to the two action paths (Payment & Self-Study)
            notify_institution(
                institution=application.institution,
                title="الموافقة على طلب الاعتماد وتحديد التكلفة - قرار القبول المبدئي وفتح التقييم الذاتي",
                message=(
                    f"تمت الموافقة المبدئية من مدير عام الاعتماد والتراخيص على طلبكم رقم ({application.application_number}) "
                    f"وتحديد تكلفة الاعتماد بمبلغ ({cost_val:,.2f} {currency}). توجيهات المجلس: {approval_notes or 'استكمال الدراسة الذاتية وفق المعايير المعتمدة'}. "
                    f"اضغط للانتقال مباشرة إلى المسارين: (1) سداد الفاتورة (/operations/invoices/{inv.pk}/) و (2) إعداد التقييم الذاتي (/accreditation/{application.pk}/self-study/)."
                ),
                url=f"/accreditation/{application.pk}/#approved-paths",
                extra_recipients=application.applicant_user
            )

            messages.success(request, f"تم بنجاح قبول الطلب رقم ({application.application_number}) وتحديد التكلفة المالية بمبلغ ({cost_val:,.2f} {currency}) وإشعار رئيس الجامعة ومسؤول الجودة للانتقال مباشرة إلى مساري التسديد وإعداد التقييم الذاتي.")
            return redirect('accreditation:board_applications_list')

        elif action in ['reject_application', 'return_for_modification']:
            reason = request.POST.get('rejection_reason', '').strip()
            if not reason:
                messages.error(request, "إدخال سبب الرفض أو التعديل إلزامي؛ لا يمكن رفض أو إعادة طلب اعتماد دون توضيح الأسباب القانونية والفنية ومبررات التعديل.")
                return redirect('accreditation:board_application_review', pk=application.pk)

            application.rejection_reason = reason
            application.reviewed_by = request.user
            application.reviewed_at = timezone.now()
            application.status = ApplicationStatus.REJECTED
            application.save()

            ApplicationStatusHistory.objects.create(
                application=application,
                from_stage=StageChoices.STAGE_1,
                to_stage=StageChoices.STAGE_1,
                from_status=ApplicationStatus.PENDING_REVIEW,
                to_status=ApplicationStatus.REJECTED,
                changed_by=request.user,
                reason=f"رفض طلب الاعتماد وإعادته للتعديل: {reason}"
            )

            record_audit_log(
                user=request.user,
                action='APPLICATION_REJECTED',
                target_model='AccreditationApplication',
                target_id=application.pk,
                details=f"رفض طلب الاعتماد ({application.application_number}) وإعادته للتعديل. السبب: {reason}",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            # 1. Notify University President with direct link to the modification/resubmit report page
            presidents = User.objects.filter(
                role=User.Roles.UNIVERSITY_PRESIDENT,
                institution=application.institution,
                is_active=True
            )
            if not presidents.exists():
                presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
            for pres in presidents:
                send_notification(
                    user=pres,
                    title="إشعار بالتعديل وإعادة التقديم لتقرير طلب الاعتماد",
                    message=(
                        f"تفيدكم أمانة المجلس (مدير عام الاعتماد والتراخيص) بطلب تعديل / عدم قبول تقرير طلب الاعتماد رقم ({application.application_number}) "
                        f"لجامعتكم للأسباب التالية: ({reason}). اضغط للانتقال مباشرة إلى تقرير التعديل وتعديل الطلب وإعادة إرساله إلى مدير عام الاعتماد."
                    ),
                    url=f"/accreditation/{application.pk}/resubmit/"
                )

            # 2. Notify Institution Officer & applicant with direct link to the modification/resubmit report page
            notify_institution(
                institution=application.institution,
                title="إشعار بالتعديل وإعادة التقديم لتقرير طلب الاعتماد",
                message=(
                    f"بعد دراسة تقرير طلبكم رقم ({application.application_number}) من قِبل مدير عام الاعتماد والتراخيص، تقرر إعادته للتعديل للأسباب التالية: ({reason}). "
                    f"اضغط للانتقال مباشرة من هذا الإشعار إلى تقرير التعديل وتقرير الطلب وتعديله وإرساله مرة أخرى إلى مدير عام الاعتماد."
                ),
                url=f"/accreditation/{application.pk}/resubmit/",
                extra_recipients=application.applicant_user
            )

            messages.warning(request, f"تم إصدار تقرير التعديل / عدم القبول لطلب الاعتماد رقم ({application.application_number}) وإشعار رئيس الجامعة والمؤسسة للانتقال مباشرة إلى صفحة تعديل الطلب وإعادة التقديم.")
            return redirect('accreditation:board_applications_list')

    history = application.status_history.select_related('changed_by').all().order_by('-created_at')
    
    # Safe resolution of establishment decree or license number
    decree_or_license = ""
    if getattr(application, 'establishment_decree_number', None):
        decree_or_license = application.establishment_decree_number
    elif application.institution and application.institution.decree_number:
        decree_or_license = application.institution.decree_number
    else:
        decree_or_license = "غير مسجل"

    return render(request, 'accreditation/board_application_review.html', {
        'app': application,
        'history': history,
        'establishment_decree_or_license': decree_or_license,
    })


@login_required
def application_report(request, pk):
    """
    Renders the Official Accreditation Application Dossier / Report (تقرير طلب الاعتماد الرسمي)
    accessible to the University President, Institution Officers, DG of Accreditation, and Council Board.
    """
    application = get_object_or_404(
        AccreditationApplication.objects.select_related(
            'institution', 'program', 'applicant_user', 'standard_version', 'president_endorsed_by', 'reviewed_by'
        ),
        pk=pk
    )

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك باستعراض تقرير هذا الطلب.")
        return redirect('core_dashboard')

    decree_or_license = ""
    if getattr(application, 'establishment_decree_number', None):
        decree_or_license = application.establishment_decree_number
    elif application.institution and application.institution.decree_number:
        decree_or_license = application.institution.decree_number
    else:
        decree_or_license = "غير مسجل"

    history = application.status_history.select_related('changed_by').all().order_by('-created_at')
    latest_invoice = application.invoices.order_by('-issued_at').first()

    context = {
        'app': application,
        'establishment_decree_or_license': decree_or_license,
        'history': history,
        'latest_invoice': latest_invoice,
        'now': timezone.now(),
    }
    return render(request, 'accreditation/application_report.html', context)


@login_required
def application_resubmit(request, pk):
    """
    Allows the Institution Officer or University President to modify notes / documents
    and resubmit a rejected or returned application back to PENDING_REVIEW.
    """
    application = get_object_or_404(AccreditationApplication, pk=pk)

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بتعديل أو إعادة تقديم هذا الطلب.")
        return redirect('core_dashboard')

    is_inst_rep = (
        request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and
        (not request.user.institution_id or request.user.institution_id == application.institution_id)
    )
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    if not (is_inst_rep or is_admin):
        return HttpResponseForbidden("تعديل وإعادة تقديم الطلبات مخصص لممثلي المؤسسة التعليمية المعتمدين ورئيس الجامعة.")

    allowed_resubmit_statuses = [
        ApplicationStatus.REJECTED,
        getattr(ApplicationStatus, 'RETURNED_FOR_MODIFICATION', 'RETURNED_FOR_MODIFICATION'),
        ApplicationStatus.DESK_DEFICIENCY,
    ]
    if application.status not in allowed_resubmit_statuses and not is_admin:
        messages.warning(request, "هذا الطلب ليس بحالة معاد للتعديل أو مرفوض.")
        return redirect('accreditation:application_detail', pk=application.pk)

    if request.method == 'POST':
        notes = request.POST.get('notes', '').strip()
        license_file = request.FILES.get('initial_license_document')
        contact_name = request.POST.get('contact_person_name', '').strip()
        contact_phone = request.POST.get('contact_phone', '').strip()
        contact_email = request.POST.get('contact_email', '').strip()
        decree_num = request.POST.get('establishment_decree_number', '').strip()
        academic_year = request.POST.get('academic_year', '').strip()

        with transaction.atomic():
            prev_status = application.status
            if notes:
                application.notes = (application.notes or '') + f"\n[تعديل وإعادة إرسال {timezone.now().strftime('%Y-%m-%d')}]: {notes}"
            if contact_name:
                application.contact_person_name = contact_name
            if contact_phone:
                application.contact_phone = contact_phone
            if contact_email:
                application.contact_email = contact_email
            if decree_num and application.institution:
                application.institution.decree_number = decree_num
                application.institution.save(update_fields=['decree_number'])
            if academic_year:
                application.academic_year = academic_year
            if license_file:
                application.initial_license_document = license_file

            application.status = ApplicationStatus.PENDING_REVIEW
            application.submission_date = timezone.now()
            application.save()

            ApplicationStatusHistory.objects.create(
                application=application,
                from_stage=StageChoices.STAGE_1,
                to_stage=StageChoices.STAGE_1,
                from_status=prev_status,
                to_status=ApplicationStatus.PENDING_REVIEW,
                changed_by=request.user,
                reason=f"تعديل تقرير الطلب واستيفاء المطلوب وإعادة إرساله لمدير عام الاعتماد: {notes or 'تم التعديل'}"
            )

            record_audit_log(
                user=request.user,
                action='APPLICATION_RESUBMITTED_AFTER_REJECTION',
                target_model='AccreditationApplication',
                target_id=application.pk,
                details=f"تعديل وإعادة تقديم تقرير طلب الاعتماد ({application.application_number}) إلى مدير عام الاعتماد",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            # Notify DG of Accreditation & Secretariat with direct link to Application Report & Board Review
            dg_reviewers = User.objects.filter(
                role__in=[
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED
            )
            for dg in dg_reviewers:
                send_notification(
                    user=dg,
                    title="تم تعديل وإعادة إرسال تقرير طلب الاعتماد إليكم",
                    message=f"قامت مؤسسة ({application.institution.name}) بتعديل تقرير طلب الاعتماد رقم ({application.application_number}) وإعادة إرساله إليكم بعد استيفاء الملاحظات ({notes[:120]}). اضغط لمراجعة التقرير واتخاذ قرار القبول وتحديد التكلفة.",
                    url=f"/accreditation/board-review/{application.pk}/"
                )

            # Notify University President
            presidents = User.objects.filter(
                role=User.Roles.UNIVERSITY_PRESIDENT,
                institution=application.institution,
                is_active=True
            )
            if not presidents.exists():
                presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
            for pres in presidents:
                send_notification(
                    user=pres,
                    title="تم تعديل وإعادة إرسال تقرير طلب الاعتماد لمدير عام الاعتماد",
                    message=f"تم تعديل واستيفاء ملاحظات تقرير طلب الاعتماد رقم ({application.application_number}) وإعادة إرساله رسمياً إلى مدير عام الاعتماد والتراخيص.",
                    url=f"/accreditation/{application.pk}/report/"
                )

            messages.success(request, f"تم بنجاح تعديل تقرير طلب الاعتماد رقم ({application.application_number}) وإعادة إرساله مباشرة إلى مدير عام الاعتماد والتراخيص.")
            return redirect('accreditation:application_report', pk=application.pk)

    return render(request, 'accreditation/application_resubmit.html', {'app': application})


@login_required
def self_study_indicators_edit(request, pk):
    """Detailed Self-Study (SSR) entry form for each standard & indicator."""
    application = get_object_or_404(
        AccreditationApplication.objects.select_related('institution', 'program', 'standard_version'),
        pk=pk
    )

    # Council Board & Secretariat are strictly forbidden from entering scores or submitting SSR indicators
    if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER]:
        if request.method == 'POST':
            return HttpResponseForbidden("غير مصرح لأعضاء المجلس أو الأمانة الفنية برصد درجات أو تعديل أو تسليم التقييم الذاتي للمؤسسة.")
        messages.info(request, "تم توجيهك إلى العرض الرسمي لتقرير الدراسة الذاتية؛ استمارة المؤشرات مخصصة للمؤسسة فقط.")
        return redirect('accreditation:self_study_report_view', pk=application.pk)

    if request.user.role == User.Roles.EXTERNAL_REVIEWER:
        if request.method == 'POST':
            return HttpResponseForbidden("المحكمون الخارجيون غير مخولين بتعبئة التقييم الذاتي للمؤسسة.")
        return redirect('accreditation:self_study_report_view', pk=application.pk)

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لتقرير التقييم الذاتي لهذه المؤسسة.")
        return redirect('core_dashboard')

    is_owner_officer = (
        request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]
        and (not request.user.institution_id or request.user.institution_id == application.institution_id)
    )
    is_admin = request.user.is_superuser or request.user.role == User.Roles.ADMIN
    if not (is_owner_officer or is_admin):
        if request.method == 'POST':
            return HttpResponseForbidden("غير مصرح لك بتعبئة تقييم هذه المؤسسة.")
        messages.error(request, "غير مصرح لك بتعبئة تقييم هذه المؤسسة.")
        return redirect('accreditation:application_detail', pk=application.pk)

    if not application.can_start_self_study and not is_admin:
        if application.status == ApplicationStatus.REJECTED:
            messages.error(request, "لا يمكن تعبئة التقييم الذاتي لطلب تم رفضه من قبل المجلس.")
        else:
            messages.warning(request, "لا يمكن البدء في إعداد التقييم الذاتي قبل موافقة المجلس وقبول الطلب وتحديد التكلفة.")
        return redirect('accreditation:application_detail', pk=application.pk)

    ssr, _ = SelfStudyReport.objects.get_or_create(application=application)

    # Determine indicators by application track and standard version
    track_to_query = application.track
    categories = StandardCategory.objects.filter(track=track_to_query, is_active=True).prefetch_related('indicators').order_by('order')
    if not categories.exists() and application.track == AccreditationTrackType.MEDICAL_PROGRAMMATIC:
        categories = StandardCategory.objects.filter(track=AccreditationTrackType.PROGRAMMATIC, is_active=True).prefetch_related('indicators').order_by('order')

    all_indicators = []
    for cat in categories:
        for ind in cat.indicators.all().order_by('order'):
            all_indicators.append(ind)

    total_indicators_count = len(all_indicators)

    if request.method == 'POST':
        if ssr.is_locked and not is_admin:
            messages.error(request, "تقرير التقييم الذاتي مغلق رسمياً بعد الإرسال ولا يمكن تعديله.")
            return redirect('accreditation:self_study_report_view', pk=application.pk)

        # Process each indicator response
        for ind in all_indicators:
            compliance = request.POST.get(f"compliance_{ind.id}")
            justification = request.POST.get(f"justification_{ind.id}", '').strip()
            strengths = request.POST.get(f"strengths_{ind.id}", '').strip()
            gaps = request.POST.get(f"gaps_{ind.id}", '').strip()
            corrective = request.POST.get(f"corrective_{ind.id}", '').strip()
            responsible = request.POST.get(f"responsible_{ind.id}", '').strip()
            target_date = request.POST.get(f"target_date_{ind.id}") or None

            if compliance:
                SelfStudyIndicatorResponse.objects.update_or_create(
                    report=ssr,
                    indicator=ind,
                    defaults={
                        'compliance_level': compliance,
                        'justification': justification,
                        'strengths': strengths,
                        'gaps_and_weaknesses': gaps,
                        'corrective_actions': corrective,
                        'responsible_party': responsible,
                        'target_completion_date': target_date,
                    }
                )

        # Update overall SSR general fields
        ssr.executive_summary = request.POST.get('executive_summary', ssr.executive_summary)
        ssr.internal_committee_names = request.POST.get('internal_committee_names', ssr.internal_committee_names)
        ssr.methodology = request.POST.get('methodology', ssr.methodology)
        ssr.strengths_overview = request.POST.get('strengths_overview', ssr.strengths_overview)
        ssr.weaknesses_and_challenges = request.POST.get('weaknesses_and_challenges', ssr.weaknesses_and_challenges)
        ssr.save()

        if 'submit_self_study_official' in request.POST:
            # Check completeness
            answered_count = SelfStudyIndicatorResponse.objects.filter(report=ssr).count()
            if answered_count < total_indicators_count and total_indicators_count > 0:
                messages.warning(request, f"تنبيه: لقد قمت بتقييم ({answered_count}) من أصل ({total_indicators_count}) مؤشراً. يجب استكمال جميع المؤشرات قبل التسليم النهائي.")
                return redirect('accreditation:self_study_indicators_edit', pk=application.pk)

            ssr.is_locked = True
            ssr.save()

            is_external_mod = application.status in [
                ApplicationStatus.DRAFT_REPORT_ISSUED,
                ApplicationStatus.WAITING_INSTITUTION_RESPONSE,
                ApplicationStatus.RESPONSE_SUBMITTED,
                ApplicationStatus.SITE_VISIT_COMPLETED,
            ]
            if is_external_mod:
                try:
                    from apps.accounts.models import UserDocument
                    mod_title = f"تقرير دراسة التقييم الذاتي (النسخة المعدلة بعد ملاحظات المقيم الخارجي) - {application.institution.name} [{application.application_number}]"
                    UserDocument.objects.update_or_create(
                        application=application,
                        doc_type=UserDocument.DocumentType.SELF_STUDY,
                        title=mod_title,
                        defaults={
                            'owner': request.user,
                            'description': f"النسخة المعدلة لتقرير التقييم الذاتي والمؤشرات استجابةً لملاحظات المقيم الخارجي ({application.application_number})",
                            'system_source_url': f"/accreditation/{application.pk}/self-study/report/",
                        }
                    )
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                from apps.site_visits.services import get_panel_reviewers
                for rev in get_panel_reviewers(application):
                    send_notification(
                        user=rev,
                        title=f"تم تعديل وإرسال التقييم الذاتي بناءً على ملاحظاتكم: {application.application_number}",
                        message=f"قامت مؤسسة ({application.institution.name}) بتعديل تقرير التقييم الذاتي للطلب ({application.application_number}) استجابةً لملاحظاتكم. اضغط لفتح تقرير التقييم الذاتي المعدل.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                for st in User.objects.filter(role__in=[User.Roles.DG_EVALUATION, User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY_GENERAL], is_active=True):
                    send_notification(
                        user=st,
                        title=f"تم إرسال التقييم الذاتي المعدل بعد ملاحظات المقيم الخارجي: {application.application_number}",
                        message=f"أرسلت مؤسسة ({application.institution.name}) النسخة المعدلة من تقرير التقييم الذاتي للطلب ({application.application_number}) وتم حفظها في مكتبتكم بجانب النسخة الأصلية.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                messages.success(request, "تم بنجاح حفظ وإرسال النسخة المعدلة من تقرير التقييم الذاتي للمقيم الخارجي ومدير عام التقييم والمراجعة الخارجية.")
                return redirect('accreditation:self_study_report_view', pk=application.pk)

            if application.status != ApplicationStatus.SELF_EVALUATION_SUBMITTED:
                application.status = ApplicationStatus.SELF_EVALUATION_SUBMITTED
                application.current_stage = StageChoices.STAGE_2
                application.save()

                ApplicationStatusHistory.objects.create(
                    application=application,
                    from_stage=StageChoices.STAGE_1,
                    to_stage=StageChoices.STAGE_2,
                    from_status=ApplicationStatus.SELF_EVALUATION_IN_PROGRESS,
                    to_status=ApplicationStatus.SELF_EVALUATION_SUBMITTED,
                    changed_by=request.user,
                    reason="تسليم التقييم الذاتي المكتمل رسمياً للمجلس وبدء الفحص المكتبي"
                )

                record_audit_log(
                    user=request.user,
                    action='SELF_EVALUATION_SUBMITTED',
                    target_model='SelfStudyReport',
                    target_id=ssr.pk,
                    details=f"تسليم تقرير الدراسة والتقييم الذاتي للطلب ({application.application_number})",
                    request=request
                )

                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                # Notify CAQA Council Staff & DG of Accreditation
                staff_users = User.objects.filter(
                    role__in=[
                        User.Roles.COUNCIL_SECRETARY,
                        User.Roles.COUNCIL_SECRETARY_GENERAL,
                        User.Roles.DG_ACCREDITATION,
                        User.Roles.DG_EVALUATION,
                        User.Roles.ADMIN,
                    ],
                    is_active=True,
                )
                for st in staff_users:
                    send_notification(
                        user=st,
                        title="تم استلام تقرير التقييم الذاتي",
                        message=f"تم إرسال تقرير التقييم الذاتي من مؤسسة ({application.institution.name}) لطلب ({application.application_number}). اضغط للانتقال مباشرة وفتح تقرير التقييم الذاتي للبدء بالفحص المكتبي.",
                        url=f"/accreditation/{application.pk}/self-study/report/"
                    )
                    if st.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.DG_ACCREDITATION, User.Roles.COUNCIL_SECRETARY_GENERAL]:
                        send_notification(
                            user=st,
                            title=f"تم إرسال التقييم الذاتي من المؤسسة والشواهد لإجراء الفحص المكتبي: {application.application_number}",
                            message=f"قامت مؤسسة ({application.institution.name}) بإرسال تقرير التقييم الذاتي والشواهد المرفقة للطلب ({application.application_number}). اضغط للانتقال مباشرة لإجراء الفحص المكتبي الشكلي والموضوعي (DeskReviewEvaluation).",
                            url=f"/accreditation/{application.pk}/desk-review/"
                        )

                try:
                    from apps.decisions.models import SovereignTransaction
                    SovereignTransaction.record_lifecycle_movement(
                        transaction_type=SovereignTransaction.TransactionType.SELF_STUDY_SUBMISSION,
                        subject=f"تسليم تقرير التقييم الذاتي والشواهد ({application.application_number})",
                        description=f"تسليم تقرير التقييم الذاتي المكتمل لطلب ({application.application_number}) من مؤسسة ({application.institution.name}).",
                        sender=request.user,
                        sending_authority=application.institution.name,
                        receiving_authority="الإدارة العامة للاعتماد والتراخيص - الأمانة الفنية",
                        status=SovereignTransaction.TransactionStatus.SUBMITTED,
                        action_reason="تسليم رسمي لتقرير الدراسة الذاتية وبنك الشواهد",
                        from_status=ApplicationStatus.SELF_EVALUATION_IN_PROGRESS,
                        application=application,
                        prefix='SSR',
                    )
                except Exception:
                    pass

            messages.success(request, "تم بنجاح إرسال تقرير التقييم الذاتي رسمياً إلى مجلس الاعتماد الأكاديمي، وتم قفل التعديل وبدء مرحلة الفحص المكتبي.")
            return redirect('accreditation:self_study_report_view', pk=application.pk)

        else:
            # Save Draft
            if application.status == ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION:
                application.status = ApplicationStatus.SELF_EVALUATION_IN_PROGRESS
                application.save()

            messages.success(request, "تم حفظ مسودة بيانات التقييم الذاتي بنجاح. يمكنك استكمال بقية المؤشرات في أي وقت.")
            return redirect('accreditation:self_study_indicators_edit', pk=application.pk)

    # Load existing responses
    existing_responses = {
        r.indicator_id: r for r in SelfStudyIndicatorResponse.objects.filter(report=ssr)
    }
    completed_count = len(existing_responses)
    progress_percentage = int((completed_count / total_indicators_count * 100)) if total_indicators_count > 0 else 100

    context = {
        'app': application,
        'ssr': ssr,
        'categories': categories,
        'all_indicators': all_indicators,
        'existing_responses': existing_responses,
        'completed_count': completed_count,
        'total_indicators_count': total_indicators_count,
        'progress_percentage': progress_percentage,
        'compliance_choices': SelfStudyIndicatorResponse.ComplianceLevel.choices,
    }
    return render(request, 'accreditation/self_study_indicators_form.html', context)


@login_required
def self_study_report_view(request, pk):
    """Formatted, comprehensive Self-Study Report (SSR) View."""
    application = get_object_or_404(
        AccreditationApplication.objects.select_related('institution', 'program', 'standard_version'),
        pk=pk
    )

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك باستعراض هذا التقرير.")
        return redirect('core_dashboard')

    if not _verify_reviewer_access(request, application):
        messages.error(request, "غير مصرح لك: لست عضواً مكلفاً بتحكيم هذا الطلب.")
        return redirect('core_dashboard')

    if not _verify_reviewer_coi_clean(request, application):
        messages.error(request, "يجب توقيع إقرار الحيادية وخلو تضارب المصالح أولاً قبل الاطلاع على تقرير الدراسة الذاتية والشواهد.")
        return redirect('accreditation:coi_declare', pk=application.pk)

    ssr = get_object_or_404(SelfStudyReport, application=application)

    if request.user.role == User.Roles.EXTERNAL_REVIEWER:
        record_audit_log(
            user=request.user,
            action='SSR_DOSSIER_ACCESSED',
            target_model='SelfStudyReport',
            target_id=ssr.pk,
            details=f"اطلاع المحكم الخارجي على تقرير الدراسة الذاتية للطلب ({application.application_number})",
            request=request
        )

    categories = StandardCategory.objects.filter(track=application.track, is_active=True).prefetch_related('indicators').order_by('order')
    if not categories.exists() and application.track == AccreditationTrackType.MEDICAL_PROGRAMMATIC:
        categories = StandardCategory.objects.filter(track=AccreditationTrackType.PROGRAMMATIC, is_active=True).prefetch_related('indicators').order_by('order')

    responses = {
        r.indicator_id: r for r in SelfStudyIndicatorResponse.objects.filter(report=ssr).select_related('indicator')
    }

    evidences_by_indicator = {}
    for ev in application.evidences.select_related('indicator').all():
        evidences_by_indicator.setdefault(ev.indicator_id, []).append(ev)

    context = {
        'app': application,
        'ssr': ssr,
        'categories': categories,
        'responses': responses,
        'evidences_by_indicator': evidences_by_indicator,
    }
    return render(request, 'accreditation/self_study_report_view.html', context)


# Numerical scale mapping for valid mathematical comparisons
COMPLIANCE_SCORE_MAP = {
    'MET': 3.0,
    'PARTIALLY_MET': 1.5,
    'NOT_MET': 0.0,
    'INSUFFICIENT_EVIDENCE': 0.0,
}

RUBRIC_SCORE_MAP = {
    'FULLY_MET': 3.0,
    'SUBSTANTIALLY_MET': 2.0,
    'PARTIALLY_MET': 1.0,
    'NOT_MET': 0.0,
}

@login_required
def secretariat_comparison_dashboard(request, pk):
    """
    Compares Institution Self-Assessment vs. External Review Team Assessment side-by-side.
    Accessible to Secretariat (COUNCIL_SECRETARY), Board Members, and Admins.
    """
    application = get_object_or_404(
        AccreditationApplication.objects.select_related('institution', 'program', 'standard_version'),
        pk=pk
    )

    if not (request.user.is_council or request.user.is_board or request.user.is_staff):
        messages.error(request, "غير مصرح لك: مقارنة التقييم الذاتي بالمراجعة الخارجية مخصصة للأمانة الفنية وأعضاء المجلس.")
        return redirect('core_dashboard')

    ssr = getattr(application, 'self_study_report', None)
    categories = StandardCategory.objects.filter(track=application.track, is_active=True).prefetch_related('indicators').order_by('order')
    if not categories.exists() and application.track == AccreditationTrackType.MEDICAL_PROGRAMMATIC:
        categories = StandardCategory.objects.filter(track=AccreditationTrackType.PROGRAMMATIC, is_active=True).prefetch_related('indicators').order_by('order')

    ssr_responses = {}
    if ssr:
        ssr_responses = {
            r.indicator_id: r for r in SelfStudyIndicatorResponse.objects.filter(report=ssr).select_related('indicator')
        }

    # External evaluation scores: average score per indicator if multiple evaluators
    raw_external_scores = IndicatorEvaluationScore.objects.filter(application=application).select_related('indicator', 'evaluator')
    external_by_indicator = {}
    for s in raw_external_scores:
        external_by_indicator.setdefault(s.indicator_id, []).append(s)

    # Evidences per indicator and all application evidences
    all_evidences = application.evidences.select_related('indicator').all()
    evidences_by_indicator = {}
    for ev in all_evidences:
        evidences_by_indicator.setdefault(ev.indicator_id, []).append(ev)

    # Build comparison matrix per standard and per indicator
    comparison_table = []
    category_summary = []
    chart_categories = []
    chart_ssr_averages = []
    chart_ext_averages = []

    for cat in categories:
        cat_ssr_scores = []
        cat_ext_scores = []

        cat_indicators_rows = []
        for ind in cat.indicators.all():
            ssr_resp = ssr_responses.get(ind.id)
            ext_list = external_by_indicator.get(ind.id, [])
            ind_evidences = evidences_by_indicator.get(ind.id, [])

            ssr_score_val = None
            ssr_level_display = "لم يُقيّم"
            if ssr_resp:
                ssr_level_display = ssr_resp.get_compliance_level_display()
                ssr_score_val = COMPLIANCE_SCORE_MAP.get(ssr_resp.compliance_level)
                if ssr_score_val is not None:
                    cat_ssr_scores.append(ssr_score_val)

            ext_score_val = None
            ext_level_display = "لم يُقيّم"
            ext_notes = ""
            if ext_list:
                # Calculate numeric mean
                num_scores = [RUBRIC_SCORE_MAP.get(e.score_level, 0.0) for e in ext_list]
                ext_score_val = round(sum(num_scores) / len(num_scores), 2)
                cat_ext_scores.append(ext_score_val)
                ext_level_display = ext_list[0].get_score_level_display() if len(ext_list) == 1 else f"{ext_score_val:.2f} (متوسط {len(ext_list)} مقيمين)"
                ext_notes = "; ".join([e.strengths or e.weaknesses for e in ext_list if e.strengths or e.weaknesses])

            diff_val = None
            diff_label = "غير متاح"
            if ssr_score_val is not None and ext_score_val is not None:
                diff_val = round(ssr_score_val - ext_score_val, 2)
                diff_label = f"{diff_val:+0.2f}"

            cat_indicators_rows.append({
                'indicator': ind,
                'ssr_response': ssr_resp,
                'ssr_display': ssr_level_display,
                'ssr_numeric': ssr_score_val,
                'external_scores': ext_list,
                'external_display': ext_level_display,
                'external_numeric': ext_score_val,
                'diff_val': diff_val,
                'diff_label': diff_label,
                'ext_notes': ext_notes,
                'evidences': ind_evidences,
            })

        avg_ssr = round(sum(cat_ssr_scores) / len(cat_ssr_scores), 2) if cat_ssr_scores else None
        avg_ext = round(sum(cat_ext_scores) / len(cat_ext_scores), 2) if cat_ext_scores else None

        category_summary.append({
            'category': cat,
            'indicators_count': cat.indicators.count(),
            'avg_ssr': avg_ssr,
            'avg_ext': avg_ext,
            'avg_diff': round(avg_ssr - avg_ext, 2) if (avg_ssr is not None and avg_ext is not None) else None,
            'indicators_rows': cat_indicators_rows,
        })

        chart_categories.append(f"{cat.code}: {cat.title[:20]}...")
        chart_ssr_averages.append(avg_ssr if avg_ssr is not None else 0.0)
        chart_ext_averages.append(avg_ext if avg_ext is not None else 0.0)

    from apps.accreditation.ai_analyzer import AIQualityAnalyzer
    ai_analysis = AIQualityAnalyzer.analyze_application(application)

    # Save comparison report and send to Council if requested by POST
    if request.method == 'POST' and ('save_comparison_report' in request.POST or 'send_to_council' in request.POST or 'ai_generate_draft' in request.POST):
        is_ai_draft = 'ai_generate_draft' in request.POST
        title = request.POST.get('comparison_title', '').strip() or (
            ai_analysis['draft_comparison_title'] if is_ai_draft else f"تقرير مطابقة ومقارنة التقييم الذاتي والخارجي مع الشواهد - {application.application_number}"
        )
        notes = request.POST.get('secretariat_analytical_summary', '').strip() or ai_analysis['draft_analytical_summary']

        comp_report = SecretariatAssessmentComparisonReport.objects.create(
            application=application,
            generated_by=request.user,
            title=title,
            secretariat_analytical_summary=notes,
            comparison_data_json={
                'ai_readiness_score': ai_analysis['readiness_score'],
                'ai_alignment_index': ai_analysis['alignment_index'],
                'ai_recommendation_code': ai_analysis['ai_recommendation_code'],
                'ai_recommendation_label': ai_analysis['ai_recommendation_label'],
                'ai_detected_gaps_count': ai_analysis['total_gaps_count'],
                'chart_categories': chart_categories,
                'chart_ssr_averages': chart_ssr_averages,
                'chart_ext_averages': chart_ext_averages,
                'total_categories': len(category_summary),
                'total_evidences_count': all_evidences.count(),
                'evidences_summary': [
                    {
                        'code': ev.code,
                        'title': ev.title,
                        'indicator_code': ev.indicator.code if ev.indicator else 'عام',
                        'file_url': ev.document_file.url if ev.document_file else '',
                    }
                    for ev in all_evidences
                ],
                'category_summary': [
                    {
                        'category_code': cs['category'].code,
                        'category_name': cs['category'].title,
                        'indicators_count': cs['indicators_count'],
                        'avg_ssr': cs['avg_ssr'],
                        'avg_ext': cs['avg_ext'],
                        'avg_diff': cs['avg_diff'],
                        'indicators': [
                            {
                                'code': ir['indicator'].code,
                                'title': ir['indicator'].title,
                                'ssr_display': ir['ssr_display'],
                                'ssr_numeric': ir['ssr_numeric'],
                                'ext_display': ir['external_display'],
                                'ext_numeric': ir['external_numeric'],
                                'diff_label': ir['diff_label'],
                                'ext_notes': ir['ext_notes'],
                                'evidences': [
                                    {'code': ev.code, 'title': ev.title}
                                    for ev in ir['evidences']
                                ],
                            }
                            for ir in cs['indicators_rows']
                        ]
                    }
                    for cs in category_summary
                ]
            },
            attached_to_council_briefing=not is_ai_draft
        )

        if is_ai_draft:
            record_audit_log(
                user=request.user,
                action='AI_COMPARISON_DRAFT_GENERATED',
                target_model='SecretariatAssessmentComparisonReport',
                target_id=comp_report.pk,
                details=f"توليد مسودة تقرير المقارنة التحليلي بالمساعد الذكي (AI Quality Analyzer) للطلب ({application.application_number}) بمؤشر جاهزية ({ai_analysis['readiness_score']}%)",
                request=request
            )
            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass
            messages.success(
                request,
                f"تم توليد مسودة تقرير المقارنة التحليلي واكتشاف ({ai_analysis['total_gaps_count']}) فجوة بواسطة المساعد الذكي (مؤشر الجاهزية: {ai_analysis['readiness_score']}%) وحفظها في مكتبتي. يمكنك الآن مراجعتها وإحالتها إلى مجلس الإدارة."
            )
            return redirect('accreditation:secretariat_comparison_dashboard', pk=application.pk)

        # Transition application to IN_COUNCIL_REVIEW when comparison report is saved & sent to Council
        if application.status == ApplicationStatus.FINAL_REPORT_READY:
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.IN_COUNCIL_REVIEW,
                    user=request.user,
                    reason=f"إعداد واعتماد تقرير المقارنة التحليلية مع الشواهد وإحالته لمجلس الإدارة: {title}",
                    request=request
                )
            except ValidationError:
                application.status = ApplicationStatus.IN_COUNCIL_REVIEW
                application.current_stage = StageChoices.STAGE_6
                application.save(update_fields=['status', 'current_stage'])

        record_audit_log(
            user=request.user,
            action='ASSESSMENT_COMPARISON_SAVED',
            target_model='SecretariatAssessmentComparisonReport',
            target_id=comp_report.pk,
            details=f"حفظ وإرسال تقرير مقارنة التقييم الذاتي بالمراجعة الخارجية مع الشواهد ({all_evidences.count()} شاهد) إلى مجلس الإدارة للطلب ({application.application_number})",
            request=request
        )

        # Dispatch notification to Council Board members, Chairman, Vice Chairman, and Secretariat
        board_users = User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.DG_ACCREDITATION,
                User.Roles.ADMIN,
            ],
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED
        )
        for b_user in board_users:
            send_notification(
                user=b_user,
                title=f"إحالة تقرير المقارنة التحليلي (التقييم الذاتي والخارجي مع الشواهد) إلى المجلس: {application.application_number}",
                message=(
                    f"تم إعداد واعتماد تقرير المقارنة التحليلية بين التقييم الذاتي "
                    f"والتقييم الخارجي مرفقاً بالشواهد ({all_evidences.count()} وثيقة شاهد) لطلب مؤسسة ({application.institution.name}) "
                    f"رقم ({application.application_number}) وإرساله رسمياً إلى مجلس الإدارة للعرض والتصويت واتخاذ القرار."
                ),
                url=f"/accreditation/{application.pk}/comparison-dashboard/"
            )
            send_notification(
                user=b_user,
                title=f"إحالة ملف الاعتماد المتكامل (17 قسماً) وتقرير المقارنة التحليلي لرئيس وأعضاء مجلس الإدارة: {application.application_number}",
                message=(
                    f"أحال الأمين العام للمجلس تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) (IN_COUNCIL_REVIEW) "
                    f"لطلب مؤسسة ({application.institution.name}) رقم ({application.application_number}) إلى رئيس وأعضاء مجلس الإدارة "
                    f"للدراسة والتداول والتصويت. اضغط لفتح ملف الاعتماد المتكامل (17 قسماً)."
                ),
                url=f"/accreditation/{application.pk}/dossier-17/"
            )

        try:
            from apps.decisions.models import SovereignTransaction
            SovereignTransaction.record_lifecycle_movement(
                transaction_type=SovereignTransaction.TransactionType.COMMITTEE_REPORT,
                subject=f"إحالة تقرير المقارنة التحليلي وملف الاعتماد المتكامل (17 قسماً) للمجلس ({application.application_number})",
                description=f"اعتماد وإحالة تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) لطلب ({application.application_number}) إلى رئيس وأعضاء مجلس الإدارة.",
                sender=request.user,
                sending_authority="الأمانة العامة للمجلس - الإدارة العامة للتقييم والمراجعة الخارجية",
                receiving_authority="رئيس وأعضاء مجلس إدارة مجلس الاعتماد الأكاديمي",
                status=SovereignTransaction.TransactionStatus.SUBMITTED,
                action_reason=notes or title,
                from_status=ApplicationStatus.FINAL_REPORT_READY,
                application=application,
                prefix='DOS17',
            )
        except Exception:
            pass

        # Also notify institution that their comparison report has been compiled and referred
        notify_institution(
            institution=application.institution,
            title="اكتمال إعداد التقرير المقارن مع الشواهد وإحالته لمجلس الإدارة",
            message=(
                f"أنهت الأمانة العامة والإدارة العامة للتقييم والمراجعة الخارجية إعداد التقرير المقارن التحليلي الشامل وملف الاعتماد المتكامل (17 قسماً) لطلبكم "
                f"({application.application_number}) وأحالته رسمياً إلى رئيس وأعضاء مجلس الإدارة للعرض والبت النهائي."
            ),
            url=f"/accreditation/{application.pk}/",
            extra_recipients=application.applicant_user
        )

        # Synchronize generated comparison report, 17-section dossier, and evidences into My Library (مكتبتي)
        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        messages.success(request, "تم بنجاح اعتماد وحفظ تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) وإرسالهما رسمياً إلى رئيس وأعضاء مجلس الإدارة وحفظهما في المكتبة.")
        return redirect('accreditation:secretariat_comparison_dashboard', pk=application.pk)

    saved_reports = application.comparison_reports.select_related('generated_by').all().order_by('-created_at')
    from apps.accounts.models import UserDocument
    library_ssr_docs = UserDocument.objects.filter(application=application, doc_type=UserDocument.DocumentType.SELF_STUDY).order_by('created_at')
    library_ext_docs = UserDocument.objects.filter(application=application, doc_type=UserDocument.DocumentType.EXTERNAL_REPORT).order_by('-created_at')

    context = {
        'app': application,
        'ai_analysis': ai_analysis,
        'category_summary': category_summary,
        'chart_categories_json': chart_categories,
        'chart_ssr_averages_json': chart_ssr_averages,
        'chart_ext_averages_json': chart_ext_averages,
        'saved_reports': saved_reports,
        'all_evidences': all_evidences,
        'library_ssr_docs': library_ssr_docs,
        'library_ext_docs': library_ext_docs,
    }
    return render(request, 'accreditation/secretariat_comparison_dashboard.html', context)


@login_required
def secretariat_comparison_export(request, pk):
    """Print / PDF export friendly view of the comparison report."""
    application = get_object_or_404(AccreditationApplication.objects.select_related('institution', 'program'), pk=pk)

    if not (request.user.is_council or request.user.is_board or request.user.is_staff):
        messages.error(request, "غير مصرح لك باستعراض وثيقة المقارنة الرسمية.")
        return redirect('core_dashboard')

    latest_report = application.comparison_reports.order_by('-created_at').first()
    return render(request, 'accreditation/secretariat_comparison_export.html', {
        'app': application,
        'report': latest_report,
    })


@login_required
def application_dossier_17_view(request, pk):
    """
    Renders and manages the Integrated 17-Section Accreditation Dossier (ملف الاعتماد المتكامل - 17 قسماً)
    alongside the Analytical Comparison Report (تقرير المقارنة التحليلي).
    Allows the Secretary General (COUNCIL_SECRETARY_GENERAL) to endorse and refer the 17-section dossier
    + comparison report (IN_COUNCIL_REVIEW) directly to the Council Chairman and Board Members.
    """
    application = get_object_or_404(
        AccreditationApplication.objects.select_related(
            'institution', 'program', 'standard_version', 'applicant_user', 'reviewed_by', 'president_endorsed_by'
        ),
        pk=pk
    )

    if not (request.user.is_council or request.user.is_board or request.user.is_staff or request.user.is_minister or request.user.is_prime_minister):
        messages.error(request, "غير مصرح لك بالاطلاع على ملف الاعتماد المتكامل (17 قسماً) المعروض على مجلس الإدارة.")
        return redirect('core_dashboard')

    from apps.decisions.models import AccreditationDecision, CouncilMeeting, CouncilAgendaItem, SovereignTransaction

    if request.method == 'POST' and ('refer_dossier_17_to_council' in request.POST or 'send_to_council' in request.POST):
        summary_notes = request.POST.get(
            'secretariat_analytical_summary',
            f"إحالة رسمية من الأمين العام للمجلس لتقرير المقارنة التحليلي وملف الاعتماد المتكامل (17 قسماً) للطلب ({application.application_number}) إلى رئيس وأعضاء مجلس الإدارة."
        ).strip()
        comp_title = request.POST.get(
            'comparison_title',
            f"تقرير المقارنة التحليلي المعتمد وملف الاعتماد المتكامل (17 قسماً) - {application.application_number}"
        ).strip()

        comp_report = application.comparison_reports.order_by('-created_at').first()
        if not comp_report:
            comp_report = SecretariatAssessmentComparisonReport.objects.create(
                application=application,
                generated_by=request.user,
                title=comp_title,
                secretariat_analytical_summary=summary_notes,
                comparison_data_json={'total_evidences_count': application.evidences.count()},
                attached_to_council_briefing=True,
            )
        else:
            if summary_notes:
                comp_report.secretariat_analytical_summary = summary_notes
            comp_report.attached_to_council_briefing = True
            comp_report.save()

        if application.status != ApplicationStatus.IN_COUNCIL_REVIEW:
            try:
                WorkflowEngine.execute_transition(
                    application=application,
                    target_status=ApplicationStatus.IN_COUNCIL_REVIEW,
                    user=request.user,
                    reason=f"إحالة الأمين العام للمجلس لتقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) إلى رئيس وأعضاء مجلس الإدارة",
                    request=request
                )
            except ValidationError:
                application.status = ApplicationStatus.IN_COUNCIL_REVIEW
                application.current_stage = StageChoices.STAGE_6
                application.save(update_fields=['status', 'current_stage'])

        # Optional: Link to a Council Meeting agenda item if meeting_id is provided
        meeting_id = request.POST.get('meeting_id')
        if meeting_id:
            meeting = CouncilMeeting.objects.filter(pk=meeting_id).first()
            if meeting and not CouncilAgendaItem.objects.filter(meeting=meeting, application=application).exists():
                pos = meeting.agenda_items.count() + 1
                CouncilAgendaItem.objects.create(
                    meeting=meeting,
                    position=pos,
                    item_number=f"بند ({pos})",
                    title=f"النظر في ملف الاعتماد المتكامل (17 قسماً): {application.institution.name} ({application.application_number})",
                    item_category=(
                        CouncilAgendaItem.ItemCategory.INSTITUTIONAL_ACCREDITATION
                        if application.track == AccreditationTrackType.INSTITUTIONAL
                        else CouncilAgendaItem.ItemCategory.PROGRAM_ACCREDITATION
                    ),
                    referring_entity="الأمين العام للمجلس",
                    presenter_name=request.user.get_full_name() or request.user.username,
                    presenter_user=request.user,
                    description=summary_notes,
                    initial_recommendation=getattr(getattr(application, 'external_report', None), 'get_final_recommendation_display', lambda: 'للدراسة والتصويت')(),
                    required_action=CouncilAgendaItem.RequiredAction.APPROVAL,
                    application=application,
                )

        record_audit_log(
            user=request.user,
            action='DOSSIER_17_REFERRED_TO_COUNCIL_BOARD',
            target_model='AccreditationApplication',
            target_id=application.pk,
            details=f"اعتماد وإحالة الأمين العام لتقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) للطلب ({application.application_number}) إلى رئيس وأعضاء مجلس الإدارة",
            request=request
        )

        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        board_users = User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.DG_ACCREDITATION,
                User.Roles.ADMIN,
            ],
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED
        )
        for b_user in board_users:
            send_notification(
                user=b_user,
                title=f"إحالة ملف الاعتماد المتكامل (17 قسماً) وتقرير المقارنة التحليلي لرئيس وأعضاء مجلس الإدارة: {application.application_number}",
                message=(
                    f"أحال الأمين العام للمجلس تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) (IN_COUNCIL_REVIEW) "
                    f"لطلب مؤسسة ({application.institution.name}) رقم ({application.application_number}) إلى رئيس وأعضاء مجلس الإدارة "
                    f"للدراسة والتداول والتصويت السري واتخاذ القرار."
                ),
                url=f"/accreditation/{application.pk}/dossier-17/"
            )

        messages.success(request, "تم بنجاح اعتماد وإرسال تقرير المقارنة التحليلي + ملف الاعتماد المتكامل (17 قسماً) (IN_COUNCIL_REVIEW) إلى رئيس وأعضاء مجلس الإدارة وحفظهما في مكتبتهم.")
        return redirect('accreditation:application_dossier_17_view', pk=application.pk)

    self_study = getattr(application, 'self_study_report', None)
    external_report = getattr(application, 'external_report', None)
    review_team = getattr(application, 'review_team', None)
    site_visit = getattr(application, 'site_visit', None)
    std_version = application.standard_version
    agenda_item = CouncilAgendaItem.objects.filter(application=application).select_related('meeting').order_by('-id').first()

    dossier = {
        'part_1_institution': application.institution,
        'part_2_program': application.program,
        'part_3_application': application,
        'part_4_self_study_report': self_study,
        'part_5_standards': std_version,
        'part_5_categories': std_version.categories.prefetch_related('indicators').all() if std_version else [],
        'part_6_evidences': application.evidences.select_related('indicator').all(),
        'part_7_self_eval_results': self_study.indicator_responses.select_related('indicator').all() if self_study else [],
        'part_8_desk_reviews': application.desk_reviews.select_related('reviewer').prefetch_related('checklist_items').all(),
        'part_9_site_visit': site_visit,
        'part_9_facilities': site_visit.facility_inspections.all() if site_visit else [],
        'part_9_interviews': site_visit.interviews.all() if site_visit else [],
        'part_10_external_scores': application.indicator_scores.select_related('indicator', 'evaluator').all(),
        'part_11_review_team': review_team,
        'part_11_team_members': review_team.members.select_related('user').all() if review_team else [],
        'part_11_draft_report': external_report,
        'part_12_institution_reply': {
            'text': external_report.institution_reply_text if external_report else '',
            'file': external_report.institution_reply_file if external_report else None,
            'date': external_report.institution_reply_date if external_report else None,
        },
        'part_13_final_external_report': external_report,
        'part_14_comparison_reports': application.comparison_reports.select_related('generated_by').all().order_by('-created_at'),
        'part_15_committee_recommendation': {
            'panel_recommendation': external_report.get_final_recommendation_display() if external_report else 'لم تُحدد بعد',
            'agenda_initial_recommendation': agenda_item.initial_recommendation if agenda_item else 'إحالة لمجلس الإدارة للتصويت والقرار',
        },
        'part_16_previous_decisions': AccreditationDecision.objects.filter(
            application__institution=application.institution
        ).exclude(application=application).select_related('meeting', 'application'),
        'part_16_status_history': application.status_history.select_related('changed_by').all().order_by('-created_at'),
        'part_17_attachments': agenda_item.attachments.all() if agenda_item else [],
    }

    meetings = CouncilMeeting.objects.order_by('-meeting_date')[:15]
    return render(request, 'accreditation/dossier_17_view.html', {
        'app': application,
        'dossier': dossier,
        'agenda_item': agenda_item,
        'meetings': meetings,
        'latest_comparison': dossier['part_14_comparison_reports'].first(),
    })


@login_required
def ai_quality_analyzer_view(request, pk):
    """
    AI Quality Analyzer Dashboard (المساعد الذكي لتحليل الدراسة الذاتية واكتشاف الفجوات واقتراح مسودة تقرير المقارنة التحليلي).
    Analyzes Self-Study narratives, Digital Evidences (SHA-256), External Reviewer Rubrics,
    Site Visit Inspections, and Institution Replies, and allows 1-click generation of the
    Secretariat Analytical Comparison Report draft.
    """
    application = get_object_or_404(
        AccreditationApplication.objects.select_related('institution', 'program', 'standard_version'),
        pk=pk
    )

    if not _verify_tenant_access(request, application):
        messages.error(request, "غير مصرح لك بالوصول لتحليل هذا الطلب.")
        return redirect('core_dashboard')

    from apps.accreditation.ai_analyzer import AIQualityAnalyzer
    ai_analysis = AIQualityAnalyzer.analyze_application(application)

    if request.method == 'POST' and ('generate_comparison_draft' in request.POST or 'ai_generate_draft' in request.POST):
        if not (request.user.is_council or request.user.is_board or request.user.is_staff):
            messages.error(request, "غير مصرح لك: توليد واعتماد مسودة تقرير المقارنة التحليلي مخصص للأمانة العامة والإدارات المختصة.")
            return redirect('accreditation:ai_quality_analyzer', pk=application.pk)

        custom_title = request.POST.get('comparison_title', '').strip() or ai_analysis['draft_comparison_title']
        custom_summary = request.POST.get('secretariat_analytical_summary', '').strip() or ai_analysis['draft_analytical_summary']
        refer_to_council = 'refer_to_council' in request.POST

        comp_report = SecretariatAssessmentComparisonReport.objects.create(
            application=application,
            generated_by=request.user,
            title=custom_title,
            secretariat_analytical_summary=custom_summary,
            comparison_data_json={
                'ai_readiness_score': ai_analysis['readiness_score'],
                'ai_alignment_index': ai_analysis['alignment_index'],
                'ai_evidence_coverage_pct': ai_analysis['evidence_coverage_pct'],
                'ai_recommendation_code': ai_analysis['ai_recommendation_code'],
                'ai_recommendation_label': ai_analysis['ai_recommendation_label'],
                'ai_detected_gaps_count': ai_analysis['total_gaps_count'],
                'total_evidences_count': ai_analysis['total_evidences_count'],
            },
            attached_to_council_briefing=refer_to_council,
        )

        record_audit_log(
            user=request.user,
            action='AI_QUALITY_ANALYSIS_DRAFT_SAVED',
            target_model='SecretariatAssessmentComparisonReport',
            target_id=comp_report.pk,
            details=f"توليد وحفظ مسودة تقرير المقارنة التحليلي عبر المساعد الذكي للطلب ({application.application_number}) بمؤشر جاهزية ({ai_analysis['readiness_score']}%)",
            request=request
        )

        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        if refer_to_council:
            if application.status == ApplicationStatus.FINAL_REPORT_READY:
                try:
                    WorkflowEngine.execute_transition(
                        application=application,
                        target_status=ApplicationStatus.IN_COUNCIL_REVIEW,
                        user=request.user,
                        reason=f"إحالة تقرير المقارنة التحليلي المولد بالمساعد الذكي إلى مجلس الإدارة: {custom_title}",
                        request=request
                    )
                except ValidationError:
                    application.status = ApplicationStatus.IN_COUNCIL_REVIEW
                    application.current_stage = StageChoices.STAGE_6
                    application.save(update_fields=['status', 'current_stage'])

            board_users = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_EVALUATION,
                    User.Roles.DG_ACCREDITATION,
                ],
                is_active=True
            )
            for b_u in board_users:
                send_notification(
                    user=b_u,
                    title=f"إحالة تقرير التحليل الذكي والمقارنة التحليلية للمجلس: {application.application_number}",
                    message=(
                        f"تم توليد واعتماد تقرير المقارنة التحليلي المدعوم بالمساعد الذكي (مؤشر الجاهزية: {ai_analysis['readiness_score']}%) "
                        f"للطلب ({application.application_number}) وإحالته مع ملف الاعتماد المتكامل (17 قسماً) إلى مجلس الإدارة."
                    ),
                    url=f"/accreditation/{application.pk}/comparison-dashboard/"
                )
            messages.success(request, "تم توليد واعتماد مسودة تقرير المقارنة التحليلي بالمساعد الذكي وإحالته رسمياً إلى مجلس الإدارة وحفظه في مكتبتي.")
            return redirect('accreditation:secretariat_comparison_dashboard', pk=application.pk)

        messages.success(request, "تم توليد وحفظ مسودة تقرير المقارنة التحليلي بالمساعد الذكي بنجاح ومزامنتها في مكتبتي.")
        return redirect('accreditation:secretariat_comparison_dashboard', pk=application.pk)

    return render(request, 'accreditation/ai_quality_analyzer.html', {
        'app': application,
        'ai': ai_analysis,
        'can_generate_draft': (request.user.is_council or request.user.is_board or request.user.is_staff),
    })

