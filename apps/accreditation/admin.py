from django.contrib import admin
from .models import (
    AccreditationApplication,
    SelfStudyReport,
    EvidenceDocument,
    DeskReviewEvaluation,
    ReviewTeam,
    ReviewTeamMember,
    IndicatorEvaluationScore,
    ExternalReviewReport,
    DeskReviewChecklistItem,
    ApplicationStatusHistory,
    ConflictOfInterestDeclaration,
    GrievanceAppeal,
    SecretariatAssessmentComparisonReport,
)

class DeskReviewChecklistItemInline(admin.TabularInline):
    model = DeskReviewChecklistItem
    extra = 1

class ApplicationStatusHistoryInline(admin.TabularInline):
    model = ApplicationStatusHistory
    extra = 0
    readonly_fields = ('from_stage', 'to_stage', 'from_status', 'to_status', 'changed_by', 'reason', 'created_at')

    def has_add_permission(self, request, obj=None):
        return False

class ReviewTeamMemberInline(admin.TabularInline):
    model = ReviewTeamMember
    extra = 2

class EvidenceDocumentInline(admin.TabularInline):
    model = EvidenceDocument
    extra = 1

@admin.register(AccreditationApplication)
class AccreditationApplicationAdmin(admin.ModelAdmin):
    list_display = ('application_number', 'track', 'institution', 'program', 'current_stage', 'status', 'created_at')
    list_filter = ('track', 'current_stage', 'status', 'academic_year')
    search_fields = ('application_number', 'institution__name', 'program__name')
    inlines = [EvidenceDocumentInline]

@admin.register(SelfStudyReport)
class SelfStudyReportAdmin(admin.ModelAdmin):
    list_display = ('application', 'is_locked', 'created_at', 'updated_at')
    search_fields = ('application__application_number', 'internal_committee_names')

@admin.register(EvidenceDocument)
class EvidenceDocumentAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'application', 'indicator', 'uploaded_at')
    list_filter = ('application__track', 'indicator__category')
    search_fields = ('code', 'title', 'description')

@admin.register(DeskReviewEvaluation)
class DeskReviewEvaluationAdmin(admin.ModelAdmin):
    list_display = ('application', 'reviewer', 'decision', 'completeness_percentage', 'is_completed', 'reviewed_at')
    list_filter = ('decision', 'is_completed')
    search_fields = ('application__application_number', 'technical_remarks')

@admin.register(ReviewTeam)
class ReviewTeamAdmin(admin.ModelAdmin):
    list_display = ('application', 'decree_number', 'chairperson', 'formation_date')
    search_fields = ('application__application_number', 'decree_number', 'chairperson__username')
    inlines = [ReviewTeamMemberInline]

@admin.register(IndicatorEvaluationScore)
class IndicatorEvaluationScoreAdmin(admin.ModelAdmin):
    list_display = ('application', 'indicator', 'evaluator', 'score_level', 'evaluated_at')
    list_filter = ('score_level', 'indicator__category')
    search_fields = ('application__application_number', 'indicator__code', 'strengths', 'weaknesses')

@admin.register(ExternalReviewReport)
class ExternalReviewReportAdmin(admin.ModelAdmin):
    list_display = ('application', 'final_recommendation', 'draft_sent_to_institution_date', 'institution_reply_date', 'final_submitted_to_council_date')
    list_filter = ('final_recommendation',)
    search_fields = ('application__application_number', 'draft_executive_summary', 'final_report_text')

@admin.register(ApplicationStatusHistory)
class ApplicationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('application', 'from_status', 'to_status', 'changed_by', 'created_at')
    list_filter = ('from_status', 'to_status', 'created_at')
    search_fields = ('application__application_number', 'reason', 'changed_by__username')

@admin.register(ConflictOfInterestDeclaration)
class ConflictOfInterestDeclarationAdmin(admin.ModelAdmin):
    list_display = ('application', 'reviewer', 'is_conflict_acknowledged', 'signed_at', 'ip_address')
    list_filter = ('is_conflict_acknowledged', 'signed_at')
    search_fields = ('application__application_number', 'reviewer__username', 'reviewer__first_name', 'reviewer__last_name')

@admin.register(GrievanceAppeal)
class GrievanceAppealAdmin(admin.ModelAdmin):
    list_display = ('appeal_number', 'application', 'appellant_user', 'status', 'submission_date', 'resolved_at')
    list_filter = ('status', 'submission_date')
    search_fields = ('appeal_number', 'application__application_number', 'grounds_of_appeal')

@admin.register(SecretariatAssessmentComparisonReport)
class SecretariatAssessmentComparisonReportAdmin(admin.ModelAdmin):
    list_display = ('application', 'title', 'generated_by', 'attached_to_council_briefing', 'created_at')
    list_filter = ('attached_to_council_briefing', 'created_at')
    search_fields = ('application__application_number', 'title', 'secretariat_analytical_summary')

