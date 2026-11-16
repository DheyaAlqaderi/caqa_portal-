from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse
from django.db import transaction
from django.db.models import Count, Q

from apps.accounts.models import User, record_audit_log, send_notification, notify_role
from apps.institutions.models import Institution, AcademicProgram
from apps.decisions.models import (
    CouncilMeeting,
    AccreditationDecision,
    AccreditationCertificate,
    BoardNomination,
    CouncilPolicy,
    SovereignTransaction,
)


def _check_ministerial_access(user):
    """
    Ensures user is the Minister of Higher Education, System Administrator, or Superuser.
    """
    return (
        user.is_authenticated and (
            user.is_superuser or
            user.role in [User.Roles.MINISTER, User.Roles.ADMIN]
        )
    )


def _check_policy_and_council_access(user):
    """
    Allows Prime Minister, Minister, Council Leadership (Chairman, Vice Chairman, Secretary General), Board Members, and Admin
    to review and submit policies and regulations for Ministerial Ratification and track board nominations.
    """
    return (
        user.is_authenticated and (
            user.is_superuser or
            user.role in [
                User.Roles.PRIME_MINISTER,
                User.Roles.MINISTER,
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.BOARD_MEMBER,
                User.Roles.ADMIN
            ]
        )
    )


@login_required
def minister_dashboard(request):
    """
    Strategic Executive Dashboard for H.E. the Minister of Higher Education and Scientific Research.
    Provides sovereign oversight on the higher education sector, CAQA Board nominations,
    and ministerial ratification of national quality policies and regulations.
    """
    if not _check_ministerial_access(request.user):
        messages.error(request, "غير مصرح لك: هذه الواجهة مخصصة حصراً لمعالي وزير التعليم العالي والبحث العلمي وديوان الوزارة.")
        return redirect('core_dashboard')

    # 1. Higher Education Sector Statistics
    total_institutions = Institution.objects.count()
    public_universities = Institution.objects.filter(institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY).count()
    private_universities = Institution.objects.filter(institution_type=Institution.InstitutionType.PRIVATE_UNIVERSITY).count()
    community_colleges = Institution.objects.filter(
        institution_type__in=[Institution.InstitutionType.UNIVERSITY_COLLEGE, Institution.InstitutionType.HIGHER_INSTITUTE]
    ).count()

    total_programs = AcademicProgram.objects.count()

    # 2. CAQA Accreditation Progress
    active_certs = AccreditationCertificate.objects.filter(status='ACTIVE', is_revoked=False)
    inst_accredited_count = active_certs.filter(decision__application__program__isnull=True).count()
    prog_accredited_count = active_certs.filter(decision__application__program__isnull=False).count()

    total_meetings = CouncilMeeting.objects.count()
    total_decisions = AccreditationDecision.objects.count()
    full_accreditation_decisions = AccreditationDecision.objects.filter(
        decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION
    ).count()

    # 3. Mandate 2: CAQA Board Nominations to the Prime Minister
    nominations_qs = BoardNomination.objects.all().order_by('-nomination_date', '-created_at')
    nominations_total = nominations_qs.count()
    nominations_pending_pm = nominations_qs.filter(status=BoardNomination.NominationStatus.SUBMITTED_TO_PM).count()
    nominations_decreed = nominations_qs.filter(status=BoardNomination.NominationStatus.DECREE_ISSUED).count()

    recent_nominations = nominations_qs[:6]

    # 4. Mandate 3: Council Policies and Regulations Ratification
    policies_qs = CouncilPolicy.objects.all().order_by('-submission_date', '-created_at')
    policies_total = policies_qs.count()
    policies_pending = policies_qs.filter(status=CouncilPolicy.RatificationStatus.PENDING_RATIFICATION).count()
    policies_ratified = policies_qs.filter(status=CouncilPolicy.RatificationStatus.RATIFIED).count()

    pending_policies = policies_qs.filter(status=CouncilPolicy.RatificationStatus.PENDING_RATIFICATION)[:5]
    recent_ratified_policies = policies_qs.filter(status=CouncilPolicy.RatificationStatus.RATIFIED)[:5]

    # 5. Geographic Distribution of Universities
    governorate_stats = (
        Institution.objects.values('governorate')
        .annotate(total=Count('id'))
        .order_by('-total')[:7]
    )

    # 6. Recent Accreditation Decisions
    recent_decisions = (
        AccreditationDecision.objects.select_related('application__institution', 'application__program', 'meeting')
        .order_by('-decision_date')[:6]
    )

    context = {
        'total_institutions': total_institutions,
        'public_universities': public_universities,
        'private_universities': private_universities,
        'community_colleges': community_colleges,
        'total_programs': total_programs,
        'inst_accredited_count': inst_accredited_count,
        'prog_accredited_count': prog_accredited_count,
        'total_meetings': total_meetings,
        'total_decisions': total_decisions,
        'full_accreditation_decisions': full_accreditation_decisions,
        'nominations_total': nominations_total,
        'nominations_pending_pm': nominations_pending_pm,
        'nominations_decreed': nominations_decreed,
        'recent_nominations': recent_nominations,
        'policies_total': policies_total,
        'policies_pending': policies_pending,
        'policies_ratified': policies_ratified,
        'pending_policies': pending_policies,
        'recent_ratified_policies': recent_ratified_policies,
        'governorate_stats': governorate_stats,
        'recent_decisions': recent_decisions,
        'now_date': timezone.now().date(),
    }
    return render(request, 'decisions/minister_dashboard.html', context)


@login_required
def minister_nominations_list(request):
    """
    Lists all board nominations for Council Leadership and Board of Directors,
    tracked from nomination to Prime Minister to issuance of Republican Decree.
    Accessible to Minister and Council Leadership/Board for governance visibility.
    """
    if not _check_policy_and_council_access(request.user):
        messages.error(request, "غير مصرح لك باستعراض سجل ترشيحات مجلس الإدارة.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status', '')
    nominations = BoardNomination.objects.all().order_by('-nomination_date', '-created_at')
    if status_filter:
        nominations = nominations.filter(status=status_filter)

    return render(request, 'decisions/minister_nominations.html', {
        'nominations': nominations,
        'status_filter': status_filter,
        'status_choices': BoardNomination.NominationStatus.choices,
        'position_choices': BoardNomination.ProposedPosition.choices,
    })


@login_required
def minister_nomination_create(request):
    """
    Form allowing the Minister to register and submit a new nomination for CAQA Board of Directors
    to be forwarded to the Prime Minister.
    """
    if not _check_ministerial_access(request.user):
        messages.error(request, "غير مصرح لك بإنشاء ترشيحات مجلس الإدارة.")
        return redirect('core_dashboard')

    if request.method == 'POST':
        name = request.POST.get('nominee_name', '').strip()
        academic_rank = request.POST.get('academic_rank', '').strip() or 'أستاذ دكتور (بروفيسور)'
        position = request.POST.get('proposed_position', BoardNomination.ProposedPosition.BOARD_MEMBER_EXPERT)
        spec = request.POST.get('specialization', '').strip()
        current_inst = request.POST.get('current_institution', '').strip()
        cv = request.POST.get('cv_summary', '').strip()
        letter_ref = request.POST.get('nomination_letter_ref', '').strip()
        date_str = request.POST.get('nomination_date', '').strip()
        status = request.POST.get('status', BoardNomination.NominationStatus.SUBMITTED_TO_PM)
        decree_num = request.POST.get('republican_decree_number', '').strip()
        decree_date_str = request.POST.get('decree_date', '').strip()
        notes = request.POST.get('minister_notes', '').strip()
        doc_file = request.FILES.get('nomination_document')

        if not name or not spec or not current_inst:
            messages.error(request, "يرجى تعبئة كافة الحقول الأساسية لملف المرشح (الاسم، التخصص، جهة العمل).")
            return redirect('decisions:minister_nominations_list')

        # Auto-generate statutory reference number if empty
        if not letter_ref:
            count = BoardNomination.objects.count() + 1
            letter_ref = f"NOM-2026-{count:03d}"

        with transaction.atomic():
            nomination = BoardNomination.objects.create(
                nominee_name=name,
                academic_rank=academic_rank,
                proposed_position=position,
                specialization=spec,
                current_institution=current_inst,
                cv_summary=cv,
                nomination_document=doc_file,
                nomination_letter_ref=letter_ref,
                nomination_date=date_str if date_str else timezone.now().date(),
                status=status,
                republican_decree_number=decree_num,
                decree_date=decree_date_str if decree_date_str else None,
                minister_notes=notes,
                created_by=request.user,
            )

            # Centralized Sovereign Transaction Record
            pm_user = User.objects.filter(role=User.Roles.PRIME_MINISTER, is_active=True).first()
            SovereignTransaction.objects.create(
                reference_number=nomination.nomination_letter_ref,
                transaction_type=SovereignTransaction.TransactionType.NOMINATION_MEMO,
                sender=request.user,
                recipient=pm_user,
                sending_authority="وزارة التعليم العالي والبحث العلمي - ديوان معالي الوزير",
                receiving_authority="رئاسة مجلس الوزراء - ديوان دولة رئيس الوزراء",
                subject=f"ترشيح ({nomination.nominee_name}) لمنصب ({nomination.get_proposed_position_display()})",
                description=nomination.cv_summary,
                official_document=doc_file,
                status=SovereignTransaction.TransactionStatus.SUBMITTED
            )

            record_audit_log(
                user=request.user,
                action='BOARD_NOMINATION_CREATED',
                target_model='BoardNomination',
                target_id=nomination.pk,
                details=f"رفع مذكرة ترشيح رسمية برقم ({nomination.nomination_letter_ref}) للمرشح ({nomination.nominee_name}) لمنصب ({nomination.get_proposed_position_display()}) لدولة رئيس الوزراء",
                request=request
            )

            # Statutory Notification to Prime Minister
            pm_users = User.objects.filter(role=User.Roles.PRIME_MINISTER, is_active=True)
            for pm in pm_users:
                send_notification(
                    user=pm,
                    title=f"مذكرة ترشيح لعضوية مجلس إدارة الاعتماد: {nomination.nomination_letter_ref}",
                    message=f"رفع معالي وزير التعليم العالي والبحث العلمي مذكرة ترشيح رسمية برقم ({nomination.nomination_letter_ref}) لعضوية مجلس إدارة مجلس الاعتماد الأكاديمي (المرشح: {nomination.nominee_name} - {nomination.get_proposed_position_display()}).",
                    url="/decisions/minister/nominations/"
                )

        messages.success(request, f"تم بنجاح رفع مذكرة ترشيح ({nomination.nominee_name}) برقم قيد ({nomination.nomination_letter_ref}) لدولة رئيس الوزراء وتوثيقها سيادياً.")
        return redirect('decisions:minister_nominations_list')

    return redirect('decisions:minister_nominations_list')


@login_required
def minister_nomination_update(request, pk):
    """
    Updates the nomination status (e.g. recording the Republican Decree upon appointment).
    """
    if not _check_ministerial_access(request.user):
        messages.error(request, "غير مصرح لك بتحديث ترشيحات مجلس الإدارة.")
        return redirect('core_dashboard')

    nomination = get_object_or_404(BoardNomination, pk=pk)

    if request.method == 'POST':
        nomination.status = request.POST.get('status', nomination.status)
        nomination.nomination_letter_ref = request.POST.get('nomination_letter_ref', nomination.nomination_letter_ref).strip()
        nomination.republican_decree_number = request.POST.get('republican_decree_number', nomination.republican_decree_number).strip()
        decree_date_str = request.POST.get('decree_date', '').strip()
        if decree_date_str:
            nomination.decree_date = decree_date_str
        nomination.minister_notes = request.POST.get('minister_notes', nomination.minister_notes).strip()
        if request.FILES.get('nomination_document'):
            nomination.nomination_document = request.FILES.get('nomination_document')
        nomination.save()

        record_audit_log(
            user=request.user,
            action='BOARD_NOMINATION_UPDATED',
            target_model='BoardNomination',
            target_id=nomination.pk,
            details=f"تحديث موقف ترشيح ({nomination.nominee_name}) إلى ({nomination.get_status_display()}) - القرار الجمهوري: {nomination.republican_decree_number}",
            request=request
        )

        messages.success(request, f"تم تحديث بيانات وموقف ترشيح ({nomination.nominee_name}) بنجاح.")
        return redirect('decisions:minister_nominations_list')

    return redirect('decisions:minister_nominations_list')


@login_required
def pm_nomination_decree(request, pk):
    """
    Empowers H.E. the Prime Minister (دولة رئيس مجلس الوزراء) to review nominations
    referred by the Minister of Higher Education, endorse them, issue Republican Decrees,
    or return them for completion.
    """
    can_pm_decree = (
        request.user.is_superuser or
        request.user.role in [User.Roles.PRIME_MINISTER, User.Roles.MINISTER, User.Roles.ADMIN]
    )
    if not can_pm_decree:
        messages.error(request, "غير مصرح لك: اعتماد الترشيحات وإصدار القرارات الجمهورية مخصص لدولة رئيس مجلس الوزراء أو معالي الوزير.")
        return redirect('decisions:minister_nominations_list')

    nomination = get_object_or_404(BoardNomination, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', 'issue_decree')
        pm_notes = request.POST.get('pm_notes', '').strip()

        if action == 'return_completion' or request.POST.get('status') == BoardNomination.NominationStatus.RETURNED_FOR_COMPLETION:
            with transaction.atomic():
                nomination.status = BoardNomination.NominationStatus.RETURNED_FOR_COMPLETION
                nomination.pm_notes = pm_notes
                nomination.pm_endorsed_by = request.user
                nomination.pm_endorsed_at = timezone.now()
                nomination.save()

                record_audit_log(
                    user=request.user,
                    action='BOARD_NOMINATION_PM_RETURNED',
                    target_model='BoardNomination',
                    target_id=nomination.pk,
                    details=f"إعادة ملف ترشيح ({nomination.nominee_name}) لمعالي الوزير للاستكمال بملاحظات: {pm_notes}",
                    request=request
                )

                # Notify Minister of return for completion
                minister_users = User.objects.filter(role=User.Roles.MINISTER, is_active=True)
                for min_u in minister_users:
                    send_notification(
                        user=min_u,
                        title="إعادة مذكرة ترشيح للاستكمال من ديوان رئاسة الوزراء",
                        message=f"أعاد دولة رئيس مجلس الوزراء مذكرة ترشيح ({nomination.nominee_name}) للاستكمال واستيفاء المتطلبات بملاحظات: ({pm_notes or 'استكمال مسوغات الترشيح'}).",
                        url="/decisions/minister/nominations/"
                    )

            messages.warning(request, f"تمت إعادة مذكرة ترشيح ({nomination.nominee_name}) إلى وزارة التعليم العالي للاستكمال.")
            return redirect('decisions:minister_nominations_list')

        # Otherwise: Proceed with appointment decree
        decree_number = request.POST.get('republican_decree_number', '').strip()
        decree_date_str = request.POST.get('decree_date', '').strip()
        start_date_str = request.POST.get('appointment_start_date', '').strip()
        end_date_str = request.POST.get('appointment_end_date', '').strip()
        term_years = int(request.POST.get('term_years', 4))
        decree_doc = request.FILES.get('decree_document')
        status = request.POST.get('status', BoardNomination.NominationStatus.DECREE_ISSUED)

        if not decree_number:
            messages.error(request, "يرجى إدخال رقم القرار الجمهوري / قرار التعيين الصادر.")
            return redirect('decisions:minister_nominations_list')

        with transaction.atomic():
            from datetime import datetime
            nomination.republican_decree_number = decree_number
            if decree_date_str and isinstance(decree_date_str, str):
                try:
                    nomination.decree_date = datetime.strptime(decree_date_str, '%Y-%m-%d').date()
                except ValueError:
                    nomination.decree_date = timezone.now().date()
            else:
                nomination.decree_date = timezone.now().date()

            if start_date_str and isinstance(start_date_str, str):
                try:
                    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                except ValueError:
                    start_dt = nomination.decree_date
            else:
                start_dt = nomination.decree_date
            nomination.appointment_start_date = start_dt

            if end_date_str and isinstance(end_date_str, str):
                try:
                    nomination.appointment_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    nomination.appointment_end_date = None
            else:
                from apps.operations.deadline_engine import calculate_calendar_anniversary
                nomination.appointment_end_date = calculate_calendar_anniversary(start_dt, term_years)

            nomination.term_years = term_years
            if decree_doc:
                nomination.decree_document = decree_doc
            nomination.pm_notes = pm_notes
            nomination.status = status
            nomination.pm_endorsed_by = request.user
            nomination.pm_endorsed_at = timezone.now()
            nomination.save()

            # Record in Centralized Sovereign Transactions
            trx = SovereignTransaction.objects.filter(reference_number=nomination.nomination_letter_ref).first()
            if trx:
                trx.transition_to(
                    SovereignTransaction.TransactionStatus.APPROVED,
                    actor=request.user,
                    reason=f"صدور القرار الجمهوري رقم ({decree_number})"
                )
            else:
                SovereignTransaction.objects.create(
                    reference_number=f"DEC-{decree_number}",
                    transaction_type=SovereignTransaction.TransactionType.PRESIDENTIAL_DECREE,
                    sender=request.user,
                    sending_authority="رئاسة مجلس الوزراء - ديوان رئيس الوزراء",
                    receiving_authority="وزارة التعليم العالي ومجلس الاعتماد الأكاديمي",
                    subject=f"قرار تعيين جمهوري ({nomination.nominee_name}) - {nomination.get_proposed_position_display()}",
                    description=f"القرار الجمهوري رقم ({decree_number}) وتاريخ ({nomination.decree_date}) للمدة ({term_years} سنوات)",
                    official_document=nomination.decree_document,
                    status=SovereignTransaction.TransactionStatus.COMPLETED
                )

            record_audit_log(
                user=request.user,
                action='BOARD_NOMINATION_PM_DECREED',
                target_model='BoardNomination',
                target_id=nomination.pk,
                details=f"اعتماد وتوثيق القرار الجمهوري برقم ({decree_number}) لتعيين المرشح ({nomination.nominee_name}) بمنصب ({nomination.get_proposed_position_display()}) بواسطة دولة رئيس مجلس الوزراء (فترة السريان حتى: {nomination.appointment_end_date})",
                request=request
            )

            # Notifications to: Minister, Council Chairman, and General Secretariat
            notify_role(
                [
                    User.Roles.MINISTER,
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY
                ],
                title="صدور قرار تعيين جمهوري لمجلس إدارة الاعتماد",
                message=f"صدر القرار الجمهوري برقم ({decree_number}) بتعيين ({nomination.nominee_name}) في منصب ({nomination.get_proposed_position_display()}) بمجلس إدارة مجلس الاعتماد الأكاديمي.",
                url="/decisions/minister/nominations/"
            )

            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()

        messages.success(request, f"تم اعتماد الترشيح وتوثيق صدور القرار الجمهوري برقم ({decree_number}) ونفاذ فترة التعيين حتى ({nomination.appointment_end_date}) بنجاح.")
        return redirect('decisions:minister_nominations_list')

    return redirect('decisions:minister_nominations_list')


@login_required
def minister_policies_list(request):
    """
    Lists council policies, regulations, and standards manuals submitted for Ministerial Ratification.
    """
    if not _check_policy_and_council_access(request.user):
        messages.error(request, "غير مصرح لك باستعراض لوائح وسياسات المجلس.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status', '')
    policies = CouncilPolicy.objects.all().order_by('-submission_date', '-created_at')
    if status_filter:
        policies = policies.filter(status=status_filter)

    return render(request, 'decisions/minister_policies.html', {
        'policies': policies,
        'status_filter': status_filter,
        'status_choices': CouncilPolicy.RatificationStatus.choices,
        'type_choices': CouncilPolicy.PolicyType.choices,
        'can_ratify': _check_ministerial_access(request.user),
    })


@login_required
def minister_policy_create(request):
    """
    Registers a new policy or executive regulation referred from the Council to the Minister for Ratification.
    """
    if not _check_policy_and_council_access(request.user):
        messages.error(request, "غير مصرح لك بإحالة لوائح للمصادقة الوزارية.")
        return redirect('core_dashboard')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        p_type = request.POST.get('policy_type', CouncilPolicy.PolicyType.EXECUTIVE_REGULATION)
        session_ref = request.POST.get('council_session_ref', '').strip()
        date_str = request.POST.get('submission_date', '').strip()
        summary = request.POST.get('summary', '').strip()
        doc_file = request.FILES.get('document_file')

        if not title or not session_ref or not summary:
            messages.error(request, "يرجى استيفاء كافة بيانات الوثيقة (العنوان، مرجع جلسة المجلس، الخلاصة).")
            return redirect('decisions:minister_policies_list')

        with transaction.atomic():
            policy = CouncilPolicy.objects.create(
                title=title,
                policy_type=p_type,
                council_session_ref=session_ref,
                submission_date=date_str if date_str else timezone.now().date(),
                summary=summary,
                document_file=doc_file,
                status=CouncilPolicy.RatificationStatus.PENDING_RATIFICATION,
            )

            # Centralized Sovereign Transaction Record
            min_user = User.objects.filter(role=User.Roles.MINISTER, is_active=True).first()
            trx_ref = f"POL-2026-{policy.pk:03d}"
            SovereignTransaction.objects.create(
                reference_number=trx_ref,
                transaction_type=SovereignTransaction.TransactionType.POLICY_RATIFICATION,
                sender=request.user,
                recipient=min_user,
                sending_authority="مجلس الاعتماد الأكاديمي - رئاسة المجلس والأمانة العامة",
                receiving_authority="وزارة التعليم العالي - ديوان معالي الوزير",
                subject=f"إحالة ({policy.title}) للمصادقة الوزارية والنفاذ",
                description=f"وثيقة ({policy.get_policy_type_display()}) بموجب إقرار جلسة المجلس ({policy.council_session_ref})",
                official_document=policy.document_file,
                status=SovereignTransaction.TransactionStatus.SUBMITTED
            )

            record_audit_log(
                user=request.user,
                action='COUNCIL_POLICY_SUBMITTED',
                target_model='CouncilPolicy',
                target_id=policy.pk,
                details=f"إحالة ({policy.title}) لمعالي الوزير للمصادقة الوزارية بموجب جلسة المجلس ({policy.council_session_ref})",
                request=request
            )

            # Statutory Notification to H.E. Minister
            minister_users = User.objects.filter(role=User.Roles.MINISTER, is_active=True)
            for m in minister_users:
                send_notification(
                    user=m,
                    title="إحالة لائحة/سياسة صادرة عن المجلس للمصادقة الوزارية",
                    message=f"أحال مجلس الاعتماد الأكاديمي وثيقة ({policy.title}) بموجب إقرار جلسة المجلس ({policy.council_session_ref}) للمصادقة الوزارية وإصدار القرار التنفيذي.",
                    url="/decisions/minister/policies/"
                )

            # Sync to My Library
            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

        messages.success(request, f"تم بنجاح تسجيل وإحالة ({policy.title}) للعرض والمصادقة الوزارية وإشعار معالي الوزير.")
        return redirect('decisions:minister_policies_list')

    return redirect('decisions:minister_policies_list')


@login_required
def minister_policy_ratify(request, pk):
    """
    Ministerial Ratification Action: H.E. the Minister officially ratifies the policy,
    issues the Ministerial Decree number, sets the effective date, returns with directives,
    or formally rejects.
    """
    if not _check_ministerial_access(request.user):
        messages.error(request, "غير مصرح لك بالمصادقة على لوائح وسياسات المجلس.")
        return redirect('core_dashboard')

    policy = get_object_or_404(CouncilPolicy, pk=pk)

    if request.method == 'POST':
        action_decision = request.POST.get('action_decision')  # 'RATIFY' or 'RETURN_REVISION' or 'REJECT'
        decree_num = request.POST.get('ministerial_decree_number', '').strip()
        ratif_date_str = request.POST.get('ratification_date', '').strip()
        effective_date_str = request.POST.get('effective_date', '').strip()
        directive = request.POST.get('minister_directive', '').strip()

        with transaction.atomic():
            trx = SovereignTransaction.objects.filter(
                transaction_type=SovereignTransaction.TransactionType.POLICY_RATIFICATION,
                subject__icontains=policy.title
            ).first()

            if action_decision == 'RATIFY':
                if not decree_num:
                    messages.error(request, "يرجى إدخال رقم وتاريخ القرار الوزاري الصادر بالمصادقة والنفاذ.")
                    return redirect('decisions:minister_policies_list')
                policy.status = CouncilPolicy.RatificationStatus.RATIFIED
                policy.ministerial_decree_number = decree_num
                policy.ratification_date = ratif_date_str if ratif_date_str else timezone.now().date()
                policy.effective_date = effective_date_str if effective_date_str else policy.ratification_date
                policy.minister_directive = directive
                policy.ratified_by = request.user
                policy.save()

                if trx:
                    trx.transition_to(
                        SovereignTransaction.TransactionStatus.APPROVED,
                        actor=request.user,
                        reason=f"المصادقة بالقرار الوزاري رقم ({decree_num})"
                    )

                record_audit_log(
                    user=request.user,
                    action='POLICY_MINISTERIAL_RATIFIED',
                    target_model='CouncilPolicy',
                    target_id=policy.pk,
                    details=f"المصادقة الوزارية على ({policy.title}) بموجب القرار الوزاري ({decree_num})",
                    request=request
                )

                # Broadcast official notification to Council Leadership & Board Members
                notify_role(
                    [
                        User.Roles.COUNCIL_CHAIRMAN,
                        User.Roles.COUNCIL_VICE_CHAIRMAN,
                        User.Roles.COUNCIL_SECRETARY_GENERAL,
                        User.Roles.COUNCIL_SECRETARY,
                        User.Roles.BOARD_MEMBER
                    ],
                    title="المصادقة الوزارية على لائحة/سياسة صادرة عن المجلس ونفاذها",
                    message=f"أصدر معالي الوزير القرار الوزاري ({decree_num}) بالمصادقة على وثيقة ({policy.title}) وبدء سريانها ونفاذها.",
                    url="/decisions/minister/policies/"
                )

                # Sync ratified policy to My Library
                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                messages.success(request, f"تمت المصادقة الوزارية بنجاح وإصدار القرار الوزاري ({decree_num}) ونفاذ ({policy.title}).")

            elif action_decision == 'RETURN_REVISION':
                policy.status = CouncilPolicy.RatificationStatus.RETURNED_WITH_REMARKS
                policy.minister_directive = directive
                policy.save()

                if trx:
                    trx.transition_to(
                        SovereignTransaction.TransactionStatus.RETURNED_FOR_COMPLETION,
                        actor=request.user,
                        reason=f"إعادة بملاحظات للتعديل: {directive}"
                    )

                record_audit_log(
                    user=request.user,
                    action='POLICY_RETURNED_FOR_REVISION',
                    target_model='CouncilPolicy',
                    target_id=policy.pk,
                    details=f"إعادة وثيقة ({policy.title}) للمجلس لإجراء تعديلات وملاحظات معالي الوزير",
                    request=request
                )

                notify_role(
                    [
                        User.Roles.COUNCIL_CHAIRMAN,
                        User.Roles.COUNCIL_VICE_CHAIRMAN,
                        User.Roles.COUNCIL_SECRETARY_GENERAL,
                        User.Roles.COUNCIL_SECRETARY
                    ],
                    title="إعادة وثيقة لائحة/سياسة بملاحظات وتوجيهات معالي الوزير",
                    message=f"أعاد معالي الوزير وثيقة ({policy.title}) للمجلس لاستيفاء الملاحظات: ({directive or 'تعديل الصياغة والمواد'}).",
                    url="/decisions/minister/policies/"
                )

                messages.warning(request, f"تمت إعادة وثيقة ({policy.title}) إلى المجلس مع توجيهات وملاحظات معالي الوزير.")

            elif action_decision == 'REJECT':
                policy.status = CouncilPolicy.RatificationStatus.REJECTED
                policy.minister_directive = directive
                policy.save()

                if trx:
                    trx.transition_to(
                        SovereignTransaction.TransactionStatus.REJECTED,
                        actor=request.user,
                        reason=f"رفض المصادقة: {directive}"
                    )

                record_audit_log(
                    user=request.user,
                    action='POLICY_MINISTERIAL_REJECTED',
                    target_model='CouncilPolicy',
                    target_id=policy.pk,
                    details=f"رفض المصادقة الوزارية على وثيقة ({policy.title}): {directive}",
                    request=request
                )

                notify_role(
                    [
                        User.Roles.COUNCIL_CHAIRMAN,
                        User.Roles.COUNCIL_SECRETARY_GENERAL
                    ],
                    title="قرار معالي الوزير حيال اللائحة/السياسة المعروضة",
                    message=f"تقرر عدم المصادقة على وثيقة ({policy.title}) للأسباب: ({directive or 'غير معتمد'}).",
                    url="/decisions/minister/policies/"
                )

                messages.error(request, f"تم توثيق عدم المصادقة على وثيقة ({policy.title}) وإشعار قيادة المجلس.")

        return redirect('decisions:minister_policies_list')

    return redirect('decisions:minister_policies_list')
