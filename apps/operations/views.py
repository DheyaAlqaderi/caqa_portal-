from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import models, transaction
from .models import TrainingProgram, TrainingParticipant, SupportTicket, FeeSchedule, Invoice
from apps.accounts.models import User, record_audit_log
from apps.accreditation.models import AccreditationApplication
from .services import (
    notify_invoice_issued,
    notify_payment_receipt_uploaded,
    notify_payment_receipt_acknowledged,
    notify_payment_confirmed,
    notify_payment_rejected,
    notify_finance_to_secretariat,
)

@login_required
def training_list(request):
    programs = TrainingProgram.objects.filter(is_active=True).order_by('-start_date')
    user_registrations = set(
        TrainingParticipant.objects.filter(user=request.user).values_list('program_id', flat=True)
    )
    return render(request, 'operations/training_list.html', {
        'programs': programs,
        'user_registrations': user_registrations,
    })

@login_required
def training_register(request, pk):
    program = get_object_or_404(TrainingProgram, pk=pk, is_active=True)
    participant, created = TrainingParticipant.objects.get_or_create(
        program=program,
        user=request.user
    )
    if created:
        messages.success(request, f"تم تسجيلك بنجاح في البرنامج التدريبي: ({program.title}).")
    else:
        messages.info(request, "أنت مسجل بالفعل في هذا البرنامج التدريبي.")
    return redirect('operations:training_list')

@login_required
def support_tickets(request):
    if request.user.is_council or request.user.is_staff:
        tickets = SupportTicket.objects.select_related('institution', 'user').order_by('-created_at')
    elif request.user.role == User.Roles.PUBLIC_VERIFIER or not request.user.institution:
        tickets = SupportTicket.objects.filter(user=request.user).order_by('-created_at')
    else:
        tickets = SupportTicket.objects.filter(
            models.Q(institution=request.user.institution) | models.Q(user=request.user)
        ).select_related('institution', 'user').order_by('-created_at')

    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        category = request.POST.get('category', SupportTicket.TicketCategory.TECHNICAL)
        message = request.POST.get('message', '').strip()
        target_inst = request.POST.get('target_institution_name', '').strip()
        verif_code = request.POST.get('verification_code', '').strip()
        ticket_num = f"TCK-{timezone.now().year}-{SupportTicket.objects.count()+1:04d}"

        inst = request.user.institution

        ticket = SupportTicket.objects.create(
            institution=inst,
            user=request.user,
            ticket_number=ticket_num,
            category=category,
            subject=subject,
            message=message,
            target_institution_name=target_inst,
            verification_code=verif_code,
        )
        record_audit_log(
            user=request.user,
            action='SUPPORT_TICKET_CREATED',
            target_model='SupportTicket',
            target_id=ticket.pk,
            details=f"فتح تذكرة استفسار/بلاغ جودة جديدة برقم ({ticket.ticket_number}) - التصنيف: {ticket.get_category_display()}",
            request=request
        )
        messages.success(request, f"تم إرسال تذكرتك بنجاح برقم ({ticket.ticket_number}) وسيتم الرد عليك وتدقيق طلبك رسمياً.")
        return redirect('operations:support_tickets')

    return render(request, 'operations/support_tickets.html', {'tickets': tickets, 'categories': SupportTicket.TicketCategory.choices})

@login_required
def invoices_list(request):
    can_manage_finance = (
        request.user.role in [
            User.Roles.DG_FINANCE_ADMIN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_issue_financial_clearance')
        or request.user.has_perm_code('can_verify_payment')
        or request.user.is_superuser
    )

    if request.user.is_council or request.user.is_staff or can_manage_finance:
        invoices = Invoice.objects.select_related('application__institution', 'fee_schedule').order_by('-issued_at')
    else:
        invoices = Invoice.objects.filter(application__institution=request.user.institution).order_by('-issued_at')

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        invoices = invoices.filter(status=status_filter)

    applications = []
    fee_schedules = []
    if can_manage_finance:
        applications = AccreditationApplication.objects.select_related('institution', 'program').all().order_by('-created_at')[:50]
        fee_schedules = FeeSchedule.objects.filter(is_active=True).order_by('service_name')

    return render(request, 'operations/invoices_list.html', {
        'invoices': invoices,
        'status_filter': status_filter,
        'can_manage_finance': can_manage_finance,
        'applications': applications,
        'fee_schedules': fee_schedules,
    })


@login_required
def invoice_create(request):
    """
    Allows DG Finance & Administration to issue an official financial claim/invoice
    linked to an accreditation application and regulatory fee schedule.
    """
    can_manage_finance = (
        request.user.role in [
            User.Roles.DG_FINANCE_ADMIN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
        or request.user.has_perm_code('can_issue_financial_clearance')
        or request.user.has_perm_code('can_verify_payment')
        or request.user.is_superuser
    )
    if not can_manage_finance:
        messages.error(request, "غير مصرح لك: إصدار المطالبات وسندات الإبراء المالي مخصص حصراً للشؤون المالية والإدارية.")
        return redirect('operations:invoices_list')

    if request.method == 'POST':
        app_id = request.POST.get('application_id')
        fee_id = request.POST.get('fee_schedule_id')
        custom_amount = request.POST.get('custom_amount', '').strip()

        if not app_id or not fee_id:
            messages.error(request, "يرجى اختيار طلب الاعتماد ولائحة الرسوم المعتمدة.")
            return redirect('operations:invoices_list')

        app = get_object_or_404(AccreditationApplication, pk=app_id)
        fee = get_object_or_404(FeeSchedule, pk=fee_id)
        try:
            amount = float(custom_amount) if custom_amount else fee.amount_yer
        except ValueError:
            amount = fee.amount_yer

        inv_count = Invoice.objects.count() + 1
        inv_num = f"INV-{timezone.now().year}-{inv_count:04d}"

        with transaction.atomic():
            invoice = Invoice.objects.create(
                invoice_number=inv_num,
                application=app,
                fee_schedule=fee,
                total_amount=amount,
                status=Invoice.PaymentStatus.UNPAID
            )

            record_audit_log(
                user=request.user,
                action='INVOICE_CREATED',
                target_model='Invoice',
                target_id=invoice.pk,
                details=f"إصدار مطالبة مالية رسمية ({inv_num}) للمؤسسة ({app.institution.name}) بمبلغ ({amount} ر.ي)",
                request=request
            )

            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()

            notify_invoice_issued(invoice)

        messages.success(request, f"تم إصدار المطالبة المالية بنجاح برقم ({inv_num}) للمؤسسة ({app.institution.name}).")
        return redirect('operations:invoice_detail', pk=invoice.pk)

    return redirect('operations:invoices_list')

@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('application__institution', 'fee_schedule'), pk=pk)

    # Tenant Isolation Guard
    if request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and request.user.institution_id:
        if invoice.application.institution_id != request.user.institution_id:
            messages.error(request, "غير مصرح لك بالاطلاع على مطالبات مالية لمؤسسة أخرى.")
            return redirect('operations:invoices_list')

    if request.method == 'POST' and 'upload_proof' in request.POST:
        # Check institution permission: only officers/president of this institution or staff can upload
        if request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and request.user.institution_id != invoice.application.institution_id:
            messages.error(request, "غير مصرح لك برفع إشعار توريد لمؤسسة أخرى.")
            return redirect('operations:invoices_list')

        ref = request.POST.get('payment_reference', '').strip()
        proof_file = request.FILES.get('proof_of_payment')
        if not ref:
            messages.error(request, "يرجى إدخال رقم وتاريخ إشعار التوريد البنكي.")
            return redirect('operations:invoice_detail', pk=invoice.pk)

        with transaction.atomic():
            invoice.payment_reference = ref
            if proof_file:
                invoice.proof_of_payment = proof_file
            invoice.save()

            record_audit_log(
                user=request.user,
                action='INVOICE_RECEIPT_UPLOADED',
                target_model='Invoice',
                target_id=invoice.pk,
                details=f"رفع إشعار توريد بنكي برقم ({invoice.payment_reference}) للمطالبة ({invoice.invoice_number})",
                request=request
            )

            # Trigger Scenario 17: Notify financial officer / Secretariat
            notify_payment_receipt_uploaded(invoice)

            # Trigger Scenario 18: Acknowledge receipt to institution officers
            notify_payment_receipt_acknowledged(invoice)

        messages.success(request, "تم رفع إشعار التوريد البنكي بنجاح وبانتظار تدقيق الإدارة المالية.")
        return redirect('operations:invoice_detail', pk=invoice.pk)

    if request.method == 'POST' and 'confirm_payment' in request.POST:
        can_manage_finance = (
            request.user.role in [
                User.Roles.DG_FINANCE_ADMIN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.ADMIN
            ]
            or request.user.has_perm_code('can_issue_financial_clearance')
            or request.user.has_perm_code('can_verify_payment')
            or request.user.is_superuser
        )
        if not can_manage_finance:
            messages.error(request, "غير مصرح لك: اعتماد وتأكيد السداد المالي مخصص حصراً لمدير عام الشؤون المالية والإدارية وأمانة المجلس.")
            return redirect('operations:invoice_detail', pk=invoice.pk)

        with transaction.atomic():
            invoice.status = Invoice.PaymentStatus.PAID
            invoice.verified_by = request.user
            invoice.paid_at = timezone.now()
            invoice.save()

            app = invoice.application
            if app:
                from apps.accreditation.models import ApplicationStatus, ApplicationStatusHistory
                if app.status == ApplicationStatus.DESK_ACCEPTED:
                    try:
                        from apps.accreditation.workflow import WorkflowEngine
                        WorkflowEngine.execute_transition(
                            application=app,
                            target_status=ApplicationStatus.FINANCIAL_CLEARED,
                            user=request.user,
                            reason=f"تأكيد السداد وإصدار سند الإبراء المالي للمطالبة ({invoice.invoice_number})",
                            request=request
                        )
                    except Exception:
                        app.status = ApplicationStatus.FINANCIAL_CLEARED
                        app.save(update_fields=['status'])
                else:
                    ApplicationStatusHistory.objects.create(
                        application=app,
                        from_stage=app.current_stage,
                        to_stage=app.current_stage,
                        from_status=app.status,
                        to_status=ApplicationStatus.FINANCIAL_CLEARED,
                        changed_by=request.user,
                        reason=f"تأكيد السداد المالي وإصدار المخالصة المالية (FINANCIAL_CLEARED) للمطالبة ({invoice.invoice_number})"
                    )

            try:
                from apps.decisions.models import SovereignTransaction
                SovereignTransaction.record_lifecycle_movement(
                    transaction_type=SovereignTransaction.TransactionType.FINANCIAL_CLAIM_CLEARANCE,
                    subject=f"تأكيد السداد وسند الإبراء المالي ({invoice.invoice_number})",
                    description=f"إبراء الذمة المالية للمطالبة ({invoice.invoice_number}) بمبلغ ({invoice.total_amount} ر.ي) للطلب ({app.application_number if app else ''}).",
                    sender=request.user,
                    sending_authority="الإدارة العامة للشؤون المالية والإدارية",
                    receiving_authority="الإدارة العامة للتقييم والمراجعة الخارجية",
                    status=SovereignTransaction.TransactionStatus.APPROVED,
                    action_reason=f"مرجع التوريد: {invoice.payment_reference}",
                    from_status='UNPAID',
                    application=app,
                    prefix='FIN',
                )
            except Exception:
                pass

            record_audit_log(
                user=request.user,
                action='INVOICE_PAID_CONFIRMED',
                target_model='Invoice',
                target_id=invoice.pk,
                details=f"تأكيد استلام وتوريد الرسوم للمطالبة ({invoice.invoice_number})",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            # Trigger Scenario 19: Notify institution officers that payment is confirmed
            notify_payment_confirmed(invoice)

            # Trigger Scenario 21: Internal finance-to-Secretariat handoff notification
            notify_finance_to_secretariat(invoice)

        messages.success(request, "تم تأكيد السداد وإصدار سند الإبراء المالي الرسمي.")
        return redirect('operations:invoice_detail', pk=invoice.pk)

    if request.method == 'POST' and 'reject_payment' in request.POST:
        can_manage_finance = (
            request.user.role in [
                User.Roles.DG_FINANCE_ADMIN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
                User.Roles.ADMIN
            ]
            or request.user.has_perm_code('can_issue_financial_clearance')
            or request.user.has_perm_code('can_verify_payment')
            or request.user.is_superuser
        )
        if not can_manage_finance:
            messages.error(request, "غير مصرح لك: مراجعة ورفض سندات السداد مخصص حصراً لمدير عام الشؤون المالية والإدارية وأمانة المجلس.")
            return redirect('operations:invoice_detail', pk=invoice.pk)

        public_reason = request.POST.get('rejection_reason', '').strip()
        internal_notes = request.POST.get('internal_notes', '').strip()

        with transaction.atomic():
            invoice.status = Invoice.PaymentStatus.UNPAID
            invoice.verified_by = request.user
            invoice.save()

            audit_details = f"رفض إشعار التوريد للمطالبة ({invoice.invoice_number}). سبب معلن: {public_reason}"
            if internal_notes:
                audit_details += f" | ملاحظات مالية داخلية سرية: {internal_notes}"

            record_audit_log(
                user=request.user,
                action='INVOICE_PAYMENT_REJECTED',
                target_model='Invoice',
                target_id=invoice.pk,
                details=audit_details,
                request=request
            )

            # Trigger Scenario 20: Notify institution officers
            notify_payment_rejected(invoice, public_reason=public_reason)

        messages.warning(request, "تم تسجيل رفض إشعار التوريد وإخطار المؤسسة باستدراك السند المطلوب.")
        return redirect('operations:invoice_detail', pk=invoice.pk)

    return render(request, 'operations/invoice_detail.html', {'invoice': invoice})
