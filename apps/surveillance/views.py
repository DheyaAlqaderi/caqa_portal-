from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse, Http404, HttpResponseForbidden
from django.db.models import Q
from django.core.exceptions import PermissionDenied

from .models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
    CorrectiveActionItem,
    ImprovementPlanEvidence,
)
from apps.decisions.models import AccreditationDecision
from apps.accounts.models import User, record_audit_log, send_notification, notify_institution


def _get_institution_for_decision(decision):
    return decision.application.institution if decision.application else None


def _check_institution_access(user, decision):
    """
    Verifies that an INSTITUTION_OFFICER or UNIVERSITY_PRESIDENT belongs to the decision's institution.
    Council, Board, Surveillance Auditor, and Admin have administrative scope.
    """
    if user.is_superuser or user.role == User.Roles.ADMIN:
        return True
    if user.is_council or user.is_board or user.role == User.Roles.SURVEILLANCE_AUDITOR:
        return True
    if user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]:
        inst = _get_institution_for_decision(decision)
        if inst and user.institution_id == inst.id:
            return True
    return False


@login_required
def surveillance_dashboard(request):
    """
    Role-scoped Surveillance and Continuous Improvement Dashboard.
    - External Reviewers: strictly routed to their assigned assessments.
    - Institution Representatives: strictly isolated to their own accredited decisions and plans.
    - Secretariat: full operational view with status, deadline, and compliance filters.
    - Council Board: oversight view emphasizing submissions referred to the Council.
    """
    user = request.user

    # External Reviewer isolated dashboard
    if user.role == User.Roles.EXTERNAL_REVIEWER and not (user.is_staff or user.is_superuser):
        return redirect('surveillance:reviewer_assignments')

    decisions_qs = AccreditationDecision.objects.filter(
        decision_type__in=[
            AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION
        ]
    ).select_related(
        'application__institution',
        'application__program',
        'meeting'
    ).prefetch_related('annual_reports', 'surveillance_visits')

    # Tenant Isolation for Institution Officers
    if user.role == User.Roles.INSTITUTION_OFFICER:
        if not user.institution:
            messages.warning(request, "حسابك غير مرتبط بأي مؤسسة تعليمية معتمدة.")
            return render(request, 'surveillance/dashboard.html', {
                'decisions': [],
                'total_accredited': 0,
                'full_accredited': 0,
                'conditional_accredited': 0,
                'annual_reports_count': 0,
                'surveillance_visits_count': 0,
            })
        decisions_qs = decisions_qs.filter(application__institution=user.institution)

    # Optional Filters for Secretariat and Council
    status_filter = request.GET.get('status')
    track_filter = request.GET.get('track')

    total_accredited = decisions_qs.count()
    full_accredited = decisions_qs.filter(decision_type=AccreditationDecision.DecisionType.FULL_ACCREDITATION).count()
    conditional_accredited = decisions_qs.filter(decision_type=AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION).count()
    annual_reports_count = AnnualMonitoringReport.objects.filter(decision__in=decisions_qs).count()
    surveillance_visits_count = SurveillanceVisit.objects.filter(decision__in=decisions_qs).count()

    # Council Referred Items
    referred_plans = ContinuousImprovementPlan.objects.filter(
        decision__in=decisions_qs,
        status__in=[
            ContinuousImprovementPlan.PlanStatus.REFERRED_TO_COUNCIL,
            ContinuousImprovementPlan.PlanStatus.FOLLOWUP_REQUIRED
        ]
    ).select_related('decision__application__institution')

    referred_reports = AnnualMonitoringReport.objects.filter(
        decision__in=decisions_qs,
        review_status__in=[
            AnnualMonitoringReport.ReviewStatus.REFERRED_TO_COUNCIL,
            AnnualMonitoringReport.ReviewStatus.TECHNICALLY_ACCEPTED,
            AnnualMonitoringReport.ReviewStatus.TRIGGER_SITE_AUDIT,
            AnnualMonitoringReport.ReviewStatus.ACTION_REQUIRED,
        ]
    ).select_related('decision__application__institution')

    context = {
        'decisions': decisions_qs,
        'total_accredited': total_accredited,
        'full_accredited': full_accredited,
        'conditional_accredited': conditional_accredited,
        'annual_reports_count': annual_reports_count,
        'surveillance_visits_count': surveillance_visits_count,
        'referred_plans': referred_plans,
        'referred_reports': referred_reports,
        'is_council_member': user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.ADMIN] or user.is_superuser,
        'is_board_member': user.role in [User.Roles.BOARD_MEMBER, User.Roles.ADMIN] or user.is_superuser,
    }
    return render(request, 'surveillance/dashboard.html', context)


@login_required
def manage_decision_surveillance(request, decision_pk):
    """
    Central management view for a specific decision's improvement plan, action items,
    annual reports, and surveillance visits with strict multi-tenant validation.
    """
    decision = get_object_or_404(
        AccreditationDecision.objects.select_related(
            'application__institution',
            'application__program'
        ),
        pk=decision_pk
    )

    # Server-Side Tenant Scoping Guard
    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك: هذه الوثيقة تتبع مؤسسة تعليمية أخرى.")
        return redirect('surveillance:dashboard')

    # External Reviewers cannot access general management view directly
    if request.user.role == User.Roles.EXTERNAL_REVIEWER and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "المحكم الخارجي يمكنه الوصول فقط عبر مهام الزيارات الميدانية المكلف بها.")
        return redirect('surveillance:reviewer_assignments')

    plan, _ = ContinuousImprovementPlan.objects.get_or_create(
        decision=decision,
        defaults={
            'plan_title': f"خطة التحسين المستمر لـ {decision.application.program.name if decision.application.program else decision.application.institution.name}",
            'implementation_timeframe': f"{decision.validity_years} سنوات",
            'corrective_actions_matrix': decision.corrective_requirements or "تنفيذ التوصيات الواردة في التقرير الفني النهائي.",
            'status': ContinuousImprovementPlan.PlanStatus.DRAFT,
        }
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. Institution Saves Draft Improvement Plan
        if action == 'save_plan':
            # Check editing permission on plan status
            if request.user.role == User.Roles.INSTITUTION_OFFICER and not plan.is_editable_by_institution:
                messages.error(request, "لا يمكن تعديل الخطة بعد تقديمها رسمياً إلا إذا أعادتها الأمانة العامة لاستكمال الملاحظات.")
                return redirect('surveillance:manage', decision_pk=decision.pk)

            plan.plan_title = request.POST.get('plan_title', plan.plan_title).strip()
            plan.implementation_timeframe = request.POST.get('implementation_timeframe', plan.implementation_timeframe).strip()
            plan.corrective_actions_matrix = request.POST.get('corrective_actions_matrix', '').strip()
            plan.budget_allocated = request.POST.get('budget_allocated', '').strip()
            plan.save()

            record_audit_log(
                user=request.user,
                action='IMPROVEMENT_PLAN_SAVED',
                target_model='ContinuousImprovementPlan',
                target_id=plan.pk,
                details=f"تحديث مسودة خطة التحسين المستمر ({plan.plan_title})",
                request=request
            )
            messages.success(request, "تم حفظ بيانات خطة التحسين المستمر بنجاح.")

        # 2. Institution Submits Annual Report
        elif action == 'submit_annual_report':
            if request.user.role not in [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN] and not request.user.is_superuser:
                messages.error(request, "إعداد ورفع التقارير السنوية مخصص لممثلي المؤسسة التعليمية فقط.")
                return redirect('surveillance:manage', decision_pk=decision.pk)

            year_num = int(request.POST.get('year_number', 1))
            period = request.POST.get('reporting_period', f"العام {year_num}").strip()
            summary = request.POST.get('progress_summary', '').strip()
            improvements = request.POST.get('quality_improvements_achieved', '').strip()
            report_file = request.FILES.get('report_file')

            report = AnnualMonitoringReport.objects.create(
                decision=decision,
                year_number=year_num,
                reporting_period=period,
                progress_summary=summary,
                quality_improvements_achieved=improvements,
                report_file=report_file,
                submitted_by=request.user,
                review_status=AnnualMonitoringReport.ReviewStatus.SUBMITTED,
            )

            record_audit_log(
                user=request.user,
                action='ANNUAL_REPORT_SUBMITTED',
                target_model='AnnualMonitoringReport',
                target_id=report.pk,
                details=f"رفع التقرير السنوي رقم ({year_num}) للفترة ({period}) لقرار الاعتماد ({decision.decree_number})",
                request=request
            )

            # Notify Secretariat & DG_QUALITY
            secretaries = User.objects.filter(
                role__in=[
                    User.Roles.DG_QUALITY,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                ],
                is_active=True
            )
            for sec in secretaries:
                send_notification(
                    user=sec,
                    title="استلام تقرير متابعة سنوي جديد",
                    message=f"قامت {decision.application.institution.name} بتسليم التقرير السنوي ({period}) وهو بانتظار المراجعة الفنية.",
                    url=f"/surveillance/manage/{decision.pk}/"
                )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            messages.success(request, f"تم رفع التقرير السنوي رقم ({year_num}) بنجاح وإحالته للأمانة العامة للمراجعة الفنية.")

        return redirect('surveillance:manage', decision_pk=decision.pk)

    action_items = plan.action_items.all()
    evidences = plan.evidences.all()
    reports = decision.annual_reports.all()
    visits = decision.surveillance_visits.all()

    can_edit_plan = (request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and plan.is_editable_by_institution) or request.user.is_superuser
    is_secretariat = request.user.is_council or request.user.role == User.Roles.ADMIN or request.user.is_superuser
    is_board = request.user.is_board or request.user.role == User.Roles.ADMIN or request.user.is_superuser

    context = {
        'decision': decision,
        'plan': plan,
        'action_items': action_items,
        'evidences': evidences,
        'reports': reports,
        'visits': visits,
        'can_edit_plan': can_edit_plan,
        'is_secretariat': is_secretariat,
        'is_board': is_board,
        'visit_types': SurveillanceVisit.VisitReason.choices,
        'compliance_statuses': SurveillanceVisit.ComplianceStatus.choices,
        'available_reviewers': User.objects.filter(
            role=User.Roles.EXTERNAL_REVIEWER,
            approval_status=User.ApprovalStatus.APPROVED
        ) if is_secretariat else [],
    }
    return render(request, 'surveillance/manage.html', context)


# =============================================================================
# CONTINUOUS IMPROVEMENT PLAN WORKFLOW ACTIONS
# =============================================================================

@login_required
def plan_submit(request, plan_pk):
    """
    Institution officially submits CIP for Secretariat Technical Review.
    Locks the plan from further editing until/unless returned for revision.
    """
    plan = get_object_or_404(ContinuousImprovementPlan.objects.select_related('decision__application__institution'), pk=plan_pk)
    decision = plan.decision

    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك بالوصول لهذه الخطة.")
        return redirect('surveillance:dashboard')

    if request.user.role not in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and not request.user.is_superuser:
        messages.error(request, "تقديم خطة التحسين مخصص لممثلي المؤسسة فقط.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if not plan.is_editable_by_institution:
        messages.warning(request, f"الخطة بالفعل في حالة ({plan.get_status_display()}) ولا يمكن إعادة تقديمها حالياً.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if plan.action_items.count() == 0:
        messages.error(request, "يرجى إضافة بند إجراء تصحيحي واحد على الأقل قبل تقديم الخطة للأمانة العامة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    plan.status = ContinuousImprovementPlan.PlanStatus.SUBMITTED if plan.status == ContinuousImprovementPlan.PlanStatus.DRAFT else ContinuousImprovementPlan.PlanStatus.RESUBMITTED
    plan.submitted_by = request.user
    plan.submitted_at = timezone.now()
    plan.save()

    record_audit_log(
        user=request.user,
        action='IMPROVEMENT_PLAN_SUBMITTED',
        target_model='ContinuousImprovementPlan',
        target_id=plan.pk,
        details=f"تقديم خطة التحسين المستمر ({plan.plan_title}) للمراجعة الفنية للأمانة العامة",
        request=request
    )

    try:
        from apps.accounts.library_service import sync_system_assets_to_library
        sync_system_assets_to_library()
    except Exception:
        pass

    # Notify Secretariat & DG_QUALITY
    secretaries = User.objects.filter(
        role__in=[
            User.Roles.DG_QUALITY,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
        ],
        is_active=True
    )
    for sec in secretaries:
        send_notification(
            user=sec,
            title="تقديم خطة تحسين مستمر جديدة",
            message=f"قدمت مؤسسة ({decision.application.institution.name}) خطة التحسين المستمر برسم المراجعة الفنية.",
            url=f"/surveillance/manage/{decision.pk}/"
        )

    messages.success(request, "تم تقديم خطة التحسين المستمر رسمياً للأمانة العامة، وهي الآن قيد المراجعة الفنية.")
    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def plan_secretariat_review(request, plan_pk):
    """
    Council Secretariat reviews CIP:
    - Return for correction (NEEDS_REVISION) with feedback.
    - Mark as technically reviewed (TECHNICALLY_REVIEWED).
    - Refer to Council Board (REFERRED_TO_COUNCIL).
    - Request follow-up site visit (FOLLOWUP_REQUIRED).
    """
    plan = get_object_or_404(ContinuousImprovementPlan.objects.select_related('decision__application__institution'), pk=plan_pk)
    decision = plan.decision

    if not (request.user.is_council or request.user.role == User.Roles.ADMIN or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: مراجعة خطط التحسين فنياً مقتصرة على الأمانة العامة للمجلس والإدارة العامة للجودة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        action = request.POST.get('review_action')
        notes = request.POST.get('secretariat_review_notes', '').strip()

        plan.reviewed_by = request.user
        plan.reviewed_at = timezone.now()
        plan.secretariat_review_notes = notes

        institution = decision.application.institution
        officers = User.objects.filter(institution=institution, role=User.Roles.INSTITUTION_OFFICER, approval_status=User.ApprovalStatus.APPROVED)

        if action == 'request_revision':
            if not notes:
                messages.error(request, "يرجى تدوين الملاحظات والمبررات المطلوبة من المؤسسة عند إعادة الخطة للتعديل.")
                return redirect('surveillance:manage', decision_pk=decision.pk)

            plan.status = ContinuousImprovementPlan.PlanStatus.NEEDS_REVISION
            plan.save()

            notify_institution(
                institution=institution,
                title="إعادة خطة التحسين المستمر لاستكمال ملاحظات",
                message=f"أعادت الأمانة العامة خطة التحسين للمؤسسة مع ملاحظات: {notes[:100]}...",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=plan.submitted_by
            )
            messages.warning(request, "تمت إعادة خطة التحسين للمؤسسة مع الملاحظات الفنية.")

        elif action == 'mark_technically_reviewed':
            plan.status = ContinuousImprovementPlan.PlanStatus.TECHNICALLY_REVIEWED
            plan.save()
            messages.success(request, "تم اعتماد استيفاء المراجعة الفنية للخطة بنجاح.")

        elif action == 'refer_to_council':
            plan.status = ContinuousImprovementPlan.PlanStatus.REFERRED_TO_COUNCIL
            plan.save()

            board_members = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                ],
                is_active=True
            )
            for bm in board_members:
                send_notification(
                    user=bm,
                    title="إحالة خطة تحسين مستمر لمجلس الإدارة",
                    message=f"أحالت الأمانة العامة خطة التحسين لمؤسسة ({institution.name}) للمجلس للاعتماد الرسمي.",
                    url=f"/surveillance/manage/{decision.pk}/"
                )
            messages.success(request, "تم رفع وإحالة خطة التحسين المستمر إلى مجلس الإدارة للبت والاعتماد.")

        elif action == 'require_followup':
            plan.status = ContinuousImprovementPlan.PlanStatus.FOLLOWUP_REQUIRED
            plan.save()
            messages.info(request, "تم تسجيل متطلب تنفيذ زيارة استطلاعية تحققية للخطة.")

        record_audit_log(
            user=request.user,
            action='IMPROVEMENT_PLAN_REVIEWED',
            target_model='ContinuousImprovementPlan',
            target_id=plan.pk,
            details=f"إجراء المراجعة الفنية للأمانة ({action}) على خطة ({plan.plan_title}) - الحالة الجديدة: ({plan.status})",
            request=request
        )

    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def plan_council_decision(request, plan_pk):
    """
    Council Board formally decides on the Continuous Improvement Plan.
    Separation of duties: only Council Board or Superuser can officially endorse.
    """
    plan = get_object_or_404(ContinuousImprovementPlan.objects.select_related('decision__application__institution'), pk=plan_pk)
    decision = plan.decision

    if not (request.user.is_board or request.user.role == User.Roles.ADMIN or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: اعتماد وقرارات خطط التحسين اختصاص أصيل لمجلس الإدارة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        decision_action = request.POST.get('council_decision_action')
        approval_notes = request.POST.get('approval_notes', '').strip()

        plan.decided_by = request.user
        plan.decided_at = timezone.now()
        plan.approval_notes = approval_notes

        institution = decision.application.institution
        officers = User.objects.filter(institution=institution, role=User.Roles.INSTITUTION_OFFICER, approval_status=User.ApprovalStatus.APPROVED)

        if decision_action == 'approve':
            plan.is_approved_by_council = True
            plan.status = ContinuousImprovementPlan.PlanStatus.APPROVED_BY_COUNCIL
            plan.save()

            notify_institution(
                institution=institution,
                title="اعتماد خطة التحسين المستمر رسمياً",
                message=f"أصدر مجلس الإدارة قراره باعتماد خطة التحسين المستمر لمؤسستكم ({plan.plan_title}).",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=plan.submitted_by
            )
            messages.success(request, "تم اعتماد خطة التحسين المستمر رسمياً بقرار مجلس الإدارة.")

        elif decision_action == 'require_revision':
            plan.status = ContinuousImprovementPlan.PlanStatus.NEEDS_REVISION
            plan.is_approved_by_council = False
            plan.save()

            notify_institution(
                institution=institution,
                title="توجيهات مجلس الإدارة بشأن خطة التحسين",
                message=f"أعاد مجلس الإدارة خطة التحسين للتعديل بموجب التوجيهات: {approval_notes[:100]}...",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=plan.submitted_by
            )
            messages.warning(request, "تم تسجيل توجيهات المجلس بإعادة الخطة للتعديل.")

        record_audit_log(
            user=request.user,
            action='IMPROVEMENT_PLAN_COUNCIL_DECIDED',
            target_model='ContinuousImprovementPlan',
            target_id=plan.pk,
            details=f"قرار مجلس الإدارة ({decision_action}) على خطة التحسين ({plan.plan_title})",
            request=request
        )

    return redirect('surveillance:manage', decision_pk=decision.pk)


# =============================================================================
# CORRECTIVE ACTION ITEMS AND EVIDENCE MANAGEMENT
# =============================================================================

@login_required
def action_item_create(request, plan_pk):
    """Adds a measurable corrective action item to the improvement plan."""
    plan = get_object_or_404(ContinuousImprovementPlan.objects.select_related('decision__application__institution'), pk=plan_pk)
    decision = plan.decision

    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك بإضافة إجراءات لهذه الخطة.")
        return redirect('surveillance:dashboard')

    if request.user.role == User.Roles.INSTITUTION_OFFICER and not plan.is_editable_by_institution:
        messages.error(request, "لا يمكن إضافة بنود إلى الخطة في حالتها الحالية.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        deficiency = request.POST.get('deficiency_title', '').strip()
        activity = request.POST.get('corrective_activity', '').strip()
        responsible = request.POST.get('responsible_person', '').strip()
        dept = request.POST.get('department', '').strip()
        due_date = request.POST.get('due_date')
        kpi = request.POST.get('kpi_measure', '').strip()
        evidence_doc = request.FILES.get('evidence_document')

        if not deficiency or not activity or not due_date:
            messages.error(request, "الملاحظة، الإجراء التصحيحي، وتاريخ الاستحقاق كلها حقول إلزامية.")
            return redirect('surveillance:manage', decision_pk=decision.pk)

        item = CorrectiveActionItem.objects.create(
            plan=plan,
            deficiency_title=deficiency,
            corrective_activity=activity,
            responsible_person=responsible,
            department=dept,
            due_date=due_date,
            kpi_measure=kpi,
            evidence_document=evidence_doc,
            status=CorrectiveActionItem.ActionStatus.IN_PROGRESS,
        )

        record_audit_log(
            user=request.user,
            action='CORRECTIVE_ACTION_CREATED',
            target_model='CorrectiveActionItem',
            target_id=item.pk,
            details=f"إضافة بند إجراء تصحيحي جديد ({item.deficiency_title}) لخطة التحسين ({plan.plan_title})",
            request=request
        )
        messages.success(request, f"تمت إضافة الإجراء التصحيحي ({item.deficiency_title}) بنجاح.")

    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def action_item_edit(request, item_pk):
    """Edits an existing corrective action item."""
    item = get_object_or_404(CorrectiveActionItem.objects.select_related('plan__decision__application__institution'), pk=item_pk)
    plan = item.plan
    decision = plan.decision

    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك بتعديل هذا الإجراء.")
        return redirect('surveillance:dashboard')

    if request.user.role == User.Roles.INSTITUTION_OFFICER and not plan.is_editable_by_institution:
        messages.error(request, "الخطة ليست في وضع التعديل حالياً.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        item.deficiency_title = request.POST.get('deficiency_title', item.deficiency_title).strip()
        item.corrective_activity = request.POST.get('corrective_activity', item.corrective_activity).strip()
        item.responsible_person = request.POST.get('responsible_person', item.responsible_person).strip()
        item.department = request.POST.get('department', item.department).strip()
        item.kpi_measure = request.POST.get('kpi_measure', item.kpi_measure).strip()
        due = request.POST.get('due_date')
        if due:
            item.due_date = due
        if 'evidence_document' in request.FILES:
            item.evidence_document = request.FILES['evidence_document']

        # Secretariat or Council verification
        if request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.ADMIN] or request.user.is_superuser:
            sec_notes = request.POST.get('secretariat_verification_notes')
            if sec_notes is not None:
                item.secretariat_verification_notes = sec_notes.strip()
            item_status = request.POST.get('status')
            if item_status in CorrectiveActionItem.ActionStatus.values:
                item.status = item_status

        item.save()
        messages.success(request, "تم تحديث بند الإجراء التصحيحي بنجاح.")

    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def action_item_delete(request, item_pk):
    """Deletes an action item if the plan is in an editable state."""
    item = get_object_or_404(CorrectiveActionItem.objects.select_related('plan__decision__application__institution'), pk=item_pk)
    plan = item.plan
    decision = plan.decision

    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك بحذف هذا الإجراء.")
        return redirect('surveillance:dashboard')

    if request.user.role == User.Roles.INSTITUTION_OFFICER and not plan.is_editable_by_institution:
        messages.error(request, "لا يمكن حذف بنود من خطة قيد المراجعة أو معتمدة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    title = item.deficiency_title
    item.delete()
    messages.info(request, f"تم حذف الإجراء التصحيحي ({title}).")
    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def evidence_upload(request, plan_pk):
    """Uploads supporting documentation / evidence for a plan or specific action item."""
    plan = get_object_or_404(ContinuousImprovementPlan.objects.select_related('decision__application__institution'), pk=plan_pk)
    decision = plan.decision

    if not _check_institution_access(request.user, decision):
        messages.error(request, "غير مصرح لك برفع شواهد لهذه الخطة.")
        return redirect('surveillance:dashboard')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        desc = request.POST.get('description', '').strip()
        doc_file = request.FILES.get('evidence_file')
        action_item_id = request.POST.get('action_item_id')

        if not title or not doc_file:
            messages.error(request, "عنوان الشاهد وملف الوثيقة كلاهما مطلوب.")
            return redirect('surveillance:manage', decision_pk=decision.pk)

        action_item = None
        if action_item_id:
            action_item = CorrectiveActionItem.objects.filter(pk=action_item_id, plan=plan).first()

        ev = ImprovementPlanEvidence.objects.create(
            plan=plan,
            action_item=action_item,
            title=title,
            description=desc,
            evidence_file=doc_file,
            uploaded_by=request.user
        )

        record_audit_log(
            user=request.user,
            action='EVIDENCE_DOCUMENT_UPLOADED',
            target_model='ImprovementPlanEvidence',
            target_id=ev.pk,
            details=f"رفع وثيقة شاهد إثبات ({ev.title}) لخطة التحسين ({plan.plan_title})",
            request=request
        )
        messages.success(request, f"تم رفع وثيقة الشاهد ({ev.title}) بنجاح.")

    return redirect('surveillance:manage', decision_pk=decision.pk)


# =============================================================================
# ANNUAL MONITORING REPORTS WORKFLOW
# =============================================================================

@login_required
def report_secretariat_review(request, report_pk):
    """
    Secretariat reviews an Annual Institutional Monitoring Report:
    - Return for correction (NEEDS_CORRECTION).
    - Mark as technically accepted (TECHNICALLY_ACCEPTED).
    - Refer to Council Board (REFERRED_TO_COUNCIL).
    - Trigger site audit (TRIGGER_SITE_AUDIT).
    """
    report = get_object_or_404(AnnualMonitoringReport.objects.select_related('decision__application__institution'), pk=report_pk)
    decision = report.decision

    if not (request.user.is_council or request.user.role == User.Roles.ADMIN or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: المراجعة الفنية للتقارير السنوية مقتصرة على الأمانة العامة والإدارة العامة للجودة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        action = request.POST.get('review_action')
        comments = request.POST.get('secretariat_review_comments', '').strip()

        report.reviewed_by = request.user
        report.reviewed_at = timezone.now()
        report.secretariat_review_comments = comments

        institution = decision.application.institution
        officers = User.objects.filter(institution=institution, role=User.Roles.INSTITUTION_OFFICER, approval_status=User.ApprovalStatus.APPROVED)

        if action == 'request_corrections':
            report.review_status = AnnualMonitoringReport.ReviewStatus.NEEDS_CORRECTION
            report.save()

            notify_institution(
                institution=institution,
                title="طلب تعديل واستكمال التقرير السنوي",
                message=f"أعادت الأمانة التقرير السنوي رقم ({report.year_number}) مع ملاحظات للمراجعة.",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=report.submitted_by
            )
            messages.warning(request, "تمت إعادة التقرير السنوي للمؤسسة لتقديم إيضاحات واستكمالات.")

        elif action == 'accept_technical':
            report.review_status = AnnualMonitoringReport.ReviewStatus.TECHNICALLY_ACCEPTED
            report.save()
            messages.success(request, "تم قبول التقرير السنوي فنياً من الأمانة العامة.")

        elif action == 'refer_to_council':
            report.review_status = AnnualMonitoringReport.ReviewStatus.REFERRED_TO_COUNCIL
            report.save()

            board_members = User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                ],
                is_active=True
            )
            for bm in board_members:
                send_notification(
                    user=bm,
                    title="إحالة تقرير سنوي لمجلس الإدارة",
                    message=f"أحيل التقرير السنوي لمؤسسة ({institution.name}) للمجلس للاعتماد الرسمي.",
                    url=f"/surveillance/manage/{decision.pk}/"
                )
            messages.success(request, "تمت إحالة التقرير السنوي لمجلس الإدارة.")

        elif action == 'trigger_site_audit':
            report.review_status = AnnualMonitoringReport.ReviewStatus.TRIGGER_SITE_AUDIT
            report.save()
            messages.info(request, "تم تسجيل متطلب زيارة استطلاعية تحققية بناء على فحص التقرير.")

        record_audit_log(
            user=request.user,
            action='ANNUAL_REPORT_REVIEWED',
            target_model='AnnualMonitoringReport',
            target_id=report.pk,
            details=f"مراجعة الأمانة الفنية للتقرير السنوي رقم ({report.year_number}) - الحالة الجديدة: ({report.review_status})",
            request=request
        )

    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def report_council_decision(request, report_pk):
    """
    Council Board formally decides on the Annual Monitoring Report.
    """
    report = get_object_or_404(AnnualMonitoringReport.objects.select_related('decision__application__institution'), pk=report_pk)
    decision = report.decision

    if not (request.user.is_board or request.user.role == User.Roles.ADMIN or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: قرارات التقارير السنوية اختصاص أصيل لمجلس الإدارة.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        action = request.POST.get('council_action')
        feedback = request.POST.get('council_feedback_comments', '').strip()

        report.decided_at = timezone.now()
        report.council_feedback_comments = feedback

        institution = decision.application.institution
        officers = User.objects.filter(institution=institution, role=User.Roles.INSTITUTION_OFFICER, approval_status=User.ApprovalStatus.APPROVED)

        if action == 'satisfactory':
            report.review_status = AnnualMonitoringReport.ReviewStatus.SATISFACTORY
            report.save()

            notify_institution(
                institution=institution,
                title="اعتماد التقرير السنوي واستمرار الاعتماد",
                message=f"اعتمد مجلس الإدارة التقرير السنوي رقم ({report.year_number}) مع تأكيد استمرار سريان الاعتماد.",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=report.submitted_by
            )
            messages.success(request, "تم اعتماد التقرير السنوي رسمياً والتأكيد على استمرار سريان وثيقة الاعتماد.")

        elif action == 'action_required':
            report.review_status = AnnualMonitoringReport.ReviewStatus.ACTION_REQUIRED
            report.save()

            notify_institution(
                institution=institution,
                title="توجيه إنذار / إجراء تصحيحي من مجلس الإدارة",
                message=f"وجه مجلس الإدارة اشتراطات وتدابير تصحيحية حيال التقرير السنوي: {feedback[:100]}...",
                url=f"/surveillance/manage/{decision.pk}/",
                extra_recipients=report.submitted_by
            )
            messages.warning(request, "تم تسجيل قرار المجلس بفرض تدابير واشتراطات تصحيحية.")

        elif action == 'trigger_audit':
            report.review_status = AnnualMonitoringReport.ReviewStatus.TRIGGER_SITE_AUDIT
            report.save()
            messages.info(request, "قرر المجلس تكليف فريق متابعة ميداني استطلاعي للتحقق.")

        record_audit_log(
            user=request.user,
            action='ANNUAL_REPORT_COUNCIL_DECIDED',
            target_model='AnnualMonitoringReport',
            target_id=report.pk,
            details=f"قرار المجلس حيال التقرير السنوي رقم ({report.year_number}) - النتيجة: ({report.review_status})",
            request=request
        )

    return redirect('surveillance:manage', decision_pk=decision.pk)


# =============================================================================
# EXTERNAL REVIEWER FOLLOW-UP ASSESSMENTS & VISITS
# =============================================================================

@login_required
def surveillance_visit_assign(request, decision_pk):
    """
    Council Secretariat assigns an External Reviewer for on-site follow-up verification.
    """
    decision = get_object_or_404(AccreditationDecision.objects.select_related('application__institution'), pk=decision_pk)

    if not (request.user.is_council or request.user.role == User.Roles.ADMIN or request.user.is_superuser):
        messages.error(request, "غير مصرح لك: تكليف الزيارات الاستطلاعية من اختصاص الأمانة العامة والإدارة العامة للجودة فقط.")
        return redirect('surveillance:manage', decision_pk=decision.pk)

    if request.method == 'POST':
        v_type = request.POST.get('visit_type', SurveillanceVisit.VisitReason.ROUTINE)
        v_date = request.POST.get('visit_date') or timezone.now().date()
        scope = request.POST.get('scope_and_deliverables', '').strip()
        auditor_ids = request.POST.getlist('auditor_ids')

        visit = SurveillanceVisit.objects.create(
            decision=decision,
            visit_type=v_type,
            visit_date=v_date,
            scope_and_deliverables=scope,
            assigned_by=request.user,
            status=SurveillanceVisit.VisitStatus.ASSIGNED,
            field_audit_report='',
            recommendations_to_council=''
        )

        for a_id in auditor_ids:
            auditor = User.objects.filter(pk=a_id, role=User.Roles.EXTERNAL_REVIEWER).first()
            if auditor:
                visit.auditors.add(auditor)
                send_notification(
                    user=auditor,
                    title="تكليف بمهمة زيارة استطلاعية وتحققية",
                    message=f"تم تكليفكم بمهمة زيارة استطلاعية لمؤسسة ({decision.application.institution.name}) بتاريخ {v_date}.",
                    url=f"/surveillance/reviewer/visit/{visit.pk}/"
                )

        record_audit_log(
            user=request.user,
            action='SURVEILLANCE_VISIT_ASSIGNED',
            target_model='SurveillanceVisit',
            target_id=visit.pk,
            details=f"تكليف زيارة متابعة ({visit.get_visit_type_display()}) لمؤسسة ({decision.application.institution.name})",
            request=request
        )
        messages.success(request, "تم إنشاء تكليف الزيارة الاستطلاعية وإشعار المحكمين المكلفين بنجاح.")

    return redirect('surveillance:manage', decision_pk=decision.pk)


@login_required
def reviewer_assignments_dashboard(request):
    """
    Dashboard for External Reviewers: displays strictly their assigned surveillance visits.
    Reviewer cannot browse any other institutions or surveillance decisions.
    """
    user = request.user
    if user.role != User.Roles.EXTERNAL_REVIEWER and not (user.is_staff or user.is_superuser):
        messages.error(request, "هذه اللوحة مخصصة للخبراء والمحكمين الخارجيين فقط.")
        return redirect('surveillance:dashboard')

    assigned_visits = SurveillanceVisit.objects.filter(
        auditors=user
    ).select_related(
        'decision__application__institution',
        'decision__application__program'
    ).order_by('-visit_date')

    context = {
        'assigned_visits': assigned_visits,
    }
    return render(request, 'surveillance/reviewer_assignments.html', context)


@login_required
def reviewer_visit_coi(request, visit_pk):
    """
    External Reviewer signs/declares Conflict of Interest (COI) before accessing materials.
    """
    visit = get_object_or_404(SurveillanceVisit.objects.select_related('decision__application__institution'), pk=visit_pk)

    if request.user not in visit.auditors.all() and not request.user.is_superuser:
        messages.error(request, "غير مصرح لك: لست من المحكمين المكلفين بهذه الزيارة الاستطلاعية.")
        return redirect('surveillance:reviewer_assignments')

    if request.method == 'POST':
        acknowledged = request.POST.get('acknowledge_coi') == '1'
        if not acknowledged:
            messages.error(request, "يجب قراءة وتأكيد إقرار النزاهة والحياد للمتابعة.")
            return redirect('surveillance:reviewer_visit_detail', visit_pk=visit.pk)

        visit.coi_declared_by.add(request.user)

        record_audit_log(
            user=request.user,
            action='SURVEILLANCE_COI_DECLARED',
            target_model='SurveillanceVisit',
            target_id=visit.pk,
            details=f"توقيع إقرار النزاهة والحياد للزيارة الاستطلاعية لمؤسسة ({visit.decision.application.institution.name})",
            request=request
        )
        messages.success(request, "تم تسجيل إقرار النزاهة والحياد بنجاح. يمكنك الآن الاطلاع على وثائق الخطة وتقديم تقريرك.")

    return redirect('surveillance:reviewer_visit_detail', visit_pk=visit.pk)


@login_required
def reviewer_visit_detail(request, visit_pk):
    """
    External Reviewer view for an assigned visit.
    Enforces COI declaration before unlocking materials.
    Allows submitting field audit findings and recommendations to Secretariat.
    """
    visit = get_object_or_404(
        SurveillanceVisit.objects.select_related(
            'decision__application__institution',
            'decision__application__program'
        ),
        pk=visit_pk
    )

    # Check assignment
    is_assigned = request.user in visit.auditors.all()
    if not is_assigned and not (request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.ADMIN] or request.user.is_superuser):
        messages.error(request, "غير مصرح لك بالاطلاع على تكليف زيارة لم يتم تعيينك فيها.")
        return redirect('surveillance:reviewer_assignments')

    has_declared_coi = request.user in visit.coi_declared_by.all() or request.user.is_superuser

    decision = visit.decision
    plan = getattr(decision, 'improvement_plan', None)
    action_items = plan.action_items.all() if plan else []
    evidences = plan.evidences.all() if plan else []

    if request.method == 'POST' and is_assigned:
        if not has_declared_coi:
            messages.error(request, "لا يمكنك تسليم التقرير قبل التوقيع على إقرار النزاهة والحياد.")
            return redirect('surveillance:reviewer_visit_detail', visit_pk=visit.pk)

        findings = request.POST.get('field_audit_report', '').strip()
        progress = request.POST.get('findings_verified_progress', '').strip()
        gaps = request.POST.get('remaining_gaps', '').strip()
        evidence_notes = request.POST.get('supporting_evidence_notes', '').strip()
        compliance_res = request.POST.get('compliance_result', SurveillanceVisit.ComplianceStatus.MAINTAINED)
        recommendations = request.POST.get('recommendations_to_council', '').strip()

        if not findings or not recommendations:
            messages.error(request, "تقرير المعاينة الميدانية والتوصيات المرفوعة كلاهما مطلوب.")
            return redirect('surveillance:reviewer_visit_detail', visit_pk=visit.pk)

        visit.field_audit_report = findings
        visit.findings_verified_progress = progress
        visit.remaining_gaps = gaps
        visit.supporting_evidence_notes = evidence_notes
        visit.compliance_result = compliance_res
        visit.recommendations_to_council = recommendations
        visit.status = SurveillanceVisit.VisitStatus.REPORT_SUBMITTED
        visit.save()

        record_audit_log(
            user=request.user,
            action='REVIEWER_SURVEILLANCE_REPORT_SUBMITTED',
            target_model='SurveillanceVisit',
            target_id=visit.pk,
            details=f"تسليم تقرير الزيارة الاستطلاعية بواسطة المحكم ({request.user.username}) لقرار ({decision.decree_number})",
            request=request
        )

        # Notify Secretariat & DG_QUALITY
        secretaries = User.objects.filter(
            role__in=[
                User.Roles.DG_QUALITY,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
            ],
            is_active=True
        )
        for sec in secretaries:
            send_notification(
                user=sec,
                title="تسليم تقرير محكم زيارة استطلاعية",
                message=f"سلم المحكم ({request.user.get_full_name() or request.user.username}) تقرير الزيارة الاستطلاعية لمؤسسة ({decision.application.institution.name}).",
                url=f"/surveillance/manage/{decision.pk}/"
            )

        try:
            from apps.accounts.library_service import sync_system_assets_to_library
            sync_system_assets_to_library()
        except Exception:
            pass

        messages.success(request, "تم تسليم تقرير الزيارة الاستطلاعية بنجاح إلى الأمانة العامة للمجلس.")
        return redirect('surveillance:reviewer_visit_detail', visit_pk=visit.pk)

    context = {
        'visit': visit,
        'decision': decision,
        'plan': plan,
        'action_items': action_items,
        'evidences': evidences,
        'has_declared_coi': has_declared_coi,
        'compliance_statuses': SurveillanceVisit.ComplianceStatus.choices,
        'is_assigned': is_assigned,
    }
    return render(request, 'surveillance/reviewer_visit_detail.html', context)


# =============================================================================
# SECURE DOCUMENT DOWNLOADS
# =============================================================================

@login_required
def download_plan_evidence(request, evidence_pk):
    """
    Validates institutional or assignment permissions before serving evidence files.
    """
    ev = get_object_or_404(ImprovementPlanEvidence.objects.select_related('plan__decision__application__institution'), pk=evidence_pk)
    decision = ev.plan.decision

    # Authorization Check
    authorized = False
    if request.user.is_superuser or request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.ADMIN]:
        authorized = True
    elif request.user.role == User.Roles.INSTITUTION_OFFICER:
        inst = _get_institution_for_decision(decision)
        if inst and request.user.institution_id == inst.id:
            authorized = True
    elif request.user.role == User.Roles.EXTERNAL_REVIEWER:
        # Check active assignment with COI
        assigned = SurveillanceVisit.objects.filter(decision=decision, auditors=request.user, coi_declared_by=request.user).exists()
        if assigned:
            authorized = True

    if not authorized:
        raise PermissionDenied("غير مصرح لك بتحميل هذا الملف.")

    if not ev.evidence_file:
        raise Http404("الملف غير متوفر على الخادم.")

    response = HttpResponse(ev.evidence_file.read(), content_type='application/octet-stream')
    response['Content-Disposition'] = f'inline; filename="{ev.evidence_file.name.split("/")[-1]}"'
    return response


@login_required
def download_annual_report_file(request, report_pk):
    """
    Validates institutional or assignment permissions before serving annual report files.
    """
    report = get_object_or_404(AnnualMonitoringReport.objects.select_related('decision__application__institution'), pk=report_pk)
    decision = report.decision

    authorized = False
    if request.user.is_superuser or request.user.role in [User.Roles.COUNCIL_SECRETARY, User.Roles.BOARD_MEMBER, User.Roles.ADMIN]:
        authorized = True
    elif request.user.role == User.Roles.INSTITUTION_OFFICER:
        inst = _get_institution_for_decision(decision)
        if inst and request.user.institution_id == inst.id:
            authorized = True
    elif request.user.role == User.Roles.EXTERNAL_REVIEWER:
        assigned = SurveillanceVisit.objects.filter(decision=decision, auditors=request.user, coi_declared_by=request.user).exists()
        if assigned:
            authorized = True

    if not authorized:
        raise PermissionDenied("غير مصرح لك بتحميل هذا الملف.")

    if not report.report_file:
        raise Http404("الملف غير متوفر على الخادم.")

    response = HttpResponse(report.report_file.read(), content_type='application/octet-stream')
    response['Content-Disposition'] = f'inline; filename="{report.report_file.name.split("/")[-1]}"'
    return response
