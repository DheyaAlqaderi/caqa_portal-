from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import SiteVisitSchedule, FacilityInspection, StakeholderInterview, AcademicAuditRecord
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus

from apps.accounts.models import User, record_audit_log
from apps.accreditation.workflow import WorkflowEngine

@login_required
def site_visit_console(request, app_pk):
    application = get_object_or_404(AccreditationApplication, pk=app_pk)

    # Tenant Isolation Guard
    if request.user.role == User.Roles.INSTITUTION_OFFICER and request.user.institution_id:
        if application.institution_id != request.user.institution_id:
            messages.error(request, "غير مصرح لك: ملف الزيارة الميدانية يتبع مؤسسة تعليمية أخرى.")
            return redirect('core_dashboard')

    # Reviewer Assignment Guard
    if request.user.role == User.Roles.EXTERNAL_REVIEWER and not request.user.is_staff:
        has_membership = hasattr(application, 'review_team') and application.review_team.members.filter(user=request.user).exists()
        is_chair = hasattr(application, 'review_team') and application.review_team.chairperson_id == request.user.id
        if not (has_membership or is_chair):
            messages.error(request, "غير مصرح لك: لست عضواً مكلفاً بتحكيم هذا الطلب.")
            return redirect('core_dashboard')

    visit, created = SiteVisitSchedule.objects.get_or_create(
        application=application,
        defaults={
            'start_date': timezone.now().date(),
            'end_date': timezone.now().date() + timezone.timedelta(days=4),
            'visit_location': f"المقر الرئيسي لـ {application.institution.name}",
            'agenda_details': "اليوم 1: اللقاء الافتتاحي وفحص القاعات\nاليوم 2: فحص المختبرات ومصادر التعلم\nاليوم 3: مقابلات أصحاب المصلحة\nاليوم 4: فحص الامتحانات وأعمال الطلاب واللقاء الختامي",
        }
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_schedule':
            if not (request.user.is_council or request.user.is_reviewer or request.user.is_staff):
                messages.error(request, "غير مصرح لك: تعديل واعتماد جدول الزيارة الميدانية خاص بأمانة المجلس وفريق التقييم.")
                return redirect('site_visits:console', app_pk=application.pk)

            old_start = str(visit.start_date)
            old_end = str(visit.end_date)
            old_status = visit.status

            visit.start_date = request.POST.get('start_date')
            visit.end_date = request.POST.get('end_date')
            visit.visit_location = request.POST.get('visit_location', '')
            visit.agenda_details = request.POST.get('agenda_details', '')
            visit.logistics_coordinator = request.POST.get('logistics_coordinator', '')
            new_status = request.POST.get('status', visit.status)
            visit.status = new_status
            visit.final_exit_meeting_notes = request.POST.get('final_exit_meeting_notes', '')
            visit.save()

            record_audit_log(
                user=request.user,
                action='SITE_VISIT_SCHEDULE_UPDATED',
                target_model='SiteVisitSchedule',
                target_id=visit.pk,
                details=f"تحديث جدول الزيارة الميدانية للطلب ({application.application_number}) بالحالة ({visit.get_status_display()})",
                request=request
            )

            from apps.site_visits.services import (
                notify_site_visit_plan_published,
                notify_site_visit_schedule_changed,
                notify_site_visit_cancelled,
                notify_site_visit_completed,
            )

            if visit.status == SiteVisitSchedule.VisitStatus.COMPLETED:
                try:
                    if application.status == ApplicationStatus.PANEL_ASSIGNED:
                        WorkflowEngine.execute_transition(
                            application=application,
                            target_status=ApplicationStatus.SITE_VISIT_SCHEDULED,
                            user=request.user,
                            reason="تأكيد وجدولة الزيارة الميدانية",
                            request=request
                        )
                    WorkflowEngine.execute_transition(
                        application=application,
                        target_status=ApplicationStatus.SITE_VISIT_COMPLETED,
                        user=request.user,
                        reason="اختتام الزيارة الميدانية وتوثيق محضر اللقاء الختامي",
                        request=request
                    )
                    messages.success(request, "تم تسجيل اكتمال الزيارة الميدانية بنجاح وانتقال الطلب للمرحلة 5.")
                except Exception as e:
                    messages.warning(request, f"تم حفظ الزيارة: {e}")

                # Scenario 31: Site visit completion notification
                notify_site_visit_completed(visit)

            elif visit.status == SiteVisitSchedule.VisitStatus.POSTPONED or 'cancel_visit' in request.POST:
                cancel_reason = request.POST.get('cancel_reason', request.POST.get('final_exit_meeting_notes', '')).strip()
                # Scenario 30: Site visit cancelled / postponed
                notify_site_visit_cancelled(visit, reason=cancel_reason)
                messages.warning(request, "تم تسجيل تأجيل الزيارة الميدانية وإشعار كافة المشاركين والمؤسسة.")

            elif old_start != str(visit.start_date) or old_end != str(visit.end_date):
                if application.status == ApplicationStatus.PANEL_ASSIGNED:
                    try:
                        WorkflowEngine.execute_transition(
                            application=application,
                            target_status=ApplicationStatus.SITE_VISIT_SCHEDULED,
                            user=request.user,
                            reason="تأكيد وجدولة الزيارة الميدانية",
                            request=request
                        )
                    except Exception:
                        pass
                # Scenario 28: Schedule changed
                notify_site_visit_schedule_changed(visit, old_dates=f"{old_start} إلى {old_end}")
                messages.success(request, "تم تحديث مواعيد الزيارة الميدانية وإشعار المؤسسة والمحكمين بالتعديل.")

            else:
                if application.status == ApplicationStatus.PANEL_ASSIGNED:
                    try:
                        WorkflowEngine.execute_transition(
                            application=application,
                            target_status=ApplicationStatus.SITE_VISIT_SCHEDULED,
                            user=request.user,
                            reason="تأكيد وجدولة الزيارة الميدانية",
                            request=request
                        )
                    except Exception:
                        pass
                # Scenario 27: Published / Confirmed site visit plan
                notify_site_visit_plan_published(visit)
                messages.success(request, "تم اعتماد وتثبيت خطة الزيارة الميدانية وإشعار المؤسسة وفريق التقييم.")

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            return redirect('site_visits:console', app_pk=application.pk)

        elif action == 'request_correction':
            if not (request.user.is_council or request.user.is_staff):
                messages.error(request, "غير مصرح لك بطلب تصحيحات إدارية.")
                return redirect('site_visits:console', app_pk=application.pk)

            correction_reason = request.POST.get('correction_reason', '').strip()
            reviewer_id = request.POST.get('reviewer_id')
            target_reviewer = User.objects.filter(pk=reviewer_id).first() if reviewer_id else None

            from apps.site_visits.services import notify_assignment_or_visit_requires_correction
            notify_assignment_or_visit_requires_correction(application, target_reviewer=target_reviewer, reason=correction_reason)
            messages.warning(request, "تم تسجيل طلب الاستدراك والتصحيح وإشعار المعنيين.")
            return redirect('site_visits:console', app_pk=application.pk)

        elif action in ['add_facility', 'add_interview', 'add_academic_audit'] and not (request.user.is_reviewer or request.user.is_staff):
            messages.error(request, "غير مصرح لك: توثيق معاينات المرافق والمعامل ومحاضر المقابلات والتدقيق الأكاديمي خاص بأعضاء فريق المحكمين والخبراء فقط.")
            return redirect('site_visits:console', app_pk=application.pk)

        elif action == 'add_facility':
            FacilityInspection.objects.create(
                visit=visit,
                category=request.POST.get('category'),
                facility_name=request.POST.get('facility_name'),
                inspector=request.user,
                capacity_students=int(request.POST.get('capacity_students', 30)),
                adequacy_rating=request.POST.get('adequacy_rating'),
                safety_compliance='safety_compliance' in request.POST,
                detailed_observations=request.POST.get('detailed_observations', ''),
            )
            messages.success(request, "تمت إضافة سجل معاينة المرفق بنجاح.")
            return redirect('site_visits:console', app_pk=application.pk)

        elif action == 'add_interview':
            StakeholderInterview.objects.create(
                visit=visit,
                target_group=request.POST.get('target_group'),
                conducted_by=request.user,
                attendees_count=int(request.POST.get('attendees_count', 10)),
                interview_date=timezone.now(),
                key_themes_discussed=request.POST.get('key_themes_discussed', ''),
                feedback_summary=request.POST.get('feedback_summary', ''),
                satisfaction_level=request.POST.get('satisfaction_level', 'عالٍ'),
            )
            messages.success(request, "تم توثيق محضر مقابلة أصحاب المصلحة بنجاح.")
            return redirect('site_visits:console', app_pk=application.pk)

        elif action == 'add_academic_audit':
            AcademicAuditRecord.objects.create(
                visit=visit,
                audit_type=request.POST.get('audit_type'),
                course_or_subject=request.POST.get('course_or_subject'),
                sampling_details=request.POST.get('sampling_details', ''),
                auditor=request.user,
                compliance_rating=request.POST.get('compliance_rating'),
                findings_and_evidence=request.POST.get('findings_and_evidence', ''),
            )
            messages.success(request, "تم توثيق سجل التدقيق والفحص الأكاديمي بنجاح.")
            return redirect('site_visits:console', app_pk=application.pk)

    inspections = visit.facility_inspections.all()
    interviews = visit.interviews.all()
    audits = visit.academic_audits.all()

    context = {
        'app': application,
        'visit': visit,
        'inspections': inspections,
        'interviews': interviews,
        'audits': audits,
        'facility_categories': FacilityInspection.FacilityCategory.choices,
        'adequacy_levels': FacilityInspection.AdequacyLevel.choices,
        'stakeholder_groups': StakeholderInterview.StakeholderGroup.choices,
        'audit_types': AcademicAuditRecord.AuditType.choices,
        'compliance_levels': AcademicAuditRecord.ComplianceLevel.choices,
    }
    return render(request, 'site_visits/console.html', context)
