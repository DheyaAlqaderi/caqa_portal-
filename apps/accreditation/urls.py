from django.urls import path
from . import views

app_name = 'accreditation'

urlpatterns = [
    # Applications List by Track
    path('institutional/', views.institutional_list, name='institutional_list'),
    path('programmatic/', views.programmatic_list, name='programmatic_list'),
    
    # Central Board Applications Review
    path('board-management/', views.board_applications_list, name='board_applications_list'),
    path('board-review/<int:pk>/', views.board_application_review, name='board_application_review'),
    
    # Application Intake & Details
    path('create/', views.application_create, name='application_create'),
    path('<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail_alias'),
    path('<int:pk>/report/', views.application_report, name='application_report'),
    path('<int:pk>/submit-draft/', views.application_submit_draft, name='application_submit_draft'),
    path('<int:pk>/resubmit/', views.application_resubmit, name='application_resubmit'),
    path('<int:pk>/president-endorse/', views.university_president_endorse, name='president_endorse'),
    path('<int:pk>/endorse/', views.university_president_endorse, name='university_president_endorse'),

    # Self-Study (SSR) & Indicators Evaluation
    path('<int:pk>/self-study/', views.self_study_edit, name='self_study_edit'),
    path('<int:pk>/self-study/indicators/', views.self_study_indicators_edit, name='self_study_indicators_edit'),
    path('<int:pk>/self-study/report/', views.self_study_report_view, name='self_study_report_view'),

    # Evidence, Desk Review & External Review
    path('<int:pk>/evidences/', views.evidence_manage, name='evidence_manage'),
    path('<int:pk>/desk-review/', views.desk_review_process, name='desk_review_process'),
    path('<int:pk>/review-team/', views.assign_review_team, name='assign_review_team'),
    path('<int:pk>/assign-team/', views.assign_review_team, name='assign_review_team_alias'),
    path('<int:pk>/evaluation-rubrics/', views.external_rubrics_evaluation, name='external_rubrics_evaluation'),
    path('<int:pk>/coi/', views.coi_declare, name='coi_declare'),
    path('<int:pk>/external-report/', views.external_report_manage, name='external_report_manage'),
    path('<int:pk>/comparison-dashboard/', views.secretariat_comparison_dashboard, name='secretariat_comparison_dashboard'),
    path('<int:pk>/comparison-export/', views.secretariat_comparison_export, name='secretariat_comparison_export'),
    path('<int:pk>/dossier-17/', views.application_dossier_17_view, name='application_dossier_17_view'),
    path('<int:pk>/ai-analyzer/', views.ai_quality_analyzer_view, name='ai_quality_analyzer'),
    path('<int:pk>/grievance/create/', views.grievance_create, name='grievance_create'),
    path('grievances/', views.grievances_list, name='grievances_list'),
    path('grievances/<int:pk>/review/', views.grievance_review, name='grievance_review'),
    path('<int:pk>/timeline/', views.application_timeline, name='application_timeline'),
    path('evidence/download/<int:pk>/', views.evidence_download, name='evidence_download'),
]
