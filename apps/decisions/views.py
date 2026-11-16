import hashlib
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import HttpResponseForbidden, JsonResponse
from .models import (
    CouncilMeeting,
    CouncilMeetingAttendance,
    CouncilAgendaItem,
    CouncilMeetingAttachment,
    CouncilAgendaDiscussion,
    CouncilBallot,
    CouncilBallotVoterRecord,
    CouncilSecretVote,
    CouncilPublicVote,
    CouncilMeetingMinutes,
    CouncilMeetingMinutesVersion,
    CouncilResolution,
    CouncilPolicy,
    AccreditationDecision,
    AccreditationCertificate,
    CertificateRevocationRecord,
    SovereignTransaction,
    TransactionMovementHistory
)
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus, GrievanceAppeal
from apps.standards.models import StandardVersion
from apps.accounts.models import User, record_audit_log, send_notification, notify_institution, notify_role
from apps.accounts.sms_service import notify_accreditation_decision_sms
from apps.operations.deadline_engine import calculate_calendar_anniversary

@login_required
def council_meetings_list(request):
    meetings = CouncilMeeting.objects.prefetch_related(
        'decisions__application', 'attendances__member', 'ballots', 'agenda_items', 'resolutions'
    ).order_by('-meeting_date')
    can_create_meeting = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    return render(request, 'decisions/meetings_list.html', {
        'meetings': meetings,
        'can_create_meeting': can_create_meeting,
        'meeting_types': CouncilMeeting.MeetingType.choices,
    })

@login_required
def council_meeting_create(request):
    """
    Creates a new Board of Directors Council Meeting (Ordinary or Extraordinary).
    Authorized: Council Chairman, Council Vice Chairman, Secretary General, Meeting Secretary, or System Admin.
    """
    can_create = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_create:
        messages.error(request, "غير مصرح لك: إنشاء جلسات مجلس الإدارة مقتصر على رئاسة المجلس والأمانة العامة وسكرتارية الجلسات.")
        return redirect('decisions:meetings_list')

    if request.method == 'POST':
        meeting_number = request.POST.get('meeting_number', '').strip()
        meeting_type = request.POST.get('meeting_type', CouncilMeeting.MeetingType.ORDINARY)
        meeting_date = request.POST.get('meeting_date') or timezone.now().date()
        meeting_time = request.POST.get('meeting_time', '').strip() or None
        end_time = request.POST.get('end_time', '').strip() or None
        location = request.POST.get('location', '').strip() or 'المقر الرئيسي لمجلس الاعتماد الأكاديمي - صنعاء'
        meeting_link = request.POST.get('meeting_link', '').strip()
        chairperson_name = request.POST.get('chairperson_name', '').strip() or request.user.get_full_name()
        chairperson_user_id = request.POST.get('chairperson_user_id')
        secretary_name = request.POST.get('secretary_name', '').strip()
        secretary_user_id = request.POST.get('secretary_user_id')
        agenda = request.POST.get('meeting_agenda', '').strip()
        quorum_required = int(request.POST.get('quorum_required') or 4)
        use_dynamic_quorum = request.POST.get('use_dynamic_quorum') in ['1', 'true', 'on', 'True']
        initial_status = request.POST.get('status', CouncilMeeting.MeetingStatus.DRAFT)
        if initial_status not in [CouncilMeeting.MeetingStatus.DRAFT, CouncilMeeting.MeetingStatus.UNDER_PREPARATION]:
            initial_status = CouncilMeeting.MeetingStatus.DRAFT

        if not meeting_number:
            year = timezone.now().year
            count = CouncilMeeting.objects.count() + 1
            meeting_number = f"جلسة مجلس الإدارة رقم ({count:02d}) لسنة {year}"

        chair_user = User.objects.filter(pk=chairperson_user_id).first() if chairperson_user_id else (
            User.objects.filter(role=User.Roles.COUNCIL_CHAIRMAN, is_active=True).first()
        )
        sec_user = User.objects.filter(pk=secretary_user_id).first() if secretary_user_id else (
            User.objects.filter(role=User.Roles.COUNCIL_SECRETARY, is_active=True).first()
        )
        if not secretary_name and sec_user:
            secretary_name = sec_user.get_full_name()

        with transaction.atomic():
            meeting = CouncilMeeting.objects.create(
                meeting_number=meeting_number,
                meeting_type=meeting_type,
                meeting_date=meeting_date,
                meeting_time=meeting_time,
                end_time=end_time,
                location=location,
                meeting_link=meeting_link,
                chairperson_name=chairperson_name,
                chairperson_user=chair_user,
                secretary_name=secretary_name,
                secretary_user=sec_user,
                meeting_agenda=agenda,
                quorum_required=quorum_required,
                use_dynamic_quorum=use_dynamic_quorum,
                status=initial_status
            )

            uploaded_file = request.FILES.get('attachment')
            if uploaded_file:
                CouncilMeetingAttachment.objects.create(
                    meeting=meeting,
                    title=request.POST.get('attachment_title', 'مذكرة الدعوة وجدول الأعمال'),
                    document_type='INVITATION_PACKAGE',
                    file=uploaded_file,
                    uploaded_by=request.user
                )

            record_audit_log(
                user=request.user,
                action='COUNCIL_MEETING_CREATED',
                target_model='CouncilMeeting',
                target_id=meeting.pk,
                details=f"إنشاء جلسة مجلس إدارة جديدة رقم ({meeting.meeting_number}) بتاريخ ({meeting.meeting_date})",
                request=request
            )

        messages.success(request, f"تم بنجاح إنشاء مسودة ({meeting.meeting_number}). يمكنك الآن مراجعة جدول الأعمال وتوجيه الدعوات الرسمية للأعضاء.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    return redirect('decisions:meetings_list')

@login_required
def issue_decision_for_application(request, app_pk):
    application = get_object_or_404(AccreditationApplication, pk=app_pk)

    if not (request.user.is_board or request.user.is_staff):
        messages.error(request, "غير مصرح لك: حضور جلسات المجلس والتصويت وإصدار قرارات الاعتماد والشهادات مخصص حصراً لمجلس إدارة المجلس.")
        return redirect('accreditation:application_detail', pk=application.pk)

    meetings = CouncilMeeting.objects.order_by('-meeting_date')

    if request.method == 'POST':
        meeting_id = request.POST.get('meeting_id') or request.POST.get('meeting')
        decision_type = request.POST.get('decision_type')
        decree_number = request.POST.get('decree_number', '').strip()
        validity_years = int(request.POST.get('validity_years', 5))
        start_date = request.POST.get('start_date') or timezone.now().date()
        legal_justifications = request.POST.get('legal_justifications', '')
        corrective_requirements = request.POST.get('corrective_requirements', '') or request.POST.get('conditions', '')
        votes_in_favor = int(request.POST.get('votes_in_favor', 7))
        votes_against = int(request.POST.get('votes_against', 0))

        if meeting_id:
            meeting = get_object_or_404(CouncilMeeting, pk=meeting_id)
        else:
            meeting = CouncilMeeting.objects.create(
                meeting_number=f"الجلسة الدورية رقم ({CouncilMeeting.objects.count()+1}) لسنة {timezone.now().year}",
                meeting_date=timezone.now().date(),
                chairperson_name="أ.د. رئيس مجلس الاعتماد الأكاديمي",
                meeting_agenda=f"النظر في التقرير النهائي لطلب اعتماد: {application.application_number}",
                minutes_summary="ناقش المجلس التقرير النهائي لفريق المحكمين وصوت بالأغلبية على القرار التالي.",
            )

        # Validate meeting validity & quorum
        if meeting.status == CouncilMeeting.MeetingStatus.CANCELLED:
            messages.error(request, "لا يمكن إصدار قرار اعتماد من جلسة ملغاة رسمياً.")
            return redirect('decisions:issue_decision', app_pk=application.pk)

        if meeting.attendances.exists() and not meeting.is_quorum_met():
            messages.error(
                request,
                f"لا يمكن إصدار قرار اعتماد قبل اكتمال النصاب القانوني للجلسة ({meeting.confirmed_attendance_count()} من أصل {meeting.effective_quorum_required()})."
            )
            return redirect('decisions:issue_decision', app_pk=application.pk)

        # Ensure no open unclosed ballot exists for this application in this meeting
        if CouncilBallot.objects.filter(
            meeting=meeting,
            application=application,
            status=CouncilBallot.BallotStatus.OPEN
        ).exists():
            messages.error(request, "لا يمكن إصدار قرار اعتماد أثناء وجود اقتراع مفتوح لم يُغلق ويُعتمد فرزه بعد.")
            return redirect('decisions:issue_decision', app_pk=application.pk)

        # If a ballot was closed & tallied for this meeting & application, auto-adopt the official tally
        ballot = CouncilBallot.objects.filter(
            meeting=meeting,
            application=application,
            status=CouncilBallot.BallotStatus.CLOSED
        ).first()
        if ballot:
            votes_in_favor = ballot.votes_full_count + ballot.votes_conditional_count
            votes_against = ballot.votes_denied_count

        if not decree_number:
            decree_number = f"قرار مجلس الاعتماد رقم ({application.pk}) لسنة {timezone.now().year}"

        # Prevent duplicate decree_number crash (UNIQUE constraint failed)
        if AccreditationDecision.objects.filter(decree_number=decree_number).exclude(application=application).exists():
            decree_number = f"{decree_number} - ({application.pk})"
            counter = 1
            while AccreditationDecision.objects.filter(decree_number=decree_number).exclude(application=application).exists():
                decree_number = f"{decree_number}-{counter}"
                counter += 1

        # Calculate calendar-aware expiry date
        from datetime import datetime, date
        if isinstance(start_date, str):
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date_obj = start_date
        
        expiry_date_obj = calculate_calendar_anniversary(start_date_obj, validity_years)

        with transaction.atomic():
            decision, created = AccreditationDecision.objects.update_or_create(
                application=application,
                defaults={
                    'meeting': meeting,
                    'decision_type': decision_type,
                    'decree_number': decree_number or f"قرار وزاري رقم ({application.pk:03d}) لسنة {timezone.now().year}",
                    'decision_date': timezone.now().date(),
                    'validity_years': validity_years,
                    'start_date': start_date_obj,
                    'expiry_date': expiry_date_obj,
                    'legal_justifications': legal_justifications,
                    'corrective_requirements': corrective_requirements,
                    'votes_in_favor': votes_in_favor,
                    'votes_against': votes_against,
                }
            )

            # Update application state
            if decision_type == AccreditationDecision.DecisionType.FULL_ACCREDITATION:
                application.status = ApplicationStatus.FULL_ACCREDITATION
                application.current_stage = StageChoices.STAGE_7  # move to post-accreditation surveillance
            elif decision_type == AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION:
                application.status = ApplicationStatus.CONDITIONAL_ACCREDITATION
                application.current_stage = StageChoices.STAGE_7
            else:
                application.status = ApplicationStatus.DENIED
                application.current_stage = StageChoices.STAGE_6
            application.save()

            # Link to CouncilAgendaItem and CouncilResolution if present on this meeting
            agenda_item = meeting.agenda_items.filter(application=application).first()
            if agenda_item:
                agenda_item.status = CouncilAgendaItem.ItemStatus.DECIDED
                agenda_item.save(update_fields=['status'])
                if not CouncilResolution.objects.filter(meeting=meeting, agenda_item=agenda_item).exists():
                    res_num = f"RES-{meeting.meeting_number}-{agenda_item.position}"[:60]
                    while CouncilResolution.objects.filter(resolution_number=res_num).exists():
                        res_num = f"{res_num}-{application.pk}"[:60]
                    CouncilResolution.objects.create(
                        meeting=meeting,
                        agenda_item=agenda_item,
                        ballot=ballot,
                        accreditation_decision=decision,
                        resolution_number=res_num,
                        resolution_type=CouncilResolution.ResolutionType.FINAL_DECISION,
                        title=f"قرار اعتماد: {decision.decree_number}",
                        decision_text=legal_justifications or f"إصدار قرار ({decision.get_decision_type_display()}) للطلب ({application.application_number}).",
                        responsible_entity="الأمانة العامة - الإدارة العامة للاعتماد والتراخيص",
                        issued_by=request.user,
                    )

            # Centralized Sovereign Transaction Record
            ref_dec = f"DEC-{decision.decree_number}"[:60]
            while SovereignTransaction.objects.filter(reference_number=ref_dec).exists():
                ref_dec = f"DEC-{decision.pk}-{timezone.now().strftime('%H%M%S')}"[:60]
            SovereignTransaction.objects.create(
                reference_number=ref_dec,
                transaction_type=SovereignTransaction.TransactionType.ACCREDITATION_DECISION,
                sender=request.user,
                sending_authority="مجلس الاعتماد الأكاديمي - هيئة مجلس الإدارة",
                receiving_authority=f"جامعة ({application.institution.name}) ووزارة التعليم العالي",
                subject=f"قرار اعتماد أكاديمي: {decision.decree_number} ({decision.get_decision_type_display()})",
                description=f"القرار الصادر في الجلسة ({meeting.meeting_number}) لطلب ({application.application_number}) بموافقة ({votes_in_favor}) واعتراض ({votes_against})",
                status=SovereignTransaction.TransactionStatus.COMPLETED,
                meeting=meeting,
                application=application
            )

            # If full or conditional accreditation, issue official certificate
            if decision_type in [AccreditationDecision.DecisionType.FULL_ACCREDITATION, AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION]:
                cert_code = f"YEM-CAQA-{decision.decree_number[-4:] if len(decision.decree_number)>=4 else '2026'}-{application.pk:04d}"
                cert, cert_created = AccreditationCertificate.objects.get_or_create(
                    decision=decision,
                    defaults={
                        'national_registry_code': cert_code,
                        'issue_date': timezone.now().date(),
                        'printed_at': timezone.now(),
                    }
                )
                # Generate QR verification link
                verification_url = request.build_absolute_uri(f"/decisions/verify/{cert.certificate_uuid}/")
                cert.generate_qr_code(verification_url)
                cert.save()

                cert_url = f"/decisions/certificate/{cert.pk}/"

                # 1. Notify University President directly
                presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, institution=application.institution, is_active=True)
                if not presidents.exists():
                    presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
                for pres in presidents:
                    send_notification(
                        user=pres,
                        title="صدور قرار وشهادة الاعتماد الأكاديمي الرسمية",
                        message=f"يسر مجلس الاعتماد الأكاديمي إحاطتكم بصدور القرار الرسمي رقم ({decision.decree_number}) بمنح الاعتماد لجامعتكم ({application.institution.name}) - مسار ({application.get_track_display()}).",
                        url=cert_url
                    )

                # 2. Notify Institution Officers
                notify_institution(
                    institution=application.institution,
                    title="صدور شهادة الاعتماد الأكاديمي الرسمية",
                    message=f"تهانينا! أصدر مجلس الاعتماد الأكاديمي رسمياً شهادة الاعتماد للطلب ({application.application_number}) بموجب {decision.decree_number}.",
                    url=cert_url,
                    extra_recipients=application.applicant_user
                )

                # 3. Statutorily notify Minister, Secretary General, and Directorates
                notify_role(
                    [User.Roles.MINISTER, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.DG_ACCREDITATION, User.Roles.DG_QUALITY],
                    title="صدور قرار اعتماد أكاديمي رسمي",
                    message=f"أصدر المجلس رسمياً القرار رقم ({decision.decree_number}) بمنح الاعتماد للطلب ({application.application_number}) - مؤسسة ({application.institution.name}).",
                    url=cert_url
                )

                # Dispatch sovereign SMS alerts to university leaders and minister
                notify_accreditation_decision_sms(decision=decision, application=application)

                # Instantly synchronize newly issued certificate & decision into My Library (مكتبتي)
                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                messages.success(request, f"تم إصدار قرار الاعتماد بنجاح برقم ({decision.decree_number})، وتوليد شهادة الاعتماد الوطنية الرسمية وإشعار رئيس الجامعة والوزارة فوراً.")
                return redirect('decisions:certificate_detail', pk=cert.pk)
            else:
                # Instantly synchronize decision into My Library (مكتبتي)
                try:
                    from apps.accounts.library_service import sync_system_assets_to_library
                    sync_system_assets_to_library()
                except Exception:
                    pass

                app_url = f"/accreditation/{application.pk}/"

                # 1. Notify University President directly
                presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, institution=application.institution, is_active=True)
                if not presidents.exists():
                    presidents = User.objects.filter(role=User.Roles.UNIVERSITY_PRESIDENT, is_active=True)
                for pres in presidents:
                    send_notification(
                        user=pres,
                        title="قرار مجلس الاعتماد بشأن طلب الاعتماد",
                        message=f"نحيطكم علماً بصدور قرار المجلس رقم ({decision.decree_number}) بشأن طلبكم ({application.application_number}) بقرار: {decision.get_decision_type_display()}.",
                        url=app_url
                    )

                # 2. Notify institution officers
                notify_institution(
                    institution=application.institution,
                    title="قرار المجلس حيال طلب الاعتماد",
                    message=f"نحيطكم علماً بصدور قرار المجلس رقم ({decision.decree_number}) بشأن طلبكم ({application.application_number}).",
                    url=app_url,
                    extra_recipients=application.applicant_user
                )

                notify_role(
                    [User.Roles.MINISTER, User.Roles.COUNCIL_SECRETARY_GENERAL, User.Roles.DG_ACCREDITATION],
                    title="صدور قرار برفض/تأجيل طلب اعتماد",
                    message=f"أصدر المجلس القرار رقم ({decision.decree_number}) بشأن الطلب ({application.application_number}) - مؤسسة ({application.institution.name}).",
                    url=app_url
                )

                messages.warning(request, f"تم تسجيل قرار المجلس برقم ({decision.decree_number}) وإشعار رئيس الجامعة والمؤسسة بحيثيات القرار.")
                return redirect('accreditation:application_detail', pk=application.pk)

    existing_decision = getattr(application, 'council_decision', None)
    if existing_decision:
        default_decree_number = existing_decision.decree_number
    else:
        next_num = AccreditationDecision.objects.count() + 1
        default_decree_number = f"قرار مجلس الاعتماد الأكاديمي رقم ({next_num}) لسنة {timezone.now().year}"
        while AccreditationDecision.objects.filter(decree_number=default_decree_number).exists():
            next_num += 1
            default_decree_number = f"قرار مجلس الاعتماد الأكاديمي رقم ({next_num}) لسنة {timezone.now().year}"

    context = {
        'app': application,
        'meetings': meetings,
        'existing_decision': existing_decision,
        'default_decree_number': default_decree_number,
        'decision_types': AccreditationDecision.DecisionType.choices,
    }
    return render(request, 'decisions/issue_decision.html', context)

from apps.accounts.models import User

@login_required
def certificate_detail(request, pk):
    cert = get_object_or_404(
        AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program',
            'decision__meeting'
        ),
        pk=pk
    )

    # Tenant Isolation: Institution officer or president can only view their own certificate
    if request.user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT] and request.user.institution_id:
        if cert.decision.application.institution_id != request.user.institution_id:
            messages.error(request, "غير مصرح لك: هذه الوثيقة تتبع مؤسسة تعليمية أخرى.")
            return redirect('core_dashboard')

    chairman = User.objects.filter(role=User.Roles.COUNCIL_CHAIRMAN, is_active=True).first()
    sec_gen = User.objects.filter(role=User.Roles.COUNCIL_SECRETARY_GENERAL, is_active=True).first()

    verification_url = request.build_absolute_uri(f"/decisions/verify/{cert.certificate_uuid}/")
    return render(request, 'decisions/certificate_view.html', {
        'cert': cert,
        'verification_url': verification_url,
        'chairman_name': chairman.get_full_name() if (chairman and chairman.get_full_name()) else "أ.د. أحمد علي الحبوبي",
        'secretary_general_name': sec_gen.get_full_name() if (sec_gen and sec_gen.get_full_name()) else "أ.د. محمد عبدالرحمن",
    })

def verify_certificate_public(request, uuid):
    cert = get_object_or_404(
        AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program'
        ),
        certificate_uuid=uuid
    )
    # Automatic expiry check
    if cert.status == AccreditationCertificate.CertificateStatus.ACTIVE:
        if cert.decision.expiry_date and cert.decision.expiry_date < timezone.now().date():
            cert.status = AccreditationCertificate.CertificateStatus.EXPIRED
            cert.save(update_fields=['status'])

    chairman = User.objects.filter(role=User.Roles.COUNCIL_CHAIRMAN, is_active=True).first()
    sec_gen = User.objects.filter(role=User.Roles.COUNCIL_SECRETARY_GENERAL, is_active=True).first()

    from apps.accounts.models import record_audit_log
    record_audit_log(
        user=None,
        action='PUBLIC_VERIFICATION_LOOKUP',
        target_model='AccreditationCertificate',
        target_id=cert.pk,
        details=f"استعلام تحقق عام من الشهادة ({cert.national_registry_code}) عبر المعرف الرقمي",
        request=request
    )
    return render(request, 'decisions/verify_public.html', {
        'cert': cert,
        'chairman_name': chairman.get_full_name() if (chairman and chairman.get_full_name()) else "أ.د. أحمد علي الحبوبي",
        'secretary_general_name': sec_gen.get_full_name() if (sec_gen and sec_gen.get_full_name()) else "أ.د. محمد عبدالرحمن",
    })


@login_required
def certificate_status_manage(request, pk):
    """Allows Council / Board members to suspend, revoke, or reinstate a certificate."""
    cert = get_object_or_404(
        AccreditationCertificate.objects.select_related(
            'decision__application__institution',
            'decision__application__program'
        ),
        pk=pk
    )
    
    if not (request.user.is_board or request.user.is_council or request.user.is_staff):
        messages.error(request, "غير مصرح لك: سحب أو تعليق أو تعديل سريان الشهادات الرسمية مخصص لمجلس الإدارة فقط.")
        return redirect('decisions:certificate_detail', pk=cert.pk)

    if request.method == 'POST':
        action_type = request.POST.get('action_type')
        decree_reference = request.POST.get('decree_reference', '').strip()
        justification = request.POST.get('justification', '').strip()

        from .models import CertificateRevocationRecord
        if action_type == 'REVOKE':
            cert.status = AccreditationCertificate.CertificateStatus.REVOKED
            cert.is_revoked = True
            cert.revocation_date = timezone.now().date()
            cert.revocation_decree = decree_reference
            cert.revocation_reason = justification
            cert.revoked_by = request.user
            msg = f"تم سحب وإلغاء الشهادة رسمياً بموجب ({decree_reference})."
        elif action_type == 'SUSPEND':
            cert.status = AccreditationCertificate.CertificateStatus.SUSPENDED
            cert.is_revoked = True
            cert.revocation_date = timezone.now().date()
            cert.revocation_decree = decree_reference
            cert.revocation_reason = justification
            cert.revoked_by = request.user
            msg = f"تم تعليق سريان الشهادة مؤقتاً بموجب ({decree_reference})."
        elif action_type == 'REINSTATE':
            cert.status = AccreditationCertificate.CertificateStatus.ACTIVE
            cert.is_revoked = False
            cert.revocation_reason = ""
            msg = f"تم إلغاء التعليق وإعادة تفعيل سريان الشهادة في السجل الوطني بموجب ({decree_reference})."
        else:
            msg = "لم يطرأ تغيير."
        
        cert.save()

        CertificateRevocationRecord.objects.create(
            certificate=cert,
            action_type=action_type,
            decree_reference=decree_reference,
            justification=justification,
            executed_by=request.user
        )

        from apps.accounts.models import record_audit_log
        record_audit_log(
            user=request.user,
            action=f"CERTIFICATE_{action_type}",
            target_model='AccreditationCertificate',
            target_id=cert.pk,
            details=f"تعديل حالة الشهادة ({cert.national_registry_code}) إلى ({cert.status}). القرار: {decree_reference}",
            request=request
        )

        messages.success(request, msg)
        return redirect('decisions:certificate_detail', pk=cert.pk)

    history = cert.revocation_history.select_related('executed_by').all().order_by('-action_date')
    return render(request, 'decisions/certificate_status_manage.html', {'cert': cert, 'history': history})


# ------------------------------------------------------------------------------
# BOARD MEETINGS, QUORUM & SECRET BALLOT OPERATIONS
# ------------------------------------------------------------------------------

@login_required
def meeting_detail(request, pk):
    """
    Detailed view of a Council Board Meeting: agenda items, attendance, quorum status,
    scheduled applications, discussions, public & secret ballots, minutes, and resolutions.
    """
    meeting = get_object_or_404(
        CouncilMeeting.objects.prefetch_related(
            'attendances__member',
            'ballots__secret_votes',
            'ballots__public_votes__voter',
            'ballots__voter_records',
            'decisions__application__institution',
            'agenda_items__discussions__speaker',
            'agenda_items__ballots',
            'agenda_items__resolutions',
            'agenda_items__attachments',
            'resolutions__agenda_item',
            'attachments'
        ),
        pk=pk
    )

    attendances = meeting.attendances.select_related('member').all().order_by('member__first_name')
    user_attendance = attendances.filter(member=request.user).first()

    # Access Control: Board, Council, Staff, Minister, Prime Minister, or Invited Participant
    has_access = (
        request.user.is_board or
        request.user.is_council or
        request.user.is_staff or
        request.user.is_minister or
        request.user.is_prime_minister or
        (user_attendance is not None)
    )
    if not has_access:
        messages.error(request, "غير مصرح لك باستعراض وثائق جلسات مجلس الإدارة.")
        return redirect('core_dashboard')

    # Automatically mark invitation as read when an invited attendee opens the meeting page
    if user_attendance and not user_attendance.invitation_read:
        user_attendance.invitation_read = True
        user_attendance.invitation_read_at = timezone.now()
        user_attendance.save(update_fields=['invitation_read', 'invitation_read_at'])

    quorum_met = meeting.is_quorum_met()
    confirmed_count = meeting.confirmed_attendance_count()
    effective_quorum = meeting.effective_quorum_required()
    active_voting_members_count = meeting.active_voting_members_count()

    # Active ballots in this meeting
    ballots = meeting.ballots.select_related('agenda_item', 'application__institution').all().order_by('-opened_at')

    # Check for each ballot whether the current user has already cast a vote (Secret or Public)
    user_voted_ballot_ids = set()
    if request.user.is_authenticated:
        secret_voted = set(
            CouncilBallotVoterRecord.objects.filter(
                ballot__in=ballots,
                voter=request.user
            ).values_list('ballot_id', flat=True)
        )
        public_voted = set(
            CouncilPublicVote.objects.filter(
                ballot__in=ballots,
                voter=request.user
            ).values_list('ballot_id', flat=True)
        )
        user_voted_ballot_ids = secret_voted | public_voted

    # Applications eligible to be linked/deliberated in this meeting
    eligible_applications = AccreditationApplication.objects.filter(
        status__in=[
            ApplicationStatus.FINAL_REPORT_READY,
            ApplicationStatus.IN_COUNCIL_REVIEW,
            ApplicationStatus.RESPONSE_SUBMITTED
        ]
    ).select_related('institution', 'program')

    is_guest_or_expert = (
        user_attendance is not None and
        user_attendance.attendee_category in [
            CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT,
            CouncilMeetingAttendance.AttendeeCategory.GUEST
        ] and not (request.user.is_board or request.user.is_council or request.user.is_staff)
    )

    agenda_items = meeting.agenda_items.select_related(
        'application__institution', 'application__program', 'policy', 'grievance', 'standard_version', 'presenter_user'
    ).prefetch_related('discussions__speaker', 'ballots', 'resolutions', 'attachments', 'conflict_of_interest_members').all()

    if is_guest_or_expert:
        # Restrict guests/experts to agenda items they are explicitly authorized to view
        authorized_ids = request.user.expert_authorized_agenda_items.filter(meeting=meeting).values_list('id', flat=True)
        if authorized_ids.exists():
            agenda_items = agenda_items.filter(id__in=authorized_ids)
        meeting_attachments = meeting.attachments.filter(is_confidential=False)
    else:
        meeting_attachments = meeting.attachments.all()

    official_minutes = getattr(meeting, 'official_minutes', None)
    minutes_versions = official_minutes.versions.select_related('modified_by').all() if official_minutes else []
    resolutions = meeting.resolutions.select_related('agenda_item', 'ballot', 'responsible_user', 'issued_by').all()

    can_manage_meeting = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )

    # Voting right strictly limited to voting Board Members (excluding guests/experts and technical-only admins)
    is_voting_member = (
        request.user.role in [
            User.Roles.BOARD_MEMBER,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN
        ] and (
            user_attendance is None or
            user_attendance.attendee_category == CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER
        )
    )

    all_board_users = User.objects.filter(
        role__in=[User.Roles.COUNCIL_CHAIRMAN, User.Roles.COUNCIL_VICE_CHAIRMAN, User.Roles.BOARD_MEMBER],
        is_active=True
    )
    all_invitable_users = User.objects.filter(is_active=True).order_by('first_name', 'username')

    context = {
        'meeting': meeting,
        'attendances': attendances,
        'user_attendance': user_attendance,
        'quorum_met': quorum_met,
        'confirmed_count': confirmed_count,
        'attendees_confirmed_count': confirmed_count,
        'effective_quorum': effective_quorum,
        'active_voting_members_count': active_voting_members_count,
        'ballots': ballots,
        'user_voted_ballot_ids': user_voted_ballot_ids,
        'eligible_applications': eligible_applications,
        'agenda_items': agenda_items,
        'meeting_attachments': meeting_attachments,
        'official_minutes': official_minutes,
        'minutes_versions': minutes_versions,
        'resolutions': resolutions,
        'can_manage_meeting': can_manage_meeting,
        'is_voting_member': is_voting_member,
        'can_vote': is_voting_member,
        'is_guest_or_expert': is_guest_or_expert,
        'item_categories': CouncilAgendaItem.ItemCategory.choices,
        'required_actions': CouncilAgendaItem.RequiredAction.choices,
        'intervention_types': CouncilAgendaDiscussion.InterventionType.choices,
        'resolution_types': CouncilResolution.ResolutionType.choices,
        'implementation_statuses': CouncilResolution.ImplementationStatus.choices,
        'meeting_statuses': CouncilMeeting.MeetingStatus.choices,
        'attendee_categories': CouncilMeetingAttendance.AttendeeCategory.choices,
        'participation_modes': CouncilMeetingAttendance.ParticipationMode.choices,
        'rsvp_statuses': CouncilMeetingAttendance.RSVPStatus.choices,
        'all_board_users': all_board_users,
        'all_invitable_users': all_invitable_users,
        'policies_list': CouncilPolicy.objects.all(),
        'grievances_list': GrievanceAppeal.objects.select_related('application__institution').all(),
        'standards_list': StandardVersion.objects.all(),
    }
    return render(request, 'decisions/meeting_detail.html', context)


@login_required
def meeting_send_invitations(request, pk):
    """
    Distributes official invitations to all active and authorized Council Board Members,
    initiating attendance RSVP tracking, recording sender/timestamp, and logging the sovereign transaction.
    """
    can_dispatch = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_dispatch:
        messages.error(request, "غير مصرح لك بتوجيه دعوات جلسات مجلس الإدارة.")
        return redirect('decisions:meetings_list')

    meeting = get_object_or_404(CouncilMeeting, pk=pk)

    if meeting.status == CouncilMeeting.MeetingStatus.CANCELLED:
        messages.error(request, "لا يمكن إرسال دعوات لجلسة ملغاة رسمياً.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    # Target strictly active, eligible Board Members & Leadership
    board_members = User.objects.filter(
        role__in=[
            User.Roles.BOARD_MEMBER,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    if not board_members.exists():
        messages.warning(request, "لا يوجد أعضاء مجلس إدارة نشطون مسجلون في النظام.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    now_ts = timezone.now()
    with transaction.atomic():
        invited_count = 0
        for member in board_members:
            att, created = CouncilMeetingAttendance.objects.get_or_create(
                meeting=meeting,
                member=member,
                defaults={
                    'status': CouncilMeetingAttendance.RSVPStatus.INVITED,
                    'attendee_category': CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
                    'created_by': request.user,
                    'sent_by': request.user,
                    'invitation_sent_at': now_ts,
                }
            )
            if not created and not att.invitation_sent_at:
                att.sent_by = request.user
                att.invitation_sent_at = now_ts
                att.save(update_fields=['sent_by', 'invitation_sent_at'])

            # Add to meeting attendees M2M
            meeting.attendees.add(member)

            # In-App Notification
            send_notification(
                user=member,
                title=f"دعوة رسمية لحضور جلسة مجلس الإدارة ({meeting.meeting_number})",
                message=(
                    f"يدعوكم رئيس مجلس الاعتماد لحضور الجلسة {meeting.get_meeting_type_display()} "
                    f"المنعقدة بتاريخ ({meeting.meeting_date}) الساعة ({meeting.meeting_time or 'المحددة'}) "
                    f"بمقر ({meeting.location}). يرجى تأكيد حضوركم والاطلاع على جدول الأعمال."
                ),
                url=f"/decisions/meetings/{meeting.pk}/"
            )
            invited_count += 1

        if meeting.status in [CouncilMeeting.MeetingStatus.DRAFT, CouncilMeeting.MeetingStatus.UNDER_PREPARATION]:
            meeting.status = CouncilMeeting.MeetingStatus.INVITATIONS_SENT
            meeting.save(update_fields=['status'])

        # Log Centralized Sovereign Transaction
        trx_ref = f"INV-{meeting.meeting_number.replace(' ', '-').replace('/', '-')}-{meeting.pk}"
        SovereignTransaction.objects.update_or_create(
            reference_number=trx_ref,
            defaults={
                'transaction_type': SovereignTransaction.TransactionType.MEETING_INVITATION,
                'sender': request.user,
                'sending_authority': "مجلس الاعتماد الأكاديمي - رئاسة المجلس وسكرتارية الجلسات",
                'receiving_authority': "السادة أعضاء مجلس إدارة مجلس الاعتماد الأكاديمي",
                'subject': f"دعوة حضور {meeting.meeting_number}",
                'description': f"جدول الأعمال: {meeting.meeting_agenda}",
                'status': SovereignTransaction.TransactionStatus.SUBMITTED,
                'meeting': meeting
            }
        )

        record_audit_log(
            user=request.user,
            action='COUNCIL_MEETING_INVITATIONS_DISPATCHED',
            target_model='CouncilMeeting',
            target_id=meeting.pk,
            details=f"توجيه الدعوات الرسمية لجلسة المجلس ({meeting.meeting_number}) لعدد ({invited_count}) من أعضاء المجلس",
            request=request
        )

    messages.success(request, f"تم بنجاح توجيه الدعوات الرسمية لجلسة المجلس ({meeting.meeting_number}) وإشعار ({invited_count}) عضواً بمجلس الإدارة.")
    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_rsvp(request, pk):
    """
    Allows an invited Board Member or Expert to respond to a meeting invitation (Confirm attendance or Apologize).
    """
    meeting = get_object_or_404(CouncilMeeting, pk=pk)

    attendance = CouncilMeetingAttendance.objects.filter(meeting=meeting, member=request.user).first()
    if not attendance and not request.user.is_superuser:
        messages.error(request, "لم يتم العثور على دعوة موجهة لحسابك في هذه الجلسة.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    if request.method == 'POST':
        response_status = request.POST.get('status') or request.POST.get('response')  # 'CONFIRMED' or 'APOLOGIZED'
        participation_mode = request.POST.get('participation_mode', CouncilMeetingAttendance.ParticipationMode.IN_PERSON)
        remarks = request.POST.get('remarks', '').strip()

        if response_status not in [CouncilMeetingAttendance.RSVPStatus.CONFIRMED, CouncilMeetingAttendance.RSVPStatus.APOLOGIZED]:
            messages.error(request, "يرجى تحديد موقف الحضور بدقة (تأكيد الحضور أو الاعتذار).")
            return redirect('decisions:meeting_detail', pk=meeting.pk)

        now_ts = timezone.now()
        is_present = (response_status == CouncilMeetingAttendance.RSVPStatus.CONFIRMED)
        if not attendance:
            attendance = CouncilMeetingAttendance.objects.create(
                meeting=meeting,
                member=request.user,
                status=response_status,
                participation_mode=participation_mode,
                invitation_read=True,
                invitation_read_at=now_ts,
                confirmed_at=now_ts,
                is_currently_present=is_present,
                remarks=remarks
            )
        else:
            attendance.status = response_status
            if participation_mode in [c[0] for c in CouncilMeetingAttendance.ParticipationMode.choices]:
                attendance.participation_mode = participation_mode
            if not attendance.invitation_read:
                attendance.invitation_read = True
                attendance.invitation_read_at = now_ts
            attendance.confirmed_at = now_ts
            attendance.is_currently_present = is_present
            attendance.remarks = remarks
            attendance.save()

        record_audit_log(
            user=request.user,
            action='COUNCIL_MEETING_RSVP',
            target_model='CouncilMeetingAttendance',
            target_id=attendance.pk,
            details=f"تسجيل موقف ({attendance.get_status_display()}) لعضو المجلس ({request.user.get_full_name()}) لجلسة ({meeting.meeting_number})",
            request=request
        )

        # Notify Council Chairman, Secretary General & Meeting Secretary of RSVP & Quorum Status
        quorum_badge = "النصاب القانوني مكتمل ومتحقق" if meeting.is_quorum_met() else "النصاب غير مكتمل بعد"
        for lead in User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
            ],
            is_active=True
        ):
            send_notification(
                user=lead,
                title=f"تحديث موقف الحضور والنصاب ({meeting.meeting_number}): {quorum_badge}",
                message=(
                    f"سجل عضو المجلس ({request.user.get_full_name() or request.user.username}) موقفه "
                    f"({attendance.get_status_display()}) لجلسة ({meeting.meeting_number}). "
                    f"الحضور المؤكد: ({meeting.confirmed_attendance_count()}/{meeting.effective_quorum_required()}) — [{quorum_badge}]."
                ),
                url=f"/decisions/meetings/{meeting.pk}/"
            )

        messages.success(request, f"تم بنجاح تسجيل موقفك ({attendance.get_status_display()}) لجلسة المجلس ({meeting.meeting_number}).")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_status_transition(request, pk):
    """
    Transitions a Council Meeting through its controlled lifecycle statuses,
    enforcing quorum checks before IN_SESSION and notifying members upon cancellation/suspension.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بتغيير حالة جلسة مجلس الإدارة.")
        return redirect('decisions:meeting_detail', pk=pk)

    meeting = get_object_or_404(CouncilMeeting, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('new_status', '').strip()
        reason = request.POST.get('reason', '').strip()

        if new_status == CouncilMeeting.MeetingStatus.IN_SESSION and not meeting.is_quorum_met():
            messages.error(
                request,
                f"تعذر افتتاح الجلسة رسمياً: النصاب القانوني غير مكتمل ({meeting.confirmed_attendance_count()} حاضرون من أصل {meeting.effective_quorum_required()} مطلوب وفق المادة 6)."
            )
            return redirect('decisions:meeting_detail', pk=meeting.pk)

        try:
            with transaction.atomic():
                old_status = meeting.status
                meeting.transition_status(new_status, reason=reason)

                if new_status == CouncilMeeting.MeetingStatus.CANCELLED:
                    # Cancel any open ballots
                    meeting.ballots.filter(status=CouncilBallot.BallotStatus.OPEN).update(
                        status=CouncilBallot.BallotStatus.CANCELLED,
                        closed_at=timezone.now()
                    )

                # Notify invited members of cancellation, suspension, or session start
                if new_status in [
                    CouncilMeeting.MeetingStatus.CANCELLED,
                    CouncilMeeting.MeetingStatus.TEMPORARILY_SUSPENDED,
                    CouncilMeeting.MeetingStatus.IN_SESSION
                ]:
                    for att in meeting.attendances.select_related('member').all():
                        send_notification(
                            user=att.member,
                            title=f"تحديث حالة جلسة المجلس ({meeting.meeting_number}): {meeting.get_status_display()}",
                            message=f"تم تحديث حالة الجلسة إلى ({meeting.get_status_display()}). {reason}",
                            url=f"/decisions/meetings/{meeting.pk}/"
                        )

                record_audit_log(
                    user=request.user,
                    action='COUNCIL_MEETING_STATUS_CHANGED',
                    target_model='CouncilMeeting',
                    target_id=meeting.pk,
                    details=f"تغيير حالة الجلسة ({meeting.meeting_number}) من ({old_status}) إلى ({new_status}). السبب: {reason}",
                    request=request
                )
            messages.success(request, f"تم تحديث حالة الجلسة بنجاح إلى ({meeting.get_status_display()}).")
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, 'message') else exc))

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_update_schedule(request, pk):
    """
    Updates meeting schedule, times, location, link, or quorum configuration and notifies members.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بتعديل جدول وموعد الجلسة.")
        return redirect('decisions:meeting_detail', pk=pk)

    meeting = get_object_or_404(CouncilMeeting, pk=pk)
    if request.method == 'POST':
        meeting.meeting_date = request.POST.get('meeting_date') or meeting.meeting_date
        if 'meeting_time' in request.POST:
            meeting.meeting_time = request.POST.get('meeting_time') or None
        if 'end_time' in request.POST:
            meeting.end_time = request.POST.get('end_time') or None
        if 'location' in request.POST:
            meeting.location = request.POST.get('location', '').strip() or meeting.location
        if 'meeting_link' in request.POST:
            meeting.meeting_link = request.POST.get('meeting_link', '').strip()
        if 'chairperson_name' in request.POST:
            meeting.chairperson_name = request.POST.get('chairperson_name', '').strip() or meeting.chairperson_name
        if 'secretary_name' in request.POST:
            meeting.secretary_name = request.POST.get('secretary_name', '').strip()
        if 'quorum_required' in request.POST and request.POST.get('quorum_required'):
            meeting.quorum_required = int(request.POST.get('quorum_required'))
        if 'use_dynamic_quorum' in request.POST:
            meeting.use_dynamic_quorum = request.POST.get('use_dynamic_quorum') in ['1', 'true', 'on', 'True']
        if 'meeting_agenda' in request.POST:
            meeting.meeting_agenda = request.POST.get('meeting_agenda', '').strip() or meeting.meeting_agenda
        meeting.save()

        # Notify invited members of schedule modification
        for att in meeting.attendances.select_related('member').all():
            send_notification(
                user=att.member,
                title=f"تعديل موعد/بيانات جلسة المجلس ({meeting.meeting_number})",
                message=f"تم تحديث بيانات انعقاد الجلسة ({meeting.meeting_number}) بتاريخ ({meeting.meeting_date}) في ({meeting.location}).",
                url=f"/decisions/meetings/{meeting.pk}/"
            )

        record_audit_log(
            user=request.user,
            action='COUNCIL_MEETING_SCHEDULE_UPDATED',
            target_model='CouncilMeeting',
            target_id=meeting.pk,
            details=f"تحديث بيانات وموعد الجلسة ({meeting.meeting_number})",
            request=request
        )
        messages.success(request, "تم تحديث بيانات وموعد الجلسة وإشعار الأعضاء بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_add_participant(request, pk):
    """
    Adds a Voting Member, Invited Expert (Article 6 - non-voting), or Guest to the meeting,
    dispatches an invitation notification, and optionally grants access to specific agenda items.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بإضافة مشاركين أو خبراء للجلسة.")
        return redirect('decisions:meeting_detail', pk=pk)

    meeting = get_object_or_404(CouncilMeeting, pk=pk)
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        attendee_category = request.POST.get(
            'attendee_category',
            CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT
        )
        participation_mode = request.POST.get(
            'participation_mode',
            CouncilMeetingAttendance.ParticipationMode.IN_PERSON
        )
        initial_status = request.POST.get('status', CouncilMeetingAttendance.RSVPStatus.INVITED)
        agenda_item_id = request.POST.get('agenda_item_id')
        remarks = request.POST.get('remarks', '').strip()

        participant = get_object_or_404(User, pk=user_id)

        # Enforce Article 6: non-board users cannot be added as VOTING_MEMBER
        if participant.role not in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.BOARD_MEMBER
        ] and attendee_category == CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER:
            attendee_category = CouncilMeetingAttendance.AttendeeCategory.INVITED_EXPERT

        now_ts = timezone.now()
        with transaction.atomic():
            att, created = CouncilMeetingAttendance.objects.update_or_create(
                meeting=meeting,
                member=participant,
                defaults={
                    'attendee_category': attendee_category,
                    'participation_mode': participation_mode,
                    'status': initial_status,
                    'created_by': request.user,
                    'sent_by': request.user,
                    'invitation_sent_at': now_ts,
                    'is_currently_present': initial_status in ['CONFIRMED', 'ATTENDED'],
                    'remarks': remarks,
                }
            )
            if agenda_item_id:
                item = CouncilAgendaItem.objects.filter(pk=agenda_item_id, meeting=meeting).first()
                if item:
                    item.authorized_experts.add(participant)

            send_notification(
                user=participant,
                title=f"دعوة للمشاركة في جلسة المجلس ({meeting.meeting_number}) بصفتكم ({att.get_attendee_category_display()})",
                message=f"تمت دعوتكم للمشاركة في ({meeting.meeting_number}) بتاريخ ({meeting.meeting_date}).",
                url=f"/decisions/meetings/{meeting.pk}/"
            )

            record_audit_log(
                user=request.user,
                action='COUNCIL_MEETING_PARTICIPANT_ADDED',
                target_model='CouncilMeetingAttendance',
                target_id=att.pk,
                details=f"إضافة المشارك ({participant.get_full_name()}) بصفة ({att.get_attendee_category_display()}) للجلسة ({meeting.meeting_number})",
                request=request
            )
        messages.success(request, f"تمت إضافة ({participant.get_full_name()}) بصفة ({att.get_attendee_category_display()}) وإرسال الدعوة.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_record_attendance(request, pk):
    """
    Records or updates official attendance, arrival/departure times, online/in-person mode,
    and member withdrawal during a session, dynamically rechecking quorum per Article 6.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بتسجيل وتعديل محضر الحضور والغياب.")
        return redirect('decisions:meeting_detail', pk=pk)

    meeting = get_object_or_404(CouncilMeeting, pk=pk)
    if request.method == 'POST':
        attendance_id = request.POST.get('attendance_id')
        member_id = request.POST.get('member_id')
        att = None
        if attendance_id:
            att = get_object_or_404(CouncilMeetingAttendance, pk=attendance_id, meeting=meeting)
        elif member_id:
            att = get_object_or_404(CouncilMeetingAttendance, member_id=member_id, meeting=meeting)

        if att:
            new_status = request.POST.get('status', att.status)
            participation_mode = request.POST.get('participation_mode', att.participation_mode)
            arrival_time = request.POST.get('arrival_time') or att.arrival_time
            departure_time = request.POST.get('departure_time') or att.departure_time
            is_present_param = request.POST.get('is_currently_present')
            remarks = request.POST.get('remarks', att.remarks)

            att.status = new_status
            att.participation_mode = participation_mode
            att.arrival_time = arrival_time
            att.departure_time = departure_time
            if is_present_param is not None:
                att.is_currently_present = is_present_param in ['1', 'true', 'on', 'True']
            else:
                att.is_currently_present = new_status in [
                    CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
                    CouncilMeetingAttendance.RSVPStatus.ATTENDED
                ] and not bool(departure_time)
            att.remarks = remarks
            att.save()

            quorum_now = meeting.is_quorum_met()
            record_audit_log(
                user=request.user,
                action='COUNCIL_ATTENDANCE_RECORDED',
                target_model='CouncilMeetingAttendance',
                target_id=att.pk,
                details=(
                    f"تحديث سجل حضور ({att.member.get_full_name()}) إلى ({att.get_status_display()}) "
                    f"- متواجد حالياً: ({att.is_currently_present}) - النصاب متحقق: ({quorum_now})"
                ),
                request=request
            )

            if not quorum_now and meeting.status == CouncilMeeting.MeetingStatus.IN_SESSION:
                record_audit_log(
                    user=request.user,
                    action='COUNCIL_QUORUM_LOST_WARNING',
                    target_model='CouncilMeeting',
                    target_id=meeting.pk,
                    details=f"اختلال النصاب القانوني أثناء انعقاد الجلسة ({meeting.meeting_number}): الحاضرون حالياً ({meeting.confirmed_attendance_count()}) من أصل ({meeting.effective_quorum_required()})",
                    request=request
                )
                messages.warning(
                    request,
                    f"تنبيه قانوني عاجل (المادة 6): اختل النصاب القانوني للجلسة بعد تحديث الحضور/الانسحاب ({meeting.confirmed_attendance_count()} حاضرون من أصل {meeting.effective_quorum_required()} مطلوب). يتوقف التصويت حتى اكتمال النصاب."
                )
            else:
                messages.success(request, f"تم تحديث سجل حضور ({att.member.get_full_name()}) بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_upload_attachment(request, pk):
    """Uploads an official supporting document to the meeting or a specific agenda item."""
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك برفع مرفقات الجلسة.")
        return redirect('decisions:meeting_detail', pk=pk)

    meeting = get_object_or_404(CouncilMeeting, pk=pk)
    if request.method == 'POST' and request.FILES.get('file'):
        title = request.POST.get('title', 'وثيقة داعمة للجلسة').strip()
        document_type = request.POST.get('document_type', 'SUPPORTING_DOCUMENT').strip()
        agenda_item_id = request.POST.get('agenda_item_id')
        is_confidential = request.POST.get('is_confidential') in ['1', 'true', 'on', 'True']
        agenda_item = CouncilAgendaItem.objects.filter(pk=agenda_item_id, meeting=meeting).first() if agenda_item_id else None

        att = CouncilMeetingAttachment.objects.create(
            meeting=meeting,
            agenda_item=agenda_item,
            title=title,
            document_type=document_type,
            file=request.FILES['file'],
            is_confidential=is_confidential,
            uploaded_by=request.user
        )
        record_audit_log(
            user=request.user,
            action='COUNCIL_ATTACHMENT_UPLOADED',
            target_model='CouncilMeetingAttachment',
            target_id=att.pk,
            details=f"رفع وثيقة ({title}) للجلسة ({meeting.meeting_number}) - سري: ({is_confidential})",
            request=request
        )
        messages.success(request, f"تم إرفاق الوثيقة ({title}) بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def agenda_item_create(request, meeting_pk):
    """
    Creates an independent CouncilAgendaItem supporting all 12 statutory categories,
    contextual links (application, policy, grievance, standards), conflict-of-interest declarations,
    and required Council actions.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بإدراج بنود في جدول أعمال المجلس.")
        return redirect('decisions:meeting_detail', pk=meeting_pk)

    meeting = get_object_or_404(CouncilMeeting, pk=meeting_pk)
    if request.method == 'POST':
        position = int(request.POST.get('position') or (meeting.agenda_items.count() + 1))
        item_number = request.POST.get('item_number', '').strip() or f"بند ({position})"
        title = request.POST.get('title', '').strip()
        item_category = request.POST.get(
            'item_category',
            CouncilAgendaItem.ItemCategory.INSTITUTIONAL_ACCREDITATION
        )
        referring_entity = request.POST.get('referring_entity', 'الأمانة العامة للمجلس').strip()
        presenter_name = request.POST.get('presenter_name', '').strip() or request.user.get_full_name()
        description = request.POST.get('description', '').strip() or title
        justification = request.POST.get('justification', '').strip()
        initial_recommendation = request.POST.get('initial_recommendation', '').strip()
        required_action = request.POST.get(
            'required_action',
            CouncilAgendaItem.RequiredAction.APPROVAL
        )

        app_id = request.POST.get('application_id')
        policy_id = request.POST.get('policy_id')
        grievance_id = request.POST.get('grievance_id')
        standard_id = request.POST.get('standard_version_id')

        application = AccreditationApplication.objects.filter(pk=app_id).first() if app_id else None
        policy = CouncilPolicy.objects.filter(pk=policy_id).first() if policy_id else None
        grievance = GrievanceAppeal.objects.filter(pk=grievance_id).first() if grievance_id else None
        standard_version = StandardVersion.objects.filter(pk=standard_id).first() if standard_id else None

        if not title and application:
            title = f"النظر في ملف اعتماد: {application.institution.name} ({application.application_number})"

        with transaction.atomic():
            item = CouncilAgendaItem.objects.create(
                meeting=meeting,
                item_number=item_number,
                position=position,
                title=title,
                item_category=item_category,
                referring_entity=referring_entity,
                presenter_name=presenter_name,
                presenter_user=request.user,
                description=description,
                justification=justification,
                initial_recommendation=initial_recommendation,
                required_action=required_action,
                application=application,
                policy=policy,
                grievance=grievance,
                standard_version=standard_version,
                attachment=request.FILES.get('attachment')
            )

            coi_member_ids = request.POST.getlist('conflict_of_interest_members')
            if coi_member_ids:
                item.conflict_of_interest_members.set(User.objects.filter(id__in=coi_member_ids))

            # Notify invited members of the new agenda item
            for att in meeting.attendances.select_related('member').all():
                if att.attendee_category == CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER:
                    send_notification(
                        user=att.member,
                        title=f"إدراج بند جديد في جدول أعمال ({meeting.meeting_number})",
                        message=f"تم إدراج ({item.item_number}: {item.title}) ضمن جدول أعمال الجلسة.",
                        url=f"/decisions/agenda-items/{item.pk}/"
                    )

            record_audit_log(
                user=request.user,
                action='COUNCIL_AGENDA_ITEM_CREATED',
                target_model='CouncilAgendaItem',
                target_id=item.pk,
                details=f"إدراج البند ({item.item_number}: {item.title}) من الفئة ({item.get_item_category_display()}) في الجلسة ({meeting.meeting_number})",
                request=request
            )

        messages.success(request, f"تم إدراج ({item.item_number}: {item.title}) في جدول أعمال الجلسة بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def agenda_item_detail(request, item_pk):
    """
    Renders the Complete 17-Part Agenda Item File Dossier for Council members before and during the meeting.
    Enforces strict access control and confidential document protection.
    """
    item = get_object_or_404(
        CouncilAgendaItem.objects.select_related(
            'meeting',
            'application__institution',
            'application__program',
            'application__standard_version',
            'policy',
            'grievance__application__institution',
            'standard_version',
            'presenter_user'
        ).prefetch_related(
            'discussions__speaker',
            'ballots__public_votes__voter',
            'ballots__secret_votes',
            'resolutions',
            'attachments',
            'conflict_of_interest_members',
            'authorized_experts'
        ),
        pk=item_pk
    )
    meeting = item.meeting
    user_attendance = meeting.attendances.filter(member=request.user).first()

    is_council_or_board = (
        request.user.is_board or
        request.user.is_council or
        request.user.is_staff or
        request.user.is_minister or
        request.user.is_prime_minister
    )
    is_authorized_expert = (
        user_attendance is not None and
        item.authorized_experts.filter(pk=request.user.pk).exists()
    )

    if not (is_council_or_board or is_authorized_expert):
        messages.error(request, "غير مصرح لك بالاطلاع على الملف الكامل لهذا البند في جدول أعمال المجلس.")
        return redirect('core_dashboard')

    is_guest_or_expert = not is_council_or_board
    if is_guest_or_expert:
        attachments = item.attachments.filter(is_confidential=False)
        meeting_attachments = meeting.attachments.filter(is_confidential=False)
    else:
        attachments = item.attachments.all()
        meeting_attachments = meeting.attachments.all()

    # Build the 17-Part Dossier for Accreditation Items
    app = item.application
    dossier = {}
    if app:
        self_study = getattr(app, 'self_study_report', None)
        external_report = getattr(app, 'external_report', None)
        review_team = getattr(app, 'review_team', None)
        site_visit = getattr(app, 'site_visit', None)
        std_version = app.standard_version or item.standard_version

        dossier = {
            # 1. Institution information
            'part_1_institution': app.institution,
            # 2. Academic program information
            'part_2_program': app.program,
            # 3. Accreditation application
            'part_3_application': app,
            # 4. Self-evaluation report (SSR)
            'part_4_self_study_report': self_study,
            # 5. Standards and indicators
            'part_5_standards': std_version,
            'part_5_categories': std_version.categories.prefetch_related('indicators').all() if std_version else [],
            # 6. Evidence documents
            'part_6_evidences': app.evidences.select_related('indicator').all(),
            # 7. Self-evaluation results
            'part_7_self_eval_results': self_study.indicator_responses.select_related('indicator').all() if self_study else [],
            # 8. Initial / Desk review report
            'part_8_desk_reviews': app.desk_reviews.select_related('reviewer').prefetch_related('checklist_items').all(),
            # 9. Site visit report
            'part_9_site_visit': site_visit,
            'part_9_facilities': site_visit.facility_inspections.all() if site_visit else [],
            'part_9_interviews': site_visit.interviews.all() if site_visit else [],
            # 10. External evaluation results (indicator scores)
            'part_10_external_scores': app.indicator_scores.select_related('indicator', 'evaluator').all(),
            # 11. External review team report (panel & draft findings)
            'part_11_review_team': review_team,
            'part_11_team_members': review_team.members.select_related('user').all() if review_team else [],
            'part_11_draft_report': external_report,
            # 12. Institution response to initial findings (Right to Reply)
            'part_12_institution_reply': {
                'text': external_report.institution_reply_text if external_report else '',
                'file': external_report.institution_reply_file if external_report else None,
                'date': external_report.institution_reply_date if external_report else None,
            },
            # 13. Final external evaluation report
            'part_13_final_external_report': external_report,
            # 14. Comparison report between self-evaluation and external evaluation
            'part_14_comparison_reports': app.comparison_reports.select_related('generated_by').all(),
            # 15. Accreditation Committee recommendation
            'part_15_committee_recommendation': {
                'panel_recommendation': external_report.get_final_recommendation_display() if external_report else '',
                'agenda_initial_recommendation': item.initial_recommendation,
            },
            # 16. Previous observations or conditional requirements
            'part_16_previous_decisions': AccreditationDecision.objects.filter(
                application__institution=app.institution
            ).exclude(application=app).select_related('meeting', 'application'),
            'part_16_status_history': app.status_history.select_related('changed_by').all(),
            # 17. Supporting documents
            'part_17_attachments': attachments,
        }

    can_manage_meeting = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    is_voting_member = (
        request.user.role in [
            User.Roles.BOARD_MEMBER,
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN
        ] and (
            user_attendance is None or
            user_attendance.attendee_category == CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER
        )
    )
    is_conflicted = item.conflict_of_interest_members.filter(pk=request.user.pk).exists() or (
        app is not None and request.user.institution_id and request.user.institution_id == app.institution_id
    )

    context = {
        'item': item,
        'meeting': meeting,
        'app': app,
        'dossier': dossier,
        'attachments': attachments,
        'meeting_attachments': meeting_attachments,
        'discussions': item.discussions.select_related('speaker', 'recorded_by').all(),
        'ballots': item.ballots.prefetch_related('public_votes__voter', 'secret_votes').all(),
        'resolutions': item.resolutions.select_related('responsible_user', 'issued_by').all(),
        'can_manage_meeting': can_manage_meeting,
        'is_voting_member': is_voting_member,
        'is_conflicted': is_conflicted,
        'is_guest_or_expert': is_guest_or_expert,
        'intervention_types': CouncilAgendaDiscussion.InterventionType.choices,
        'resolution_types': CouncilResolution.ResolutionType.choices,
    }
    return render(request, 'decisions/agenda_item_dossier.html', context)


@login_required
def agenda_item_add_discussion(request, item_pk):
    """
    Records member discussions, questions, observations, responses, formal reservations,
    recommendations, and procedural motions (postpone, refer, request info) on an agenda item.
    """
    item = get_object_or_404(CouncilAgendaItem.objects.select_related('meeting'), pk=item_pk)
    meeting = item.meeting

    user_attendance = meeting.attendances.filter(member=request.user).first()
    if not (request.user.is_board or request.user.is_council or request.user.is_staff or user_attendance):
        messages.error(request, "غير مصرح لك بتسجيل مداخلات في هذه الجلسة.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    if request.method == 'POST':
        intervention_type = request.POST.get(
            'intervention_type',
            CouncilAgendaDiscussion.InterventionType.INTERVENTION
        )
        content = request.POST.get('content', '').strip()
        speaker_id = request.POST.get('speaker_id')
        speaker_name = request.POST.get('speaker_name', '').strip()
        apply_motion = request.POST.get('apply_motion') in ['1', 'true', 'on', 'True']

        if not content:
            messages.error(request, "يرجى كتابة نص المداخلة أو الملاحظة أو التحفظ.")
            return redirect('decisions:agenda_item_detail', item_pk=item.pk)

        speaker = User.objects.filter(pk=speaker_id).first() if speaker_id else request.user
        if not speaker_name and speaker:
            speaker_name = speaker.get_full_name() or speaker.username

        with transaction.atomic():
            disc = CouncilAgendaDiscussion.objects.create(
                agenda_item=item,
                speaker=speaker,
                speaker_name=speaker_name,
                intervention_type=intervention_type,
                content=content,
                recorded_by=request.user
            )

            if intervention_type == CouncilAgendaDiscussion.InterventionType.PRESENTATION:
                item.presentation_summary = content
                if item.status == CouncilAgendaItem.ItemStatus.SCHEDULED:
                    item.status = CouncilAgendaItem.ItemStatus.UNDER_DISCUSSION
                item.save()
            elif item.status == CouncilAgendaItem.ItemStatus.SCHEDULED:
                item.status = CouncilAgendaItem.ItemStatus.UNDER_DISCUSSION
                item.save(update_fields=['status'])

            if apply_motion and intervention_type == CouncilAgendaDiscussion.InterventionType.MOTION_POSTPONE:
                item.status = CouncilAgendaItem.ItemStatus.POSTPONED
                item.save(update_fields=['status'])
            elif apply_motion and intervention_type == CouncilAgendaDiscussion.InterventionType.MOTION_REFER:
                item.status = CouncilAgendaItem.ItemStatus.REFERRED
                item.save(update_fields=['status'])

            record_audit_log(
                user=request.user,
                action='COUNCIL_AGENDA_DISCUSSION_RECORDED',
                target_model='CouncilAgendaDiscussion',
                target_id=disc.pk,
                details=f"توثيق ({disc.get_intervention_type_display()}) للمتحدث ({speaker_name}) على ({item.item_number}) في الجلسة ({meeting.meeting_number})",
                request=request
            )

            # Notify Chairman, Secretary General & Meeting Secretary when an intervention or reservation is recorded
            for lead in User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                ],
                is_active=True
            ):
                send_notification(
                    user=lead,
                    title=f"توثيق ({disc.get_intervention_type_display()}) على ({item.item_number}) - {meeting.meeting_number}",
                    message=f"تم توثيق ({disc.get_intervention_type_display()}) للعضو ({speaker_name}) على البند ({item.title}): {content[:120]}",
                    url=f"/decisions/agenda-items/{item.pk}/"
                )

        messages.success(request, f"تم توثيق ({disc.get_intervention_type_display()}) في سجل مداولات البند والمحضر.")

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('decisions:agenda_item_detail', item_pk=item.pk)


@login_required
def agenda_item_carry_over(request, item_pk):
    """
    Carries over a postponed or incomplete agenda item from its current CouncilMeeting
    to a subsequent target CouncilMeeting, preserving its application/policy/grievance links.
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بترحيل بنود جدول الأعمال بين جلسات المجلس.")
        return redirect('decisions:agenda_item_detail', item_pk=item_pk)

    item = get_object_or_404(CouncilAgendaItem.objects.select_related('meeting'), pk=item_pk)
    if request.method == 'POST':
        target_meeting_id = request.POST.get('target_meeting_id')
        target_meeting = get_object_or_404(CouncilMeeting, pk=target_meeting_id)

        with transaction.atomic():
            item.status = CouncilAgendaItem.ItemStatus.POSTPONED
            item.save(update_fields=['status'])

            next_pos = target_meeting.agenda_items.count() + 1
            carried_item = CouncilAgendaItem.objects.create(
                meeting=target_meeting,
                position=next_pos,
                item_number=f"بند ({next_pos}) [مرحل من {item.meeting.meeting_number}]",
                title=item.title,
                item_category=item.item_category,
                referring_entity=item.referring_entity,
                presenter_name=item.presenter_name,
                presenter_user=item.presenter_user,
                description=item.description,
                justification=f"{item.justification}\n[تم ترحيل البند من الجلسة ({item.meeting.meeting_number}) لاستكمال المداولة والبت]".strip(),
                initial_recommendation=item.initial_recommendation,
                required_action=item.required_action,
                status=CouncilAgendaItem.ItemStatus.SCHEDULED,
                application=item.application,
                policy=item.policy,
                grievance=item.grievance,
                standard_version=item.standard_version,
                attachment=item.attachment,
            )
            carried_item.conflict_of_interest_members.set(item.conflict_of_interest_members.all())
            carried_item.authorized_experts.set(item.authorized_experts.all())

            record_audit_log(
                user=request.user,
                action='COUNCIL_AGENDA_ITEM_CARRIED_OVER',
                target_model='CouncilAgendaItem',
                target_id=carried_item.pk,
                details=f"ترحيل البند ({item.title}) من الجلسة ({item.meeting.meeting_number}) إلى الجلسة ({target_meeting.meeting_number})",
                request=request
            )

        messages.success(request, f"تم ترحيل البند ({item.title}) بنجاح إلى جدول أعمال الجلسة ({target_meeting.meeting_number}).")
        return redirect('decisions:meeting_detail', pk=target_meeting.pk)

    return redirect('decisions:agenda_item_detail', item_pk=item.pk)


@login_required
def agenda_item_ballot_open(request, item_pk):
    """
    Opens a Public or Secret Ballot session linked to a specific CouncilAgendaItem.
    Strictly verifies quorum before opening.
    """
    can_open = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_open:
        messages.error(request, "غير مصرح لك بفتح جلسات التصويت لمجلس الإدارة.")
        return redirect('decisions:agenda_item_detail', item_pk=item_pk)

    item = get_object_or_404(CouncilAgendaItem.objects.select_related('meeting', 'application'), pk=item_pk)
    meeting = item.meeting

    if not meeting.is_quorum_met():
        record_audit_log(
            user=request.user,
            action='COUNCIL_BALLOT_OPEN_REJECTED_NO_QUORUM',
            target_model='CouncilAgendaItem',
            target_id=item.pk,
            details=f"رفض فتح التصويت للبند ({item.item_number}) لعدم اكتمال النصاب ({meeting.confirmed_attendance_count()}/{meeting.effective_quorum_required()})",
            request=request
        )
        messages.error(
            request,
            f"تعذر فتح التصويت على البند ({item.item_number}): النصاب القانوني للجلسة غير مكتمل ({meeting.confirmed_attendance_count()} حاضرون من أصل {meeting.effective_quorum_required()} مطلوب وفق المادة 6)."
        )
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    voting_mode = request.POST.get('voting_mode', CouncilBallot.VotingMode.SECRET)
    if voting_mode not in [CouncilBallot.VotingMode.PUBLIC, CouncilBallot.VotingMode.SECRET]:
        voting_mode = CouncilBallot.VotingMode.SECRET
    proposed_decision_text = request.POST.get('proposed_decision_text', '').strip() or item.initial_recommendation
    title = request.POST.get('title', '').strip() or f"التصويت على {item.item_number}: {item.title}"

    with transaction.atomic():
        ballot = CouncilBallot.objects.create(
            meeting=meeting,
            agenda_item=item,
            application=item.application,
            title=title,
            proposed_decision_text=proposed_decision_text,
            voting_mode=voting_mode,
            status=CouncilBallot.BallotStatus.OPEN,
            opened_by=request.user,
        )
        item.status = CouncilAgendaItem.ItemStatus.VOTING_OPEN
        item.save(update_fields=['status'])

        if meeting.status in [
            CouncilMeeting.MeetingStatus.DRAFT,
            CouncilMeeting.MeetingStatus.UNDER_PREPARATION,
            CouncilMeeting.MeetingStatus.INVITATIONS_SENT
        ]:
            meeting.status = CouncilMeeting.MeetingStatus.IN_SESSION
            meeting.save(update_fields=['status'])

        # Notify present voting members
        attending_members = meeting.attendances.filter(
            attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
            status__in=['CONFIRMED', 'ATTENDED', 'INVITED'],
            is_currently_present=True
        ).values_list('member_id', flat=True)
        for u in User.objects.filter(id__in=attending_members, is_active=True):
            send_notification(
                user=u,
                title=f"فتح باب التصويت ({ballot.get_voting_mode_display()}) - {item.item_number}",
                message=f"تم فتح باب التصويت على ({item.title}) في الجلسة ({meeting.meeting_number}). يرجى الإدلاء بصوتكم.",
                url=f"/decisions/meetings/{meeting.pk}/"
            )

        record_audit_log(
            user=request.user,
            action='COUNCIL_BALLOT_OPENED',
            target_model='CouncilBallot',
            target_id=ballot.pk,
            details=f"فتح التصويت ({ballot.get_voting_mode_display()}) للبند ({item.item_number}: {item.title}) في الجلسة ({meeting.meeting_number})",
            request=request
        )

    messages.success(request, f"تم فتح باب التصويت ({ballot.get_voting_mode_display()}) بنجاح للبند ({item.item_number}).")
    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def ballot_open(request, meeting_pk, app_pk):
    """
    Opens an independent Ballot Session for an accreditation application
    deliberated in the meeting. Enforces statutory quorum before opening.
    """
    can_open = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_open:
        messages.error(request, "غير مصرح لك بفتح جلسات الاقتراع السري لمجلس الإدارة.")
        return redirect('decisions:meeting_detail', pk=meeting_pk)

    meeting = get_object_or_404(CouncilMeeting, pk=meeting_pk)
    application = get_object_or_404(AccreditationApplication, pk=app_pk)

    # Statutory Quorum Guard
    if not meeting.is_quorum_met():
        messages.error(
            request,
            f"تعذر فتح الاقتراع السري: النصاب القانوني للجلسة غير مكتمل ({meeting.confirmed_attendance_count()} حاضرون من أصل {meeting.effective_quorum_required()} مطلوب)."
        )
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    voting_mode = request.POST.get('voting_mode', CouncilBallot.VotingMode.SECRET)
    agenda_item = CouncilAgendaItem.objects.filter(meeting=meeting, application=application).first()

    with transaction.atomic():
        ballot = CouncilBallot.objects.filter(meeting=meeting, application=application).order_by('-id').first()
        if ballot and ballot.status == CouncilBallot.BallotStatus.CLOSED:
            messages.warning(request, "تم إغلاق هذا الاقتراع وفرز أصواته مسبقاً.")
            return redirect('decisions:meeting_detail', pk=meeting.pk)

        if not ballot:
            ballot = CouncilBallot.objects.create(
                meeting=meeting,
                agenda_item=agenda_item,
                application=application,
                title=f"التصويت السري على اعتماد: {application.institution.name} ({application.application_number})",
                voting_mode=voting_mode,
                status=CouncilBallot.BallotStatus.OPEN,
                opened_by=request.user,
            )
        else:
            ballot.status = CouncilBallot.BallotStatus.OPEN
            ballot.save(update_fields=['status'])

        if agenda_item:
            agenda_item.status = CouncilAgendaItem.ItemStatus.VOTING_OPEN
            agenda_item.save(update_fields=['status'])

        meeting.status = CouncilMeeting.MeetingStatus.IN_SESSION
        meeting.save(update_fields=['status'])

        # Notify confirmed board members to cast secret ballots
        attending_members = meeting.attendances.filter(
            attendee_category=CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER,
            status__in=['CONFIRMED', 'ATTENDED', 'INVITED']
        ).values_list('member_id', flat=True)
        board_users = User.objects.filter(id__in=attending_members, is_active=True)
        for u in board_users:
            send_notification(
                user=u,
                title="فتح باب الاقتراع السري الفردي لجلسة المجلس",
                message=f"تم فتح باب التصويت السري على طلب الاعتماد ({application.application_number}) - ({application.institution.name}). يرجى الإدلاء بصوتكم الآن.",
                url=f"/decisions/meetings/{meeting.pk}/"
            )

        record_audit_log(
            user=request.user,
            action='COUNCIL_BALLOT_OPENED',
            target_model='CouncilBallot',
            target_id=ballot.pk,
            details=f"فتح جلسة الاقتراع السري لطلب ({application.application_number}) في جلسة المجلس ({meeting.meeting_number}) بنصاب مكتمل",
            request=request
        )

    messages.success(request, f"تم فتح باب الاقتراع السري الفردي بنجاح للطلب ({application.application_number}) وإشعار أعضاء المجلس.")
    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def ballot_cast_vote(request, pk):
    """
    Submits an individual Council vote (Secret or Public) enforcing Article 6:
    - Strictly limits voting to voting Council members (Chairman, Vice Chairman, Board Member).
    - Strictly prohibits invited experts, guests, and non-board technical admins from voting.
    - Enforces live quorum check (blocks voting if quorum is lost due to member withdrawal).
    - Enforces present status (absent, apologized, or withdrawn members cannot vote).
    - Enforces Conflict of Interest restriction.
    - Prevents duplicate voting.
    """
    ballot = get_object_or_404(CouncilBallot.objects.select_related('meeting', 'agenda_item', 'application'), pk=pk)
    meeting = ballot.meeting

    # 1. Role & Attendee Category Check (Article 6: Experts & Guests have NO voting rights)
    user_attendance = meeting.attendances.filter(member=request.user).first()
    if user_attendance and user_attendance.attendee_category != CouncilMeetingAttendance.AttendeeCategory.VOTING_MEMBER:
        record_audit_log(
            user=request.user,
            action='COUNCIL_VOTE_REJECTED_NON_VOTING_ATTENDEE',
            target_model='CouncilBallot',
            target_id=ballot.pk,
            details=f"رفض محاولة تصويت من مشارك غير مصوت ({user_attendance.get_attendee_category_display()}) في ({ballot.title})",
            request=request
        )
        messages.error(request, "غير مصرح لك بالتصويت: بموجب المادة (6) من القرار الجمهوري، للمجلس الاستعانة بخبراء وضيوف دون أن يكون لهم صوت معدود في المداولات.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    is_board_role = request.user.role in [
        User.Roles.BOARD_MEMBER,
        User.Roles.COUNCIL_CHAIRMAN,
        User.Roles.COUNCIL_VICE_CHAIRMAN
    ]
    if not is_board_role:
        messages.error(request, "غير مصرح لك: حق التصويت في جلسات المجلس مقتصر حصراً على رئيس المجلس ونائبه وأعضاء مجلس الإدارة المعينين.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    # 2. Ballot Open Status Check
    if ballot.status != CouncilBallot.BallotStatus.OPEN:
        messages.error(request, "جلسة الاقتراع مغلقة حالياً؛ لا يمكن استقبال أي أصوات جديدة.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    # 3. Live Quorum Check (Article 6)
    if not meeting.is_quorum_met():
        messages.error(
            request,
            f"توقف التصويت قانونياً: النصاب القانوني للجلسة غير مكتمل حالياً ({meeting.confirmed_attendance_count()} حاضرون من أصل {meeting.effective_quorum_required()} مطلوب)."
        )
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    # 4. Attendance & Presence Check (Absent, Apologized, or Withdrawn members cannot vote)
    if meeting.attendances.exists():
        if not user_attendance or user_attendance.status not in [
            CouncilMeetingAttendance.RSVPStatus.CONFIRMED,
            CouncilMeetingAttendance.RSVPStatus.ATTENDED
        ] or not user_attendance.is_currently_present:
            messages.error(request, "لا يمكن الإدلاء بالصوت: يشترط تواجد العضو وحضوره الفعلي في الجلسة وقت التصويت.")
            return redirect('decisions:meeting_detail', pk=meeting.pk)

    # 5. Conflict of Interest Check
    if ballot.is_member_conflicted(request.user):
        record_audit_log(
            user=request.user,
            action='COUNCIL_VOTE_BLOCKED_CONFLICT_OF_INTEREST',
            target_model='CouncilBallot',
            target_id=ballot.pk,
            details=f"منع تصويت عضو المجلس ({request.user.get_full_name()}) لوجود تضارب مصالح مسجل على البند ({ballot.title})",
            request=request
        )
        messages.error(request, "يُحظر التصويت على هذا البند لوجود تضارب مصالح مسجل أو ارتباط بالمؤسسة المعنية.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    # 6. Duplicate Voting Prevention
    already_voted = (
        CouncilBallotVoterRecord.objects.filter(ballot=ballot, voter=request.user).exists() or
        CouncilPublicVote.objects.filter(ballot=ballot, voter=request.user).exists()
    )
    if already_voted:
        messages.warning(request, "سبق لك الإدلاء بصوتك في هذا الاقتراع؛ يمنع النظام تكرار التصويت أو تعديله لحماية النزاهة.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    if request.method == 'POST':
        choice = request.POST.get('vote_choice')
        abstain_justification = request.POST.get('abstain_justification', '').strip()

        if choice not in [c[0] for c in CouncilSecretVote.VoteChoice.choices]:
            messages.error(request, "يرجى تحديد خيار تصويت صحيح من الخيارات المعتمدة.")
            return redirect('decisions:meeting_detail', pk=meeting.pk)

        if choice == CouncilSecretVote.VoteChoice.ABSTAIN and not abstain_justification:
            messages.error(request, "وفقاً للائحة المجلس، يشترط بيان أسباب ومسوغات الامتناع عن التصويت.")
            return redirect('decisions:meeting_detail', pk=meeting.pk)

        with transaction.atomic():
            # Always record voter participation proof
            CouncilBallotVoterRecord.objects.create(
                ballot=ballot,
                voter=request.user
            )

            if ballot.voting_mode == CouncilBallot.VotingMode.PUBLIC:
                CouncilPublicVote.objects.create(
                    ballot=ballot,
                    voter=request.user,
                    vote_choice=choice,
                    justification=abstain_justification
                )
                details_msg = f"إدلاء عضو المجلس ({request.user.get_full_name()}) بصوته العلني ({choice}) في ({ballot.title})"
            else:
                # Cryptographic blind hash to verify vote validity without leaking voter identity
                salt = timezone.now().isoformat()
                cast_hash = hashlib.sha256(f"{ballot.pk}:{choice}:{salt}".encode('utf-8')).hexdigest()
                CouncilSecretVote.objects.create(
                    ballot=ballot,
                    vote_choice=choice,
                    abstain_justification=abstain_justification,
                    cast_hash=cast_hash
                )
                details_msg = f"إدلاء عضو المجلس ({request.user.get_full_name()}) بصوته السري المشفر في ({ballot.title})"

            record_audit_log(
                user=request.user,
                action='COUNCIL_BALLOT_VOTE_CAST',
                target_model='CouncilBallot',
                target_id=ballot.pk,
                details=details_msg,
                request=request
            )

        messages.success(request, "تم تسجيل وإيداع صوتك بنجاح في سجل الاقتراع الرسمي.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def ballot_close_and_tally(request, pk):
    """
    Closes the Ballot session and executes the automated tally according to Article 6:
    - Majority of present members.
    - In case of a tie, the side supported by the Council Chairperson prevails ("يرجح الجانب الذي منه رئيس المجلس").
    """
    can_close = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_close:
        messages.error(request, "غير مصرح لك بإغلاق الاقتراع وفرز الأصوات.")
        return redirect('decisions:meetings_list')

    ballot = get_object_or_404(CouncilBallot, pk=pk)
    chairperson_tie_break = request.POST.get('chairperson_tie_break', '').strip() or None

    if ballot.status == CouncilBallot.BallotStatus.CLOSED and not (ballot.tie_occurred and chairperson_tie_break):
        messages.info(request, "هذا الاقتراع مغلق وتم فرزه مسبقاً.")
        return redirect('decisions:meeting_detail', pk=ballot.meeting_id)

    with transaction.atomic():
        ballot.closed_by = request.user
        ballot.tally_results(chairperson_tie_break=chairperson_tie_break)

        record_audit_log(
            user=request.user,
            action='COUNCIL_BALLOT_CLOSED_AND_TALLIED',
            target_model='CouncilBallot',
            target_id=ballot.pk,
            details=(
                f"إغلاق وفرز أصوات ({ballot.title}): موافقة ({ballot.votes_approve_count})، "
                f"رفض ({ballot.votes_reject_count})، امتناع ({ballot.votes_abstain_count})، "
                f"النتيجة النهائية ({ballot.final_result})"
            ),
            request=request
        )

        # Notify Council Board & Secretariat of the official ballot tally & tie-breaker result (Article 6)
        tie_msg = " (مع إعمال الصوت المرجح لرئيس المجلس وفق المادة 6)" if ballot.tie_broken_by_chairperson else ""
        for u in User.objects.filter(
            role__in=[
                User.Roles.COUNCIL_CHAIRMAN,
                User.Roles.COUNCIL_VICE_CHAIRMAN,
                User.Roles.BOARD_MEMBER,
                User.Roles.COUNCIL_SECRETARY_GENERAL,
                User.Roles.COUNCIL_SECRETARY,
            ],
            is_active=True
        ):
            send_notification(
                user=u,
                title=f"نتيجة فرز الاقتراع ({ballot.title})",
                message=(
                    f"تم إغلاق الاقتراع وفرز الأصوات في ({ballot.meeting.meeting_number}): "
                    f"موافقة ({ballot.votes_approve_count})، رفض ({ballot.votes_reject_count})، امتناع ({ballot.votes_abstain_count}) "
                    f"— النتيجة النهائية: ({ballot.final_result}){tie_msg}."
                ),
                url=f"/decisions/meetings/{ballot.meeting_id}/"
            )

    messages.success(
        request,
        f"تم إغلاق الاقتراع وفرز النتائج بنجاح: موافقة ({ballot.votes_approve_count})، "
        f"رفض ({ballot.votes_reject_count})، امتناع ({ballot.votes_abstain_count}) — النتيجة: ({ballot.final_result})."
    )
    return redirect('decisions:meeting_detail', pk=ballot.meeting_id)


@login_required
def meeting_minutes_manage(request, meeting_pk):
    """
    Creates or updates the Official Meeting Minutes (CouncilMeetingMinutes).
    - Preserves previous versions in CouncilMeetingMinutesVersion (tracking who modified and when).
    - Strictly prevents modifying minutes after Chairperson approval (APPROVED lock).
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بإعداد أو تعديل محاضر جلسات المجلس.")
        return redirect('decisions:meeting_detail', pk=meeting_pk)

    meeting = get_object_or_404(CouncilMeeting, pk=meeting_pk)
    minutes = getattr(meeting, 'official_minutes', None)

    if minutes and minutes.status == CouncilMeetingMinutes.MinutesStatus.APPROVED:
        messages.error(request, "هذا المحضر معتمد ومصادق عليه رسمياً من رئيس المجلس؛ يُحظر التعديل عليه بعد الاعتماد.")
        return redirect('decisions:meeting_detail', pk=meeting.pk)

    if request.method == 'POST':
        opening_statement = request.POST.get('opening_statement', '').strip()
        discussions_record = request.POST.get('discussions_record', '').strip()
        decisions_record = request.POST.get('decisions_record', '').strip()
        closing_statement = request.POST.get('closing_statement', '').strip()
        modification_reason = request.POST.get('modification_reason', 'تحديث مسودة المحضر').strip()
        submit_for_approval = request.POST.get('submit_for_approval') in ['1', 'true', 'on', 'True']

        # Auto-compile rich default sections if empty
        if not opening_statement:
            opening_statement = (
                f"انعقدت بعون الله {meeting.meeting_number} ({meeting.get_meeting_type_display()}) "
                f"بتاريخ ({meeting.meeting_date}) في ({meeting.location}) برئاسة ({meeting.chairperson_name})، "
                f"وبحضور ({meeting.confirmed_attendance_count()}) من الأعضاء المصوتين (النصاب المطلوب: {meeting.effective_quorum_required()})."
            )
        if not discussions_record:
            disc_lines = []
            for item in meeting.agenda_items.prefetch_related('discussions').all():
                disc_lines.append(f"• {item.item_number} - {item.title}:")
                for d in item.discussions.all():
                    disc_lines.append(f"  - [{d.get_intervention_type_display()}] {d.speaker_name}: {d.content}")
            discussions_record = "\n".join(disc_lines) if disc_lines else meeting.minutes_summary
        if not decisions_record:
            dec_lines = []
            for b in meeting.ballots.all():
                dec_lines.append(
                    f"• التصويت ({b.title}): موافقة ({b.votes_approve_count}) | رفض ({b.votes_reject_count}) | امتناع ({b.votes_abstain_count}) -> النتيجة: ({b.final_result})"
                )
            for r in meeting.resolutions.all():
                dec_lines.append(f"• [{r.get_resolution_type_display()}] ({r.resolution_number}): {r.decision_text}")
            decisions_record = "\n".join(dec_lines)
        if not closing_statement:
            closing_statement = f"واختتمت الجلسة في تمام الساعة ({meeting.end_time or 'المحددة'}) بعد استكمال التداول في جميع بنود جدول الأعمال."

        new_status = (
            CouncilMeetingMinutes.MinutesStatus.PENDING_APPROVAL
            if submit_for_approval else CouncilMeetingMinutes.MinutesStatus.DRAFT
        )

        with transaction.atomic():
            if not minutes:
                minutes_number = f"MIN-{meeting.pk}-{timezone.now().year}"
                minutes = CouncilMeetingMinutes.objects.create(
                    meeting=meeting,
                    minutes_number=minutes_number,
                    version_number=1,
                    opening_statement=opening_statement,
                    discussions_record=discussions_record,
                    decisions_record=decisions_record,
                    closing_statement=closing_statement,
                    status=new_status,
                    prepared_by=request.user
                )
            else:
                # Archive previous version before updating
                snapshot = (
                    f"الافتتاح:\n{minutes.opening_statement}\n\n"
                    f"المداولات:\n{minutes.discussions_record}\n\n"
                    f"القرارات والتوصيات:\n{minutes.decisions_record}\n\n"
                    f"الخاتمة:\n{minutes.closing_statement}"
                )
                CouncilMeetingMinutesVersion.objects.create(
                    minutes=minutes,
                    version_number=minutes.version_number,
                    content_snapshot=snapshot,
                    modified_by=request.user,
                    modification_reason=modification_reason
                )
                minutes.version_number += 1
                minutes.opening_statement = opening_statement
                minutes.discussions_record = discussions_record
                minutes.decisions_record = decisions_record
                minutes.closing_statement = closing_statement
                minutes.status = new_status
                minutes.save()

            meeting.minutes_summary = f"{opening_statement}\n\n{discussions_record}\n\n{decisions_record}"
            meeting.save(update_fields=['minutes_summary'])

            record_audit_log(
                user=request.user,
                action='COUNCIL_MINUTES_SAVED',
                target_model='CouncilMeetingMinutes',
                target_id=minutes.pk,
                details=f"حفظ محضر الجلسة ({minutes.minutes_number}) الإصدار (v{minutes.version_number}) بالحالة ({minutes.get_status_display()})",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

            for lead in User.objects.filter(
                role__in=[
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                ],
                is_active=True
            ):
                send_notification(
                    user=lead,
                    title=f"تحرير ورفع محضر جلسة المجلس ({meeting.meeting_number}) - ({minutes.get_status_display()})",
                    message=(
                        f"قامت سكرتارية المجلس بتحرير وتوثيق محضر الجلسة رقم ({minutes.minutes_number}) "
                        f"الإصدار (v{minutes.version_number}) شاملاً الحضور والمداخلات والتحفظات والقرارات وحفظه في المكتبة. اضغط للمراجعة والاعتماد."
                    ),
                    url=f"/decisions/meetings/{meeting.pk}/"
                )

        messages.success(request, f"تم حفظ محضر الجلسة ({minutes.minutes_number}) - الإصدار (v{minutes.version_number}) بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_minutes_approve(request, meeting_pk):
    """
    Chairperson approves and ratifies the Official Meeting Minutes, permanently locking them
    and transitioning the meeting status to MINUTES_RATIFIED.
    """
    can_approve = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN
        ]
    )
    if not can_approve:
        messages.error(request, "غير مصرح لك: اعتماد والتوقيع النهائي على محضر الجلسة مقتصر على رئيس المجلس أو نائبه.")
        return redirect('decisions:meeting_detail', pk=meeting_pk)

    meeting = get_object_or_404(CouncilMeeting, pk=meeting_pk)
    minutes = get_object_or_404(CouncilMeetingMinutes, meeting=meeting)

    if request.method == 'POST':
        with transaction.atomic():
            minutes.status = CouncilMeetingMinutes.MinutesStatus.APPROVED
            minutes.approved_by = request.user
            minutes.approved_at = timezone.now()
            minutes.save()

            meeting.status = CouncilMeeting.MeetingStatus.MINUTES_RATIFIED
            meeting.save(update_fields=['status'])

            for att in meeting.attendances.select_related('member').all():
                send_notification(
                    user=att.member,
                    title=f"اعتماد ومصادقة محضر جلسة المجلس ({meeting.meeting_number})",
                    message=f"تم اعتماد المحضر الرسمي رقم ({minutes.minutes_number}) للجلسة ({meeting.meeting_number}) من قبل رئيس المجلس.",
                    url=f"/decisions/meetings/{meeting.pk}/minutes/print/"
                )

            record_audit_log(
                user=request.user,
                action='COUNCIL_MINUTES_APPROVED',
                target_model='CouncilMeetingMinutes',
                target_id=minutes.pk,
                details=f"اعتماد ومصادقة محضر الجلسة ({minutes.minutes_number}) نهائياً من قبل ({request.user.get_full_name()})",
                request=request
            )

            try:
                from apps.accounts.library_service import sync_system_assets_to_library
                sync_system_assets_to_library()
            except Exception:
                pass

        messages.success(request, f"تم اعتماد ومصادقة محضر الجلسة ({minutes.minutes_number}) رسمياً وقفل التعديل عليه.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def meeting_minutes_print(request, meeting_pk):
    """Renders the official printable and PDF-exportable Meeting Minutes document."""
    meeting = get_object_or_404(
        CouncilMeeting.objects.prefetch_related(
            'attendances__member',
            'agenda_items__discussions',
            'ballots',
            'resolutions',
            'decisions__application__institution'
        ),
        pk=meeting_pk
    )
    if not (request.user.is_board or request.user.is_council or request.user.is_staff or request.user.is_minister or request.user.is_prime_minister):
        messages.error(request, "غير مصرح لك باستعراض محضر الجلسة.")
        return redirect('core_dashboard')

    minutes = getattr(meeting, 'official_minutes', None)
    return render(request, 'decisions/meeting_minutes_print.html', {
        'meeting': meeting,
        'minutes': minutes,
        'attendances': meeting.attendances.select_related('member').all(),
        'agenda_items': meeting.agenda_items.prefetch_related('discussions', 'ballots', 'resolutions').all(),
        'ballots': meeting.ballots.all(),
        'resolutions': meeting.resolutions.all(),
    })


@login_required
def resolution_create(request, meeting_pk):
    """
    Creates an independent CouncilResolution distinguishing between:
    - FINAL_DECISION (within Council's statutory authority)
    - RECOMMENDATION (submitted to higher authority such as the Minister)
    - ASSIGNMENT (assigned to a directorate/committee with deadline and follow-up tracking)
    - REFERRAL (referred for further study)
    - POSTPONEMENT (postponed to a subsequent session)
    """
    can_manage = (
        request.user.is_superuser or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ]
    )
    if not can_manage:
        messages.error(request, "غير مصرح لك بإصدار وتوثيق قرارات وتوصيات وتكليفات المجلس.")
        return redirect('decisions:meeting_detail', pk=meeting_pk)

    meeting = get_object_or_404(CouncilMeeting, pk=meeting_pk)
    if request.method == 'POST':
        resolution_type = request.POST.get('resolution_type', CouncilResolution.ResolutionType.FINAL_DECISION)
        resolution_number = request.POST.get('resolution_number', '').strip()
        agenda_item_id = request.POST.get('agenda_item_id')
        ballot_id = request.POST.get('ballot_id')
        title = request.POST.get('title', '').strip()
        decision_text = request.POST.get('decision_text', '').strip()
        responsible_entity = request.POST.get('responsible_entity', '').strip()
        responsible_user_id = request.POST.get('responsible_user_id')
        receiving_entity = request.POST.get('receiving_entity', '').strip()
        deadline_date = request.POST.get('deadline_date') or None

        agenda_item = CouncilAgendaItem.objects.filter(pk=agenda_item_id, meeting=meeting).first() if agenda_item_id else None
        ballot = CouncilBallot.objects.filter(pk=ballot_id, meeting=meeting).first() if ballot_id else (
            agenda_item.ballots.order_by('-id').first() if agenda_item else None
        )
        responsible_user = User.objects.filter(pk=responsible_user_id).first() if responsible_user_id else None

        if not resolution_number:
            seq = CouncilResolution.objects.count() + 1
            resolution_number = f"RES-{timezone.now().year}-{seq:03d}"

        voting_summary = ''
        if ballot:
            voting_summary = f"موافقة ({ballot.votes_approve_count}) | رفض ({ballot.votes_reject_count}) | امتناع ({ballot.votes_abstain_count}) -> ({ballot.final_result})"

        with transaction.atomic():
            res = CouncilResolution.objects.create(
                resolution_number=resolution_number,
                meeting=meeting,
                agenda_item=agenda_item,
                ballot=ballot,
                resolution_type=resolution_type,
                title=title or (agenda_item.title if agenda_item else "قرار مجلس الإدارة"),
                decision_text=decision_text,
                voting_result_summary=voting_summary,
                responsible_entity=responsible_entity,
                responsible_user=responsible_user,
                receiving_entity=receiving_entity,
                deadline_date=deadline_date,
                attachment=request.FILES.get('attachment'),
                issued_by=request.user,
            )

            if agenda_item:
                if resolution_type == CouncilResolution.ResolutionType.POSTPONEMENT:
                    agenda_item.status = CouncilAgendaItem.ItemStatus.POSTPONED
                elif resolution_type == CouncilResolution.ResolutionType.REFERRAL:
                    agenda_item.status = CouncilAgendaItem.ItemStatus.REFERRED
                else:
                    agenda_item.status = CouncilAgendaItem.ItemStatus.DECIDED
                agenda_item.save(update_fields=['status'])

            # Notify responsible user & relevant roles
            if responsible_user:
                send_notification(
                    user=responsible_user,
                    title=f"تكليف/قرار جديد صادر عن مجلس الإدارة ({res.resolution_number})",
                    message=f"صدر ({res.get_resolution_type_display()}) برقم ({res.resolution_number}) بخصوص ({res.title}). الموعد النهائي: ({res.deadline_date or 'غير محدد'}).",
                    url=f"/decisions/meetings/{meeting.pk}/"
                )
            if resolution_type == CouncilResolution.ResolutionType.RECOMMENDATION:
                notify_role(
                    [User.Roles.MINISTER, User.Roles.COUNCIL_SECRETARY_GENERAL],
                    title=f"توصية مرفوعة من مجلس الإدارة ({res.resolution_number})",
                    message=f"رفع مجلس الإدارة التوصية رقم ({res.resolution_number}) بخصوص ({res.title}).",
                    url=f"/decisions/meetings/{meeting.pk}/"
                )

            record_audit_log(
                user=request.user,
                action='COUNCIL_RESOLUTION_ISSUED',
                target_model='CouncilResolution',
                target_id=res.pk,
                details=f"إصدار ({res.get_resolution_type_display()}) رقم ({res.resolution_number}) في الجلسة ({meeting.meeting_number})",
                request=request
            )

        messages.success(request, f"تم إصدار وتوثيق ({res.get_resolution_type_display()}) برقم ({res.resolution_number}) بنجاح.")

    return redirect('decisions:meeting_detail', pk=meeting.pk)


@login_required
def resolution_update_status(request, pk):
    """Updates implementation status and follow-up notes for a CouncilResolution."""
    res = get_object_or_404(CouncilResolution.objects.select_related('meeting'), pk=pk)
    can_update = (
        request.user.is_superuser or
        request.user == res.responsible_user or
        request.user.role in [
            User.Roles.COUNCIL_CHAIRMAN,
            User.Roles.COUNCIL_VICE_CHAIRMAN,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.DG_ACCREDITATION,
            User.Roles.DG_QUALITY,
            User.Roles.ADMIN
        ]
    )
    if not can_update:
        messages.error(request, "غير مصرح لك بتحديث حالة تنفيذ هذا القرار/التكليف.")
        return redirect('decisions:meeting_detail', pk=res.meeting_id)

    if request.method == 'POST':
        new_status = request.POST.get('implementation_status', res.implementation_status)
        followup_notes = request.POST.get('followup_notes', '').strip()
        res.implementation_status = new_status
        if followup_notes:
            res.followup_notes = followup_notes
        if new_status == CouncilResolution.ImplementationStatus.COMPLETED:
            res.completion_date = timezone.now().date()
        res.save()

        record_audit_log(
            user=request.user,
            action='COUNCIL_RESOLUTION_STATUS_UPDATED',
            target_model='CouncilResolution',
            target_id=res.pk,
            details=f"تحديث حالة تنفيذ ({res.resolution_number}) إلى ({res.get_implementation_status_display()})",
            request=request
        )
        messages.success(request, f"تم تحديث حالة متابعة ({res.resolution_number}) إلى ({res.get_implementation_status_display()}).")

    return redirect('decisions:meeting_detail', pk=res.meeting_id)


@login_required
def council_governance_dashboard(request):
    """
    Unified Role-Tailored Governance Workspace supporting:
    1. Council Chairperson Dashboard
    2. Secretary General Dashboard
    3. Council Member Dashboard
    4. Meeting Secretary Dashboard
    """
    if not (request.user.is_board or request.user.is_council or request.user.is_staff or request.user.is_minister or request.user.is_prime_minister):
        messages.error(request, "غير مصرح لك بالوصول إلى لوحة حوكمة جلسات وقرارات المجلس.")
        return redirect('core_dashboard')

    meetings = CouncilMeeting.objects.prefetch_related('attendances', 'agenda_items', 'ballots', 'resolutions').order_by('-meeting_date')
    open_ballots = CouncilBallot.objects.filter(status=CouncilBallot.BallotStatus.OPEN).select_related('meeting', 'agenda_item')
    tie_ballots = CouncilBallot.objects.filter(tie_occurred=True, tie_broken_by_chairperson=False).select_related('meeting', 'agenda_item')
    pending_minutes = CouncilMeetingMinutes.objects.exclude(status=CouncilMeetingMinutes.MinutesStatus.APPROVED).select_related('meeting')
    resolutions = CouncilResolution.objects.select_related('meeting', 'agenda_item', 'responsible_user').order_by('-issue_date')
    my_invitations = CouncilMeetingAttendance.objects.filter(member=request.user).select_related('meeting').order_by('-meeting__meeting_date')

    return render(request, 'decisions/council_workspace.html', {
        'meetings': meetings,
        'open_ballots': open_ballots,
        'tie_ballots': tie_ballots,
        'pending_minutes': pending_minutes,
        'resolutions': resolutions,
        'my_invitations': my_invitations,
    })



# ------------------------------------------------------------------------------
# CENTRALIZED SOVEREIGN TRANSACTIONS & CORRESPONDENCE
# ------------------------------------------------------------------------------

@login_required
def sovereign_transactions_list(request):
    """
    Centralized Sovereign Transactions Registry for official memos, nominations,
    presidential decrees, policy ratifications, and grievance appeals.
    """
    if not (request.user.is_council or request.user.is_board or request.user.is_minister or request.user.is_prime_minister or request.user.is_staff):
        messages.error(request, "غير مصرح لك بالوصول لسجل المعاملات السيادية الموحد.")
        return redirect('core_dashboard')

    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    search_q = request.GET.get('q', '').strip()

    transactions_qs = SovereignTransaction.objects.select_related(
        'sender', 'recipient', 'meeting', 'application__institution'
    ).all().order_by('-submission_date', '-created_at')

    if status_filter:
        transactions_qs = transactions_qs.filter(status=status_filter)
    if type_filter:
        transactions_qs = transactions_qs.filter(transaction_type=type_filter)
    if search_q:
        from django.db import models
        transactions_qs = transactions_qs.filter(
            models.Q(reference_number__icontains=search_q) |
            models.Q(subject__icontains=search_q) |
            models.Q(sending_authority__icontains=search_q) |
            models.Q(receiving_authority__icontains=search_q)
        )

    context = {
        'transactions': transactions_qs,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search_q': search_q,
        'status_choices': SovereignTransaction.TransactionStatus.choices,
        'statuses': SovereignTransaction.TransactionStatus.choices,
        'type_choices': SovereignTransaction.TransactionType.choices,
        'types': SovereignTransaction.TransactionType.choices,
        'current_status': status_filter,
        'current_type': type_filter,
        'search_query': search_q,
        'total_count': SovereignTransaction.objects.count(),
        'submitted_count': SovereignTransaction.objects.filter(status=SovereignTransaction.TransactionStatus.SUBMITTED).count(),
        'approved_count': SovereignTransaction.objects.filter(status=SovereignTransaction.TransactionStatus.APPROVED).count(),
    }
    return render(request, 'decisions/sovereign_transactions_list.html', context)


@login_required
def sovereign_transaction_detail(request, pk):
    """
    Detailed timeline, attachments, and movement history of a sovereign transaction.
    """
    if not (request.user.is_council or request.user.is_board or request.user.is_minister or request.user.is_prime_minister or request.user.is_staff):
        messages.error(request, "غير مصرح لك باستعراض بيانات هذه المعاملة السيادية.")
        return redirect('core_dashboard')

    transaction_obj = get_object_or_404(
        SovereignTransaction.objects.select_related(
            'sender', 'recipient', 'meeting', 'application__institution'
        ),
        pk=pk
    )
    movements = transaction_obj.movements.select_related('actor').all().order_by('-timestamp')

    return render(request, 'decisions/sovereign_transaction_detail.html', {
        'trx': transaction_obj,
        'transaction': transaction_obj,
        'movements': movements,
    })

