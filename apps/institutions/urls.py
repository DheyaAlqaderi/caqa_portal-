from django.urls import path
from . import views

app_name = 'institutions'

urlpatterns = [
    path('', views.institutions_list_view, name='list'),
    path('create/', views.institution_create, name='create'),
    path('<int:pk>/', views.institution_detail_view, name='detail'),
    path('<int:inst_pk>/colleges/create/', views.college_create, name='college_create'),
    path('colleges/<int:college_pk>/departments/create/', views.department_create, name='department_create'),
    path('colleges/<int:college_pk>/programs/create/', views.program_create, name='program_create'),
    path('api/structure/', views.api_dependent_structure, name='api_dependent_structure'),
]
