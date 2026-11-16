from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.conf import settings
import sys
import platform
from django.db import connection

from apps.accreditation.models import AccreditationApplication, ApplicationStatus
from apps.standards.models import AccreditationTrackType
from apps.decisions.models import AccreditationDecision, AccreditationCertificate
from apps.institutions.models import Institution, AcademicProgram

from apps.accounts.models import (
    User,
    AuditLog,
    Notification,
    SMSLog,
    UserDocument,
    DocumentShare,
    ScheduledReminderLog,
    DynamicPermission,
    RolePermissionAssignment,
    UserPermissionOverride,
    PermissionAuditRecord,
    record_audit_log,
    send_notification,
)
from apps.accounts.permissions import (
    has_permission,
    rotate_user_override,
    revoke_user_override,
    record_permission_audit,
    redact_sensitive_diagnostics,
    GOVERNANCE_LOCKED_PERMISSIONS,
)

def login_view(request):
    if request.user.is_authenticated:
        return redirect('core_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        existing_user = User.objects.filter(username=username).first()
        if existing_user and existing_user.is_locked:
            record_audit_log(
                user=existing_user,
                action='LOGIN_BLOCKED_LOCKED_ACCOUNT',
                target_model='User',
                target_id=existing_user.pk,
                details=f"منع تسجيل الدخول لحساب مقفل أمنياً (@{existing_user.username}). سبب القفل: {existing_user.lock_reason}",
                request=request
            )
            messages.error(request, f"هذا الحساب مقفل أمنياً ({existing_user.lock_reason or 'تجاوز محاولات الدخول'}). يرجى التواصل مع مدير النظام لفك القفل.")
            return render(request, 'accounts/login.html')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.failed_login_attempts > 0:
                user.failed_login_attempts = 0
                user.save(update_fields=['failed_login_attempts'])
            login(request, user)
            record_audit_log(
                user=user,
                action='LOGIN_SUCCESS',
                target_model='User',
                target_id=user.pk,
                details=f"تسجيل دخول ناجح للمستخدم ({user.username}) ذو الصفة ({user.get_role_display()})",
                request=request
            )
            messages.success(request, f"مرحباً بك د. {user.get_full_name() or user.username} في بوابة الاعتماد الأكاديمي")
            return redirect('core_dashboard')
        else:
            if existing_user and existing_user.username != 'najeebADMIN':
                from apps.accounts.models import SystemConfiguration
                max_attempts = SystemConfiguration.get_solo().max_login_attempts
                existing_user.failed_login_attempts = (existing_user.failed_login_attempts or 0) + 1
                if existing_user.failed_login_attempts >= max_attempts:
                    existing_user.is_locked = True
                    existing_user.locked_at = timezone.now()
                    existing_user.lock_reason = f"تجاوز الحد الأقصى لمحاولات الدخول الفاشلة ({max_attempts})"
                    existing_user.save(update_fields=['failed_login_attempts', 'is_locked', 'locked_at', 'lock_reason'])
                else:
                    existing_user.save(update_fields=['failed_login_attempts'])
            record_audit_log(
                user=None,
                action='LOGIN_FAILED',
                target_model='User',
                target_id=username,
                details=f"محاولة تسجيل دخول فاشلة باسم مستخدم ({username})",
                request=request
            )
            messages.error(request, "خطأ في اسم المستخدم أو كلمة المرور. يرجى التحقق وإعادة المحاولة.")
    
    return render(request, 'accounts/login.html')

def logout_view(request):
    if request.user.is_authenticated:
        record_audit_log(
            user=request.user,
            action='LOGOUT',
            target_model='User',
            target_id=request.user.pk,
            details=f"تسجيل خروج للمستخدم ({request.user.username})",
            request=request
        )
    logout(request)
    messages.info(request, "تم تسجيل الخروج بنجاح.")
    return redirect('accounts:login')

@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html', {'user': request.user})

def register_view(request):
    if request.user.is_authenticated:
        return redirect('core_dashboard')

    institutions = Institution.objects.all().order_by('name')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        phone = request.POST.get('phone', '').strip()
        national_id = request.POST.get('national_id', '').strip()

        if not username or not password or not email or not full_name:
            messages.error(request, "جميع الحقول الأساسية (الاسم الكامل، اسم المستخدم، البريد، كلمة المرور) مطلوبة.")
            return render(request, 'accounts/register.html', {'institutions': institutions})

        if password != password_confirm:
            messages.error(request, "كلمتا المرور غير متطابقتين.")
            return render(request, 'accounts/register.html', {'institutions': institutions})

        if len(password) < 8:
            messages.error(request, "يجب أن تكون كلمة المرور 8 خانات على الأقل وفق معايير الأمان.")
            return render(request, 'accounts/register.html', {'institutions': institutions})

        if User.objects.filter(username=username).exists():
            messages.error(request, "اسم المستخدم مسجل مسبقاً، يرجى اختيار اسم مستخدم آخر.")
            return render(request, 'accounts/register.html', {'institutions': institutions})

        if User.objects.filter(email=email).exists():
            messages.error(request, "البريد الإلكتروني مسجل مسبقاً، يرجى استخدام بريد إلكتروني آخر أو تسجيل الدخول.")
            return render(request, 'accounts/register.html', {'institutions': institutions})

        # Split full name into first and last name
        parts = full_name.split(' ', 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ''

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            national_id=national_id,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL,
            role=User.Roles.INSTITUTION_OFFICER  # Temporary placeholder until admin approves chosen role
        )

        record_audit_log(
            user=user,
            action='USER_REGISTERED',
            target_model='User',
            target_id=user.pk,
            details=f"تسجيل حساب جديد للمستخدم ({user.username}) بحالة بانتظار تحديد الدور والاعتماد الإداري",
            request=request
        )

        login(request, user)
        messages.success(request, "تم إنشاء حسابك بنجاح! يرجى الآن تحديد صفتك والدور المطلوب في النظام.")
        return redirect('accounts:select_role')

    return render(request, 'accounts/register.html', {'institutions': institutions})


@login_required
def select_role_view(request):
    user = request.user
    if user.is_approved:
        return redirect('core_dashboard')

    institutions = Institution.objects.all().order_by('name')

    if request.method == 'POST':
        requested_role = request.POST.get('requested_role')
        role_notes = request.POST.get('role_request_notes', '').strip()
        institution_id = request.POST.get('institution_id')
        academic_title = request.POST.get('academic_title', '').strip()
        specialization = request.POST.get('specialization', '').strip()
        evaluator_cert = request.POST.get('evaluator_certificate_number', '').strip()

        allowed_roles = [
            User.Roles.INSTITUTION_OFFICER,
            User.Roles.EXTERNAL_REVIEWER,
            User.Roles.COUNCIL_SECRETARY,
        ]

        if requested_role not in allowed_roles:
            messages.error(request, "الدور المطلوب غير متاح للتسجيل الذاتي.")
            return render(request, 'accounts/select_role.html', {'institutions': institutions})

        user.role_requested = requested_role
        user.role_request_notes = role_notes
        user.academic_title = academic_title
        user.specialization = specialization
        user.approval_status = User.ApprovalStatus.PENDING_APPROVAL

        if requested_role == User.Roles.INSTITUTION_OFFICER:
            if institution_id:
                user.institution = get_object_or_404(Institution, pk=institution_id)
            else:
                messages.error(request, "يرجى اختيار المؤسسة التعليمية التي تمثلها.")
                return render(request, 'accounts/select_role.html', {'institutions': institutions})
        elif requested_role == User.Roles.EXTERNAL_REVIEWER:
            user.evaluator_certificate_number = evaluator_cert
            if evaluator_cert:
                user.is_certified_evaluator = True

        user.save()

        record_audit_log(
            user=user,
            action='ROLE_REQUESTED',
            target_model='User',
            target_id=user.pk,
            details=f"طلب دور ({user.get_role_requested_display() if hasattr(user, 'get_role_requested_display') else requested_role}) للمستخدم ({user.username})",
            request=request
        )

        # Notify Administrators
        admins = User.objects.filter(is_superuser=True)
        for admin_user in admins:
            send_notification(
                user=admin_user,
                title="طلب اعتماد دور جديد",
                message=f"المستخدم ({user.get_full_name() or user.username}) يطلب اعتماد دوره كـ ({user.get_role_display()})",
                url="/accounts/admin/users/"
            )

        messages.info(request, "تم تسجيل طلب تحديد دورك بنجاح. حسابك حالياً قيد مراجعة وتدقيق الإدارة المختصة.")
        return redirect('accounts:pending_approval')

    return render(request, 'accounts/select_role.html', {'institutions': institutions})


@login_required
def pending_approval_view(request):
    user = request.user
    if user.is_approved:
        return redirect('core_dashboard')
    return render(request, 'accounts/pending_approval.html', {'user': user})


@login_required
def admin_users_dashboard(request):
    # Access restricted strictly to System Administrator (ADMIN), IT Director, and Council Board Member (BOARD_MEMBER)
    is_authorized = (
        request.user.is_superuser or
        request.user.role in [User.Roles.ADMIN, User.Roles.IT_DIRECTOR, User.Roles.BOARD_MEMBER]
    )
    if not is_authorized:
        messages.error(request, "غير مصرح لك: إدارة وتغيير أدوار وصلاحيات المستخدمين مقتصرة حصراً على أعضاء مجلس الإدارة ومدير النظام.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status', '')
    role_filter = request.GET.get('role', '')
    inst_filter = request.GET.get('institution', '')
    state_filter = request.GET.get('account_state', '')
    search_q = request.GET.get('q', '').strip()

    users_qs = User.objects.all().select_related('institution').order_by('-date_joined')

    if search_q:
        users_qs = users_qs.filter(
            Q(username__icontains=search_q) |
            Q(first_name__icontains=search_q) |
            Q(last_name__icontains=search_q) |
            Q(email__icontains=search_q) |
            Q(institution__name__icontains=search_q)
        )
    if status_filter and status_filter != 'ALL':
        users_qs = users_qs.filter(approval_status=status_filter)
    if role_filter:
        users_qs = users_qs.filter(Q(role=role_filter) | Q(role_requested=role_filter))
    if inst_filter:
        users_qs = users_qs.filter(institution_id=inst_filter)
    if state_filter == 'active':
        users_qs = users_qs.filter(is_active=True, is_locked=False)
    elif state_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)
    elif state_filter == 'locked':
        users_qs = users_qs.filter(is_locked=True)

    pending_count = User.objects.filter(approval_status=User.ApprovalStatus.PENDING_APPROVAL).count()
    approved_count = User.objects.filter(approval_status=User.ApprovalStatus.APPROVED).count()
    rejected_count = User.objects.filter(approval_status=User.ApprovalStatus.REJECTED).count()
    total_users_count = User.objects.count()
    active_users_count = User.objects.filter(is_active=True).count()
    inactive_users_count = User.objects.filter(is_active=False).count()
    locked_users_count = User.objects.filter(is_locked=True).count()

    context = {
        'users_list': users_qs,
        'status_filter': status_filter,
        'role_filter': role_filter,
        'inst_filter': inst_filter,
        'state_filter': state_filter,
        'search_q': search_q,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'total_users_count': total_users_count,
        'active_users_count': active_users_count,
        'inactive_users_count': inactive_users_count,
        'locked_users_count': locked_users_count,
        'roles_choices': User.Roles.choices,
        'institutions': Institution.objects.all().order_by('name'),
        'can_change_role': is_authorized,
        'is_sysadmin': request.user.role in [User.Roles.ADMIN, User.Roles.IT_DIRECTOR] or request.user.is_superuser,
    }
    return render(request, 'accounts/admin_users_dashboard.html', context)


@login_required
def admin_approve_user(request, user_id):
    is_authorized = (
        request.user.is_superuser or
        request.user.role in [User.Roles.ADMIN, User.Roles.BOARD_MEMBER]
    )
    if not is_authorized:
        messages.error(request, "غير مصرح لك: اعتماد وتغيير أدوار المستخدمين مخصص حصراً لأعضاء مجلس الإدارة ومدير النظام.")
        return redirect('core_dashboard')

    target_user = get_object_or_404(User, pk=user_id)

    # Anti-Self-Escalation Gate: User cannot approve their own account
    if target_user.pk == request.user.pk:
        messages.error(request, "حظر التصعيد الذاتي: لا يمكنك اعتماد حسابك بنفسك.")
        return redirect('accounts:admin_users_dashboard')

    if request.method == 'POST':
        # Admin / Board Member can confirm or adjust the role
        assigned_role = request.POST.get('assigned_role') or target_user.role_requested or target_user.role
        institution_id = request.POST.get('institution_id')

        # Board members cannot grant superuser privileges
        if assigned_role not in [c[0] for c in User.Roles.choices]:
            messages.error(request, "الدور المحدد غير صالح في المنظومة.")
            return redirect('accounts:admin_users_dashboard')

        target_user.role = assigned_role
        target_user.approval_status = User.ApprovalStatus.APPROVED
        target_user.approved_by = request.user
        target_user.approved_at = timezone.now()
        target_user.role_rejection_reason = ""

        if institution_id:
            target_user.institution = Institution.objects.filter(pk=institution_id).first()
        else:
            if assigned_role not in [User.Roles.INSTITUTION_OFFICER]:
                target_user.institution = None

        is_certified = request.POST.get('is_certified_evaluator')
        if is_certified is not None:
            target_user.is_certified_evaluator = (is_certified in ['1', 'true', 'True', True, 'on'])
        evaluator_cert = request.POST.get('evaluator_certificate_number')
        if evaluator_cert is not None:
            target_user.evaluator_certificate_number = evaluator_cert.strip()

        target_user.save()

        record_audit_log(
            user=request.user,
            action='USER_ROLE_APPROVED',
            target_model='User',
            target_id=target_user.pk,
            details=f"اعتماد وتفعيل حساب المستخدم ({target_user.username}) بالدور ({target_user.get_role_display()}) بواسطة ({request.user.username})",
            request=request
        )

        send_notification(
            user=target_user,
            title="تم اعتماد حسابك رسمياً",
            message=f"مرحباً بك! تمت الموافقة على طلبك وتفعيل صلاحياتك كـ ({target_user.get_role_display()}) في البوابة.",
            url="/"
        )

        messages.success(request, f"تمت الموافقة بنجاح على حساب المستخدم ({target_user.username}) وتفعيل دوره كـ ({target_user.get_role_display()}).")
        return redirect('accounts:admin_users_dashboard')

    return redirect('accounts:admin_users_dashboard')


@login_required
def admin_reject_user(request, user_id):
    is_authorized = (
        request.user.is_superuser or
        request.user.role in [User.Roles.ADMIN, User.Roles.BOARD_MEMBER]
    )
    if not is_authorized:
        messages.error(request, "غير مصرح لك: رفض واعتماد الأدوار مخصص حصراً لأعضاء مجلس الإدارة ومدير النظام.")
        return redirect('core_dashboard')

    target_user = get_object_or_404(User, pk=user_id)

    # Anti-Self-Escalation Gate: User cannot approve their own account
    if target_user.pk == request.user.pk:
        messages.error(request, "حظر التصعيد الذاتي: لا يمكنك اعتماد حسابك بنفسك.")
        return redirect('accounts:admin_users_dashboard')

    if request.method == 'POST':
        reason = request.POST.get('rejection_reason', '').strip()
        if not reason:
            messages.error(request, "يرجى إدخال سبب الرفض؛ لا يمكن رفض الطلب دون توضيح الأسباب الرسمية.")
            return redirect('accounts:admin_users_dashboard')

        target_user.approval_status = User.ApprovalStatus.REJECTED
        target_user.role_rejection_reason = reason
        target_user.approved_by = request.user
        target_user.approved_at = timezone.now()
        target_user.save()

        record_audit_log(
            user=request.user,
            action='USER_ROLE_REJECTED',
            target_model='User',
            target_id=target_user.pk,
            details=f"رفض طلب اعتماد المستخدم ({target_user.username}). السبب: {reason}",
            request=request
        )

        send_notification(
            user=target_user,
            title="إفادة حول طلب تسجيل الحساب",
            message=f"نعتذر عن عدم قبول طلب تحديد الدور بالصفة المطلوبة للأسباب التالية: {reason}",
            url="/accounts/pending-approval/"
        )

        messages.warning(request, f"تم رفض طلب المستخدم ({target_user.username}) وتوثيق السبب وإشعاره بالقرار.")
        return redirect('accounts:admin_users_dashboard')

    return redirect('accounts:admin_users_dashboard')


@login_required
def change_user_role(request, user_id):
    """
    Exclusively allows Council Board Members (BOARD_MEMBER) and System Administrator (ADMIN / superuser)
    to modify any active user's system role.
    """
    is_authorized = (
        request.user.is_superuser or
        request.user.role in [User.Roles.ADMIN, User.Roles.BOARD_MEMBER]
    )
    if not is_authorized:
        messages.error(request, "غير مصرح لك: خاصية تغيير دور المستخدم مقتصرة حصراً على أعضاء مجلس الإدارة ومدير النظام.")
        return redirect('core_dashboard')

    target_user = get_object_or_404(User, pk=user_id)

    # Anti-Self-Escalation Gate: User cannot approve their own account
    if target_user.pk == request.user.pk:
        messages.error(request, "حظر التصعيد الذاتي: لا يمكنك اعتماد حسابك بنفسك.")
        return redirect('accounts:admin_users_dashboard')

    if request.method == 'POST':
        new_role = request.POST.get('new_role')
        reason = request.POST.get('change_reason', '').strip()
        institution_id = request.POST.get('institution_id')

        valid_roles = [c[0] for c in User.Roles.choices]
        if new_role not in valid_roles:
            messages.error(request, "الدور المطلوب اختياره غير معروف بالنظام.")
            return redirect('accounts:admin_users_dashboard')

        # Safeguard: Prevent non-superusers from demoting the last superuser
        if target_user.is_superuser and new_role != User.Roles.ADMIN and not request.user.is_superuser:
            messages.error(request, "لا يمكن تغيير دور مدير النظام الفني العام.")
            return redirect('accounts:admin_users_dashboard')

        old_role = target_user.role
        target_user.role = new_role
        if institution_id:
            target_user.institution = Institution.objects.filter(pk=institution_id).first()
        elif new_role not in [User.Roles.INSTITUTION_OFFICER]:
            target_user.institution = None

        target_user.save()

        # Audit logging
        record_audit_log(
            user=request.user,
            action='USER_ROLE_CHANGED',
            target_model='User',
            target_id=target_user.pk,
            details=f"تعديل دور المستخدم ({target_user.username}) من ({old_role}) إلى ({new_role}). السبب: {reason or 'قرار إداري'}",
            request=request
        )

        # Notify affected user
        send_notification(
            user=target_user,
            title="تحديث صفة ودور حسابك في المنظومة",
            message=f"نحيطك علماً بأنه تم تعديل دور حسابك رسمياً إلى: ({target_user.get_role_display()}).",
            url="/"
        )

        messages.success(request, f"تم بنجاح تغيير دور المستخدم ({target_user.username}) إلى ({target_user.get_role_display()}).")
        return redirect('accounts:admin_users_dashboard')

    return redirect('accounts:admin_users_dashboard')


@login_required
def notifications_list(request):
    is_master_admin = (request.user.username == 'najeebADMIN' or (request.user.is_superuser and request.user.role == User.Roles.ADMIN))
    scope = request.GET.get('scope', 'all' if is_master_admin else 'mine')

    if is_master_admin and scope == 'all':
        notifications = Notification.objects.all().select_related('recipient').order_by('-created_at')
    else:
        notifications = request.user.notifications.all().order_by('-created_at')
        request.user.notifications.filter(is_read=False).update(is_read=True)

    return render(request, 'accounts/notifications.html', {
        'notifications': notifications,
        'is_master_admin': is_master_admin,
        'current_scope': scope,
    })


@login_required
def notification_mark_read(request, pk):
    is_master_admin = (request.user.username == 'najeebADMIN' or (request.user.is_superuser and request.user.role == User.Roles.ADMIN))
    if is_master_admin:
        notif = get_object_or_404(Notification, pk=pk)
    else:
        notif = get_object_or_404(Notification, pk=pk, recipient=request.user)

    notif.is_read = True
    notif.save(update_fields=['is_read'])
    if notif.url:
        return redirect(notif.url)
    return redirect('accounts:notifications_list')

@login_required
def dashboard_view(request):
    user = request.user
    if not user.is_approved:
        return redirect('accounts:pending_approval')

    # Minister of Higher Education direct access to Ministerial Strategic Dashboard
    if user.role == User.Roles.MINISTER:
        return redirect('decisions:minister_dashboard')
    
    # Base QuerySet
    if user.is_institution_rep and user.institution:
        apps_qs = AccreditationApplication.objects.filter(institution=user.institution)
    elif user.is_reviewer:
        apps_qs = AccreditationApplication.objects.filter(review_team__members__user=user).distinct()
    else:
        apps_qs = AccreditationApplication.objects.all()

    # Track-separated counts
    inst_apps_count = apps_qs.filter(track=AccreditationTrackType.INSTITUTIONAL).count()
    prog_apps_count = apps_qs.filter(track=AccreditationTrackType.PROGRAMMATIC).count()
    
    # Decisions & Accredited items
    if user.is_institution_rep and user.institution:
        decisions_qs = AccreditationDecision.objects.filter(application__institution=user.institution)
    elif user.is_reviewer:
        decisions_qs = AccreditationDecision.objects.filter(application__review_team__members__user=user).distinct()
    else:
        decisions_qs = AccreditationDecision.objects.all()

    full_accredited_count = decisions_qs.filter(decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION).count()
    conditional_accredited_count = decisions_qs.filter(decision_type=AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION).count()
    
    # Stage breakdown
    stages_stat = {
        'stage_1': apps_qs.filter(current_stage=1).count(),
        'stage_2': apps_qs.filter(current_stage=2).count(),
        'stage_3': apps_qs.filter(current_stage=3).count(),
        'stage_4': apps_qs.filter(current_stage=4).count(),
        'stage_5': apps_qs.filter(current_stage=5).count(),
        'stage_6': apps_qs.filter(current_stage=6).count(),
        'stage_7': apps_qs.filter(current_stage=7).count(),
    }

    recent_applications = apps_qs.select_related('institution', 'program').order_by('-created_at')[:8]
    total_institutions = Institution.objects.count()
    total_programs = AcademicProgram.objects.count()

    # Role-specific operational datasets and Directorate workspaces
    role = user.role
    directorate_data = {}

    if role in [User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_VICE_CHAIRMAN, User.Roles.BOARD_MEMBER]:
        from apps.accreditation.models import GrievanceAppeal
        directorate_data = {
            'pending_board_reviews': AccreditationApplication.objects.filter(status__in=[
                ApplicationStatus.PENDING_REVIEW,
                ApplicationStatus.FINAL_REPORT_READY,
                ApplicationStatus.IN_COUNCIL_REVIEW
            ]).count(),
            'pending_board_grievances': GrievanceAppeal.objects.filter(status=GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW).count(),
            'total_decisions_issued': AccreditationDecision.objects.count(),
        }
    elif role == User.Roles.COUNCIL_SECRETARY_GENERAL:
        from apps.accreditation.models import GrievanceAppeal
        from apps.operations.models import Invoice
        directorate_data = {
            'pending_intake': AccreditationApplication.objects.filter(status__in=[ApplicationStatus.PENDING_REVIEW, ApplicationStatus.SUBMITTED]).count(),
            'pending_desk': AccreditationApplication.objects.filter(status=ApplicationStatus.DESK_UNDER_REVIEW).count(),
            'pending_panel': AccreditationApplication.objects.filter(status=ApplicationStatus.DESK_ACCEPTED).count(),
            'active_appeals': GrievanceAppeal.objects.filter(status__in=[GrievanceAppeal.AppealStatus.SUBMITTED, GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW]).count(),
            'unpaid_invoices': Invoice.objects.filter(status=Invoice.PaymentStatus.UNPAID).count(),
        }
    elif role == User.Roles.DG_ACCREDITATION:
        directorate_data = {
            'pending_desk_review': AccreditationApplication.objects.filter(status__in=[
                ApplicationStatus.DESK_UNDER_REVIEW,
                ApplicationStatus.SELF_EVALUATION_SUBMITTED,
                ApplicationStatus.SUBMITTED
            ]).count(),
            'deficiency_followups': AccreditationApplication.objects.filter(status=ApplicationStatus.DESK_DEFICIENCY).count(),
            'accepted_desk_reviews': AccreditationApplication.objects.filter(status=ApplicationStatus.DESK_ACCEPTED).count(),
        }
    elif role == User.Roles.DG_EVALUATION:
        from apps.site_visits.models import SiteVisitSchedule
        directorate_data = {
            'pending_team_assignment': AccreditationApplication.objects.filter(status=ApplicationStatus.DESK_ACCEPTED).count(),
            'active_site_visits': SiteVisitSchedule.objects.filter(status__in=[SiteVisitSchedule.VisitStatus.SCHEDULED, SiteVisitSchedule.VisitStatus.IN_PROGRESS]).count() if 'apps.site_visits' in settings.INSTALLED_APPS else 0,
            'reports_pending_council': AccreditationApplication.objects.filter(status=ApplicationStatus.FINAL_REPORT_READY).count(),
            'certified_evaluators_count': User.objects.filter(role=User.Roles.EXTERNAL_REVIEWER, is_certified_evaluator=True).count(),
        }
    elif role == User.Roles.DG_FINANCE_ADMIN:
        from apps.operations.models import Invoice
        directorate_data = {
            'receipts_pending_verification': Invoice.objects.filter(status=Invoice.PaymentStatus.UNPAID).exclude(payment_reference='').count(),
            'total_paid_invoices': Invoice.objects.filter(status=Invoice.PaymentStatus.PAID).count(),
            'unpaid_invoices_count': Invoice.objects.filter(status=Invoice.PaymentStatus.UNPAID).count(),
        }
    elif role == User.Roles.LEGAL_DIRECTOR:
        from apps.accreditation.models import GrievanceAppeal
        directorate_data = {
            'pending_legal_examination': GrievanceAppeal.objects.filter(status=GrievanceAppeal.AppealStatus.SUBMITTED).count(),
            'under_committee_review': GrievanceAppeal.objects.filter(status=GrievanceAppeal.AppealStatus.UNDER_COMMITTEE_REVIEW).count(),
            'resolved_appeals': GrievanceAppeal.objects.filter(status__in=[
                GrievanceAppeal.AppealStatus.ACCEPTED_RECONSIDERATION,
                GrievanceAppeal.AppealStatus.REJECTED_DECISION_UPHELD
            ]).count(),
        }

    primary_guidance = None
    target_app = None
    if user.is_institution_rep and user.institution:
        target_app = apps_qs.order_by('-updated_at').first()
    elif user.is_reviewer:
        target_app = apps_qs.filter(current_stage__in=[3, 4]).order_by('-updated_at').first() or apps_qs.first()
    elif role == User.Roles.DG_ACCREDITATION:
        target_app = apps_qs.filter(current_stage__in=[1, 3]).order_by('created_at').first() or apps_qs.first()
    elif role == User.Roles.DG_EVALUATION:
        target_app = apps_qs.filter(current_stage=4).order_by('created_at').first() or apps_qs.first()
    elif role in [User.Roles.BOARD_MEMBER, User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_VICE_CHAIRMAN]:
        target_app = apps_qs.filter(current_stage__in=[5, 6]).order_by('created_at').first() or apps_qs.first()

    if target_app:
        from apps.accreditation.guidance_engine import get_contextual_guidance
        primary_guidance = get_contextual_guidance(user, target_app)
        if primary_guidance:
            primary_guidance['target_app'] = target_app

    context = {
        'inst_apps_count': inst_apps_count,
        'prog_apps_count': prog_apps_count,
        'full_accredited_count': full_accredited_count,
        'conditional_accredited_count': conditional_accredited_count,
        'stages_stat': stages_stat,
        'recent_applications': recent_applications,
        'total_institutions': total_institutions,
        'total_programs': total_programs,
        'directorate_data': directorate_data,
        'user_role': role,
        'guidance': primary_guidance,
    }
    return render(request, 'dashboard/index.html', context)


# ==============================================================================
# PHASE 2: PERMISSION MANAGEMENT & AUDIT VIEWS
# ==============================================================================

@login_required
def permission_matrix_view(request):
    """
    Renders the dynamic role-permission matrix with search, filters, role user counts,
    allowed actions breakdown, and conflict detection.
    Authorized for ADMIN users with can_manage_permissions capability.
    """
    if not (has_permission(request.user, 'can_manage_permissions') or (request.user.is_superuser and request.user.role == User.Roles.ADMIN)):
        messages.error(request, "غير مصرح لك: استعراض وإدارة الصلاحيات مخصصة حصراً لمدير النظام التقني.")
        return redirect('core_dashboard')

    search_q = request.GET.get('q', '').strip()
    module_filter = request.GET.get('module', '').strip()

    permissions_qs = DynamicPermission.objects.all().order_by('module', 'codename')
    if search_q:
        permissions_qs = permissions_qs.filter(
            Q(name__icontains=search_q) |
            Q(codename__icontains=search_q) |
            Q(description__icontains=search_q)
        )
    if module_filter:
        permissions_qs = permissions_qs.filter(module=module_filter)

    roles = User.Roles.choices

    # Build matrix map: {perm_id: {role: assignment}}
    assignments_qs = RolePermissionAssignment.objects.select_related('permission').all()
    matrix = {}
    role_perm_counts = {}
    for a in assignments_qs:
        matrix.setdefault(a.permission_id, {})[a.role] = a
        if a.is_granted:
            role_perm_counts[a.role] = role_perm_counts.get(a.role, 0) + 1

    # Role summary with assigned users and permissions count
    roles_summary = []
    for role_val, role_label in roles:
        role_users = list(User.objects.filter(role=role_val).values_list('username', flat=True))
        roles_summary.append({
            'code': role_val,
            'label': role_label,
            'perms_count': role_perm_counts.get(role_val, 0),
            'users_count': len(role_users),
            'users_sample': role_users[:5],
        })

    # Organize permissions by module
    modules = {}
    for p in permissions_qs:
        modules.setdefault(p.get_module_display(), []).append({
            'permission': p,
            'role_status': {
                role_val: matrix.get(p.id, {}).get(role_val)
                for role_val, _ in roles
            }
        })

    active_overrides_count = UserPermissionOverride.objects.filter(is_active=True).count()
    audit_count = PermissionAuditRecord.objects.count()
    from apps.accounts.sysadmin_views import detect_permission_conflicts
    conflicts = detect_permission_conflicts()

    context = {
        'modules': modules,
        'module_choices': DynamicPermission.Module.choices,
        'roles': roles,
        'roles_summary': roles_summary,
        'active_overrides_count': active_overrides_count,
        'audit_count': audit_count,
        'conflicts': conflicts,
        'search_q': search_q,
        'module_filter': module_filter,
    }
    return render(request, 'accounts/permission_matrix.html', context)


@login_required
def toggle_role_permission(request):
    """
    Toggles a permission grant/denial for an administrative role.
    Requires POST with CSRF and administrative reason.
    Enforces Hard Governance Gates and Anti-Self-Escalation.
    """
    if not (has_permission(request.user, 'can_manage_permissions') or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بتعديل صلاحيات الأدوار.")
        return redirect('core_dashboard')

    if request.method != 'POST':
        return redirect('accounts:permission_matrix')

    perm_id = request.POST.get('permission_id')
    role = request.POST.get('role')
    action = request.POST.get('action')  # 'grant' or 'deny'
    reason = request.POST.get('reason', '').strip()

    if not reason:
        messages.error(request, "السبب الإداري والمبرر إلزامي لتعديل صلاحيات الدور.")
        return redirect('accounts:permission_matrix')

    permission = get_object_or_404(DynamicPermission, pk=perm_id)

    # 1. Governance Gate Check:
    if permission.codename in GOVERNANCE_LOCKED_PERMISSIONS:
        allowed_roles = GOVERNANCE_LOCKED_PERMISSIONS[permission.codename]
        if action == 'grant' and role not in allowed_roles:
            record_permission_audit(
                actor=request.user,
                action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
                target_role=role,
                permission_codename=permission.codename,
                reason=f"Blocked attempt to grant governance-locked permission {permission.codename} to role {role}",
                request=request
            )
            messages.error(request, f"حظر الحوكمة السيادية: الصلاحية ({permission.name}) مقيدة سيادياً ولا يمكن منحها للدور ({role}).")
            return redirect('accounts:permission_matrix')

    # 2. Anti-Self-Escalation Check:
    # An admin cannot modify permissions assigned to their own current role
    if request.user.role == role and not request.user.is_superuser:
        record_permission_audit(
            actor=request.user,
            action_type=PermissionAuditRecord.ActionType.SECURITY_GATE_BLOCKED,
            target_role=role,
            permission_codename=permission.codename,
            reason="Blocked self-escalation attempt: user attempted to modify their own role permissions.",
            request=request
        )
        messages.error(request, "حظر التصعيد الذاتي: لا يمكنك تعديل الصلاحيات الممنوحة لدورك الإداري الحالي.")
        return redirect('accounts:permission_matrix')

    is_grant = (action == 'grant')
    assignment, created = RolePermissionAssignment.objects.get_or_create(
        role=role,
        permission=permission,
        defaults={'is_granted': is_grant, 'updated_by': request.user}
    )
    prev_val = "None" if created else ("Granted" if assignment.is_granted else "Denied")
    if not created:
        assignment.is_granted = is_grant
        assignment.updated_by = request.user
        assignment.save(update_fields=['is_granted', 'updated_by', 'updated_at'])

    record_permission_audit(
        actor=request.user,
        action_type=PermissionAuditRecord.ActionType.ROLE_ASSIGNMENT_CHANGED,
        target_role=role,
        permission_codename=permission.codename,
        previous_value=prev_val,
        new_value="Granted" if is_grant else "Denied",
        reason=reason,
        request=request
    )

    action_label = "منح" if is_grant else "حجب"
    messages.success(request, f"تم بنجاح {action_label} الصلاحية ({permission.name}) للدور ({assignment.get_role_display()}).")
    return redirect('accounts:permission_matrix')


@login_required
def manage_user_override_view(request):
    """
    Manages individual user permission overrides (temporary grants/revokes).
    Preserves complete historical audit trail of past overrides.
    """
    if not (has_permission(request.user, 'can_manage_permissions') or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بإدارة استثناءات المستخدمين.")
        return redirect('core_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'revoke_active':
            override_id = request.POST.get('override_id')
            reason = request.POST.get('reason', '').strip()
            try:
                revoke_user_override(
                    override_id=override_id,
                    revoked_by=request.user,
                    reason=reason or "إلغاء استثناء يدوي",
                    request=request
                )
                messages.success(request, "تم بنجاح إلغاء وأرشفة الاستثناء الفردي.")
            except Exception as e:
                messages.error(request, f"فشل إلغاء الاستثناء: {str(e)}")
            return redirect('accounts:user_overrides')

        elif action == 'create_override':
            target_user_id = request.POST.get('target_user_id')
            perm_id = request.POST.get('permission_id')
            override_type = request.POST.get('override_type')  # GRANT or REVOKE
            reason = request.POST.get('reason', '').strip()
            expires_at_str = request.POST.get('expires_at')

            if not reason:
                messages.error(request, "السبب الإداري والمبرر إلزامي لإنشاء استثناء مستخدم.")
                return redirect('accounts:user_overrides')

            target_user = get_object_or_404(User, pk=target_user_id)
            permission = get_object_or_404(DynamicPermission, pk=perm_id)

            expires_at = None
            if expires_at_str:
                try:
                    from datetime import datetime
                    expires_at = timezone.make_aware(datetime.strptime(expires_at_str, '%Y-%m-%d'))
                except ValueError:
                    expires_at = None

            try:
                rotate_user_override(
                    user=target_user,
                    permission=permission,
                    override_type=override_type,
                    reason=reason,
                    granted_by=request.user,
                    expires_at=expires_at,
                    request=request
                )
                messages.success(request, f"تم بنجاح إنشاء الاستثناء الفردي للمستخدم ({target_user.username}).")
            except PermissionDenied as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f"خطأ أثناء تطبيق الاستثناء: {str(e)}")
            return redirect('accounts:user_overrides')

    # GET: List active and historical overrides
    active_overrides = UserPermissionOverride.objects.filter(is_active=True).select_related('user', 'permission', 'granted_by').order_by('-created_at')
    archived_overrides = UserPermissionOverride.objects.filter(is_active=False).select_related('user', 'permission', 'granted_by', 'revoked_by').order_by('-revoked_at')[:30]
    users_list = User.objects.filter(is_active=True).order_by('username')
    permissions_list = DynamicPermission.objects.all().order_by('module', 'name')

    context = {
        'active_overrides': active_overrides,
        'archived_overrides': archived_overrides,
        'users_list': users_list,
        'permissions_list': permissions_list,
    }
    return render(request, 'accounts/permission_overrides.html', context)


@login_required
def permission_audit_view(request):
    """
    Read-only view of the permission audit log.
    Strictly protected; no modifications or deletes permitted.
    """
    if not (has_permission(request.user, 'can_manage_permissions') or has_permission(request.user, 'can_view_technical_audit') or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بالاطلاع على سجلات تدقيق الصلاحيات.")
        return redirect('core_dashboard')

    qs = PermissionAuditRecord.objects.select_related('actor', 'target_user').all()

    # Filtering
    actor_filter = request.GET.get('actor')
    target_user_filter = request.GET.get('target_user')
    action_filter = request.GET.get('action_type')
    perm_filter = request.GET.get('permission')

    if actor_filter:
        qs = qs.filter(actor__username__icontains=actor_filter)
    if target_user_filter:
        qs = qs.filter(target_user__username__icontains=target_user_filter)
    if action_filter:
        qs = qs.filter(action_type=action_filter)
    if perm_filter:
        qs = qs.filter(permission_codename__icontains=perm_filter)

    paginator = Paginator(qs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'action_types': PermissionAuditRecord.ActionType.choices,
        'filters': {
            'actor': actor_filter or '',
            'target_user': target_user_filter or '',
            'action_type': action_filter or '',
            'permission': perm_filter or '',
        }
    }
    return render(request, 'accounts/permission_audit.html', context)


@login_required
def admin_technical_diagnostics(request):
    """
    Restricted, read-only technical diagnostics for authorized administrators.
    Requires can_view_technical_audit permission.
    Strictly GET-only; rejects any state mutations.
    Requires an explicit access reason, and audits every diagnostic entry.
    """
    if not (has_permission(request.user, 'can_view_technical_audit') or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: وضع التشخيص الفني مخصص حصراً للمسؤولين المصرح لهم تقنياً.")
        return redirect('core_dashboard')

    # Strictly reject modifying methods
    if request.method not in ['GET']:
        raise PermissionDenied("Technical diagnostics endpoint is strictly read-only.")

    # Require an explicit access reason
    reason = request.GET.get('diagnostic_reason', '').strip()
    session_reason = request.session.get('active_diagnostic_reason')

    if not reason and not session_reason:
        # Prompt for reason
        return render(request, 'accounts/admin_diagnostics_prompt.html')

    active_reason = reason or session_reason
    request.session['active_diagnostic_reason'] = active_reason

    # Record Diagnostic Access in Audit Log
    record_permission_audit(
        actor=request.user,
        action_type=PermissionAuditRecord.ActionType.DIAGNOSTIC_ACCESSED,
        target_role=request.user.role,
        reason=active_reason,
        request=request
    )

    # Gather safe system indicators
    db_name = connection.settings_dict.get('ENGINE', '').split('.')[-1]

    raw_diagnostics = {
        'system_status': {
            'platform': platform.platform(),
            'python_version': sys.version.split(' ')[0],
            'server_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z'),
            'timezone': timezone.get_current_timezone_name(),
        },
        'database_health': {
            'engine': db_name,
            'is_connected': connection.ensure_connection() is None,
            'total_tables': len(connection.introspection.table_names()),
        },
        'scheduler_metrics': {
            'scheduled_reminders_count': ScheduledReminderLog.objects.count(),
            'recent_scheduled_logs': list(
                ScheduledReminderLog.objects.order_by('-sent_at')[:5].values(
                    'reminder_type', 'target_content_type', 'target_id', 'sent_at'
                )
            ),
        },
        'application_summary': {
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
            'pending_approval': User.objects.filter(approval_status=User.ApprovalStatus.PENDING_APPROVAL).count(),
        }
    }

    # Redact any confidential or sensitive variables
    scrubbed_diagnostics = redact_sensitive_diagnostics(raw_diagnostics)
    from apps.accounts.sysadmin_views import check_live_system_health, calculate_storage_metrics
    import django

    context = {
        'diagnostics': scrubbed_diagnostics,
        'diagnostic_reason': active_reason,
        'live_health': check_live_system_health(),
        'storage_metrics': calculate_storage_metrics(),
        'django_version': django.get_version(),
    }
    return render(request, 'accounts/admin_diagnostics.html', context)


@login_required
def sms_logs_view(request):
    """
    Sovereign SMS Gateway Management & Delivery Audit Log:
    Accessible by IT Director, Council Secretary General, Secretariat, and System Administrators.
    """
    from apps.accounts.sms_service import send_sms

    is_authorized = (
        request.user.role in [
            User.Roles.IT_DIRECTOR,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN,
        ]
        or request.user.is_superuser
    )
    if not is_authorized:
        messages.error(request, "غير مصرح لك: استعراض وإدارة بوابة الرسائل النصية مخصص لإدارة نظم المعلومات والأمانة العامة فقط.")
        return redirect('core_dashboard')

    if request.method == 'POST' and 'send_test_sms' in request.POST:
        test_phone = request.POST.get('test_phone', '').strip()
        test_message = request.POST.get('test_message', '').strip()
        test_type = request.POST.get('test_type', SMSLog.MessageType.GENERAL_ALERT)

        if not test_phone or not test_message:
            messages.error(request, "يرجى إدخال رقم الهاتف ونص الرسالة.")
        else:
            log_entry = send_sms(test_phone, test_message, message_type=test_type)
            if log_entry:
                if log_entry.status == SMSLog.Status.DELIVERED:
                    messages.success(request, f"تم بنجاح بث الرسالة النصية للرقم ({log_entry.phone_number}) عبر المشغل الحي ({log_entry.telecom_operator}) برقم مرجعي ({log_entry.gateway_reference}).")
                else:
                    messages.success(request, f"تم بنجاح توثيق ومعالجة الرسالة للرقم ({log_entry.phone_number}) عبر شبكة ({log_entry.telecom_operator}) بالرقم المرجعي ({log_entry.gateway_reference}) في سجل البوابة السيادي (وضع المحاكاة الداخلي).")
            else:
                messages.error(request, "فشل إرسال الرسالة، يرجى التأكد من صحة رقم الهاتف اليمني.")
        return redirect('accounts:sms_logs')

    logs = SMSLog.objects.select_related('recipient').all().order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        logs = logs.filter(status=status_filter)

    type_filter = request.GET.get('type')
    if type_filter:
        logs = logs.filter(message_type=type_filter)

    total_count = SMSLog.objects.count()
    sent_count = SMSLog.objects.filter(status__in=[SMSLog.Status.SENT, SMSLog.Status.DELIVERED]).count()
    failed_count = SMSLog.objects.filter(status=SMSLog.Status.FAILED).count()

    paginator = Paginator(logs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'accounts/sms_logs.html', {
        'page_obj': page_obj,
        'total_count': total_count,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'statuses': SMSLog.Status.choices,
        'message_types': SMSLog.MessageType.choices,
        'current_status': status_filter or '',
        'current_type': type_filter or '',
    })


# ==============================================================================
# MY WORKSPACE LIBRARY & DOCUMENT VAULT (قسم مكتبتي)
# ==============================================================================

from django.http import FileResponse, HttpResponseForbidden, Http404
from django.db.models import Q
from apps.accounts.library_service import get_authorized_recipients, sync_system_assets_to_library

@login_required
def library_index_view(request):
    """
    My Workspace Library (قسم مكتبتي):
    Displays 3 smart tabs:
    1. تقاريري وملفاتي المنشأة (Created & Uploaded by Me)
    2. المستندات والتقارير المستلمة (Received from Other Target Users)
    3. الصور والأدلة والشواهد (Visual Evidences & Field Photos)
    """
    user = request.user

    # Auto-synchronize institutional system assets (Certificates, Decisions, Reports, Evidences)
    try:
        sync_system_assets_to_library(user)
        if request.GET.get('sync') == '1':
            messages.success(request, "تمت مزامنة وتحديث مستندات وشهادات وتقارير مكتبتك بنجاح وفق خطوط السلطة والصلاحيات.")
    except Exception:
        pass

    active_tab = request.GET.get('tab', 'my_docs')
    search_q = request.GET.get('q', '').strip()
    type_filter = request.GET.get('type', '')

    # 1. My Created / Uploaded Documents
    my_docs = UserDocument.objects.filter(owner=user, is_archived=False).select_related('application__institution')
    if type_filter:
        my_docs = my_docs.filter(doc_type=type_filter)
    if search_q:
        my_docs = my_docs.filter(Q(title__icontains=search_q) | Q(description__icontains=search_q))

    # 2. Received Documents from others
    received_shares = DocumentShare.objects.filter(recipient=user, document__is_archived=False).select_related(
        'document__owner', 'document__application__institution', 'sender'
    )
    if search_q:
        received_shares = received_shares.filter(
            Q(document__title__icontains=search_q) |
            Q(document__description__icontains=search_q) |
            Q(sender__first_name__icontains=search_q) |
            Q(sender__last_name__icontains=search_q) |
            Q(notes__icontains=search_q)
        )

    # 3. Images, Field Photos, and Evidences (Tenant & Role Isolated)
    if user.is_institution_rep and user.institution:
        media_evidences = UserDocument.objects.filter(
            Q(owner=user) | Q(shares__recipient=user) | Q(application__institution=user.institution),
            doc_type__in=[UserDocument.DocumentType.IMAGE, UserDocument.DocumentType.EVIDENCE],
            is_archived=False
        ).select_related('owner', 'application__institution').distinct()
    elif user.is_reviewer:
        media_evidences = UserDocument.objects.filter(
            Q(owner=user) | Q(shares__recipient=user) | Q(application__review_team__members__user=user),
            doc_type__in=[UserDocument.DocumentType.IMAGE, UserDocument.DocumentType.EVIDENCE],
            is_archived=False
        ).select_related('owner', 'application__institution').distinct()
    elif user.is_superuser or user.role in [User.Roles.ADMIN, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_CHAIRMAN]:
        media_evidences = UserDocument.objects.filter(
            doc_type__in=[UserDocument.DocumentType.IMAGE, UserDocument.DocumentType.EVIDENCE],
            is_archived=False
        ).select_related('owner', 'application__institution').distinct()
    else:
        media_evidences = UserDocument.objects.filter(
            Q(owner=user) | Q(shares__recipient=user),
            doc_type__in=[UserDocument.DocumentType.IMAGE, UserDocument.DocumentType.EVIDENCE],
            is_archived=False
        ).select_related('owner', 'application__institution').distinct()

    if search_q:
        media_evidences = media_evidences.filter(Q(title__icontains=search_q) | Q(description__icontains=search_q))

    # Metrics
    my_docs_count = my_docs.count() if (type_filter or search_q) else UserDocument.objects.filter(owner=user, is_archived=False).count()
    received_count = received_shares.count() if search_q else DocumentShare.objects.filter(recipient=user, document__is_archived=False).count()
    media_count = media_evidences.count()

    # Authorized recipients filter for sending modal
    authorized_recipients = get_authorized_recipients(user)

    # Relevant applications for uploading
    if user.is_institution_rep and user.institution:
        relevant_apps = AccreditationApplication.objects.filter(institution=user.institution)
    elif user.is_reviewer:
        relevant_apps = AccreditationApplication.objects.filter(review_team__members__user=user).distinct()
    else:
        relevant_apps = AccreditationApplication.objects.all().order_by('-created_at')[:30]

    context = {
        'active_tab': active_tab,
        'my_docs': my_docs.order_by('-created_at'),
        'received_shares': received_shares.order_by('-shared_at'),
        'media_evidences': media_evidences.order_by('-created_at'),
        'my_docs_count': my_docs_count,
        'received_count': received_count,
        'media_count': media_count,
        'authorized_recipients': authorized_recipients,
        'relevant_apps': relevant_apps,
        'doc_types': UserDocument.DocumentType.choices,
        'search_q': search_q,
        'type_filter': type_filter,
    }
    return render(request, 'accounts/library.html', context)


@login_required
def library_upload_view(request):
    """Handles uploading a new file/report/evidence to user's library."""
    if request.method != 'POST':
        return redirect('accounts:library_index')

    title = request.POST.get('title', '').strip()
    doc_type = request.POST.get('doc_type', UserDocument.DocumentType.REPORT)
    description = request.POST.get('description', '').strip()
    app_id = request.POST.get('application_id')
    uploaded_file = request.FILES.get('file')

    if not title or not uploaded_file:
        messages.error(request, "يرجى تحديد عنوان الوثيقة واختيار الملف المراد رفعه.")
        return redirect('accounts:library_index')

    application = None
    if app_id:
        try:
            application = AccreditationApplication.objects.get(pk=app_id)
        except (AccreditationApplication.DoesNotExist, ValueError):
            application = None

    doc = UserDocument.objects.create(
        owner=request.user,
        title=title,
        doc_type=doc_type,
        description=description,
        file=uploaded_file,
        file_size_bytes=uploaded_file.size,
        application=application
    )

    record_audit_log(
        user=request.user,
        action='LIBRARY_DOCUMENT_UPLOADED',
        target_model='UserDocument',
        target_id=doc.pk,
        details=f"رفع وحفظ مستند جديد ({doc.title}) بنوع ({doc.get_doc_type_display()}) بمكتبة المستخدم",
        request=request
    )

    messages.success(request, f"تم بنجاح حفظ الوثيقة ({doc.title}) في مكتبتك الخاصة.")
    tab = 'media' if doc.is_image else 'my_docs'
    return redirect(f"/accounts/library/?tab={tab}")


@login_required
def library_send_view(request, doc_id):
    """
    Dispatches a document from user's library to an authorized recipient
    strictly verified against the separation of powers matrix.
    """
    if request.method != 'POST':
        return redirect('accounts:library_index')

    doc = get_object_or_404(UserDocument, pk=doc_id, is_archived=False)

    # Check permission to share: User must be owner OR recipient of an existing share
    is_owner = (doc.owner_id == request.user.id)
    is_recipient = doc.shares.filter(recipient=request.user).exists()
    if not (is_owner or is_recipient or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بإحالة أو إرسال هذه الوثيقة.")
        return redirect('accounts:library_index')

    recipient_id = request.POST.get('recipient_id')
    notes = request.POST.get('notes', '').strip()

    if not recipient_id:
        messages.error(request, "يرجى اختيار المستخدم المصرح له باستلام الوثيقة.")
        return redirect('accounts:library_index')

    # Security Governance Gate: Recipient MUST be in get_authorized_recipients
    authorized_qs = get_authorized_recipients(request.user)
    try:
        recipient = authorized_qs.get(pk=recipient_id)
    except User.DoesNotExist:
        messages.error(request, "انتهاك حوكمة: لا تملك الصلاحية النظامية لإحالة الوثائق لهذا المستخدم وفق مصفوفة فصل السلطات.")
        return redirect('accounts:library_index')

    # Create or update share
    share, created = DocumentShare.objects.get_or_create(
        document=doc,
        sender=request.user,
        recipient=recipient,
        defaults={'notes': notes}
    )
    if not created:
        share.notes = notes
        share.shared_at = timezone.now()
        share.is_read = False
        share.save()

    # Dispatch notification to recipient
    send_notification(
        user=recipient,
        title=f"استلام مستند جديد في مكتبتك من {request.user.get_full_name() or request.user.username}",
        message=f"أحال إليك ({request.user.get_full_name() or request.user.username} - {request.user.get_role_display()}) وثيقة ({doc.title}) بمكتبتك. الملاحظة: {notes or 'لا توجد ملاحظات'}",
        url="/accounts/library/?tab=received"
    )

    record_audit_log(
        user=request.user,
        action='LIBRARY_DOCUMENT_SHARED',
        target_model='DocumentShare',
        target_id=share.pk,
        details=f"إحالة المستند ({doc.title}) إلى المستخدم ({recipient.username} - {recipient.get_role_display()})",
        request=request
    )

    messages.success(request, f"تم بنجاح إرسال وإحالة الوثيقة ({doc.title}) إلى سعادة ({recipient.get_full_name() or recipient.username}).")
    return redirect('accounts:library_index')


@login_required
def library_delete_view(request, doc_id):
    """Deletes owned document or removes received share from inbox."""
    if request.method != 'POST':
        return redirect('accounts:library_index')

    doc = get_object_or_404(UserDocument, pk=doc_id)

    if doc.owner_id == request.user.id or request.user.is_superuser:
        doc.is_archived = True
        doc.save(update_fields=['is_archived'])
        record_audit_log(
            user=request.user,
            action='LIBRARY_DOCUMENT_DELETED',
            target_model='UserDocument',
            target_id=doc.pk,
            details=f"حذف المستند ({doc.title}) من مكتبة المستخدم",
            request=request
        )
        messages.success(request, f"تم حذف المستند ({doc.title}) من مكتبتك بنجاح.")
    else:
        # User is recipient: remove their share
        deleted_count, _ = DocumentShare.objects.filter(document=doc, recipient=request.user).delete()
        if deleted_count:
            messages.success(request, f"تمت إزالة الوثيقة المحالة ({doc.title}) من صندوق المستندات المستلمة.")
        else:
            messages.error(request, "غير مصرح لك بحذف هذه الوثيقة.")

    return redirect('accounts:library_index')


@login_required
def library_download_view(request, doc_id):
    """Secure preview/download for owned or received documents."""
    doc = get_object_or_404(UserDocument, pk=doc_id, is_archived=False)

    is_owner = (doc.owner_id == request.user.id)
    share = doc.shares.filter(recipient=request.user).first()
    is_recipient = bool(share)
    is_same_institution = bool(
        request.user.is_institution_rep and request.user.institution_id and
        doc.application and doc.application.institution_id == request.user.institution_id
    )
    is_assigned_reviewer = bool(
        request.user.is_reviewer and doc.application and doc.application.review_team and
        doc.application.review_team.members.filter(user=request.user).exists()
    )
    is_privileged = request.user.is_superuser or request.user.role in [
        User.Roles.ADMIN, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_CHAIRMAN
    ]

    if not (is_owner or is_recipient or is_same_institution or is_assigned_reviewer or is_privileged):
        return HttpResponseForbidden("غير مصرح لك: هذه الوثيقة خاصة وغير مدرجة ضمن مكتبتك أو المستندات المحالة إليك.")

    # Mark as read if user is recipient
    if share and not share.is_read:
        share.is_read = True
        share.read_at = timezone.now()
        share.save(update_fields=['is_read', 'read_at'])

    # If document has a system source URL and no physical uploaded file (or is a certificate/decision/report), redirect to official view
    if doc.system_source_url and not doc.file:
        return redirect(doc.system_source_url)

    try:
        if doc.file:
            return FileResponse(doc.file.open('rb'))
        elif doc.system_source_url:
            return redirect(doc.system_source_url)
    except (FileNotFoundError, ValueError):
        if doc.system_source_url:
            return redirect(doc.system_source_url)
        raise Http404("الملف غير متوفر على خادم التخزين.")


@login_required
def library_save_system_asset_view(request):
    """
    One-click 'حفظ في مكتبتي' (Save to My Library) action from any system screen/report.
    Ensures the viewed asset (Self Study Report, External Report, Comparison, Application Dossier, Certificate, Decision)
    is securely synchronized, pinned, and immediately accessible in the user's workspace library.
    """
    asset_type = request.GET.get('asset_type')
    app_id = request.GET.get('app_id')

    if not app_id or not asset_type:
        messages.warning(request, "معلومات المستند غير مكتملة.")
        return redirect('accounts:library_index')

    app = get_object_or_404(AccreditationApplication, pk=app_id)
    sync_system_assets_to_library()

    doc_type_map = {
        'ssr': UserDocument.DocumentType.SELF_STUDY,
        'external_report': UserDocument.DocumentType.EXTERNAL_REPORT,
        'comparison': UserDocument.DocumentType.COMPARISON_REPORT,
        'application': UserDocument.DocumentType.APPLICATION_DOSSIER,
        'certificate': UserDocument.DocumentType.CERTIFICATE,
        'decision': UserDocument.DocumentType.DECISION,
    }
    target_doc_type = doc_type_map.get(asset_type)
    doc = UserDocument.objects.filter(application=app, doc_type=target_doc_type).first()

    if doc:
        # If user is not the creator, pin it in their received vault via DocumentShare
        if doc.owner != request.user:
            DocumentShare.objects.get_or_create(
                document=doc,
                sender=doc.owner,
                recipient=request.user,
                defaults={'notes': 'تم حفظ الوثيقة يدوياً في مكتبتي الخاصة للاطلاع والرجوع والمشاركة السريعة.'}
            )
        messages.success(request, f"تم بنجاح حفظ وثيقة ({doc.title}) في مكتبتك الخاصة!")
        target_tab = 'my_docs' if doc.owner == request.user else 'received'
        return redirect(f"/accounts/library/?tab={target_tab}&q={app.application_number}")
    else:
        messages.info(request, "تمت مزامنة أصول الطلب مع مكتبتك بنجاح.")
        return redirect('accounts:library_index')




