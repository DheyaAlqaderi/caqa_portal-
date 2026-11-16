from django.urls import path
from . import views
from . import sysadmin_views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('select-role/', views.select_role_view, name='select_role'),
    path('pending-approval/', views.pending_approval_view, name='pending_approval'),
    path('profile/', views.profile_view, name='profile'),
    
    # System Administrator Centralized Dashboard & Technical Modules
    path('sysadmin/dashboard/', sysadmin_views.sysadmin_dashboard_view, name='sysadmin_dashboard'),
    path('sysadmin/reference-data/', sysadmin_views.sysadmin_reference_data_view, name='sysadmin_reference_data'),
    path('sysadmin/settings/', sysadmin_views.sysadmin_settings_view, name='sysadmin_settings'),
    path('sysadmin/notifications-monitor/', sysadmin_views.sysadmin_notifications_monitor_view, name='sysadmin_notifications_monitor'),
    path('sysadmin/files-storage/', sysadmin_views.sysadmin_files_storage_view, name='sysadmin_files_storage'),
    path('sysadmin/workflow-monitor/', sysadmin_views.sysadmin_workflow_monitor_view, name='sysadmin_workflow_monitor'),
    path('sysadmin/security-center/', sysadmin_views.sysadmin_security_center_view, name='sysadmin_security_center'),
    path('sysadmin/backups/', sysadmin_views.sysadmin_backups_view, name='sysadmin_backups'),

    # Admin & Council Board Member User Role Management
    path('admin/users/', views.admin_users_dashboard, name='admin_users_dashboard'),
    path('admin/users/create/', sysadmin_views.admin_create_user_view, name='admin_create_user'),
    path('admin/users/<int:user_id>/edit/', sysadmin_views.admin_edit_user_view, name='admin_edit_user'),
    path('admin/users/<int:user_id>/toggle-active/', sysadmin_views.admin_toggle_user_active_view, name='admin_toggle_user_active'),
    path('admin/users/<int:user_id>/toggle-lock/', sysadmin_views.admin_toggle_user_lock_view, name='admin_toggle_user_lock'),
    path('admin/users/<int:user_id>/reset-password/', sysadmin_views.admin_reset_user_password_view, name='admin_reset_user_password'),
    path('admin/users/<int:user_id>/activity/', sysadmin_views.admin_user_activity_view, name='admin_user_activity'),
    path('admin/users/<int:user_id>/approve/', views.admin_approve_user, name='admin_approve_user'),
    path('admin/users/<int:user_id>/reject/', views.admin_reject_user, name='admin_reject_user'),
    path('admin/users/<int:user_id>/change-role/', views.change_user_role, name='change_user_role'),

    # Notifications
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:pk>/read/', views.notification_mark_read, name='notification_mark_read'),

    # Phase 2: Centralized Dynamic Permission Management & Governance
    path('permissions/matrix/', views.permission_matrix_view, name='permission_matrix'),
    path('permissions/toggle/', views.toggle_role_permission, name='toggle_role_permission'),
    path('permissions/overrides/', views.manage_user_override_view, name='user_overrides'),
    path('permissions/audit/', views.permission_audit_view, name='permission_audit'),

    # Phase 2: Restricted Technical Diagnostics
    path('admin/diagnostics/', views.admin_technical_diagnostics, name='admin_diagnostics'),

    # SMS Gateway & Mobile Notification Registry
    path('admin/sms-gateway/', views.sms_logs_view, name='sms_logs'),

    # My Workspace Library & Document Vault (قسم مكتبتي)
    path('library/', views.library_index_view, name='library_index'),
    path('library/save-asset/', views.library_save_system_asset_view, name='library_save_system_asset'),
    path('library/upload/', views.library_upload_view, name='library_upload'),
    path('library/<int:doc_id>/send/', views.library_send_view, name='library_send'),
    path('library/<int:doc_id>/delete/', views.library_delete_view, name='library_delete'),
    path('library/<int:doc_id>/download/', views.library_download_view, name='library_download'),
]
