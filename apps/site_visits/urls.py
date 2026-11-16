from django.urls import path
from . import views

app_name = 'site_visits'

urlpatterns = [
    path('app/<int:app_pk>/', views.site_visit_console, name='console'),
]
