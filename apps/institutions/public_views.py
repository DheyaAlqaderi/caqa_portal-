from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.utils import timezone
from django.core.paginator import Paginator
import uuid

from apps.institutions.models import Institution, College, AcademicProgram
from apps.decisions.models import AccreditationCertificate, AccreditationDecision
from apps.accreditation.models import AccreditationApplication, AccreditationTrackType
from apps.accounts.models import record_audit_log


def public_registry_view(request):
    """
    Public National Accreditation Registry & Student Verification Directory.
    Open to the general public, students, and employers without authentication.
    """
    active_tab = request.GET.get('tab', 'institutions')
    search_q = request.GET.get('q', '').strip()
    inst_type = request.GET.get('inst_type', '').strip()
    governorate = request.GET.get('governorate', '').strip()
    degree_level = request.GET.get('degree_level', '').strip()
    status_filter = request.GET.get('status', '').strip()

    # --- Live National Counters ---
    total_institutions = Institution.objects.count()
    accredited_inst_count = Institution.objects.filter(
        accreditation_applications__council_decision__certificate__status=AccreditationCertificate.CertificateStatus.ACTIVE,
        accreditation_applications__track=AccreditationTrackType.INSTITUTIONAL
    ).distinct().count()

    accredited_prog_count = AcademicProgram.objects.filter(
        program_applications__council_decision__certificate__status=AccreditationCertificate.CertificateStatus.ACTIVE
    ).distinct().count()

    active_certs_count = AccreditationCertificate.objects.filter(
        status=AccreditationCertificate.CertificateStatus.ACTIVE
    ).count()

    # Available Governorates for Filter Dropdown
    governorates_list = list(
        Institution.objects.exclude(governorate='')
        .values_list('governorate', flat=True)
        .distinct()
        .order_by('governorate')
    )

    # --------------------------------------------------------------------------
    # Tab 1: Institutions Directory
    # --------------------------------------------------------------------------
    institutions_qs = Institution.objects.prefetch_related(
        'colleges__programs',
        'accreditation_applications__council_decision__certificate'
    ).order_by('name')

    if search_q:
        institutions_qs = institutions_qs.filter(
            models.Q(name__icontains=search_q) |
            models.Q(code__icontains=search_q) |
            models.Q(decree_number__icontains=search_q) |
            models.Q(governorate__icontains=search_q)
        )

    if inst_type:
        institutions_qs = institutions_qs.filter(institution_type=inst_type)

    if governorate:
        institutions_qs = institutions_qs.filter(governorate=governorate)

    # Attach Institutional Accreditation Certificate Info to each institution
    institutions_list = []
    for inst in institutions_qs:
        inst_cert = None
        for app in inst.accreditation_applications.all():
            if app.track == AccreditationTrackType.INSTITUTIONAL and hasattr(app, 'council_decision'):
                if hasattr(app.council_decision, 'certificate'):
                    c = app.council_decision.certificate
                    if c.status == AccreditationCertificate.CertificateStatus.ACTIVE:
                        inst_cert = c
                        break
                    elif not inst_cert:
                        inst_cert = c

        if status_filter == 'accredited' and (not inst_cert or inst_cert.status != AccreditationCertificate.CertificateStatus.ACTIVE):
            continue

        institutions_list.append({
            'obj': inst,
            'certificate': inst_cert,
            'colleges_count': inst.colleges.count(),
            'programs_count': sum(c.programs.count() for c in inst.colleges.all()),
        })

    inst_paginator = Paginator(institutions_list, 12)
    inst_page = inst_paginator.get_page(request.GET.get('page_inst', 1))

    # --------------------------------------------------------------------------
    # Tab 2: Accredited Academic Programs Directory
    # --------------------------------------------------------------------------
    programs_qs = AcademicProgram.objects.select_related(
        'college__institution'
    ).prefetch_related(
        'program_applications__council_decision__certificate'
    ).order_by('college__institution__name', 'name')

    if search_q:
        programs_qs = programs_qs.filter(
            models.Q(name__icontains=search_q) |
            models.Q(code__icontains=search_q) |
            models.Q(college__name__icontains=search_q) |
            models.Q(college__institution__name__icontains=search_q) |
            models.Q(ministry_approval_decree__icontains=search_q)
        )

    if degree_level:
        programs_qs = programs_qs.filter(degree_level=degree_level)

    if governorate:
        programs_qs = programs_qs.filter(college__institution__governorate=governorate)

    programs_list = []
    for prog in programs_qs:
        prog_cert = None
        for app in prog.program_applications.all():
            if hasattr(app, 'council_decision') and hasattr(app.council_decision, 'certificate'):
                c = app.council_decision.certificate
                if c.status == AccreditationCertificate.CertificateStatus.ACTIVE:
                    prog_cert = c
                    break
                elif not prog_cert:
                    prog_cert = c

        if status_filter == 'accredited' and (not prog_cert or prog_cert.status != AccreditationCertificate.CertificateStatus.ACTIVE):
            continue

        programs_list.append({
            'obj': prog,
            'institution': prog.college.institution,
            'college': prog.college,
            'certificate': prog_cert,
        })

    prog_paginator = Paginator(programs_list, 15)
    prog_page = prog_paginator.get_page(request.GET.get('page_prog', 1))

    # --------------------------------------------------------------------------
    # Tab 3: Direct Certificate Verification Lookup (if search submitted)
    # --------------------------------------------------------------------------
    verify_query = request.GET.get('verify_code', '').strip()
    verify_cert = None
    verify_searched = False
    if verify_query:
        verify_searched = True
        active_tab = 'verify'
        # Check by national registry code, decree number, or UUID
        lookup_qs = AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program',
            'decision__meeting'
        )
        # Try UUID first
        try:
            val_uuid = uuid.UUID(verify_query)
            verify_cert = lookup_qs.filter(certificate_uuid=val_uuid).first()
        except ValueError:
            pass

        if not verify_cert:
            verify_cert = lookup_qs.filter(
                models.Q(national_registry_code__iexact=verify_query) |
                models.Q(national_registry_code__icontains=verify_query) |
                models.Q(decision__decree_number__icontains=verify_query)
            ).first()

        if verify_cert:
            record_audit_log(
                user=request.user if request.user.is_authenticated else None,
                action='PUBLIC_REGISTRY_VERIFY_LOOKUP',
                target_model='AccreditationCertificate',
                target_id=verify_cert.pk,
                details=f"استعلام تحقق وطني مباشر من الشهادة ({verify_cert.national_registry_code})",
                request=request
            )

    context = {
        'active_tab': active_tab,
        'search_q': search_q,
        'inst_type': inst_type,
        'governorate': governorate,
        'degree_level': degree_level,
        'status_filter': status_filter,
        'verify_query': verify_query,
        'verify_cert': verify_cert,
        'verify_searched': verify_searched,

        # Counters
        'total_institutions': total_institutions,
        'accredited_inst_count': accredited_inst_count,
        'accredited_prog_count': accredited_prog_count,
        'active_certs_count': active_certs_count,

        # Data Pages
        'inst_page': inst_page,
        'prog_page': prog_page,
        'governorates_list': governorates_list,
        'institution_types': Institution.InstitutionType.choices,
        'degree_levels': AcademicProgram.DegreeLevel.choices,
    }
    return render(request, 'public/registry.html', context)


def public_institution_detail(request, pk):
    """
    Detailed public profile of a higher education institution,
    its official license, colleges, and accredited programs.
    """
    institution = get_object_or_404(
        Institution.objects.prefetch_related(
            'colleges__programs__program_applications__council_decision__certificate',
            'accreditation_applications__council_decision__certificate'
        ),
        pk=pk
    )

    # Check for Institutional Certificate (prioritizing active)
    inst_cert = None
    for app in institution.accreditation_applications.all():
        if app.track == AccreditationTrackType.INSTITUTIONAL and hasattr(app, 'council_decision'):
            if hasattr(app.council_decision, 'certificate'):
                c = app.council_decision.certificate
                if c.status == AccreditationCertificate.CertificateStatus.ACTIVE:
                    inst_cert = c
                    break
                elif not inst_cert:
                    inst_cert = c

    # Organize colleges and programs
    colleges_data = []
    total_programs = 0
    accredited_programs = 0

    for col in institution.colleges.all():
        programs_in_col = []
        for prog in col.programs.all():
            prog_cert = None
            for app in prog.program_applications.all():
                if hasattr(app, 'council_decision') and hasattr(app.council_decision, 'certificate'):
                    prog_cert = app.council_decision.certificate
                    break
            if prog_cert and prog_cert.status == AccreditationCertificate.CertificateStatus.ACTIVE:
                accredited_programs += 1
            total_programs += 1

            programs_in_col.append({
                'prog': prog,
                'certificate': prog_cert,
            })

        colleges_data.append({
            'college': col,
            'programs': programs_in_col,
        })

    record_audit_log(
        user=request.user if request.user.is_authenticated else None,
        action='PUBLIC_INSTITUTION_PROFILE_VIEW',
        target_model='Institution',
        target_id=institution.pk,
        details=f"استعراض الملف العام للمؤسسة التعليمية ({institution.name})",
        request=request
    )

    context = {
        'institution': institution,
        'inst_cert': inst_cert,
        'colleges_data': colleges_data,
        'total_programs': total_programs,
        'accredited_programs': accredited_programs,
    }
    return render(request, 'public/institution_detail.html', context)


def public_program_detail(request, pk):
    """
    Detailed public profile of an academic program,
    its license decree, degree details, and accreditation certificate.
    """
    program = get_object_or_404(
        AcademicProgram.objects.select_related('college__institution', 'department').prefetch_related(
            'program_applications__council_decision__certificate',
            'program_applications__council_decision__meeting'
        ),
        pk=pk
    )

    prog_cert = None
    app_obj = None
    for app in program.program_applications.all():
        if hasattr(app, 'council_decision') and hasattr(app.council_decision, 'certificate'):
            prog_cert = app.council_decision.certificate
            app_obj = app
            break

    record_audit_log(
        user=request.user if request.user.is_authenticated else None,
        action='PUBLIC_PROGRAM_PROFILE_VIEW',
        target_model='AcademicProgram',
        target_id=program.pk,
        details=f"استعراض الملف العام للبرنامج الأكاديمي ({program.name}) - {program.college.institution.name}",
        request=request
    )

    context = {
        'program': program,
        'institution': program.college.institution,
        'college': program.college,
        'prog_cert': prog_cert,
        'application': app_obj,
    }
    return render(request, 'public/program_detail.html', context)
