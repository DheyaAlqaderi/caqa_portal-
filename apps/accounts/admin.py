from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, AuditLog, Notification

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'academic_title', 'first_name', 'last_name', 'role', 'approval_status', 'role_requested', 'institution', 'is_certified_evaluator', 'is_staff')
    list_filter = ('role', 'approval_status', 'role_requested', 'is_certified_evaluator', 'is_staff', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'national_id', 'specialization')
    fieldsets = UserAdmin.fieldsets + (
        ('معلومات الاعتماد الأكاديمي والصفة', {
            'fields': (
                'role',
                'approval_status',
                'role_requested',
                'role_request_notes',
                'role_rejection_reason',
                'approved_by',
                'approved_at',
                'phone',
                'national_id',
                'academic_title',
                'specialization',
                'institution',
                'is_certified_evaluator',
                'evaluator_certificate_number',
            )
        }),
    )

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'recipient', 'title', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('recipient__username', 'title', 'message')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'target_model', 'target_id', 'ip_address')
    list_filter = ('action', 'target_model', 'created_at')
    search_fields = ('user__username', 'target_model', 'target_id', 'details', 'ip_address')
    readonly_fields = ('user', 'action', 'target_model', 'target_id', 'details', 'ip_address', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

