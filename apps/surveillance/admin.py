from django.contrib import admin
from .models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
    CorrectiveActionItem,
    ImprovementPlanEvidence
)

class CorrectiveActionItemInline(admin.TabularInline):
    model = CorrectiveActionItem
    extra = 1

class ImprovementPlanEvidenceInline(admin.TabularInline):
    model = ImprovementPlanEvidence
    extra = 1

@admin.register(ContinuousImprovementPlan)
class ContinuousImprovementPlanAdmin(admin.ModelAdmin):
    list_display = ('plan_title', 'decision', 'status', 'submission_date', 'implementation_timeframe', 'is_approved_by_council')
    list_filter = ('status', 'is_approved_by_council')
    search_fields = ('plan_title', 'corrective_actions_matrix')
    inlines = [CorrectiveActionItemInline, ImprovementPlanEvidenceInline]

@admin.register(CorrectiveActionItem)
class CorrectiveActionItemAdmin(admin.ModelAdmin):
    list_display = ('deficiency_title', 'plan', 'responsible_person', 'department', 'due_date', 'status')
    list_filter = ('status', 'due_date')
    search_fields = ('deficiency_title', 'corrective_activity', 'responsible_person', 'department')

@admin.register(AnnualMonitoringReport)
class AnnualMonitoringReportAdmin(admin.ModelAdmin):
    list_display = ('reporting_period', 'year_number', 'decision', 'review_status', 'submission_date')
    list_filter = ('review_status', 'year_number')
    search_fields = ('reporting_period', 'progress_summary', 'quality_improvements_achieved')

@admin.register(SurveillanceVisit)
class SurveillanceVisitAdmin(admin.ModelAdmin):
    list_display = ('decision', 'visit_type', 'status', 'visit_date', 'compliance_result')
    list_filter = ('status', 'visit_type', 'compliance_result')
    search_fields = ('field_audit_report', 'recommendations_to_council', 'scope_and_deliverables')

@admin.register(ImprovementPlanEvidence)
class ImprovementPlanEvidenceAdmin(admin.ModelAdmin):
    list_display = ('title', 'plan', 'uploaded_by', 'uploaded_at')
    search_fields = ('title', 'description')
