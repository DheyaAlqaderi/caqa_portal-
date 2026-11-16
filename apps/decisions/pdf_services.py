import os
import io
from django.http import HttpResponse, Http404
from django.utils import timezone
from fpdf import FPDF
from .models import AccreditationCertificate


class CertificatePDF(FPDF):
    def __init__(self, **kwargs):
        super().__init__(orientation='landscape', unit='mm', format='A4', **kwargs)
        # 297mm width x 210mm height
        self.set_margins(15, 12, 15)
        self.set_auto_page_break(False)


def generate_official_certificate_pdf(cert: AccreditationCertificate, request=None) -> bytes:
    """
    Generates an official high-resolution landscape A4 PDF Certificate for CAQA Yemen.
    Includes national heraldry, decree references, QR verification code, and dual signatures.
    """
    pdf = CertificatePDF()
    pdf.add_page()

    # Font Setup (using Windows Arial which has native Arabic/Unicode glyphs)
    font_path = 'C:/Windows/Fonts/arial.ttf'
    font_bold_path = 'C:/Windows/Fonts/arialbd.ttf'
    if not os.path.exists(font_bold_path):
        font_bold_path = font_path

    pdf.add_font('ArialUni', '', font_path)
    pdf.add_font('ArialUniBold', '', font_bold_path)

    # 1. Ornamental Double Border (Emerald & Gold)
    # Outer Border (Emerald)
    pdf.set_draw_color(11, 104, 72)  # #0b6848
    pdf.set_line_width(2.0)
    pdf.rect(8, 8, 281, 194)

    # Inner Border (Gold)
    pdf.set_draw_color(196, 154, 69)  # #c49a45
    pdf.set_line_width(0.8)
    pdf.rect(11, 11, 275, 188)

    # Thin Accent Inner Line
    pdf.set_draw_color(11, 104, 72)
    pdf.set_line_width(0.3)
    pdf.rect(13, 13, 271, 184)

    # 2. Header: Republic of Yemen & CAQA
    pdf.set_y(16)
    pdf.set_font('ArialUniBold', size=13)
    pdf.set_text_color(15, 30, 47)  # Dark Navy
    pdf.cell(0, 7, text='الجمهورية اليمنية', align='C', center=True)
    pdf.ln(6)

    pdf.set_font('ArialUni', size=11)
    pdf.cell(0, 6, text='وزارة التعليم العالي والبحث العلمي', align='C', center=True)
    pdf.ln(6)

    pdf.set_font('ArialUniBold', size=14)
    pdf.set_text_color(11, 104, 72)  # Emerald
    pdf.cell(0, 7, text='مجلس الاعتماد الأكاديمي وضمان جودة التعليم العالي', align='C', center=True)
    pdf.ln(5)

    pdf.set_font('ArialUni', size=9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, text='Council for Academic Accreditation & Quality Assurance of Higher Education - Yemen', align='C', center=True)
    pdf.ln(8)

    # Decorative Line Under Header
    pdf.set_draw_color(196, 154, 69)
    pdf.set_line_width(0.6)
    pdf.line(40, pdf.get_y(), 257, pdf.get_y())
    pdf.ln(4)

    # 3. Certificate Title Banner
    app = cert.decision.application
    inst = app.institution
    prog = app.program
    decision = cert.decision

    pdf.set_font('ArialUniBold', size=20)
    pdf.set_text_color(11, 104, 72)
    pdf.cell(0, 10, text='شهادة اعتماد أكاديمي رسمي', align='C', center=True)
    pdf.ln(8)

    # National Registry Code
    pdf.set_font('ArialUniBold', size=11)
    pdf.set_text_color(196, 154, 69)  # Gold
    pdf.cell(0, 6, text=f'رقم القيد في السجل الوطني:  {cert.national_registry_code}', align='C', center=True)
    pdf.ln(9)

    # 4. Preamble & Decree
    pdf.set_font('ArialUni', size=11)
    pdf.set_text_color(30, 41, 59)

    preamble_text = (
        f"بناءً على قانون التعليم العالي رقم (13) ولائحته التنفيذية، وقرار إنشاء مجلس الاعتماد الأكاديمي، "
        f"وبعد استيفاء كافة معايير ضمان الجودة الوطنية وإنجاز التقييم الخارجي المستقل والمطابقة الشاملة، "
        f"قرر مجلس الإدارة في جلسته رقم ({decision.meeting.meeting_number}) بموجب القرار الوزاري رقم ({decision.decree_number}):"
    )
    pdf.set_x(25)
    pdf.multi_cell(247, 6, text=preamble_text, align='C')
    pdf.ln(5)

    # 5. The Award Awarded
    pdf.set_font('ArialUniBold', size=16)
    if decision.decision_type == decision.DecisionType.FULL_ACCREDITATION:
        award_title = "منح شهادة الاعتماد الأكاديمي الوطني الكامل"
        pdf.set_text_color(11, 104, 72)
    elif decision.decision_type == decision.DecisionType.CONDITIONAL_ACCREDITATION:
        award_title = "منح شهادة الاعتماد الأكاديمي الوطني المشروط"
        pdf.set_text_color(217, 119, 6)
    else:
        award_title = f"منح شهادة الاعتماد الأكاديمي ({decision.get_decision_type_display()})"
        pdf.set_text_color(15, 30, 47)

    pdf.cell(0, 8, text=award_title, align='C', center=True)
    pdf.ln(7)

    # Recipient: Institution & Program
    pdf.set_font('ArialUniBold', size=15)
    pdf.set_text_color(15, 30, 47)
    pdf.cell(0, 8, text=f"لمؤسسة:  {inst.name}  ({inst.governorate})", align='C', center=True)
    pdf.ln(6)

    if prog:
        pdf.set_font('ArialUniBold', size=13)
        pdf.set_text_color(11, 104, 72)
        pdf.cell(0, 7, text=f"للبرنامج الأكاديمي:  {prog.name} ({prog.get_degree_level_display()}) - {prog.college.name}", align='C', center=True)
        pdf.ln(6)
    else:
        pdf.set_font('ArialUni', size=12)
        pdf.set_text_color(11, 104, 72)
        pdf.cell(0, 7, text='نطاق الاعتماد:  اعتماد مؤسسي شامل لكافة كليات ومراكز الجامعة', align='C', center=True)
        pdf.ln(6)

    # Validity Period
    pdf.set_font('ArialUni', size=11)
    pdf.set_text_color(71, 85, 105)
    validity_text = (
        f"سريان الاعتماد: لمدة ({decision.validity_years}) سنوات "
        f"اعتباراً من تاريخ {decision.start_date} وحتى تاريخ {decision.expiry_date}"
    )
    pdf.cell(0, 6, text=validity_text, align='C', center=True)
    pdf.ln(7)

    # Status notice if not active
    if cert.status != AccreditationCertificate.CertificateStatus.ACTIVE:
        pdf.set_font('ArialUniBold', size=11)
        pdf.set_text_color(220, 38, 38)
        pdf.cell(0, 6, text=f"[تنبيه قانوني: حالة الوثيقة في السجل الوطني: {cert.get_status_display()}]", align='C', center=True)
        pdf.ln(5)

    # 6. Bottom Signatures & QR Code Area
    bottom_y = 152

    # QR Code on Left Side (width 26mm x 26mm)
    qr_placed = False
    if cert.qr_code_image and os.path.exists(cert.qr_code_image.path):
        try:
            pdf.image(cert.qr_code_image.path, x=22, y=bottom_y, w=28, h=28)
            qr_placed = True
        except Exception:
            qr_placed = False

    if not qr_placed:
        # Generate QR code dynamically in memory if missing
        try:
            import qrcode
            verify_url = f"https://caqa.gov.ye/decisions/verify/{cert.certificate_uuid}/"
            if request:
                verify_url = request.build_absolute_uri(f"/decisions/verify/{cert.certificate_uuid}/")
            qr_obj = qrcode.make(verify_url)
            buf = io.BytesIO()
            qr_obj.save(buf, format='PNG')
            buf.seek(0)
            pdf.image(buf, x=22, y=bottom_y, w=28, h=28)
            qr_placed = True
        except Exception:
            pass

    # QR Label Under Image
    pdf.set_xy(16, bottom_y + 29)
    pdf.set_font('ArialUni', size=7)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(40, 4, text='مسح رمز التحقق الرقمي المعتمد', align='C')

    # Dual Signatures: Secretary General & Chairman
    # Secretary General (Center-Left)
    pdf.set_xy(75, bottom_y)
    pdf.set_font('ArialUniBold', size=11)
    pdf.set_text_color(15, 30, 47)
    pdf.cell(70, 6, text='أمين عام المجلس', align='C')
    pdf.set_xy(75, bottom_y + 16)
    pdf.set_font('ArialUni', size=10)
    pdf.cell(70, 5, text='د. محمد ضيف الله', align='C')

    # Council Chairperson (Right)
    pdf.set_xy(180, bottom_y)
    pdf.set_font('ArialUniBold', size=11)
    pdf.set_text_color(15, 30, 47)
    pdf.cell(85, 6, text='رئيس مجلس الاعتماد الأكاديمي', align='C')
    pdf.set_xy(180, bottom_y + 16)
    pdf.set_font('ArialUni', size=10)
    pdf.cell(85, 5, text=decision.meeting.chairperson_name or 'أ.د. رئيس المجلس', align='C')

    # 7. Document Security Footer
    pdf.set_xy(15, 192)
    pdf.set_font('ArialUni', size=7)
    pdf.set_text_color(148, 163, 184)
    uuid_str = str(cert.certificate_uuid)
    pdf.cell(0, 4, text=f'المعرف الرقمي المشفر (UUID): {uuid_str}  •  صدرت بتاريخ {cert.issue_date}  •  وثيقة رسمية مؤمنة إلكترونياً ومسجلة بالسجل الوطني', align='C', center=True)

    return bytes(pdf.output())


def export_certificate_pdf_view(request, pk):
    """
    HTTP View to download or stream the official Certificate PDF.
    """
    try:
        cert = AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program',
            'decision__meeting'
        ).get(pk=pk)
    except AccreditationCertificate.DoesNotExist:
        raise Http404("شهادة الاعتماد المطلوبة غير موجودة.")

    pdf_bytes = generate_official_certificate_pdf(cert, request=request)
    filename = f"CAQA_Certificate_{cert.national_registry_code}.pdf".replace(' ', '_')

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    # Use inline so browser can display it directly with print/download buttons
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


def export_certificate_pdf_by_uuid_view(request, uuid):
    """
    Public HTTP View to download or stream the official Certificate PDF by UUID.
    """
    try:
        cert = AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program',
            'decision__meeting'
        ).get(certificate_uuid=uuid)
    except AccreditationCertificate.DoesNotExist:
        raise Http404("شهادة الاعتماد المطلوبة غير موجودة.")

    pdf_bytes = generate_official_certificate_pdf(cert, request=request)
    filename = f"CAQA_Certificate_{cert.national_registry_code}.pdf".replace(' ', '_')

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
