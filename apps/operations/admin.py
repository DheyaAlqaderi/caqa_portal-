from django.contrib import admin
from .models import TrainingProgram, TrainingParticipant, SupportTicket, FeeSchedule, Invoice

class TrainingParticipantInline(admin.TabularInline):
    model = TrainingParticipant
    extra = 1

@admin.register(TrainingProgram)
class TrainingProgramAdmin(admin.ModelAdmin):
    list_display = ('title', 'track', 'trainer_name', 'start_date', 'end_date', 'is_active')
    list_filter = ('track', 'is_active', 'start_date')
    search_fields = ('title', 'trainer_name', 'target_audience')
    inlines = [TrainingParticipantInline]

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'institution', 'user', 'category', 'status', 'created_at', 'resolved_at')
    list_filter = ('category', 'status', 'created_at')
    search_fields = ('ticket_number', 'subject', 'message', 'institution__name')

@admin.register(FeeSchedule)
class FeeScheduleAdmin(admin.ModelAdmin):
    list_display = ('service_name', 'track', 'amount_yer', 'regulatory_reference', 'is_active')
    list_filter = ('track', 'is_active')
    search_fields = ('service_name', 'regulatory_reference')

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'application', 'fee_schedule', 'total_amount', 'status', 'issued_at', 'paid_at')
    list_filter = ('status', 'issued_at')
    search_fields = ('invoice_number', 'payment_reference', 'application__application_number')
