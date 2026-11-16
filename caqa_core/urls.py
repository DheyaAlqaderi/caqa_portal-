from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.accounts.views import dashboard_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard_view, name='core_dashboard'),
    path('registry/', include('apps.institutions.public_urls')),
    path('public/', include('apps.institutions.public_urls')),
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),
    path('institutions/', include('apps.institutions.urls', namespace='institutions')),
    path('standards/', include('apps.standards.urls', namespace='standards')),
    path('accreditation/', include('apps.accreditation.urls', namespace='accreditation')),
    path('site-visits/', include('apps.site_visits.urls', namespace='site_visits')),
    path('decisions/', include('apps.decisions.urls', namespace='decisions')),
    path('surveillance/', include('apps.surveillance.urls', namespace='surveillance')),
    path('operations/', include('apps.operations.urls', namespace='operations')),
    path('api/v1/', include('apps.accreditation.api_urls', namespace='api_v1')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
