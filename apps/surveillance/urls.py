from django.urls import path
from . import views

app_name = 'surveillance'

urlpatterns = [
    path('', views.surveillance_dashboard, name='dashboard'),
    path('manage/<int:decision_pk>/', views.manage_decision_surveillance, name='manage'),
    
    # Continuous Improvement Plan Workflow
    path('plan/<int:plan_pk>/submit/', views.plan_submit, name='plan_submit'),
    path('plan/<int:plan_pk>/secretariat-review/', views.plan_secretariat_review, name='plan_secretariat_review'),
    path('plan/<int:plan_pk>/council-decision/', views.plan_council_decision, name='plan_council_decision'),
    
    # Corrective Action Items & Evidence
    path('plan/<int:plan_pk>/action-item/create/', views.action_item_create, name='action_item_create'),
    path('action-item/<int:item_pk>/edit/', views.action_item_edit, name='action_item_edit'),
    path('action-item/<int:item_pk>/delete/', views.action_item_delete, name='action_item_delete'),
    path('plan/<int:plan_pk>/evidence/upload/', views.evidence_upload, name='evidence_upload'),
    
    # Annual Reports Workflow
    path('report/<int:report_pk>/secretariat-review/', views.report_secretariat_review, name='report_secretariat_review'),
    path('report/<int:report_pk>/council-decision/', views.report_council_decision, name='report_council_decision'),
    
    # External Follow-up & Visits
    path('decision/<int:decision_pk>/visit/assign/', views.surveillance_visit_assign, name='visit_assign'),
    path('reviewer/assignments/', views.reviewer_assignments_dashboard, name='reviewer_assignments'),
    path('reviewer/visit/<int:visit_pk>/', views.reviewer_visit_detail, name='reviewer_visit_detail'),
    path('reviewer/visit/<int:visit_pk>/coi/', views.reviewer_visit_coi, name='reviewer_visit_coi'),
    
    # Secure Document Access
    path('download/evidence/<int:evidence_pk>/', views.download_plan_evidence, name='download_evidence'),
    path('download/report/<int:report_pk>/', views.download_annual_report_file, name='download_report_file'),
]
