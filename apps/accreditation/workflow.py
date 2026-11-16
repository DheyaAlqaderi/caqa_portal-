"""
CAQA Accreditation Workflow Engine
Manages state transitions, role authorizations, validation guards, and historical auditing.
"""
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.accounts.models import User, record_audit_log
from .models import (
    AccreditationApplication,
    StageChoices,
    ApplicationStatus,
    ApplicationStatusHistory,
    DeskReviewEvaluation,
    ReviewTeam,
    ExternalReviewReport,
)

class WorkflowEngine:
    # State transition definitions:
    # (current_status, target_status): {
    #     'allowed_roles': [...],
    #     'target_stage': StageChoices,
    #     'guard': callable(app) -> (bool, error_msg)
    # }
    
    @staticmethod
    def _guard_submitted(app):
        if not hasattr(app, 'self_study_report'):
            return False, "لا يمكن تسليم الطلب رسمياً قبل إنشاء وحفظ تقرير الدراسة الذاتية (SSR)."
        if app.evidences.count() == 0:
            return False, "يجب رفع وثيقة أو شاهد واحد على الأقل في بنك الأدلة قبل التسليم."
        return True, ""

    @staticmethod
    def _guard_self_study_submitted(app):
        if not hasattr(app, 'self_study_report'):
            return False, "يجب إنشاء وحفظ تقرير الدراسة الذاتية أولاً."
        return True, ""

    @staticmethod
    def _guard_desk_accepted(app):
        latest_desk = app.desk_reviews.order_by('-reviewed_at').first()
        if not latest_desk or not latest_desk.is_completed:
            return False, "يجب إكمال واعتماد استمارة الفحص المكتبي الأولي أولاً."
        if latest_desk.decision != DeskReviewEvaluation.DeskDecision.ACCEPTED:
            return False, "قرار الفحص المكتبي الحالي لا يجيز الانتقال للمرحلة التالية."
        return True, ""

    @staticmethod
    def _guard_panel_assigned(app):
        if not hasattr(app, 'review_team'):
            return False, "يجب إصدار قرار تشكيل لجنة المراجعة والتقييم وتعيين رئيس الفريق أولاً."
        return True, ""

    @staticmethod
    def _guard_final_report_ready(app):
        if not hasattr(app, 'external_report'):
            return False, "يجب حفظ تقرير المراجعة الخارجية أولاً."
        return True, ""

    @staticmethod
    def _guard_decision_issued(app):
        if not hasattr(app, 'council_decision'):
            return False, "لا يمكن إتمام هذه المرحلة قبل تسجيل وتوثيق قرار مجلس الإدارة الرسمي."
        return True, ""

    @classmethod
    def get_transition_rule(cls, from_status, to_status):
        rules = {
            # Application Intake & Council Board Review Transitions
            (ApplicationStatus.DRAFT, ApplicationStatus.PENDING_REVIEW): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'تقديم طلب الاعتماد للمجلس للمراجعة وتحديد التكلفة'
            },
            (ApplicationStatus.DRAFT, ApplicationStatus.PRESIDENT_ENDORSED): {
                'allowed_roles': [User.Roles.UNIVERSITY_PRESIDENT, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'اعتماد ومصادقة رئيس الجامعة على طلب الاعتماد'
            },
            (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.PRESIDENT_ENDORSED): {
                'allowed_roles': [User.Roles.UNIVERSITY_PRESIDENT, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'اعتماد ومصادقة رئيس الجامعة على طلب الاعتماد'
            },
            (ApplicationStatus.PRESIDENT_ENDORSED, ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'قبول طلب الاعتماد المصدق وتحديد التكلفة والمطالبة بالتقييم الذاتي'
            },
            (ApplicationStatus.PRESIDENT_ENDORSED, ApplicationStatus.REJECTED): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'رفض/إرجاع طلب الاعتماد من قبل المجلس'
            },
            (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'قبول طلب الاعتماد وتحديد التكلفة والمطالبة بالتقييم الذاتي'
            },
            (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.REJECTED): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'رفض طلب الاعتماد من قبل المجلس'
            },
            (ApplicationStatus.REJECTED, ApplicationStatus.PENDING_REVIEW): {
                'allowed_roles': [
                    User.Roles.INSTITUTION_OFFICER,
                    User.Roles.UNIVERSITY_PRESIDENT,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'تعديل وإعادة تقديم طلب الاعتماد للمراجعة'
            },
            (ApplicationStatus.REJECTED, ApplicationStatus.DRAFT): {
                'allowed_roles': [
                    User.Roles.INSTITUTION_OFFICER,
                    User.Roles.UNIVERSITY_PRESIDENT,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'إعادة فتح الطلب للتعديل كمسودة'
            },
            (ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION, ApplicationStatus.SELF_EVALUATION_IN_PROGRESS): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_1,
                'guard': None,
                'label': 'بدء استكمال التقييم الذاتي'
            },
            (ApplicationStatus.SELF_EVALUATION_IN_PROGRESS, ApplicationStatus.SELF_EVALUATION_SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_2,
                'guard': cls._guard_self_study_submitted,
                'label': 'تسليم تقرير التقييم الذاتي رسمياً للمجلس'
            },
            (ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION, ApplicationStatus.SELF_EVALUATION_SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_2,
                'guard': cls._guard_self_study_submitted,
                'label': 'تسليم تقرير التقييم الذاتي رسمياً للمجلس'
            },
            (ApplicationStatus.SELF_EVALUATION_SUBMITTED, ApplicationStatus.DESK_UNDER_REVIEW): {
                'allowed_roles': [
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_desk_review',
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'بدء إجراءات الفحص المكتبي للتقييم الذاتي'
            },

            # Legacy & Direct Transitions (Preserved for backwards compatibility)
            (ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_2,
                'guard': cls._guard_submitted,
                'label': 'تسليم التقرير رسمياً للأمانة الفنية'
            },
            (ApplicationStatus.SUBMITTED, ApplicationStatus.DESK_UNDER_REVIEW): {
                'allowed_roles': [
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_desk_review',
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'بدء إجراءات الفحص المكتبي'
            },
            (ApplicationStatus.DESK_UNDER_REVIEW, ApplicationStatus.DESK_DEFICIENCY): {
                'allowed_roles': [
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_desk_review',
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'إشعار المؤسسة بوجود نواقص واستيفاءات'
            },
            (ApplicationStatus.DESK_DEFICIENCY, ApplicationStatus.SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'إعادة إرسال الملف بعد استكمال النواقص'
            },
            (ApplicationStatus.DESK_DEFICIENCY, ApplicationStatus.SELF_EVALUATION_SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'إعادة إرسال تقرير التقييم الذاتي بعد استكمال النواقص'
            },
            (ApplicationStatus.DESK_DEFICIENCY, ApplicationStatus.DESK_UNDER_REVIEW): {
                'allowed_roles': [
                    User.Roles.INSTITUTION_OFFICER,
                    User.Roles.UNIVERSITY_PRESIDENT,
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_2,
                'guard': None,
                'label': 'إعادة فحص الملف مكتبياً بعد استكمال النواقص'
            },
            (ApplicationStatus.DESK_UNDER_REVIEW, ApplicationStatus.DESK_ACCEPTED): {
                'allowed_roles': [
                    User.Roles.DG_ACCREDITATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_desk_review',
                'target_stage': StageChoices.STAGE_3,
                'guard': cls._guard_desk_accepted,
                'label': 'اعتماد استيفاء الشروط والأهلية والانتقال للتحكيم'
            },
            (ApplicationStatus.DESK_ACCEPTED, ApplicationStatus.FINANCIAL_CLEARED): {
                'allowed_roles': [
                    User.Roles.DG_FINANCE_ADMIN,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_verify_payment',
                'target_stage': StageChoices.STAGE_3,
                'guard': None,
                'label': 'تأكيد السداد وإصدار سند الإبراء المالي للطلب'
            },
            (ApplicationStatus.FINANCIAL_CLEARED, ApplicationStatus.PANEL_ASSIGNED): {
                'allowed_roles': [
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_nominate_reviewers',
                'target_stage': StageChoices.STAGE_3,
                'guard': cls._guard_panel_assigned,
                'label': 'إصدار قرار تكليف لجنة المحكمين بعد الإبراء المالي'
            },
            (ApplicationStatus.DESK_ACCEPTED, ApplicationStatus.PANEL_ASSIGNED): {
                'allowed_roles': [
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_nominate_reviewers',
                'target_stage': StageChoices.STAGE_3,
                'guard': cls._guard_panel_assigned,
                'label': 'إصدار قرار تكليف لجنة المحكمين'
            },
            (ApplicationStatus.PANEL_ASSIGNED, ApplicationStatus.SITE_VISIT_SCHEDULED): {
                'allowed_roles': [
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.EXTERNAL_REVIEWER,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_site_visit',
                'target_stage': StageChoices.STAGE_4,
                'guard': None,
                'label': 'تأكيد وجدولة الزيارة الميدانية'
            },
            (ApplicationStatus.SITE_VISIT_SCHEDULED, ApplicationStatus.SITE_VISIT_COMPLETED): {
                'allowed_roles': [
                    User.Roles.EXTERNAL_REVIEWER,
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'required_permission': 'can_conduct_site_visit',
                'target_stage': StageChoices.STAGE_5,
                'guard': None,
                'label': 'اختتام الزيارة الميدانية'
            },
            (ApplicationStatus.SITE_VISIT_COMPLETED, ApplicationStatus.DRAFT_REPORT_ISSUED): {
                'allowed_roles': [User.Roles.EXTERNAL_REVIEWER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_5,
                'guard': None,
                'label': 'إصدار مسودة تقرير المراجعة الخارجية'
            },
            (ApplicationStatus.DRAFT_REPORT_ISSUED, ApplicationStatus.WAITING_INSTITUTION_RESPONSE): {
                'allowed_roles': [
                    User.Roles.EXTERNAL_REVIEWER,
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_5,
                'guard': None,
                'label': 'إرسال المسودة للمؤسسة لممارسة حق الرد'
            },
            (ApplicationStatus.WAITING_INSTITUTION_RESPONSE, ApplicationStatus.RESPONSE_SUBMITTED): {
                'allowed_roles': [User.Roles.INSTITUTION_OFFICER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_5,
                'guard': None,
                'label': 'تسليم رد المؤسسة الرسمي (حق الرد)'
            },
            (ApplicationStatus.RESPONSE_SUBMITTED, ApplicationStatus.FINAL_REPORT_READY): {
                'allowed_roles': [User.Roles.EXTERNAL_REVIEWER, User.Roles.ADMIN],
                'target_stage': StageChoices.STAGE_6,
                'guard': cls._guard_final_report_ready,
                'label': 'اعتماد التقرير النهائي ورفعه للمجلس'
            },
            (ApplicationStatus.FINAL_REPORT_READY, ApplicationStatus.IN_COUNCIL_REVIEW): {
                'allowed_roles': [
                    User.Roles.COUNCIL_SECRETARY_GENERAL,
                    User.Roles.DG_EVALUATION,
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.COUNCIL_SECRETARY,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_6,
                'guard': None,
                'label': 'إدراج الملف في جلسة مداولات المجلس'
            },
            (ApplicationStatus.IN_COUNCIL_REVIEW, ApplicationStatus.FULL_ACCREDITATION): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_7,
                'guard': cls._guard_decision_issued,
                'label': 'منح الاعتماد الأكاديمي الكامل (5 سنوات)'
            },
            (ApplicationStatus.IN_COUNCIL_REVIEW, ApplicationStatus.CONDITIONAL_ACCREDITATION): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_7,
                'guard': cls._guard_decision_issued,
                'label': 'منح الاعتماد المشروط مع خطة تصحيحية'
            },
            (ApplicationStatus.IN_COUNCIL_REVIEW, ApplicationStatus.DENIED): {
                'allowed_roles': [
                    User.Roles.COUNCIL_CHAIRMAN,
                    User.Roles.COUNCIL_VICE_CHAIRMAN,
                    User.Roles.BOARD_MEMBER,
                    User.Roles.ADMIN
                ],
                'target_stage': StageChoices.STAGE_6,
                'guard': cls._guard_decision_issued,
                'label': 'تأجيل أو رفض منح الاعتماد'
            },
        }
        return rules.get((from_status, to_status))

    @classmethod
    def can_transition(cls, application, target_status, user):
        """
        Validates whether user is allowed to transition application to target_status.
        Returns: (is_allowed: bool, reason: str)
        """
        if not user or not user.is_authenticated:
            return False, "يجب تسجيل الدخول أولاً لتنفيذ هذه العملية."

        # If user is INSTITUTION_OFFICER or UNIVERSITY_PRESIDENT, check tenant isolation
        if user.role in [User.Roles.INSTITUTION_OFFICER, User.Roles.UNIVERSITY_PRESIDENT]:
            if application.institution_id != user.institution_id:
                return False, "غير مصرح لك: هذا الطلب يتبع مؤسسة تعليمية أخرى."

        # If user is EXTERNAL_REVIEWER, check if assigned to this panel
        if user.role == User.Roles.EXTERNAL_REVIEWER and not user.is_staff:
            has_membership = hasattr(application, 'review_team') and application.review_team.members.filter(user=user).exists()
            is_chair = hasattr(application, 'review_team') and application.review_team.chairperson_id == user.id
            if not (has_membership or is_chair):
                return False, "غير مصرح لك: لست عضواً في لجنة المحكمين المكلفة بهذا الطلب."

        rule = cls.get_transition_rule(application.status, target_status)
        if not rule:
            return False, f"الانتقال الإجرائي من حالة ({application.get_status_display()}) إلى ({target_status}) غير مسموح به في دورة العمل."

        # Check role permission
        if user.role not in rule['allowed_roles'] and not user.is_superuser:
            req_perm = rule.get('required_permission')
            if not (req_perm and (user.has_perm_code(req_perm) or user.has_permission(req_perm, resource=application))):
                return False, "ليس لديك الصلاحية الإدارية المخولة لتنفيذ هذا الانتقال."

        # Execute guard check if present
        if rule['guard']:
            valid, err = rule['guard'](application)
            if not valid:
                return False, err

        return True, ""

    @classmethod
    def execute_transition(cls, application, target_status, user, reason="", request=None):
        """
        Executes and records the state transition in database with full audit trail.
        """
        can_move, error_msg = cls.can_transition(application, target_status, user)
        if not can_move:
            raise ValidationError(error_msg)

        rule = cls.get_transition_rule(application.status, target_status)
        old_status = application.status
        old_stage = application.current_stage
        new_stage = rule['target_stage']

        # Update application model
        application.status = target_status
        application.current_stage = new_stage
        if target_status == ApplicationStatus.SUBMITTED and not application.submission_date:
            application.submission_date = timezone.now()
        application.save()

        # Record history entry
        ApplicationStatusHistory.objects.create(
            application=application,
            from_stage=old_stage,
            to_stage=new_stage,
            from_status=old_status,
            to_status=target_status,
            changed_by=user,
            reason=reason or rule.get('label', '')
        )

        # Record system audit log
        record_audit_log(
            user=user,
            action='WORKFLOW_TRANSITION',
            target_model='AccreditationApplication',
            target_id=application.pk,
            details=f"الانتقال من [{old_status} - مرحلة {old_stage}] إلى [{target_status} - مرحلة {new_stage}]. السبب: {reason}",
            request=request
        )

        # Record Central Sovereign Transaction movement
        try:
            from apps.decisions.models import SovereignTransaction
            SovereignTransaction.record_lifecycle_movement(
                transaction_type=SovereignTransaction.TransactionType.OFFICIAL_MEMO,
                subject=f"{rule.get('label', 'انتقال حالة الطلب')} - ({application.application_number})",
                description=f"الانتقال من [{old_status}] إلى [{target_status}]. البيان: {reason or rule.get('label', '')}",
                sender=user,
                sending_authority=application.institution.name if getattr(user, 'is_institution_rep', False) else 'الأمانة العامة لمجلس الاعتماد',
                receiving_authority='مجلس الاعتماد الأكاديمي' if getattr(user, 'is_institution_rep', False) else application.institution.name,
                status=SovereignTransaction.TransactionStatus.COMPLETED,
                action_reason=reason or rule.get('label', ''),
                from_status=old_status,
                application=application,
                prefix='WFL',
            )
        except Exception:
            pass

        return True, f"تم بنجاح تغيير حالة الطلب إلى ({application.get_status_display()})."
