from django.core.management.base import BaseCommand
from apps.accounts.models import User
from apps.institutions.models import Institution


class Command(BaseCommand):
    help = "Seed demo accounts for all Yemen CAQA governance and administrative roles"

    def handle(self, *args, **options):
        # 1. Fetch or create reference institution
        sanaa_univ = Institution.objects.filter(code="UNIV-SANAA").first()
        if not sanaa_univ:
            sanaa_univ = Institution.objects.filter(name__contains="صنعاء").first()
        if not sanaa_univ:
            sanaa_univ = Institution.objects.first()

        demo_users = [
            {
                "username": "council_chairman",
                "email": "chairman@caqa.gov.ye",
                "first_name": "أ.د. رئيس",
                "last_name": "مجلس الاعتماد الأكاديمي",
                "academic_title": "أ.د.",
                "role": User.Roles.COUNCIL_CHAIRMAN,
                "is_staff": True,
            },
            {
                "username": "council_vice_chairman",
                "email": "vice_chairman@caqa.gov.ye",
                "first_name": "أ.د. نائب رئيس",
                "last_name": "المجلس",
                "academic_title": "أ.د.",
                "role": User.Roles.COUNCIL_VICE_CHAIRMAN,
                "is_staff": True,
            },
            {
                "username": "board_member",
                "email": "board_member@caqa.gov.ye",
                "first_name": "أ.د. عضو",
                "last_name": "مجلس الإدارة",
                "academic_title": "أ.د.",
                "role": User.Roles.BOARD_MEMBER,
                "is_staff": True,
            },
            {
                "username": "minister",
                "email": "minister@mohesr.gov.ye",
                "first_name": "معالي وزير",
                "last_name": "التعليم العالي والبحث العلمي",
                "academic_title": "معالي الأستاذ الدكتور",
                "role": User.Roles.MINISTER,
                "is_staff": True,
            },
            {
                "username": "sec_general",
                "email": "sec_general@caqa.gov.ye",
                "first_name": "د. أمين عام",
                "last_name": "المجلس",
                "academic_title": "د.",
                "role": User.Roles.COUNCIL_SECRETARY_GENERAL,
                "is_staff": True,
            },
            {
                "username": "dg_accreditation",
                "email": "dg_accreditation@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "الاعتماد والتراخيص",
                "academic_title": "د.",
                "role": User.Roles.DG_ACCREDITATION,
                "is_staff": True,
            },
            {
                "username": "dg_evaluation",
                "email": "dg_evaluation@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "التقييم والمراجعة الخارجية",
                "academic_title": "د.",
                "role": User.Roles.DG_EVALUATION,
                "is_staff": True,
            },
            {
                "username": "dg_quality",
                "email": "dg_quality@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "ضمان الجودة والتأهيل",
                "academic_title": "د.",
                "role": User.Roles.DG_QUALITY,
                "is_staff": True,
            },
            {
                "username": "dg_finance",
                "email": "dg_finance@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "الشؤون المالية والإدارية",
                "academic_title": "أستاذ",
                "role": User.Roles.DG_FINANCE_ADMIN,
                "is_staff": True,
            },
            {
                "username": "dir_legal",
                "email": "legal@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "الشؤون القانونية والطعون",
                "academic_title": "المستشار",
                "role": User.Roles.LEGAL_DIRECTOR,
                "is_staff": True,
            },
            {
                "username": "dir_it",
                "email": "it_director@caqa.gov.ye",
                "first_name": "مدير عام",
                "last_name": "نظم المعلومات والتحول الرقمي",
                "academic_title": "م.",
                "role": User.Roles.IT_DIRECTOR,
                "is_staff": True,
            },
            {
                "username": "council_sec",
                "email": "council_sec@caqa.gov.ye",
                "first_name": "أمين سر",
                "last_name": "المجلس الفني",
                "academic_title": "د.",
                "role": User.Roles.COUNCIL_SECRETARY,
                "is_staff": True,
            },
            {
                "username": "univ_officer_sanaa",
                "email": "quality@su.edu.ye",
                "first_name": "د. ممثل الجودة",
                "last_name": "جامعة صنعاء",
                "academic_title": "د.",
                "role": User.Roles.INSTITUTION_OFFICER,
                "institution": sanaa_univ,
                "is_staff": False,
            },
            {
                "username": "ext_reviewer_1",
                "email": "evaluator.omar@caqa.gov.ye",
                "first_name": "أ.د. خبير محكم",
                "last_name": "دولي",
                "academic_title": "أ.د.",
                "role": User.Roles.EXTERNAL_REVIEWER,
                "is_certified_evaluator": True,
                "is_staff": False,
            },
        ]

        created_count = 0
        updated_count = 0

        for user_data in demo_users:
            uname = user_data["username"]
            role_val = user_data["role"]
            inst = user_data.get("institution")

            user, created = User.objects.get_or_create(
                username=uname,
                defaults={
                    "email": user_data["email"],
                    "first_name": user_data["first_name"],
                    "last_name": user_data["last_name"],
                    "academic_title": user_data.get("academic_title", ""),
                    "role": role_val,
                    "approval_status": User.ApprovalStatus.APPROVED,
                    "is_staff": user_data.get("is_staff", False),
                    "is_active": True,
                    "institution": inst,
                    "is_certified_evaluator": user_data.get("is_certified_evaluator", False),
                }
            )

            # Ensure correct role, password, and approval status
            user.set_password("password123")
            user.role = role_val
            user.approval_status = User.ApprovalStatus.APPROVED
            user.is_active = True
            if inst:
                user.institution = inst
            if user_data.get("is_certified_evaluator"):
                user.is_certified_evaluator = True
            user.save()

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created demo account: {uname} ({role_val})"))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f"Updated demo account: {uname} ({role_val})"))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully seeded demo accounts! Created: {created_count}, Updated: {updated_count}. Password: password123"
        ))
