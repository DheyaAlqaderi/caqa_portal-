from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import StandardCategory, StandardIndicator, StandardVersion, AccreditationTrackType
from apps.accounts.models import record_audit_log

def standards_guide_view(request):
    selected_track = request.GET.get('track', AccreditationTrackType.INSTITUTIONAL)
    
    categories = StandardCategory.objects.filter(track=selected_track).prefetch_related('indicators').order_by('order')
    
    total_categories = categories.count()
    total_indicators = StandardIndicator.objects.filter(category__track=selected_track).count()
    core_indicators = StandardIndicator.objects.filter(category__track=selected_track, is_core_standard=True).count()

    context = {
        'selected_track': selected_track,
        'categories': categories,
        'total_categories': total_categories,
        'total_indicators': total_indicators,
        'core_indicators': core_indicators,
        'track_choices': AccreditationTrackType.choices,
    }
    return render(request, 'standards/guide.html', context)


@login_required
def standards_manage_dashboard(request):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: إدارة المعايير والمؤشرات مخصصة للأمانة الفنية ومسؤولي المجلس.")
        return redirect('standards:guide')

    selected_track = request.GET.get('track', '')
    categories_qs = StandardCategory.objects.all().select_related('version').prefetch_related('indicators').order_by('track', 'order')
    
    if selected_track:
        categories_qs = categories_qs.filter(track=selected_track)

    versions = StandardVersion.objects.all().order_by('-created_at')

    context = {
        'categories': categories_qs,
        'versions': versions,
        'selected_track': selected_track,
        'track_choices': AccreditationTrackType.choices,
        'total_categories': StandardCategory.objects.count(),
        'total_indicators': StandardIndicator.objects.count(),
        'core_indicators': StandardIndicator.objects.filter(is_core_standard=True).count(),
    }
    return render(request, 'standards/manage_dashboard.html', context)


@login_required
def category_create(request):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بإضافة معايير جديدة.")
        return redirect('standards:guide')

    versions = StandardVersion.objects.filter(status=StandardVersion.VersionStatus.ACTIVE)

    if request.method == 'POST':
        track = request.POST.get('track')
        version_id = request.POST.get('version_id')
        code = request.POST.get('code', '').strip().upper()
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        weight = float(request.POST.get('weight_percentage', 10.0))
        order = int(request.POST.get('order', 1))

        if not code or not title:
            messages.error(request, "رمز المعيار وعنوانه حقول مطلوبة.")
            return render(request, 'standards/category_form.html', {'versions': versions, 'track_choices': AccreditationTrackType.choices})

        if StandardCategory.objects.filter(track=track, code=code).exists():
            messages.error(request, f"المعيار برمز ({code}) مسجل مسبقاً في هذا المسار.")
            return render(request, 'standards/category_form.html', {'versions': versions, 'track_choices': AccreditationTrackType.choices})

        version = StandardVersion.objects.filter(pk=version_id).first() if version_id else None

        category = StandardCategory.objects.create(
            track=track,
            version=version,
            code=code,
            title=title,
            description=description,
            weight_percentage=weight,
            order=order
        )

        record_audit_log(
            user=request.user,
            action='STANDARD_CATEGORY_CREATED',
            target_model='StandardCategory',
            target_id=category.pk,
            details=f"إنشاء معيار رئيسي جديد ({category.code}: {category.title}) في مسار ({category.get_track_display()})",
            request=request
        )

        messages.success(request, f"تم إنشاء المعيار ({category.code}: {category.title}) بنجاح.")
        return redirect('standards:manage_dashboard')

    return render(request, 'standards/category_form.html', {'versions': versions, 'track_choices': AccreditationTrackType.choices})


@login_required
def category_edit(request, pk):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بتعديل المعايير.")
        return redirect('standards:guide')

    category = get_object_or_404(StandardCategory, pk=pk)
    versions = StandardVersion.objects.all()

    if request.method == 'POST':
        category.title = request.POST.get('title', '').strip()
        category.description = request.POST.get('description', '').strip()
        category.weight_percentage = float(request.POST.get('weight_percentage', category.weight_percentage))
        category.order = int(request.POST.get('order', category.order))
        category.is_active = 'is_active' in request.POST
        version_id = request.POST.get('version_id')
        if version_id:
            category.version = StandardVersion.objects.filter(pk=version_id).first()
        category.save()

        record_audit_log(
            user=request.user,
            action='STANDARD_CATEGORY_UPDATED',
            target_model='StandardCategory',
            target_id=category.pk,
            details=f"تحديث بيانات المعيار ({category.code}: {category.title})",
            request=request
        )

        messages.success(request, f"تم تحديث بيانات المعيار ({category.code}) بنجاح.")
        return redirect('standards:manage_dashboard')

    return render(request, 'standards/category_form.html', {'category': category, 'versions': versions, 'track_choices': AccreditationTrackType.choices})


@login_required
def indicator_create(request, category_pk):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بإضافة مؤشرات.")
        return redirect('standards:guide')

    category = get_object_or_404(StandardCategory, pk=category_pk)

    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        title = request.POST.get('title', '').strip()
        explanation = request.POST.get('explanation', '').strip()
        suggested_evidences = request.POST.get('suggested_evidences', '').strip()
        is_core = 'is_core_standard' in request.POST
        order = int(request.POST.get('order', category.indicators.count() + 1))

        if not code or not title:
            messages.error(request, "رمز المؤشر وعنوانه حقول مطلوبة.")
            return render(request, 'standards/indicator_form.html', {'category': category})

        if StandardIndicator.objects.filter(category=category, code=code).exists():
            messages.error(request, f"المؤشر برمز ({code}) مسجل مسبقاً في هذا المعيار.")
            return render(request, 'standards/indicator_form.html', {'category': category})

        indicator = StandardIndicator.objects.create(
            category=category,
            code=code,
            title=title,
            explanation=explanation,
            suggested_evidences=suggested_evidences,
            is_core_standard=is_core,
            order=order
        )

        record_audit_log(
            user=request.user,
            action='STANDARD_INDICATOR_CREATED',
            target_model='StandardIndicator',
            target_id=indicator.pk,
            details=f"إضافة مؤشر فرعي جديد ({indicator.code}: {indicator.title}) للمعيار ({category.code})",
            request=request
        )

        messages.success(request, f"تمت إضافة المؤشر ({indicator.code}) بنجاح.")
        return redirect('standards:manage_dashboard')

    next_order = category.indicators.count() + 1
    default_code = f"{category.code.replace('STD', 'IND')}.{next_order}"
    return render(request, 'standards/indicator_form.html', {'category': category, 'default_code': default_code, 'next_order': next_order})


@login_required
def indicator_edit(request, pk):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بتعديل المؤشرات.")
        return redirect('standards:guide')

    indicator = get_object_or_404(StandardIndicator, pk=pk)

    if request.method == 'POST':
        indicator.title = request.POST.get('title', '').strip()
        indicator.explanation = request.POST.get('explanation', '').strip()
        indicator.suggested_evidences = request.POST.get('suggested_evidences', '').strip()
        indicator.is_core_standard = 'is_core_standard' in request.POST
        indicator.order = int(request.POST.get('order', indicator.order))
        indicator.save()

        record_audit_log(
            user=request.user,
            action='STANDARD_INDICATOR_UPDATED',
            target_model='StandardIndicator',
            target_id=indicator.pk,
            details=f"تحديث بيانات المؤشر ({indicator.code})",
            request=request
        )

        messages.success(request, f"تم تحديث بيانات المؤشر ({indicator.code}) بنجاح.")
        return redirect('standards:manage_dashboard')

    return render(request, 'standards/indicator_form.html', {'indicator': indicator, 'category': indicator.category})


@login_required
def version_create(request):
    if not (request.user.is_council or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بإضافة إصدارات معايير.")
        return redirect('standards:guide')

    if request.method == 'POST':
        track = request.POST.get('track')
        title = request.POST.get('title', '').strip()
        version_number = request.POST.get('version_number', '1.0').strip()
        spec = request.POST.get('specialization_or_field', '').strip()
        decree = request.POST.get('adoption_decree', '').strip()

        ver = StandardVersion.objects.create(
            track=track,
            title=title,
            version_number=version_number,
            specialization_or_field=spec,
            adoption_decree=decree,
            status=StandardVersion.VersionStatus.ACTIVE
        )

        record_audit_log(
            user=request.user,
            action='STANDARD_VERSION_CREATED',
            target_model='StandardVersion',
            target_id=ver.pk,
            details=f"إصدار جديد للمعايير الوطنية ({ver.title}) رقم {ver.version_number}",
            request=request
        )

        messages.success(request, f"تم تسجيل إصدار المعايير الجديد ({ver.title}) بنجاح.")
        return redirect('standards:manage_dashboard')

    return render(request, 'standards/version_form.html', {'track_choices': AccreditationTrackType.choices})
