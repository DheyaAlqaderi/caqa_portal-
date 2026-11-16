from django.urls import path
from . import views

app_name = 'standards'

urlpatterns = [
    path('', views.standards_guide_view, name='guide'),
    path('manage/', views.standards_manage_dashboard, name='manage_dashboard'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_pk>/indicators/create/', views.indicator_create, name='indicator_create'),
    path('indicators/<int:pk>/edit/', views.indicator_edit, name='indicator_edit'),
    path('versions/create/', views.version_create, name='version_create'),
]
