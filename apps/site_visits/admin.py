from django.contrib import admin
from .models import SiteVisitSchedule, FacilityInspection, StakeholderInterview, AcademicAuditRecord

class FacilityInspectionInline(admin.TabularInline):
    model = FacilityInspection
    extra = 1

class StakeholderInterviewInline(admin.TabularInline):
    model = StakeholderInterview
    extra = 1

class AcademicAuditRecordInline(admin.TabularInline):
    model = AcademicAuditRecord
    extra = 1

@admin.register(SiteVisitSchedule)
class SiteVisitScheduleAdmin(admin.ModelAdmin):
    list_display = ('application', 'start_date', 'end_date', 'status', 'logistics_coordinator')
    list_filter = ('status',)
    search_fields = ('application__application_number', 'visit_location')
    inlines = [FacilityInspectionInline, StakeholderInterviewInline, AcademicAuditRecordInline]

@admin.register(FacilityInspection)
class FacilityInspectionAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'category', 'visit', 'inspector', 'adequacy_rating', 'safety_compliance')
    list_filter = ('category', 'adequacy_rating', 'safety_compliance')
    search_fields = ('facility_name', 'detailed_observations')

@admin.register(StakeholderInterview)
class StakeholderInterviewAdmin(admin.ModelAdmin):
    list_display = ('target_group', 'visit', 'conducted_by', 'attendees_count', 'interview_date')
    list_filter = ('target_group',)
    search_fields = ('target_group', 'key_themes_discussed', 'feedback_summary')

@admin.register(AcademicAuditRecord)
class AcademicAuditRecordAdmin(admin.ModelAdmin):
    list_display = ('course_or_subject', 'audit_type', 'visit', 'auditor', 'compliance_rating', 'audit_date')
    list_filter = ('audit_type', 'compliance_rating')
    search_fields = ('course_or_subject', 'findings_and_evidence')
