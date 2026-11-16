from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_GET
from .models import Institution, College, Department, AcademicProgram
from apps.accounts.models import User, record_audit_log

def is_licensing_authorized(user):
    """
    Checks if user is legally authorized by CAQA regulations to license institutions
    and manage national academic registry structures.
    """
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    return (
        user.role in [
            User.Roles.ADMIN,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
        ] or (hasattr(user, 'has_perm_code') and user.has_perm_code('can_manage_accreditation'))
    )

def institutions_list_view(request):
    institutions = Institution.objects.prefetch_related('colleges__programs', 'colleges__departments').all()
    can_create = is_licensing_authorized(request.user)
    return render(request, 'institutions/list.html', {
        'institutions': institutions,
        'can_create': can_create
    })

@login_required
def institution_create(request):
    """
    Allows Directorate General of Accreditation, Council Secretariat, and Admins to officially register
    a new higher education institution with its ministerial / republican decree number.
    """
    if request.user.role in [User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER, User.Roles.INSTITUTION_OFFICER]:
        messages.error(request, "غير مصرح لك: قيد وترخيص المؤسسات التعليمية بالسجل الوطني مخصص للإدارة العامة للاعتماد والتراخيص والأمانة الفنية فقط.")
        return redirect('institutions:list')

    if not is_licensing_authorized(request.user):
        messages.error(request, "غير مصرح لك: قيد وترخيص المؤسسات التعليمية بالسجل الوطني مخصص للإدارة العامة للاعتماد والتراخيص والأمانة الفنية فقط.")
        return redirect('institutions:list')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_en = request.POST.get('name_en', '').strip()
        code = request.POST.get('code', '').strip().upper()
        inst_type = request.POST.get('institution_type', Institution.InstitutionType.PUBLIC_UNIVERSITY)
        decree = request.POST.get('decree_number', '').strip()
        year_str = request.POST.get('establishment_year', '').strip()
        governorate = request.POST.get('governorate', '').strip()
        city = request.POST.get('city', '').strip()
        address = request.POST.get('address', '').strip()
        website = request.POST.get('website', '').strip()
        official_email = request.POST.get('official_email', '').strip()
        official_phone = request.POST.get('official_phone', '').strip()
        president = request.POST.get('president_name', '').strip()
        quality_dean = request.POST.get('quality_center_dean', '').strip()

        if not name or not code or not governorate:
            messages.error(request, "يرجى ملء الحقول الأساسية: اسم المؤسسة، الرمز التعريفي، والمحافظة.")
            return render(request, 'institutions/institution_form.html', {'types': Institution.InstitutionType.choices})

        if Institution.objects.filter(code=code).exists():
            messages.error(request, f"الرمز التعريفي ({code}) مسجل مسبقاً لمؤسسة أخرى.")
            return render(request, 'institutions/institution_form.html', {'types': Institution.InstitutionType.choices})

        year = int(year_str) if year_str.isdigit() else None

        inst = Institution.objects.create(
            name=name,
            name_en=name_en,
            code=code,
            institution_type=inst_type,
            decree_number=decree,
            establishment_year=year,
            governorate=governorate,
            city=city,
            address=address,
            website=website,
            official_email=official_email,
            official_phone=official_phone,
            president_name=president,
            quality_center_dean=quality_dean,
        )

        record_audit_log(
            user=request.user,
            action='INSTITUTION_REGISTERED',
            target_model='Institution',
            target_id=inst.pk,
            details=f"قيد وترخيص مؤسسة تعليمية جديدة ({inst.name}) بالرمز ({inst.code}) بموجب قرار ({inst.decree_number})",
            request=request
        )

        messages.success(request, f"تم بنجاح قيد وترخيص المؤسسة التعليمية ({inst.name}) في السجل الوطني.")
        return redirect('institutions:detail', pk=inst.pk)

    return render(request, 'institutions/institution_form.html', {
        'types': Institution.InstitutionType.choices
    })

def institution_detail_view(request, pk):
    institution = get_object_or_404(
        Institution.objects.prefetch_related('colleges__programs', 'colleges__departments__programs'),
        pk=pk
    )
    is_owner_or_authorized = (
        is_licensing_authorized(request.user) or
        (request.user.is_authenticated and request.user.role == User.Roles.INSTITUTION_OFFICER and request.user.institution_id == institution.id)
    )
    return render(request, 'institutions/detail.html', {
        'institution': institution,
        'can_manage': is_owner_or_authorized,
    })

@login_required
def college_create(request, inst_pk):
    institution = get_object_or_404(Institution, pk=inst_pk)
    
    # Board members and external reviewers cannot manage academic structures
    if request.user.role in [User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER]:
        return HttpResponseForbidden("غير مصرح لأعضاء مجلس الإدارة أو المحكمين بإدارة الهيكل الأكاديمي للمؤسسات التعليمية.")

    is_sec_or_admin = is_licensing_authorized(request.user)
    is_owner_officer = (
        request.user.role == User.Roles.INSTITUTION_OFFICER and
        request.user.institution_id == institution.id
    )
    if not (is_sec_or_admin or is_owner_officer):
        messages.error(request, "غير مصرح لك بإدارة الهيكل الأكاديمي لهذه المؤسسة.")
        return redirect('institutions:detail', pk=institution.pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        dean_name = request.POST.get('dean_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        year_str = request.POST.get('establishment_year', '').strip()
        year = int(year_str) if year_str.isdigit() else None

        if not name:
            messages.error(request, "اسم الكلية حقل إلزامي.")
            return redirect('institutions:detail', pk=institution.pk)

        if College.objects.filter(institution=institution, name=name).exists():
            messages.error(request, f"الكلية ({name}) مسجلة مسبقاً في هذه المؤسسة.")
            return redirect('institutions:detail', pk=institution.pk)

        college = College.objects.create(
            institution=institution,
            name=name,
            dean_name=dean_name,
            email=email,
            phone=phone,
            establishment_year=year
        )
        record_audit_log(
            user=request.user,
            action='COLLEGE_CREATED',
            target_model='College',
            target_id=college.pk,
            details=f"إضافة كلية جديدة ({college.name}) لمؤسسة ({institution.name})",
            request=request
        )
        messages.success(request, f"تمت إضافة الكلية ({college.name}) بنجاح.")
    return redirect('institutions:detail', pk=institution.pk)

@login_required
def department_create(request, college_pk):
    college = get_object_or_404(College.objects.select_related('institution'), pk=college_pk)
    institution = college.institution

    # Board members and external reviewers cannot manage academic structures
    if request.user.role in [User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER]:
        return HttpResponseForbidden("غير مصرح لأعضاء مجلس الإدارة أو المحكمين بإدارة الهيكل الأكاديمي للمؤسسات التعليمية.")

    is_sec_or_admin = is_licensing_authorized(request.user)
    is_owner_officer = (
        request.user.role == User.Roles.INSTITUTION_OFFICER and
        request.user.institution_id == institution.id
    )
    if not (is_sec_or_admin or is_owner_officer):
        messages.error(request, "غير مصرح لك بإدارة أقسام هذه الكلية.")
        return redirect('institutions:detail', pk=institution.pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        head_name = request.POST.get('head_name', '').strip()
        year_str = request.POST.get('establishment_year', '').strip()
        year = int(year_str) if year_str.isdigit() else None

        if not name:
            messages.error(request, "اسم القسم حقل إلزامي.")
            return redirect('institutions:detail', pk=institution.pk)

        if Department.objects.filter(college=college, name=name).exists():
            messages.error(request, f"القسم ({name}) مسجل مسبقاً في هذه الكلية.")
            return redirect('institutions:detail', pk=institution.pk)

        dept = Department.objects.create(
            college=college,
            name=name,
            head_name=head_name,
            establishment_year=year
        )
        record_audit_log(
            user=request.user,
            action='DEPARTMENT_CREATED',
            target_model='Department',
            target_id=dept.pk,
            details=f"إضافة قسم أكاديمي جديد ({dept.name}) لكلية ({college.name})",
            request=request
        )
        messages.success(request, f"تمت إضافة القسم الأكاديمي ({dept.name}) بنجاح.")
    return redirect('institutions:detail', pk=institution.pk)

@login_required
def program_create(request, college_pk):
    college = get_object_or_404(College.objects.select_related('institution'), pk=college_pk)
    institution = college.institution

    # Board members and external reviewers cannot manage academic structures
    if request.user.role in [User.Roles.BOARD_MEMBER, User.Roles.EXTERNAL_REVIEWER]:
        return HttpResponseForbidden("غير مصرح لأعضاء مجلس الإدارة أو المحكمين بإدارة الهيكل الأكاديمي للمؤسسات التعليمية.")

    is_sec_or_admin = is_licensing_authorized(request.user)
    is_owner_officer = (
        request.user.role == User.Roles.INSTITUTION_OFFICER and
        request.user.institution_id == institution.id
    )
    if not (is_sec_or_admin or is_owner_officer):
        messages.error(request, "غير مصرح لك بإضافة برامج لهذه الكلية.")
        return redirect('institutions:detail', pk=institution.pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        degree_level = request.POST.get('degree_level', AcademicProgram.DegreeLevel.BACHELOR)
        study_system = request.POST.get('study_system', AcademicProgram.StudySystem.CREDIT_HOURS)
        duration_str = request.POST.get('study_duration_years', '4.0').strip()
        credit_hours_str = request.POST.get('total_credit_hours', '130').strip()
        head_name = request.POST.get('department_head', '').strip()
        ministry_decree = request.POST.get('ministry_approval_decree', '').strip()
        dept_id = request.POST.get('department_id')

        department = None
        if dept_id:
            department = Department.objects.filter(pk=dept_id, college=college).first()

        if not name:
            messages.error(request, "اسم البرنامج الأكاديمي إلزامي.")
            return redirect('institutions:detail', pk=institution.pk)

        if AcademicProgram.objects.filter(college=college, name=name).exists():
            messages.error(request, f"البرنامج الأكاديمي ({name}) مسجل مسبقاً في هذه الكلية.")
            return redirect('institutions:detail', pk=institution.pk)

        try:
            duration = float(duration_str)
        except ValueError:
            duration = 4.0

        try:
            credit_hours = int(credit_hours_str)
        except ValueError:
            credit_hours = 130

        program = AcademicProgram.objects.create(
            college=college,
            department=department,
            name=name,
            code=code,
            degree_level=degree_level,
            study_system=study_system,
            study_duration_years=duration,
            total_credit_hours=credit_hours,
            department_head=head_name,
            ministry_approval_decree=ministry_decree
        )
        record_audit_log(
            user=request.user,
            action='PROGRAM_CREATED',
            target_model='AcademicProgram',
            target_id=program.pk,
            details=f"إضافة برنامج أكاديمي ({program.name}) بكلية ({college.name})",
            request=request
        )
        messages.success(request, f"تمت إضافة البرنامج الأكاديمي ({program.name}) بنجاح.")
    return redirect('institutions:detail', pk=institution.pk)

@require_GET
def api_dependent_structure(request):
    """
    Returns dependent cascade:
    ?institution_id=X -> colleges
    ?college_id=Y -> departments & programs
    """
    inst_id = request.GET.get('institution_id')
    college_id = request.GET.get('college_id')

    if inst_id:
        colleges = College.objects.filter(institution_id=inst_id).values('id', 'name')
        return JsonResponse({'colleges': list(colleges)})
    elif college_id:
        departments = Department.objects.filter(college_id=college_id).values('id', 'name')
        programs = AcademicProgram.objects.filter(college_id=college_id).values('id', 'name', 'department_id')
        return JsonResponse({
            'departments': list(departments),
            'programs': list(programs),
        })
    return JsonResponse({'error': 'Missing parameters'}, status=400)
