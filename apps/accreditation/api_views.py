from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from apps.decisions.models import AccreditationCertificate
from apps.accreditation.models import AccreditationApplication, ReviewTeam, ReviewTeamMember
from apps.standards.models import StandardCategory, StandardVersion
from apps.institutions.models import Institution
from apps.accounts.models import User

@require_GET
def public_verify_api(request, uuid):
    cert = get_object_or_404(
        AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program'
        ),
        certificate_uuid=uuid
    )
    data = {
        'certificate_uuid': str(cert.certificate_uuid),
        'national_registry_code': cert.national_registry_code,
        'status': cert.status,
        'status_display': cert.get_status_display(),
        'is_valid': cert.status == AccreditationCertificate.CertificateStatus.ACTIVE,
        'institution_name': cert.decision.application.institution.name,
        'program_name': cert.decision.application.program.name if cert.decision.application.program else None,
        'track': cert.decision.application.get_track_display(),
        'decree_number': cert.decision.decree_number,
        'issue_date': cert.issue_date.isoformat() if cert.issue_date else None,
        'expiry_date': cert.decision.expiry_date.isoformat() if cert.decision.expiry_date else None,
        'is_revoked': cert.is_revoked,
        'revocation_reason': cert.revocation_reason if cert.is_revoked else None,
    }
    return JsonResponse({'success': True, 'certificate': data})

@login_required
@require_GET
def application_timeline_api(request, pk):
    app = get_object_or_404(AccreditationApplication, pk=pk)
    
    # Check tenant and role permissions
    u = request.user
    if not (u.is_superuser or u.is_staff):
        if u.role == User.Roles.INSTITUTION_OFFICER:
            if not u.institution or app.institution_id != u.institution_id:
                return JsonResponse({'success': False, 'error': 'غير مصرح لك بالاطلاع على هذا الطلب'}, status=403)
        elif u.role == User.Roles.EXTERNAL_REVIEWER:
            assigned = ReviewTeamMember.objects.filter(team__application=app, user=u).exists() or \
                       ReviewTeam.objects.filter(application=app, chairperson=u).exists()
            if not assigned:
                return JsonResponse({'success': False, 'error': 'غير مصرح لك بالاطلاع على هذا الطلب'}, status=403)
        elif u.role not in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER]:
            return JsonResponse({'success': False, 'error': 'غير مصرح لك بالاطلاع على هذا السجل'}, status=403)

    history = app.status_history.select_related('changed_by').all().order_by('created_at')
    items = []
    for h in history:
        items.append({
            'from_stage': h.from_stage,
            'to_stage': h.to_stage,
            'from_status': h.from_status,
            'to_status': h.to_status,
            'changed_by': h.changed_by.get_full_name() or h.changed_by.username if h.changed_by else 'النظام',
            'reason': h.reason,
            'timestamp': h.created_at.isoformat(),
        })
    return JsonResponse({
        'success': True,
        'application_number': app.application_number,
        'current_stage': app.current_stage,
        'current_status': app.status,
        'history': items
    })

@require_GET
def standards_catalog_api(request):
    categories = StandardCategory.objects.filter(is_active=True).prefetch_related('indicators').order_by('track', 'order')
    results = []
    for cat in categories:
        inds = []
        for ind in cat.indicators.all().order_by('order'):
            inds.append({
                'code': ind.code,
                'title': ind.title,
                'is_core': ind.is_core_standard,
            })
        results.append({
            'track': cat.track,
            'track_display': cat.get_track_display(),
            'code': cat.code,
            'title': cat.title,
            'weight_percentage': float(cat.weight_percentage),
            'indicators_count': len(inds),
            'indicators': inds,
        })
    return JsonResponse({'success': True, 'count': len(results), 'categories': results})

@require_GET
def system_statistics_api(request):
    total_inst = Institution.objects.count()
    total_apps = AccreditationApplication.objects.count()
    active_certs = AccreditationCertificate.objects.filter(status=AccreditationCertificate.CertificateStatus.ACTIVE).count()
    revoked_certs = AccreditationCertificate.objects.filter(status=AccreditationCertificate.CertificateStatus.REVOKED).count()

    from django.db.models import Count
    status_counts = dict(
        AccreditationApplication.objects.values('status').annotate(total=Count('id')).values_list('status', 'total')
    )

    return JsonResponse({
        'success': True,
        'institutions_count': total_inst,
        'applications_count': total_apps,
        'active_certificates_count': active_certs,
        'revoked_certificates_count': revoked_certs,
        'applications_by_status': status_counts,
    })
