from django.db import models
from apps.accounts.models import User, send_notification, notify_institution
from apps.accounts.sms_service import notify_invoice_sms


def notify_invoice_issued(invoice, on_commit=False):
    """
    Scenario 16: Notify authorized institution officers when a financial invoice/claim is issued.
    Guarantees strict institution isolation and prevents duplicate notifications.
    Supports on_commit transaction-safe dispatch.
    """
    if not invoice or not invoice.application or not invoice.application.institution:
        return []

    institution = invoice.application.institution
    amount_yer = invoice.total_amount
    service_name = invoice.fee_schedule.service_name if invoice.fee_schedule else "رسوم الاعتماد"

    # Send formal SMS alert to university representatives
    try:
        notify_invoice_sms(invoice)
    except Exception:
        pass

    return notify_institution(
        institution=institution,
        title=f"صدور مطالبة مالية برقم: {invoice.invoice_number}",
        message=(
            f"أصدرت الإدارة المالية مطالبة مالية لطلب الاعتماد ({invoice.application.application_number}) "
            f"بمبلغ ({amount_yer:,.0f} ر.ي) لبند ({service_name}). "
            f"يرجى استكمال إجراءات السداد البنكي ورفع سند التوريد."
        ),
        url=f"/operations/invoices/{invoice.pk}/",
        extra_recipients=invoice.application.applicant_user,
        on_commit=on_commit
    )


def notify_payment_receipt_uploaded(invoice, on_commit=False):
    """
    Scenario 17: Notify authorized financial officer and Secretariat recipients
    when a payment receipt/proof is uploaded by the institution.
    """
    if not invoice or not invoice.application:
        return []

    staff_users = User.objects.filter(
        role__in=[User.Roles.DG_FINANCE_ADMIN, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    created_notifs = []
    for staff in staff_users:
        notif = send_notification(
            user=staff,
            title=f"إشعار توريد مالي جديد: {invoice.invoice_number}",
            message=(
                f"قامت مؤسسة ({invoice.application.institution.name}) برفع سند توريد بنكي "
                f"برقم مرجعي ({invoice.payment_reference}) للمطالبة ({invoice.invoice_number}). "
                f"يرجى التدقيق والمطابقة المالية."
            ),
            url=f"/operations/invoices/{invoice.pk}/",
            on_commit=on_commit
        )
        if notif:
            created_notifs.append(notif)

    return created_notifs


def notify_payment_receipt_acknowledged(invoice, on_commit=False):
    """
    Scenario 18: Acknowledge receipt to institution officers that the payment proof
    has been received and is awaiting verification by CAQA finance.
    (Does NOT confirm payment).
    """
    if not invoice or not invoice.application or not invoice.application.institution:
        return []

    institution = invoice.application.institution
    return notify_institution(
        institution=institution,
        title=f"تأكيد استلام سند التوريد للمطالبة: {invoice.invoice_number}",
        message=(
            f"تم بنجاح استلام إشعار وسند التوريد البنكي رقم ({invoice.payment_reference}) "
            f"للمطالبة ({invoice.invoice_number})، والمعاملة الآن قيد المراجعة والتدقيق "
            f"لدى الإدارة المالية لمجلس الاعتماد الأكاديمي."
        ),
        url=f"/operations/invoices/{invoice.pk}/",
        extra_recipients=invoice.application.applicant_user,
        on_commit=on_commit
    )


def notify_payment_confirmed(invoice, on_commit=False):
    """
    Scenario 19: Notify all authorized officers of the relevant institution
    that their accreditation fee payment has been officially confirmed and cleared.
    """
    if not invoice or not invoice.application or not invoice.application.institution:
        return []

    institution = invoice.application.institution
    return notify_institution(
        institution=institution,
        title=f"تأكيد واعتماد السداد المالي: {invoice.invoice_number}",
        message=(
            f"تم اعتماد وتأكيد استلام الرسوم المالية رسمياً للمطالبة رقم ({invoice.invoice_number}) "
            f"بمبلغ ({invoice.total_amount:,.0f} ر.ي) وإبراء الذمة المالية "
            f"لطلب الاعتماد ({invoice.application.application_number})."
        ),
        url=f"/operations/invoices/{invoice.pk}/",
        extra_recipients=invoice.application.applicant_user,
        on_commit=on_commit
    )


def notify_payment_rejected(invoice, public_reason="", on_commit=False):
    """
    Scenario 20: Notify institution officers when a payment receipt is rejected,
    providing the public justification without exposing internal financial audit notes.
    """
    if not invoice or not invoice.application or not invoice.application.institution:
        return []

    institution = invoice.application.institution
    clean_reason = public_reason.strip() if public_reason else "سند التوريد غير مطابق أو غير مكتمل البيانات"

    return notify_institution(
        institution=institution,
        title=f"إعادة إشعار التوريد للمراجعة: {invoice.invoice_number}",
        message=(
            f"نحيطكم علماً بأنه تعذر اعتماد إشعار التوريد البنكي للمطالبة ({invoice.invoice_number}). "
            f"السبب: {clean_reason}. يرجى مراجعة بيانات الإيداع وإعادة رفع السند الصحيح."
        ),
        url=f"/operations/invoices/{invoice.pk}/",
        extra_recipients=invoice.application.applicant_user,
        on_commit=on_commit
    )


def notify_finance_to_secretariat(invoice, on_commit=False):
    """
    Scenario 21: Internal finance-to-Secretariat notification.
    Notifies authorized Secretariat recipients when financial verification is complete
    and the application is clear to proceed with accreditation technical review.
    """
    if not invoice or not invoice.application:
        return []

    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.DG_ACCREDITATION,
            User.Roles.DG_FINANCE_ADMIN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    created_notifs = []
    for sec in secretariat_users:
        notif = send_notification(
            user=sec,
            title=f"اكتمال السداد المالي للطلب: {invoice.application.application_number}",
            message=(
                f"أكدت الإدارة المالية استلام وتوريد الرسوم كاملة للمطالبة ({invoice.invoice_number}) "
                f"التابعة لمؤسسة ({invoice.application.institution.name}) واعتماد المخالصة المالية (FINANCIAL_CLEARED). "
                f"الطلب جاهز للمتابعة الإجرائية واستكمال متطلبات التقييم."
            ),
            url=f"/accreditation/{invoice.application.pk}/",
            on_commit=on_commit
        )
        if notif:
            created_notifs.append(notif)

    return created_notifs
