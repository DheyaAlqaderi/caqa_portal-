from django.db import models
from apps.accounts.models import User, send_notification, notify_institution


def get_panel_reviewers(application):
    """
    Returns the set of active, approved external reviewers assigned to this application's panel.
    Strictly isolated: does not include reviewers from other applications or panels.
    """
    reviewers = set()
    if hasattr(application, 'review_team') and application.review_team:
        team = application.review_team
        if team.chairperson and team.chairperson.is_active and team.chairperson.is_approved:
            reviewers.add(team.chairperson)
        for member in team.members.select_related('user').all():
            if member.user and member.user.is_active and member.user.is_approved:
                reviewers.add(member.user)
    return reviewers


def notify_reviewer_team_assigned(review_team):
    """
    Scenario 22: Notify authorized Secretariat users when a review team is formally assigned.
    Also dispatches individual invitations to each assigned reviewer (Scenario 23).
    """
    if not review_team or not review_team.application:
        return []

    application = review_team.application
    decree = review_team.decree_number
    chair_name = review_team.chairperson.get_full_name() if review_team.chairperson else "رئيس الفريق"

    created_notifs = []

    # 1. Notify Secretariat users & DG_EVALUATION
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"اعتماد تشكيل فريق التقييم الخارجي: {application.application_number}",
            message=(
                f"تم اعتماد قرار تشكيل فريق التقييم الخارجي رقم ({decree}) "
                f"للطلب ({application.application_number}) برئاسة ({chair_name})."
            ),
            url=f"/accreditation/{application.pk}/review-team/"
        )
        if n:
            created_notifs.append(n)

    # 2. Notify assigned reviewers individually (Scenario 23 & Delivery of Self-Study Report)
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        ssr_notif = notify_self_study_delivered_to_reviewer(rev, application)
        if ssr_notif:
            created_notifs.append(ssr_notif)
        inv_notif = notify_reviewer_invitation(rev, application, decree_number=decree)
        if inv_notif:
            created_notifs.append(inv_notif)

        # Dispatch formal SMS alert to nominated external peer reviewer
        try:
            from apps.accounts.sms_service import notify_reviewer_assignment_sms
            notify_reviewer_assignment_sms(rev, application)
        except Exception:
            pass

    return created_notifs


def notify_self_study_delivered_to_reviewer(reviewer, application):
    """
    Notify assigned external reviewer that the institution's self-study report
    and quality evidences have been officially delivered by the Secretariat for external review.
    """
    if not reviewer or not reviewer.is_active or not reviewer.is_approved:
        return None
    return send_notification(
        user=reviewer,
        title=f"إيصال ملف التقييم الذاتي والشواهد: {application.application_number}",
        message=(
            f"أحالت أمانة المجلس ملف دراسة التقييم الذاتي والشواهد لمؤسسة "
            f"({application.institution.name}) الخاصة بالطلب ({application.application_number}) "
            f"إلى عهدتكم لمباشرة المراجعة والمطابقة والتقييم الخارجي."
        ),
        url=f"/accreditation/{application.pk}/self-study/report/"
    )


def notify_reviewer_invitation(reviewer, application, decree_number=""):
    """
    Scenario 23: Notify an assigned reviewer individually with the assignment details
    and required conflict-of-interest declaration deadline.
    """
    if not reviewer or not reviewer.is_active or not reviewer.is_approved:
        return None

    dec_text = f" بموجب القرار الإداري رقم ({decree_number})" if decree_number else ""
    return send_notification(
        user=reviewer,
        title=f"تكليف بمهمة تحكيم خارجي: {application.application_number}",
        message=(
            f"يسر مجلس الاعتماد الأكاديمي إحاطتكم بصدور قرار تكليفكم{dec_text} "
            f"ضمن فريق المراجعة والتقييم الخارجي لطلب الاعتماد ({application.application_number}) "
            f"الخاص بمؤسسة ({application.institution.name}). "
            f"يرجى مراجعة تفاصيل التكليف والتوقيع على إقرار النزاهة وعدم تعارض المصالح."
        ),
        url=f"/accreditation/{application.pk}/coi/"
    )


def notify_reviewer_accepted(reviewer, application):
    """
    Scenario 24: Notify authorized Secretariat recipients when a reviewer accepts an assignment
    and signs the clean conflict-of-interest declaration.
    """
    if not application or not reviewer:
        return []

    rev_name = reviewer.get_full_name() or reviewer.username
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    created_notifs = []
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"قبول تكليف التحكيم الخارجي: {application.application_number}",
            message=(
                f"أكد الخبير المحكّم ({rev_name}) قبول مهمة التقييم الخارجي لطلب الاعتماد "
                f"({application.application_number}) ووقع إقرار خلو تعارض المصالح بنجاح."
            ),
            url=f"/accreditation/{application.pk}/review-team/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_reviewer_declined(reviewer, application, reason=""):
    """
    Scenario 25: Notify authorized Secretariat recipients when a reviewer declines an assignment.
    """
    if not application or not reviewer:
        return []

    rev_name = reviewer.get_full_name() or reviewer.username
    clean_reason = f" السبب: {reason.strip()}" if reason and reason.strip() else ""

    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    created_notifs = []
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"اعتذار محكّم عن التكليف: {application.application_number}",
            message=(
                f"اعتذر الخبير المحكّم ({rev_name}) عن المشاركة في تحكيم طلب الاعتماد "
                f"({application.application_number}).{clean_reason} "
                f"يرجى اتخاذ الإجراء اللازم لتكليف محكّم بديل في اللجنة."
            ),
            url=f"/accreditation/{application.pk}/review-team/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_conflict_of_interest_declared(reviewer, application, has_conflict=True):
    """
    Scenario 26: Notify authorized Secretariat recipients when a reviewer submits
    a conflict-of-interest declaration.
    Confidential: Conflict details are strictly restricted to Secretariat and NEVER exposed to institutions.
    """
    if not application or not reviewer:
        return []

    rev_name = reviewer.get_full_name() or reviewer.username
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )

    created_notifs = []
    for sec in secretariat_users:
        if has_conflict:
            title = f"إفادة بوجود تعارض مصالح: {application.application_number}"
            message = (
                f"أفاد المحكّم ({rev_name}) بوجود تعارض مصالح محتمل حيال طلب الاعتماد "
                f"({application.application_number}) لمؤسسة ({application.institution.name}). "
                f"يتطلب الإجراء استبدال المحكّم لضمان النزاهة والحياد."
            )
        else:
            title = f"توقيع إقرار النزاهة: {application.application_number}"
            message = (
                f"وقع المحكّم ({rev_name}) إقرار خلو تعارض المصالح لطلب الاعتماد "
                f"({application.application_number})."
            )

        n = send_notification(
            user=sec,
            title=title,
            message=message,
            url=f"/accreditation/{application.pk}/review-team/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_site_visit_plan_published(visit):
    """
    Scenario 27: Notify the institution's authorized officers and assigned reviewers
    when the site visit plan is formally approved and published.
    """
    if not visit or not visit.application:
        return []

    application = visit.application
    created_notifs = []

    # 1. Notify institution officers (strict tenant isolation)
    inst_notifs = notify_institution(
        institution=application.institution,
        title=f"اعتماد خطة الزيارة الميدانية: {application.application_number}",
        message=(
            f"تم اعتماد وتثبيت البرنامج الزمني للزيارة الميدانية لطلب الاعتماد "
            f"({application.application_number}) للفترة من ({visit.start_date}) "
            f"إلى ({visit.end_date}) في مقر ({visit.visit_location}). "
            f"يرجى الاطلاع على الجدول الزمني وتنسيق الترتيبات اللوجستية المطلوبة."
        ),
        url=f"/site-visits/app/{application.pk}/",
        extra_recipients=application.applicant_user
    )
    created_notifs.extend(inst_notifs)

    # 2. Notify assigned reviewers
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        n = send_notification(
            user=rev,
            title=f"برنامج الزيارة الميدانية المعتمد: {application.application_number}",
            message=(
                f"تم اعتماد جدول وبرنامج الزيارة الميدانية لمؤسسة ({application.institution.name}) "
                f"للفترة من ({visit.start_date}) إلى ({visit.end_date}). "
                f"يرجى مراجعة محاور الزيارة ومواعيد المقابلات والمعاينات."
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_site_visit_schedule_changed(visit, old_dates=""):
    """
    Scenario 28: Notify all affected institution officers and assigned reviewers
    when an approved visit schedule changes.
    """
    if not visit or not visit.application:
        return []

    application = visit.application
    created_notifs = []
    old_text = f" (المواعيد السابقة: {old_dates})" if old_dates else ""

    # 1. Notify institution officers
    inst_notifs = notify_institution(
        institution=application.institution,
        title=f"تعديل مواعيد الزيارة الميدانية: {application.application_number}",
        message=(
            f"نحيطكم علماً بتحديث وتعديل مواعيد الزيارة الميدانية لطلب الاعتماد "
            f"({application.application_number}){old_text} لتصبح رسمياً من "
            f"({visit.start_date}) إلى ({visit.end_date})."
        ),
        url=f"/site-visits/app/{application.pk}/",
        extra_recipients=application.applicant_user
    )
    created_notifs.extend(inst_notifs)

    # 2. Notify assigned reviewers
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        n = send_notification(
            user=rev,
            title=f"تحديث مواعيد الزيارة الميدانية: {application.application_number}",
            message=(
                f"تم تعديل المواعيد المحددة للزيارة الميدانية لمؤسسة ({application.institution.name}){old_text} "
                f"لتصبح من ({visit.start_date}) إلى ({visit.end_date})."
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_site_visit_reminder(visit):
    """
    Scenario 29: Site visit reminder helper.
    Prepared for integration with scheduled tasks in Phase 3.
    """
    if not visit or not visit.application:
        return []

    application = visit.application
    created_notifs = []

    # 1. Remind institution officers
    inst_notifs = notify_institution(
        institution=application.institution,
        title=f"تذكير باقتراب موعد الزيارة الميدانية: {application.application_number}",
        message=(
            f"تذكير: تنطلق فعاليات الزيارة الميدانية لطلب الاعتماد ({application.application_number}) "
            f"بتاريخ ({visit.start_date}). يرجى استكمال كافة التجهيزات والمنسق اللوجستي."
        ),
        url=f"/site-visits/app/{application.pk}/",
        extra_recipients=application.applicant_user
    )
    created_notifs.extend(inst_notifs)

    # 2. Remind assigned reviewers
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        n = send_notification(
            user=rev,
            title=f"تذكير بموعد الزيارة الميدانية: {application.application_number}",
            message=(
                f"تذكير: تبدأ الزيارة الميدانية لتقييم مؤسسة ({application.institution.name}) "
                f"بتاريخ ({visit.start_date})."
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_site_visit_cancelled(visit, reason=""):
    """
    Scenario 30: Notify all affected authorized participants when a visit is formally cancelled or postponed.
    """
    if not visit or not visit.application:
        return []

    application = visit.application
    clean_reason = f" السبب: {reason.strip()}" if reason and reason.strip() else ""
    created_notifs = []

    # 1. Notify institution officers
    inst_notifs = notify_institution(
        institution=application.institution,
        title=f"تأجيل / إلغاء الزيارة الميدانية: {application.application_number}",
        message=(
            f"نحيطكم علماً بأنه تقرر تأجيل الزيارة الميدانية المقررة لطلب الاعتماد "
            f"({application.application_number}) حتى إشعار آخر.{clean_reason}"
        ),
        url=f"/site-visits/app/{application.pk}/",
        extra_recipients=application.applicant_user
    )
    created_notifs.extend(inst_notifs)

    # 2. Notify assigned reviewers
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        n = send_notification(
            user=rev,
            title=f"إشعار تأجيل الزيارة الميدانية: {application.application_number}",
            message=(
                f"نحيطكم علماً بتأجيل الزيارة الميدانية المقررة لتقييم مؤسسة ({application.institution.name}).{clean_reason}"
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    # 3. Notify Secretariat & DG_EVALUATION
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"تسجيل تأجيل الزيارة الميدانية: {application.application_number}",
            message=(
                f"تم تأجيل الزيارة الميدانية لطلب الاعتماد ({application.application_number}) "
                f"الخاص بمؤسسة ({application.institution.name}).{clean_reason}"
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_site_visit_completed(visit):
    """
    Scenario 31: Notify authorized Secretariat recipients and relevant reviewers
    when the site visit is formally completed.
    """
    if not visit or not visit.application:
        return []

    application = visit.application
    created_notifs = []

    # 1. Notify Secretariat & DG_EVALUATION
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"اختتام الزيارة الميدانية رسمياً: {application.application_number}",
            message=(
                f"أتم فريق التقييم الخارجي فعاليات الزيارة الميدانية لطلب الاعتماد "
                f"({application.application_number}) الخاص بمؤسسة ({application.institution.name}) "
                f"وتم توثيق محضر اللقاء الختامي بنجاح."
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    # 2. Notify assigned reviewers
    reviewers = get_panel_reviewers(application)
    for rev in reviewers:
        n = send_notification(
            user=rev,
            title=f"اكتمال الزيارة الميدانية: {application.application_number}",
            message=(
                f"تم بنجاح توثيق اختتام الزيارة الميدانية لمؤسسة ({application.institution.name}). "
                f"يرجى البدء في إعداد مسودة تقرير المراجعة الخارجية الموحد."
            ),
            url=f"/site-visits/app/{application.pk}/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs


def notify_assignment_or_visit_requires_correction(application, target_reviewer=None, reason=""):
    """
    Scenario 32: Notify responsible Secretariat recipients and affected reviewers
    when an assignment, COI situation, or visit schedule requires correction.
    """
    if not application:
        return []

    clean_reason = f" التفاصيل: {reason.strip()}" if reason and reason.strip() else ""
    created_notifs = []

    # 1. Notify Secretariat & DG_EVALUATION
    secretariat_users = User.objects.filter(
        role__in=[
            User.Roles.DG_EVALUATION,
            User.Roles.COUNCIL_SECRETARY_GENERAL,
            User.Roles.DG_ACCREDITATION,
            User.Roles.COUNCIL_SECRETARY,
            User.Roles.ADMIN
        ],
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED
    )
    for sec in secretariat_users:
        n = send_notification(
            user=sec,
            title=f"طلب تصحيح في ملف التقييم / الزيارة: {application.application_number}",
            message=(
                f"يتطلب ملف تشكيل اللجنة أو برنامج الزيارة للطلب ({application.application_number}) "
                f"إجراء تصحيح واستدراك إداري.{clean_reason}"
            ),
            url=f"/accreditation/{application.pk}/review-team/"
        )
        if n:
            created_notifs.append(n)

    # 2. Notify affected reviewer if targeted
    if target_reviewer and target_reviewer.is_active and target_reviewer.is_approved:
        n = send_notification(
            user=target_reviewer,
            title=f"توجيه إداري بشأن مهمة التقييم: {application.application_number}",
            message=(
                f"تطلب أمانة المجلس مراجعة واستدراك بيانات في مهمة التقييم للطلب "
                f"({application.application_number}).{clean_reason}"
            ),
            url=f"/accreditation/{application.pk}/coi/"
        )
        if n:
            created_notifs.append(n)

    return created_notifs
