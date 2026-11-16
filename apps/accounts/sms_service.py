import re
import uuid
import logging
from django.utils import timezone
from .models import User, SMSLog

logger = logging.getLogger(__name__)

YEMEN_OPERATORS = {
    '77': 'يمن موبايل (Yemen Mobile)',
    '78': 'يمن موبايل (Yemen Mobile)',
    '73': 'يو - إم تي إن (YOU Telecom)',
    '71': 'سبأفون (Sabafon)',
    '70': 'واي (Y Telecom)',
}

def normalize_yemeni_phone(raw_phone):
    """
    Normalizes any entered Yemeni phone number into standard formats
    and identifies the telecom operator.
    
    Returns:
        tuple: (normalized_e164, local_format, operator_name)
    """
    if not raw_phone:
        return None, None, 'غير محدد'

    # Remove non-digit characters
    digits = re.sub(r'\D', '', str(raw_phone))

    # Strip Yemen country code if present (967 or 00967)
    if digits.startswith('00967'):
        digits = digits[5:]
    elif digits.startswith('967'):
        digits = digits[3:]

    # Strip leading zero if present
    if digits.startswith('0'):
        digits = digits[1:]

    # Yemeni mobile numbers are 9 digits starting with 7
    if len(digits) == 9 and digits.startswith('7'):
        prefix = digits[:2]
        operator = YEMEN_OPERATORS.get(prefix, 'مشغل يمني')
        e164 = f"+967{digits}"
        local = f"0{digits}"
        return e164, local, operator

    # Fallback for landline or other formats
    return f"+967{digits}", digits, 'مشغل اتصالات'


def send_sms(recipient_or_phone, message_text, message_type=SMSLog.MessageType.GENERAL_ALERT, on_commit=False):
    """
    Core SMS Gateway dispatcher for CAQA Yemen.
    
    Accepts:
        recipient_or_phone: User instance OR raw phone string.
        message_text: The Arabic SMS text content.
        message_type: SMSLog.MessageType choice.
        on_commit: If True, executes after DB transaction commits.
    
    Returns:
        SMSLog instance or None if invalid.
    """
    recipient_user = None
    target_phone = None

    if isinstance(recipient_or_phone, User):
        recipient_user = recipient_or_phone
        target_phone = recipient_user.phone
    elif isinstance(recipient_or_phone, str):
        target_phone = recipient_or_phone

    if not target_phone:
        logger.warning(f"SMS dispatch skipped: No phone number provided for recipient {recipient_user}.")
        return None

    e164, local_phone, operator = normalize_yemeni_phone(target_phone)
    if not e164:
        logger.warning(f"SMS dispatch failed: Invalid phone format '{target_phone}'.")
        return None

    def _execute():
        import os
        from django.conf import settings

        gateway_mode = getattr(settings, 'SMS_GATEWAY_MODE', os.environ.get('SMS_GATEWAY_MODE', 'SIMULATION'))
        api_url = getattr(settings, 'YEMEN_MOBILE_API_URL', os.environ.get('YEMEN_MOBILE_API_URL', ''))
        api_user = getattr(settings, 'YEMEN_MOBILE_USERNAME', os.environ.get('YEMEN_MOBILE_USERNAME', ''))
        api_pass = getattr(settings, 'YEMEN_MOBILE_PASSWORD', os.environ.get('YEMEN_MOBILE_PASSWORD', ''))
        sender_id = getattr(settings, 'YEMEN_MOBILE_SENDER_ID', os.environ.get('YEMEN_MOBILE_SENDER_ID', 'CAQA-YEMEN'))

        ref_code = f"CAQA-SMS-{timezone.now().strftime('%Y%m')}-{uuid.uuid4().hex[:8].upper()}"
        status = SMSLog.Status.SENT

        if gateway_mode == 'LIVE' and api_url:
            try:
                import urllib.request
                import urllib.parse
                params = {
                    'username': api_user,
                    'password': api_pass,
                    'sender': sender_id,
                    'mobile': local_phone,
                    'message': message_text.strip()
                }
                data = urllib.parse.urlencode(params).encode('utf-8')
                req = urllib.request.Request(api_url, data=data, method='POST')
                with urllib.request.urlopen(req, timeout=10) as response:
                    resp_body = response.read().decode('utf-8')
                    gateway_resp = f"HTTP {response.status}: Live Telecom Broadcast Success. Provider Response: {resp_body[:200]}"
                    status = SMSLog.Status.DELIVERED
            except Exception as e:
                logger.error(f"Live SMS dispatch error to {local_phone}: {str(e)}")
                gateway_resp = f"خطأ في الاتصال بمزود خدمة الاتصالات الحي: {str(e)}"
                status = SMSLog.Status.FAILED
        else:
            gateway_resp = (
                f"وضع المحاكاة السيادية (Sandbox): تم التحقق من الرقم ({local_phone}) ومطابقته لمشغل ({operator}). "
                f"للبث الخلوي الحي للهاتف الفعلي عبر أبراج التغطية، يتطلب إدخال بيانات حساب الـ API الحي لمزود الخدمة (Yemen Mobile / Telecom API)."
            )

        sms_record = SMSLog.objects.create(
            recipient=recipient_user,
            phone_number=local_phone,
            telecom_operator=operator,
            message_type=message_type,
            message_body=message_text.strip(),
            status=status,
            gateway_reference=ref_code,
            gateway_response=gateway_resp
        )
        logger.info(f"SMS [{ref_code}] processed for {local_phone} ({operator}) - Mode: {gateway_mode}")
        return sms_record

    if on_commit:
        from django.db import transaction
        transaction.on_commit(_execute)
        return None

    return _execute()


# -------------------------------------------------------------------------
# Specialized Contextual Dispatchers
# -------------------------------------------------------------------------

def notify_accreditation_decision_sms(decision, application):
    """
    Sends sovereign SMS alert upon council decision issuance:
    1. To the Institution Officer / University President.
    2. To the Minister of Higher Education.
    3. To Council Chairman.
    """
    decree = decision.decree_number
    inst_name = application.institution.name
    program_name = application.program.name if application.program else "الاعتماد المؤسسي"
    
    # 1. Message to University Officer
    officers = User.objects.filter(
        institution=application.institution,
        role=User.Roles.INSTITUTION_OFFICER,
        is_active=True
    ).exclude(phone='')

    msg_univ = (
        f"مجلس الاعتماد الأكاديمي (اليمن): تهانينا! صدر رسمياً {decree} "
        f"بشأن اعتماد ({program_name}) لـ ({inst_name}). "
        f"يمكنكم استلام وطباعة الشهادة من البوابة."
    )
    for off in officers:
        send_sms(off, msg_univ, message_type=SMSLog.MessageType.ACCREDITATION_DECISION)

    # 2. Sovereign SMS to Council Leadership & Minister
    leadership = User.objects.filter(
        role__in=[User.Roles.MINISTER, User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_SECRETARY_GENERAL],
        is_active=True
    ).exclude(phone='')

    msg_lead = (
        f"CAQA - تنبيه قيادي: صدر قرار المجلس ({decree}) "
        f"بمنح الاعتماد لـ ({inst_name}) - ({program_name})."
    )
    for lead in leadership:
        send_sms(lead, msg_lead, message_type=SMSLog.MessageType.ACCREDITATION_DECISION)


def notify_reviewer_assignment_sms(reviewer, application, site_visit_schedule=None):
    """
    Sends formal SMS alert to nominated external peer reviewer.
    """
    if not reviewer or not reviewer.phone:
        return None

    inst_name = application.institution.name
    visit_info = f" المحدد موعدها: {site_visit_schedule.visit_date}" if site_visit_schedule else ""
    
    msg = (
        f"مجلس الاعتماد الأكاديمي: سعادة المحكّم د.{reviewer.get_full_name() or reviewer.username}، "
        f"صدر قرار تكليفكم رسمياً ضمن لجنة المراجعة الخارجية لـ ({inst_name}){visit_info}. "
        f"يرجى الدخول للبوابة لتأكيد إقرار النزاهة واستلام ملف الشواهد."
    )
    return send_sms(reviewer, msg, message_type=SMSLog.MessageType.REVIEWER_ASSIGNMENT)


def notify_invoice_sms(invoice):
    """
    Sends formal SMS alert when financial invoice / claims are generated.
    """
    institution = invoice.application.institution
    officers = User.objects.filter(
        institution=institution,
        role=User.Roles.INSTITUTION_OFFICER,
        is_active=True
    ).exclude(phone='')

    msg = (
        f"مجلس الاعتماد الأكاديمي: صدرت المطالبة المالية رقم ({invoice.invoice_number}) "
        f"بمبلغ ({invoice.amount:,.0f} {invoice.currency}) لطلب ({invoice.application.application_number}). "
        f"يرجى السداد ورفع سند الإيداع عبر البوابة."
    )
    for off in officers:
        send_sms(off, msg, message_type=SMSLog.MessageType.FINANCIAL_INVOICE)


def notify_grievance_sms(grievance):
    """
    Sends SMS alert when a university registers a formal appeal / grievance.
    """
    # Notify Legal Director
    legal_directors = User.objects.filter(
        role=User.Roles.LEGAL_DIRECTOR,
        is_active=True
    ).exclude(phone='')

    msg_legal = (
        f"الشؤون القانونية - CAQA: تم قيد طعن/تظلم جديد برقم ({grievance.appeal_number}) "
        f"مقدم من ({grievance.application.institution.name}) بانتظار إعداد المذكرة القانونية."
    )
    for leg in legal_directors:
        send_sms(leg, msg_legal, message_type=SMSLog.MessageType.LEGAL_GRIEVANCE)
