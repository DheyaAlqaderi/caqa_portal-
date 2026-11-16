import datetime
import logging
from django.utils import timezone
from django.db import models

from apps.accounts.models import (
    User,
    Notification,
    send_notification,
    notify_institution,
    ScheduledReminderLog,
    record_audit_log,
)
from apps.site_visits.models import SiteVisitSchedule
from apps.site_visits.services import get_panel_reviewers
from apps.decisions.models import AccreditationDecision, AccreditationCertificate
from apps.surveillance.models import (
    ContinuousImprovementPlan,
    AnnualMonitoringReport,
    SurveillanceVisit,
    CorrectiveActionItem,
)
from apps.accreditation.models import ExternalReviewReport

logger = logging.getLogger(__name__)


def calculate_calendar_anniversary(base_date, year_offset):
    """
    Calculate the exact calendar anniversary of a given date after `year_offset` years.
    Handles leap-year edge cases: If base_date is Feb 29 and target year is not a leap year,
    the anniversary resolves to Feb 28 (the final day of February).
    Does not suffer from the 1-day drift caused by timedelta(days=365).
    """
    try:
        return base_date.replace(year=base_date.year + year_offset)
    except ValueError:
        # Handles February 29 on non-leap years -> February 28
        return datetime.date(base_date.year + year_offset, 2, 28)


def _get_secretariat_users():
    """Returns active, approved Secretariat officers and Administrators."""
    return User.objects.filter(
        role__in=[User.Roles.COUNCIL_SECRETARY, User.Roles.ADMIN],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )


# =============================================================================
# SCENARIO 29: Site Visit Reminders (7 Days & 48 Hours)
# =============================================================================
def check_site_visit_reminders(reference_date=None, dry_run=False):
    """
    Scenario 29: Dispatches site visit reminders:
    - 7 days before visit
    - 48 hours (2 days) before visit
    Excludes cancelled/postponed visits and completed visits.
    Recipients: Assigned reviewers and authorized institution officers.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    # Only scheduled visits
    visits = SiteVisitSchedule.objects.select_related(
        'application__institution',
        'application__applicant_user',
    ).filter(
        status__in=[SiteVisitSchedule.VisitStatus.SCHEDULED, SiteVisitSchedule.VisitStatus.IN_PROGRESS],
        start_date__gte=today
    )

    for visit in visits:
        try:
            app = visit.application
            institution = app.institution
            days_until = (visit.start_date - today).days

            # 1. 7-Day Reminder
            if days_until <= 7 and days_until > 2:
                reminder_key = 'SITE_VISIT_7_DAYS'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'SiteVisitSchedule', visit.pk):
                    if not dry_run:
                        # Notify institution
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تذكير باقتراب موعد الزيارة الميدانية (متبقي {days_until} أيام): {app.application_number}",
                            message=(
                                f"تذكير: تنطلق فعاليات الزيارة الميدانية لطلب الاعتماد ({app.application_number}) "
                                f"بتاريخ ({visit.start_date}) في مقر ({visit.visit_location}). "
                                f"يرجى استكمال التجهيزات اللوجستية وتنسيق اللقاء الافتتاحي."
                            ),
                            url=f"/site-visits/app/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        created_count = len(inst_notifs)

                        # Notify assigned panel reviewers
                        for rev in get_panel_reviewers(app):
                            n = send_notification(
                                user=rev,
                                title=f"تذكير بموعد الزيارة الميدانية (متبقي {days_until} أيام): {app.application_number}",
                                message=(
                                    f"تذكير: تنطلق الزيارة الميدانية لمؤسسة ({institution.name}) "
                                    f"بتاريخ ({visit.start_date}). يرجى مراجعة محاور الزيارة والتقرير الذاتي."
                                ),
                                url=f"/site-visits/app/{app.pk}/"
                            )
                            if n:
                                created_count += 1

                        if created_count > 0:
                            stats['created'] += created_count
                            ScheduledReminderLog.record_sent(
                                reminder_key, 'SiteVisitSchedule', visit.pk,
                                details=f"7-day reminder dispatched for visit on {visit.start_date}"
                            )
                        else:
                            logger.warning(f"No notifications created for {reminder_key} on visit {visit.pk}. Retrying on next run.")
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

            # 2. 48-Hour (2 Days) Reminder
            elif days_until <= 2 and days_until >= 0:
                reminder_key = 'SITE_VISIT_48_HOURS'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'SiteVisitSchedule', visit.pk):
                    if not dry_run:
                        # Notify institution
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تذكير عاجل: متبقي 48 ساعة على بدء الزيارة الميدانية: {app.application_number}",
                            message=(
                                f"تذكير عاجل: تبدأ فعاليات الزيارة الميدانية الرسمية بعد 48 ساعة "
                                f"بتاريخ ({visit.start_date}). يرجى تأكيد جهوزية القاعات والمنسق المعتمد."
                            ),
                            url=f"/site-visits/app/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        created_count = len(inst_notifs)

                        # Notify assigned reviewers
                        for rev in get_panel_reviewers(app):
                            n = send_notification(
                                user=rev,
                                title=f"تذكير عاجل: الزيارة الميدانية تبدأ خلال 48 ساعة: {app.application_number}",
                                message=(
                                    f"تذكير نهائي: تبدأ أعمال النزول الميداني لتقييم ({institution.name}) "
                                    f"بتاريخ ({visit.start_date})."
                                ),
                                url=f"/site-visits/app/{app.pk}/"
                            )
                            if n:
                                created_count += 1

                        if created_count > 0:
                            stats['created'] += created_count
                            ScheduledReminderLog.record_sent(
                                reminder_key, 'SiteVisitSchedule', visit.pk,
                                details=f"48-hour reminder dispatched for visit on {visit.start_date}"
                            )
                        else:
                            logger.warning(f"No notifications created for {reminder_key} on visit {visit.pk}. Retrying on next run.")
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking site visit {visit.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 52: Continuous Improvement Plan Period Opened
# =============================================================================
def check_cip_period_opened(reference_date=None, dry_run=False):
    """
    Scenario 52: Notifies relevant institution officers when an approved
    improvement-plan submission period opens after accreditation decision.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    # Decisions that require CIP (Full or Conditional accreditation)
    decisions = AccreditationDecision.objects.select_related(
        'application__institution',
        'application__applicant_user'
    ).filter(
        decision_type__in=[
            AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
        ],
        decision_date__lte=today
    )

    for decision in decisions:
        try:
            plan = getattr(decision, 'improvement_plan', None)
            # If plan does not exist or is in DRAFT status, notify that period is open
            is_unsubmitted = (plan is None) or (plan.status == ContinuousImprovementPlan.PlanStatus.DRAFT)
            if not is_unsubmitted:
                stats['skipped'] += 1
                continue

            reminder_key = 'CIP_PERIOD_OPENED'
            if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationDecision', decision.pk):
                if not dry_run:
                    institution = decision.application.institution
                    inst_notifs = notify_institution(
                        institution=institution,
                        title=f"بدء فترة إعداد وتقديم خطة التحسين المستمر: {decision.decree_number}",
                        message=(
                            f"نحيطكم علماً بافتتاح الفترة النظامية لتقديم خطة التحسين المستمر "
                            f"المعتمدة لقرار الاعتماد رقم ({decision.decree_number}). "
                            f"يرجى الدخول وتوثيق مصفوفة معالجة الملاحظات والأنشطة التطويرية."
                        ),
                        url=f"/surveillance/manage/{decision.pk}/",
                        extra_recipients=decision.application.applicant_user
                    )
                    if inst_notifs:
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(
                            reminder_key, 'AccreditationDecision', decision.pk,
                            details=f"CIP opened notice sent for decision {decision.decree_number}"
                        )
                    else:
                        logger.warning(f"No notifications created for {reminder_key} on decision {decision.pk}. Retrying on next run.")
                else:
                    stats['created'] += 1
            else:
                stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking CIP period for decision {decision.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 59: Annual Report Deadline Reminder
# =============================================================================
def check_annual_report_reminders(reference_date=None, dry_run=False):
    """
    Scenario 59: Notifies responsible institution officers before the annual report deadline.
    Evaluates each year of accreditation validity:
    - 30 days before anniversary
    - 7 days before anniversary
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    decisions = AccreditationDecision.objects.select_related(
        'application__institution',
        'application__applicant_user',
    ).filter(
        decision_type__in=[
            AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
        ],
        decision_date__isnull=False
    )

    for decision in decisions:
        try:
            institution = decision.application.institution
            validity = decision.validity_years or 5

            for year_num in range(1, validity + 1):
                anniversary_date = calculate_calendar_anniversary(decision.decision_date, year_num)
                days_until = (anniversary_date - today).days

                # Check if report for this year is already submitted
                has_submitted = AnnualMonitoringReport.objects.filter(
                    decision=decision,
                    year_number=year_num
                ).exclude(
                    review_status=AnnualMonitoringReport.ReviewStatus.DRAFT
                ).exists()

                if has_submitted:
                    continue

                # 1. 30 Days Reminder
                if days_until <= 30 and days_until > 7:
                    reminder_key = f"ANNUAL_REPORT_Y{year_num}_30D"
                    if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationDecision', decision.pk):
                        if not dry_run:
                            inst_notifs = notify_institution(
                                institution=institution,
                                title=f"تذكير باقتراب موعد تقرير المتابعة السنوي (العام {year_num}): {decision.decree_number}",
                                message=(
                                    f"تذكير: يستحق موعد تسليم تقرير المتابعة السنوي رقم ({year_num}) "
                                    f"لقرار الاعتماد ({decision.decree_number}) بعد ({days_until}) يوماً "
                                    f"بتاريخ ({anniversary_date}). يرجى استكمال مؤشرات الإنجاز ورفع التقرير."
                                ),
                                url=f"/surveillance/manage/{decision.pk}/",
                                extra_recipients=decision.application.applicant_user
                            )
                            if inst_notifs:
                                stats['created'] += len(inst_notifs)
                                ScheduledReminderLog.record_sent(
                                    reminder_key, 'AccreditationDecision', decision.pk,
                                    details=f"Annual report Y{year_num} 30-day reminder"
                                )
                            else:
                                logger.warning(f"No notifications created for {reminder_key} on decision {decision.pk}. Retrying on next run.")
                        else:
                            stats['created'] += 1
                    else:
                        stats['skipped'] += 1

                # 2. 7 Days Reminder
                elif days_until <= 7 and days_until >= 0:
                    reminder_key = f"ANNUAL_REPORT_Y{year_num}_7D"
                    if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationDecision', decision.pk):
                        if not dry_run:
                            inst_notifs = notify_institution(
                                institution=institution,
                                title=f"تذكير عاجل: متبقي 7 أيام على موعد التقرير السنوي (العام {year_num})",
                                message=(
                                    f"تذكير عاجل: متبقي ({days_until}) أيام فقط على الموعد النهائي لتسليم "
                                    f"تقرير المتابعة السنوي رقم ({year_num}) المحدد بتاريخ ({anniversary_date}). "
                                    f"يرجى رفع التقرير تفادياً لتعليق السريان."
                                ),
                                url=f"/surveillance/manage/{decision.pk}/",
                                extra_recipients=decision.application.applicant_user
                            )
                            if inst_notifs:
                                stats['created'] += len(inst_notifs)
                                ScheduledReminderLog.record_sent(
                                    reminder_key, 'AccreditationDecision', decision.pk,
                                    details=f"Annual report Y{year_num} 7-day reminder"
                                )
                            else:
                                logger.warning(f"No notifications created for {reminder_key} on decision {decision.pk}. Retrying on next run.")
                        else:
                            stats['created'] += 1
                    else:
                        stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking annual report for decision {decision.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 65: Approaching Submission Deadline (Right-to-Reply)
# =============================================================================
def check_approaching_report_deadlines(reference_date=None, dry_run=False):
    """
    Scenario 65: Sends appropriate reminders before relevant reporting deadlines,
    such as institution right-to-reply response_deadline on draft evaluation reports.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    reports = ExternalReviewReport.objects.select_related(
        'application__institution',
        'application__applicant_user'
    ).filter(
        response_deadline__isnull=False,
        institution_reply_date__isnull=True,
        response_deadline__gte=today
    )

    for report in reports:
        try:
            days_until = (report.response_deadline - today).days
            if days_until <= 5:
                reminder_key = 'REPORT_REPLY_DEADLINE_5D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'ExternalReviewReport', report.pk):
                    if not dry_run:
                        app = report.application
                        inst_notifs = notify_institution(
                            institution=app.institution,
                            title=f"اقتراب الموعد النهائي لحق الرد: {app.application_number}",
                            message=(
                                f"نحيطكم باقتراب انقضاء المهلة المحددة لحق الرد حول مسودة تقرير المراجعة "
                                f"الخارجية للطلب ({app.application_number})، والمحددة بتاريخ "
                                f"({report.response_deadline}) (متبقي {days_until} أيام). "
                                f"يرجى رفع رد وتوضيحات المؤسسة قبل إغلاق الفترة."
                            ),
                            url=f"/accreditation/applications/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(
                            reminder_key, 'ExternalReviewReport', report.pk,
                            details=f"Right-to-reply 5-day deadline reminder for report {report.pk}"
                        )
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking approaching deadline for report {report.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 66: Certificate Expiry Warning
# =============================================================================
def check_certificate_expiry_warnings(reference_date=None, dry_run=False):
    """
    Scenario 66: Notifies authorized institution officers before certificate expiration:
    - 180 days (6 months)
    - 90 days (3 months)
    - 30 days (1 month)
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    certificates = AccreditationCertificate.objects.select_related(
        'decision__application__institution',
        'decision__application__applicant_user',
    ).filter(
        status=AccreditationCertificate.CertificateStatus.ACTIVE,
        is_revoked=False,
        decision__expiry_date__isnull=False,
        decision__expiry_date__gte=today
    )

    for cert in certificates:
        try:
            expiry_date = cert.decision.expiry_date
            days_until = (expiry_date - today).days
            institution = cert.decision.application.institution
            app = cert.decision.application

            # 1. 180 Days (6 Months)
            if days_until <= 180 and days_until > 90:
                reminder_key = 'CERT_EXPIRY_180D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationCertificate', cert.pk):
                    if not dry_run:
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تنبيه: اقتراب انتهاء سريان وثيقة الاعتماد (متبقي 6 أشهر)",
                            message=(
                                f"نحيطكم علماً بأن وثيقة الاعتماد الأكاديمي رقم ({cert.national_registry_code}) "
                                f"ستنتهي بتاريخ ({expiry_date}) (متبقي {days_until} يوماً). "
                                f"يرجى البدء في تجهيز ومراجعة طلب تجديد الاعتماد وفق اللوائح."
                            ),
                            url=f"/accreditation/applications/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'AccreditationCertificate', cert.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

            # 2. 90 Days (3 Months)
            elif days_until <= 90 and days_until > 30:
                reminder_key = 'CERT_EXPIRY_90D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationCertificate', cert.pk):
                    if not dry_run:
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تنبيه هام: متبقي 3 أشهر على انتهاء وثيقة الاعتماد",
                            message=(
                                f"تنبيه عاجل: متبقي ({days_until}) يوماً على انتهاء سريان وثيقة الاعتماد "
                                f"رقم ({cert.national_registry_code}) بتاريخ ({expiry_date}). "
                                f"يرجى تقديم طلب التجديد للأمانة العامة."
                            ),
                            url=f"/accreditation/applications/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'AccreditationCertificate', cert.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

            # 3. 30 Days (1 Month)
            elif days_until <= 30 and days_until >= 0:
                reminder_key = 'CERT_EXPIRY_30D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationCertificate', cert.pk):
                    if not dry_run:
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تحذير نهائي: متبقي 30 يوماً على انتهاء صلاحية وثيقة الاعتماد",
                            message=(
                                f"تحذير نهائي: تنتهي وثيقة الاعتماد رقم ({cert.national_registry_code}) "
                                f"بتاريخ ({expiry_date}). سيتم نقل القيد تلقائياً إلى حالة منتهية عند حلول الأجل."
                            ),
                            url=f"/accreditation/applications/{app.pk}/",
                            extra_recipients=app.applicant_user
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'AccreditationCertificate', cert.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking certificate {cert.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 67: Follow-up Report Reminder
# =============================================================================
def check_followup_report_reminders(reference_date=None, dry_run=False):
    """
    Scenario 67: Reminds institutions about pending follow-up reports:
    1. Surveillance visit approaching within 7 days.
    2. CIP in NEEDS_REVISION state.
    3. Annual report in NEEDS_CORRECTION state.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    # 1. Assigned Surveillance Visits
    visits = SurveillanceVisit.objects.select_related(
        'decision__application__institution',
        'decision__application__applicant_user'
    ).filter(
        status=SurveillanceVisit.VisitStatus.ASSIGNED,
        visit_date__gte=today
    )
    for visit in visits:
        try:
            days_until = (visit.visit_date - today).days
            if days_until <= 7:
                reminder_key = 'SURVEILLANCE_VISIT_7D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'SurveillanceVisit', visit.pk):
                    if not dry_run:
                        institution = visit.decision.application.institution
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تذكير بالزيارة الاستطلاعية والمتابعة: {visit.get_visit_type_display()}",
                            message=(
                                f"تذكير: تقرر تنفيذ زيارة استطلاعية تحققية لمؤسستكم بتاريخ ({visit.visit_date}) "
                                f"(متبقي {days_until} أيام) في إطار متابعة قرار الاعتماد ({visit.decision.decree_number}). "
                                f"يرجى استكمال الوثائق الثبوتية وجداول المقابلات."
                            ),
                            url=f"/surveillance/manage/{visit.decision.pk}/",
                            extra_recipients=visit.decision.application.applicant_user
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'SurveillanceVisit', visit.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error checking surveillance visit {visit.pk}: {e}")
            stats['errors'] += 1

    # 2. CIP in NEEDS_REVISION (weekly reminder)
    rev_plans = ContinuousImprovementPlan.objects.select_related(
        'decision__application__institution',
        'submitted_by'
    ).filter(
        status=ContinuousImprovementPlan.PlanStatus.NEEDS_REVISION
    )
    for plan in rev_plans:
        try:
            reminder_key = 'CIP_NEEDS_REVISION_REMINDER'
            if not ScheduledReminderLog.is_already_sent(reminder_key, 'ContinuousImprovementPlan', plan.pk, within_days=14):
                if not dry_run:
                    institution = plan.decision.application.institution
                    inst_notifs = notify_institution(
                        institution=institution,
                        title="تذكير: إعادة تسليم خطة التحسين المستمر المعدلة",
                        message=(
                            f"نذكركم بضرورة سرعة استكمال التعديلات المطلوبة على خطة التحسين المستمر "
                            f"({plan.plan_title}) وإعادة رفعها إلى أمانة المجلس للاعتماد."
                        ),
                        url=f"/surveillance/manage/{plan.decision.pk}/",
                        extra_recipients=plan.submitted_by
                    )
                    if inst_notifs:
                        stats['created'] += len(inst_notifs)
                        occurrence_key = f"{reminder_key}:{today.isoformat()}"
                        ScheduledReminderLog.record_sent(occurrence_key, 'ContinuousImprovementPlan', plan.pk)
                    else:
                        logger.warning(f"No notifications created for {reminder_key} on plan {plan.pk}. Retrying on next run.")
                else:
                    stats['created'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error checking CIP revision for plan {plan.pk}: {e}")
            stats['errors'] += 1

    # 3. Annual Report in NEEDS_CORRECTION
    corr_reports = AnnualMonitoringReport.objects.select_related(
        'decision__application__institution',
        'submitted_by'
    ).filter(
        review_status=AnnualMonitoringReport.ReviewStatus.NEEDS_CORRECTION
    )
    for report in corr_reports:
        try:
            reminder_key = 'ANNUAL_REPORT_CORRECTION_REMINDER'
            if not ScheduledReminderLog.is_already_sent(reminder_key, 'AnnualMonitoringReport', report.pk, within_days=14):
                if not dry_run:
                    institution = report.decision.application.institution
                    inst_notifs = notify_institution(
                        institution=institution,
                        title=f"تذكير: تصحيح واستكمال تقرير المتابعة السنوي (العام {report.year_number})",
                        message=(
                            f"نذكركم بضرورة إعادة تسليم تقرير المتابعة السنوي ({report.reporting_period}) "
                            f"بعد استيفاء الملاحظات الفنية الموجهة من أمانة المجلس."
                        ),
                        url=f"/surveillance/manage/{report.decision.pk}/",
                        extra_recipients=report.submitted_by
                    )
                    if inst_notifs:
                        stats['created'] += len(inst_notifs)
                        occurrence_key = f"{reminder_key}:{today.isoformat()}"
                        ScheduledReminderLog.record_sent(occurrence_key, 'AnnualMonitoringReport', report.pk)
                    else:
                        logger.warning(f"No notifications created for {reminder_key} on report {report.pk}. Retrying on next run.")
                else:
                    stats['created'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error checking annual report correction {report.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 68: Overdue Reporting Notification
# =============================================================================
def check_overdue_reporting(reference_date=None, dry_run=False):
    """
    Scenario 68: Notifies responsible institution officers and authorized Secretariat
    recipients when a reporting deadline passes without submission.
    Frequency: Dispatched at most once every 7 days while overdue.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}
    secretariat_users = _get_secretariat_users()

    # 1. Overdue Right to Reply (ExternalReviewReport)
    overdue_replies = ExternalReviewReport.objects.select_related(
        'application__institution',
        'application__applicant_user'
    ).filter(
        response_deadline__isnull=False,
        institution_reply_date__isnull=True,
        response_deadline__lt=today
    )
    for report in overdue_replies:
        try:
            reminder_key = 'OVERDUE_REPLY_DEADLINE'
            if not ScheduledReminderLog.is_already_sent(reminder_key, 'ExternalReviewReport', report.pk, within_days=7):
                if not dry_run:
                    app = report.application
                    days_overdue = (today - report.response_deadline).days

                    # Notify institution
                    inst_notifs = notify_institution(
                        institution=app.institution,
                        title=f"تنبيه فوات المهلة: حق الرد متأخر: {app.application_number}",
                        message=(
                            f"نحيطكم علماً بانقضاء الموعد النهائي المحدد لحق الرد حول تقرير المراجعة "
                            f"الخارجية للطلب ({app.application_number}) منذ ({days_overdue}) يوماً "
                            f"دون استلام رد رسمي من مؤسستكم. سيتم رفع التقرير للمجلس بالصيغة الراهنة."
                        ),
                        url=f"/accreditation/applications/{app.pk}/",
                        extra_recipients=app.applicant_user
                    )
                    stats['created'] += len(inst_notifs)

                    # Notify Secretariat
                    for sec in secretariat_users:
                        n = send_notification(
                            user=sec,
                            title=f"فوات موعد حق الرد لمؤسسة ({app.institution.name})",
                            message=(
                                f"انقضت المهلة النظامية لحق الرد للطلب ({app.application_number}) "
                                f"الخاص بـ ({app.institution.name}) بتاريخ ({report.response_deadline}). "
                                f"يمكن للأمانة الآن إحالة التقرير النهائي للاعتماد."
                            ),
                            url=f"/accreditation/applications/{app.pk}/"
                        )
                        if n:
                            stats['created'] += 1

                    occurrence_key = f"{reminder_key}:{today.isoformat()}"
                    ScheduledReminderLog.record_sent(occurrence_key, 'ExternalReviewReport', report.pk)
                else:
                    stats['created'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error checking overdue reply for report {report.pk}: {e}")
            stats['errors'] += 1

    # 2. Overdue Annual Report
    decisions = AccreditationDecision.objects.select_related(
        'application__institution',
        'application__applicant_user'
    ).filter(
        decision_type__in=[
            AccreditationDecision.DecisionType.FULL_ACCREDITATION,
            AccreditationDecision.DecisionType.CONDITIONAL_ACCREDITATION,
        ],
        decision_date__isnull=False
    )
    for decision in decisions:
        try:
            validity = decision.validity_years or 5
            for year_num in range(1, validity + 1):
                due_date = calculate_calendar_anniversary(decision.decision_date, year_num)
                if today > due_date:
                    has_submitted = AnnualMonitoringReport.objects.filter(
                        decision=decision,
                        year_number=year_num
                    ).exclude(
                        review_status=AnnualMonitoringReport.ReviewStatus.DRAFT
                    ).exists()

                    if not has_submitted:
                        reminder_key = f"OVERDUE_ANNUAL_REPORT_Y{year_num}"
                        if not ScheduledReminderLog.is_already_sent(reminder_key, 'AccreditationDecision', decision.pk, within_days=7):
                            if not dry_run:
                                inst = decision.application.institution
                                days_past = (today - due_date).days

                                # Notify Institution
                                inst_notifs = notify_institution(
                                    institution=inst,
                                    title=f"إشعار تخلف عن تسليم تقرير المتابعة السنوي (العام {year_num})",
                                    message=(
                                        f"نحيطكم علماً بفوات الموعد النظامي لتسليم تقرير المتابعة السنوي "
                                        f"رقم ({year_num}) لقرار الاعتماد ({decision.decree_number}) منذ "
                                        f"({days_past}) يوماً. نأمل سرعة الرفع لتجنب تعليق الاعتماد."
                                    ),
                                    url=f"/surveillance/manage/{decision.pk}/",
                                    extra_recipients=decision.application.applicant_user
                                )
                                stats['created'] += len(inst_notifs)

                                # Notify Secretariat
                                for sec in secretariat_users:
                                    n = send_notification(
                                        user=sec,
                                        title=f"تأخر تقرير سنوي: ({inst.name}) - العام ({year_num})",
                                        message=(
                                            f"تخلفت مؤسسة ({inst.name}) عن رفع تقرير المتابعة السنوي رقم ({year_num}) "
                                            f"المستحق منذ ({due_date}) لقرار الاعتماد ({decision.decree_number})."
                                        ),
                                        url=f"/surveillance/manage/{decision.pk}/"
                                    )
                                    if n:
                                        stats['created'] += 1

                                occurrence_key = f"{reminder_key}:{today.isoformat()}"
                                ScheduledReminderLog.record_sent(occurrence_key, 'AccreditationDecision', decision.pk)
                            else:
                                stats['created'] += 1
                        else:
                            stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error checking overdue annual report for decision {decision.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 76: Task Deadline Reminder
# =============================================================================
def check_task_deadline_reminders(reference_date=None, dry_run=False):
    """
    Scenario 76: Notifies assigned users and institutions before task deadlines:
    - 7 days before due date
    - 2 days before due date
    Applies to CorrectiveActionItem tasks in progress.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}

    tasks = CorrectiveActionItem.objects.select_related(
        'plan__decision__application__institution',
        'plan__submitted_by'
    ).filter(
        status__in=[
            CorrectiveActionItem.ActionStatus.NOT_STARTED,
            CorrectiveActionItem.ActionStatus.IN_PROGRESS,
        ],
        due_date__gte=today
    )

    for task in tasks:
        try:
            days_until = (task.due_date - today).days
            institution = task.plan.decision.application.institution
            decision_pk = task.plan.decision.pk

            # 1. 7 Days Reminder
            if days_until <= 7 and days_until > 2:
                reminder_key = 'TASK_DEADLINE_7D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'CorrectiveActionItem', task.pk):
                    if not dry_run:
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تذكير باقتراب موعد إنجاز بند تصحيحي: {task.deficiency_title[:45]}",
                            message=(
                                f"تذكير: يستحق موعد إنجاز بند الإجراء التصحيحي ({task.deficiency_title}) "
                                f"بتاريخ ({task.due_date}) (متبقي {days_until} أيام). "
                                f"المسؤول عن التنفيذ: ({task.responsible_person}). يرجى استكمال المعالجة."
                            ),
                            url=f"/surveillance/manage/{decision_pk}/",
                            extra_recipients=task.plan.submitted_by
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'CorrectiveActionItem', task.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

            # 2. 2 Days Reminder
            elif days_until <= 2 and days_until >= 0:
                reminder_key = 'TASK_DEADLINE_2D'
                if not ScheduledReminderLog.is_already_sent(reminder_key, 'CorrectiveActionItem', task.pk):
                    if not dry_run:
                        inst_notifs = notify_institution(
                            institution=institution,
                            title=f"تذكير عاجل: متبقي يومان على موعد إنجاز بند تصحيحي: {task.deficiency_title[:40]}",
                            message=(
                                f"تنبيه عاجل: يحل موعد استحقاق الإجراء التصحيحي ({task.deficiency_title}) "
                                f"بتاريخ ({task.due_date}). يرجى رفع الشواهد والوثائق الثبوتية."
                            ),
                            url=f"/surveillance/manage/{decision_pk}/",
                            extra_recipients=task.plan.submitted_by
                        )
                        stats['created'] += len(inst_notifs)
                        ScheduledReminderLog.record_sent(reminder_key, 'CorrectiveActionItem', task.pk)
                    else:
                        stats['created'] += 1
                else:
                    stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking task deadline for item {task.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# SCENARIO 77: Overdue Task Notification
# =============================================================================
def check_overdue_tasks(reference_date=None, dry_run=False):
    """
    Scenario 77: Notifies responsible users and authorized supervisors when tasks become overdue.
    Updates task status to OVERDUE if overdue.
    Frequency: Dispatched at most once every 7 days while overdue.
    """
    today = reference_date or timezone.now().date()
    stats = {'created': 0, 'skipped': 0, 'errors': 0}
    secretariat_users = _get_secretariat_users()

    tasks = CorrectiveActionItem.objects.select_related(
        'plan__decision__application__institution',
        'plan__submitted_by'
    ).filter(
        due_date__lt=today
    ).exclude(
        status__in=[
            CorrectiveActionItem.ActionStatus.VERIFIED_AND_ACCEPTED,
            CorrectiveActionItem.ActionStatus.SUBMITTED_FOR_REVIEW
        ]
    )

    for task in tasks:
        try:
            # Update status to OVERDUE if not already set
            if not dry_run and task.status != CorrectiveActionItem.ActionStatus.OVERDUE:
                task.status = CorrectiveActionItem.ActionStatus.OVERDUE
                task.save(update_fields=['status', 'updated_at'])

            reminder_key = 'TASK_OVERDUE'
            if not ScheduledReminderLog.is_already_sent(reminder_key, 'CorrectiveActionItem', task.pk, within_days=7):
                if not dry_run:
                    institution = task.plan.decision.application.institution
                    decision_pk = task.plan.decision.pk
                    days_overdue = (today - task.due_date).days

                    # 1. Notify institution
                    inst_notifs = notify_institution(
                        institution=institution,
                        title=f"إشعار تأخر إنجاز بند تصحيحي: {task.deficiency_title[:45]}",
                        message=(
                            f"فات الموعد المحدد لإنجاز الإجراء التصحيحي ({task.deficiency_title}) "
                            f"المقرر بتاريخ ({task.due_date}) منذ ({days_overdue}) يوماً. "
                            f"المسؤول المباشر: ({task.responsible_person}). يرجى سرعة رفع الشواهد."
                        ),
                        url=f"/surveillance/manage/{decision_pk}/",
                        extra_recipients=task.plan.submitted_by
                    )
                    stats['created'] += len(inst_notifs)

                    # 2. Notify Secretariat supervisors
                    for sec in secretariat_users:
                        n = send_notification(
                            user=sec,
                            title=f"بند تصحيحي متأخر: ({institution.name})",
                            message=(
                                f"تأخر إنجاز البند التصحيحي ({task.deficiency_title}) الخاص بمؤسسة "
                                f"({institution.name}) المستحق منذ ({task.due_date})."
                            ),
                            url=f"/surveillance/manage/{decision_pk}/"
                        )
                        if n:
                            stats['created'] += 1

                    occurrence_key = f"{reminder_key}:{today.isoformat()}"
                    ScheduledReminderLog.record_sent(occurrence_key, 'CorrectiveActionItem', task.pk)
                else:
                    stats['created'] += 1
            else:
                stats['skipped'] += 1

        except Exception as e:
            logger.error(f"Error checking overdue task {task.pk}: {e}")
            stats['errors'] += 1

    return stats


# =============================================================================
# MASTER COORDINATOR
# =============================================================================
def run_all_scheduled_reminders(reference_date=None, dry_run=False, scenario_filter=None):
    """
    Executes all scheduled deadline and notification checks.
    Returns structured results dictionary.
    Handles individual scenario failures gracefully so one failure does not halt the entire batch.
    """
    today = reference_date or timezone.now().date()
    results = {
        'reference_date': str(today),
        'dry_run': dry_run,
        'scenarios': {},
        'total_created': 0,
        'total_skipped': 0,
        'total_errors': 0,
    }

    scenarios = [
        ('29', 'Site Visit Reminders', check_site_visit_reminders),
        ('52', 'Continuous Improvement Plan Period Opened', check_cip_period_opened),
        ('59', 'Annual Report Deadline Reminders', check_annual_report_reminders),
        ('65', 'Approaching Report Submission Deadlines', check_approaching_report_deadlines),
        ('66', 'Certificate Expiry Warnings', check_certificate_expiry_warnings),
        ('67', 'Follow-up Report Reminders', check_followup_report_reminders),
        ('68', 'Overdue Reporting Notifications', check_overdue_reporting),
        ('76', 'Task Deadline Reminders', check_task_deadline_reminders),
        ('77', 'Overdue Task Notifications', check_overdue_tasks),
    ]

    for code, name, func in scenarios:
        if scenario_filter and str(scenario_filter) != code:
            continue
        try:
            res = func(reference_date=today, dry_run=dry_run)
            results['scenarios'][code] = {
                'name': name,
                'created': res.get('created', 0),
                'skipped': res.get('skipped', 0),
                'errors': res.get('errors', 0),
            }
            results['total_created'] += res.get('created', 0)
            results['total_skipped'] += res.get('skipped', 0)
            results['total_errors'] += res.get('errors', 0)
        except Exception as e:
            logger.error(f"Fatal failure in scenario {code} ({name}): {e}", exc_info=True)
            results['scenarios'][code] = {
                'name': name,
                'created': 0,
                'skipped': 0,
                'errors': 1,
                'error_detail': str(e)
            }
            results['total_errors'] += 1

    return results
