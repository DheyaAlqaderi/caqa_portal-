from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User, Notification
from apps.institutions.models import Institution
from apps.standards.models import StandardVersion, AccreditationTrackType
from apps.accreditation.models import AccreditationApplication, StageChoices, ApplicationStatus
from apps.operations.models import FeeSchedule, Invoice
from apps.operations.services import (
    notify_invoice_issued,
    notify_payment_receipt_uploaded,
    notify_payment_receipt_acknowledged,
    notify_payment_confirmed,
    notify_payment_rejected,
    notify_finance_to_secretariat,
)


class FinancialNotificationsPhase2ATests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Institutions
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            code="UNIV-A",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.univ_b = Institution.objects.create(
            name="جامعة تعز",
            code="UNIV-B",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )

        # 2. Users for Institution A
        self.officer_a1 = User.objects.create_user(
            username="officer_a1",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.officer_a2 = User.objects.create_user(
            username="officer_a2",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.officer_a_inactive = User.objects.create_user(
            username="officer_a_inactive",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=False
        )
        self.officer_a_unapproved = User.objects.create_user(
            username="officer_a_unapproved",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.PENDING_APPROVAL,
            is_active=True
        )

        # 3. Users for Institution B
        self.officer_b1 = User.objects.create_user(
            username="officer_b1",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )

        # 4. Secretariat and Finance / Admin Users
        self.sec_user = User.objects.create_user(
            username="sec_finance_officer",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_active=True
        )
        self.admin_user = User.objects.create_superuser(
            username="admin_finance_user",
            password="password123",
            email="admin_fin@caqa.gov.ye",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True
        )
        self.board_user = User.objects.create_user(
            username="board_member_dr",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_staff=True,
            is_active=True
        )

        # 5. Accreditation Application
        self.std_ver = StandardVersion.objects.create(
            title="المعايير المؤسسية الوطنية",
            track=AccreditationTrackType.INSTITUTIONAL,
            version_number="1.0"
        )
        self.app_a = AccreditationApplication.objects.create(
            application_number="CAQA-INST-2026-0001",
            institution=self.univ_a,
            track=AccreditationTrackType.INSTITUTIONAL,
            standard_version=self.std_ver,
            applicant_user=self.officer_a1,
            current_stage=StageChoices.STAGE_1,
            status=ApplicationStatus.ACCEPTED_PENDING_SELF_EVALUATION
        )

        # 6. Fee Schedule & Invoice
        self.fee = FeeSchedule.objects.create(
            service_name="رسوم الاعتماد المؤسسي",
            track=AccreditationTrackType.INSTITUTIONAL,
            regulatory_reference="اللائحة المالية لرسوم الاعتماد رقم (12)",
            amount_yer=5000000.00
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-2026-0001",
            application=self.app_a,
            fee_schedule=self.fee,
            total_amount=5000000.00,
            status=Invoice.PaymentStatus.UNPAID
        )

    def test_scenario_16_invoice_issued_notifies_institution_officers(self):
        """
        Scenario 16: Issuing an invoice notifies all active, approved officers of the institution,
        and excludes inactive/unapproved officers and officers from other institutions.
        """
        notifs = notify_invoice_issued(self.invoice)
        self.assertEqual(len(notifs), 2)

        # Officer A1 and A2 received the notification
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a1, title__contains="مطالبة مالية").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.officer_a2, title__contains="مطالبة مالية").exists())

        # Inactive/unapproved officers must NOT receive notification
        self.assertFalse(Notification.objects.filter(recipient=self.officer_a_inactive).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.officer_a_unapproved).exists())

        # Officer from University B must NEVER receive notification
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b1).count(), 0)

        # Board members should NOT be notified of standard invoice issuance
        self.assertEqual(Notification.objects.filter(recipient=self.board_user).count(), 0)

    def test_scenario_17_and_18_payment_receipt_upload_and_acknowledgment(self):
        """
        Scenario 17: Uploading payment receipt notifies Secretariat/financial officers.
        Scenario 18: Receipt upload acknowledges receipt to institution officers (awaiting verification),
                     without prematurely confirming payment.
        """
        self.client.login(username="officer_a1", password="password123")

        sec_notifs_before = Notification.objects.filter(recipient=self.sec_user).count()
        inst_notifs_before = Notification.objects.filter(recipient=self.officer_a1).count()

        response = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'upload_proof': '1',
            'payment_reference': 'إشعار توريد بنكي رقم 4492 بتاريخ 2026-11-01'
        })
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_reference, 'إشعار توريد بنكي رقم 4492 بتاريخ 2026-11-01')
        # Crucial: invoice MUST NOT be marked as PAID prematurely upon upload
        self.assertEqual(self.invoice.status, Invoice.PaymentStatus.UNPAID)

        # Scenario 17: Secretariat / finance received upload notification
        self.assertEqual(Notification.objects.filter(recipient=self.sec_user).count(), sec_notifs_before + 1)
        sec_notif = Notification.objects.filter(recipient=self.sec_user).latest('created_at')
        self.assertIn("إشعار توريد مالي جديد", sec_notif.title)

        # Scenario 18: Institution officers received acknowledgment (awaiting verification)
        self.assertEqual(Notification.objects.filter(recipient=self.officer_a1).count(), inst_notifs_before + 1)
        inst_notif = Notification.objects.filter(recipient=self.officer_a1).latest('created_at')
        self.assertIn("تأكيد استلام سند التوريد", inst_notif.title)
        self.assertIn("قيد المراجعة والتدقيق", inst_notif.message)

        # Univ B officer never received anything
        self.assertEqual(Notification.objects.filter(recipient=self.officer_b1).count(), 0)

    def test_scenario_19_and_21_payment_confirmed_and_finance_to_secretariat_handoff(self):
        """
        Scenario 19: Financial officer confirms payment -> notifies all institution officers.
        Scenario 21: Financial officer confirms payment -> sends internal finance-to-Secretariat notification.
        """
        # Set receipt reference
        self.invoice.payment_reference = 'توريد بنكي رقم 8871'
        self.invoice.save()

        # Login as Secretariat / Finance officer
        self.client.login(username="sec_finance_officer", password="password123")

        sec_notifs_before = Notification.objects.filter(recipient=self.sec_user).count()

        response = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'confirm_payment': '1'
        })
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.PaymentStatus.PAID)
        self.assertEqual(self.invoice.verified_by, self.sec_user)
        self.assertIsNotNone(self.invoice.paid_at)

        # Scenario 19: All authorized institution officers receive official payment confirmation
        notifs_a1 = Notification.objects.filter(recipient=self.officer_a1, title__contains="تأكيد واعتماد السداد")
        notifs_a2 = Notification.objects.filter(recipient=self.officer_a2, title__contains="تأكيد واعتماد السداد")
        self.assertEqual(notifs_a1.count(), 1)
        self.assertEqual(notifs_a2.count(), 1)

        # Scenario 21: Internal finance-to-Secretariat handoff notification delivered
        sec_handoff_notif = Notification.objects.filter(
            recipient=self.sec_user,
            title__contains="اكتمال السداد المالي للطلب"
        ).first()
        self.assertIsNotNone(sec_handoff_notif)
        self.assertIn(self.app_a.application_number, sec_handoff_notif.title)

    def test_scenario_20_payment_rejected_without_exposing_internal_notes(self):
        """
        Scenario 20: Rejecting payment receipt notifies institution with public explanation only,
                     and NEVER exposes confidential internal financial notes.
        """
        self.invoice.payment_reference = 'إشعار غير مطابق 9901'
        self.invoice.save()

        self.client.login(username="sec_finance_officer", password="password123")

        response = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'reject_payment': '1',
            'rejection_reason': 'المبلغ المودع في السند أقل من الرسوم المقررة باللائحة',
            'internal_notes': 'تم التواصل مع البنك المركزي وتأكيد وجود فرق تدقيقي داخلي سري 50000 ريال'
        })
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.PaymentStatus.UNPAID)

        # Institution received rejection notification
        notif = Notification.objects.filter(recipient=self.officer_a1, title__contains="إعادة إشعار التوريد").first()
        self.assertIsNotNone(notif)
        self.assertIn("المبلغ المودع في السند أقل من الرسوم المقررة باللائحة", notif.message)

        # CRITICAL SECURITY CHECK: Internal notes must NEVER be in the notification message
        self.assertNotIn("البنك المركزي", notif.message)
        self.assertNotIn("سري", notif.message)
        self.assertNotIn("فرق تدقيقي داخلي", notif.message)

    def test_unauthorized_user_cannot_confirm_or_reject_payment(self):
        """Institution officers cannot confirm or reject payments; server-side permission enforced."""
        self.client.login(username="officer_a1", password="password123")

        # Attempt to confirm payment
        res = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'confirm_payment': '1'
        })
        self.assertEqual(res.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, Invoice.PaymentStatus.PAID)

        # Attempt to reject payment
        res = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'reject_payment': '1',
            'rejection_reason': 'غير مصرح'
        })
        self.assertEqual(res.status_code, 302)
        self.invoice.refresh_from_db()
        # No rejection notification generated
        self.assertEqual(Notification.objects.filter(title__contains="إعادة إشعار التوريد").count(), 0)

    def test_tenant_isolation_officer_b_cannot_view_or_upload_to_univ_a_invoice(self):
        """Cross-institution tenant isolation: Officer B is blocked from University A's invoice."""
        self.client.login(username="officer_b1", password="password123")

        # GET invoice
        get_res = self.client.get(reverse('operations:invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(get_res.status_code, 302)  # Redirected with error

        # POST upload proof
        post_res = self.client.post(reverse('operations:invoice_detail', args=[self.invoice.pk]), {
            'upload_proof': '1',
            'payment_reference': 'تسلل غير مصرح به'
        })
        self.assertEqual(post_res.status_code, 302)

        # Invoice payment reference remained unchanged
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.payment_reference, 'تسلل غير مصرح به')

    def test_duplicate_financial_notifications_prevented(self):
        """Calling financial notification helpers repeatedly does not flood users with duplicate notifications."""
        # 1st call
        notifs_1 = notify_invoice_issued(self.invoice)
        self.assertEqual(len(notifs_1), 2)
        count_1 = Notification.objects.filter(recipient=self.officer_a1, title__contains="مطالبة مالية").count()
        self.assertEqual(count_1, 1)

        # 2nd call (same event)
        notifs_2 = notify_invoice_issued(self.invoice)
        self.assertEqual(len(notifs_2), 0)
        count_2 = Notification.objects.filter(recipient=self.officer_a1, title__contains="مطالبة مالية").count()
        # Duplicate prevented
        self.assertEqual(count_2, 1)
