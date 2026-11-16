from django.urls import path
from . import public_views

urlpatterns = [
    path('', public_views.public_registry_view, name='public_registry'),
    path('institutions/<int:pk>/', public_views.public_institution_detail, name='public_institution_detail'),
    path('programs/<int:pk>/', public_views.public_program_detail, name='public_program_detail'),
]
