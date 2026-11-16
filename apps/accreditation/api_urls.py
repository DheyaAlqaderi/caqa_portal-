from django.urls import path
from . import api_views

app_name = 'api_v1'

urlpatterns = [
    path('verify/<uuid:uuid>/', api_views.public_verify_api, name='public_verify'),
    path('applications/<int:pk>/timeline/', api_views.application_timeline_api, name='application_timeline'),
    path('standards/', api_views.standards_catalog_api, name='standards_catalog'),
    path('stats/', api_views.system_statistics_api, name='system_statistics'),
]
