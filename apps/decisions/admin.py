from django.contrib import admin
from .models import (
    CouncilMeeting,
    CouncilMeetingAttendance,
    CouncilAgendaItem,
    CouncilMeetingAttachment,
    CouncilAgendaDiscussion,
    CouncilBallot,
    CouncilMeetingMinutes,
    CouncilMeetingMinutesVersion,
    CouncilResolution,
    AccreditationDecision,
    AccreditationCertificate,
    CertificateRevocationRecord,
    BoardNomination,
    CouncilPolicy,
    SovereignTransaction,
)

class AccreditationDecisionInline(admin.StackedInline):
    model = AccreditationDecision
    extra = 0

class CouncilAgendaItemInline(admin.TabularInline):
    model = CouncilAgendaItem
    extra = 0

class CertificateRevocationRecordInline(admin.TabularInline):
    model = CertificateRevocationRecord
    extra = 0
    readonly_fields = ('action_type', 'decree_reference', 'justification', 'executed_by', 'action_date')

@admin.register(CouncilMeeting)
class CouncilMeetingAdmin(admin.ModelAdmin):
    list_display = ('meeting_number', 'meeting_type', 'meeting_date', 'status', 'chairperson_name', 'location')
    list_filter = ('meeting_type', 'status', 'meeting_date')
    search_fields = ('meeting_number', 'chairperson_name', 'minutes_summary')
    inlines = [CouncilAgendaItemInline, AccreditationDecisionInline]

@admin.register(CouncilAgendaItem)
class CouncilAgendaItemAdmin(admin.ModelAdmin):
    list_display = ('item_number', 'title', 'meeting', 'item_category', 'required_action', 'status', 'position')
    list_filter = ('item_category', 'required_action', 'status')
    search_fields = ('title', 'description', 'referring_entity')

@admin.register(CouncilMeetingAttendance)
class CouncilMeetingAttendanceAdmin(admin.ModelAdmin):
    list_display = ('member', 'meeting', 'attendee_category', 'status', 'participation_mode', 'is_currently_present')
    list_filter = ('attendee_category', 'status', 'participation_mode', 'is_currently_present')

@admin.register(CouncilAgendaDiscussion)
class CouncilAgendaDiscussionAdmin(admin.ModelAdmin):
    list_display = ('agenda_item', 'speaker_name', 'intervention_type', 'created_at')
    list_filter = ('intervention_type',)

@admin.register(CouncilBallot)
class CouncilBallotAdmin(admin.ModelAdmin):
    list_display = ('title', 'meeting', 'agenda_item', 'voting_mode', 'status', 'final_result', 'majority_achieved', 'tie_broken_by_chairperson')
    list_filter = ('voting_mode', 'status', 'majority_achieved', 'tie_broken_by_chairperson')
    readonly_fields = (
        'votes_approve_count', 'votes_reject_count', 'votes_full_count',
        'votes_conditional_count', 'votes_denied_count', 'votes_abstain_count',
        'majority_achieved', 'tie_occurred', 'tie_broken_by_chairperson', 'final_result'
    )

@admin.register(CouncilMeetingMinutes)
class CouncilMeetingMinutesAdmin(admin.ModelAdmin):
    list_display = ('minutes_number', 'meeting', 'version_number', 'status', 'prepared_by', 'approved_by', 'approved_at')
    list_filter = ('status',)

@admin.register(CouncilResolution)
class CouncilResolutionAdmin(admin.ModelAdmin):
    list_display = ('resolution_number', 'title', 'meeting', 'resolution_type', 'responsible_entity', 'implementation_status', 'deadline_date')
    list_filter = ('resolution_type', 'implementation_status')
    search_fields = ('resolution_number', 'title', 'decision_text')

@admin.register(AccreditationDecision)
class AccreditationDecisionAdmin(admin.ModelAdmin):
    list_display = ('decree_number', 'application', 'decision_type', 'decision_date', 'validity_years', 'start_date', 'expiry_date')
    list_filter = ('decision_type', 'validity_years')
    search_fields = ('decree_number', 'application__application_number', 'legal_justifications')

@admin.register(AccreditationCertificate)
class AccreditationCertificateAdmin(admin.ModelAdmin):
    list_display = ('national_registry_code', 'decision', 'status', 'issue_date', 'is_revoked', 'printed_at')
    list_filter = ('status', 'is_revoked')
    search_fields = ('national_registry_code', 'certificate_uuid')
    inlines = [CertificateRevocationRecordInline]

@admin.register(CertificateRevocationRecord)
class CertificateRevocationRecordAdmin(admin.ModelAdmin):
    list_display = ('certificate', 'action_type', 'decree_reference', 'executed_by', 'action_date')
    list_filter = ('action_type', 'action_date')
    search_fields = ('certificate__national_registry_code', 'decree_reference', 'justification')

@admin.register(BoardNomination)
class BoardNominationAdmin(admin.ModelAdmin):
    list_display = ('nominee_name', 'proposed_position', 'status', 'nomination_date', 'nomination_letter_ref', 'republican_decree_number')
    list_filter = ('status', 'proposed_position', 'nomination_date')
    search_fields = ('nominee_name', 'specialization', 'current_institution', 'republican_decree_number', 'nomination_letter_ref')

@admin.register(CouncilPolicy)
class CouncilPolicyAdmin(admin.ModelAdmin):
    list_display = ('title', 'policy_type', 'status', 'submission_date', 'ratification_date', 'ministerial_decree_number')
    list_filter = ('status', 'policy_type', 'submission_date')
    search_fields = ('title', 'summary', 'ministerial_decree_number', 'council_session_ref')
