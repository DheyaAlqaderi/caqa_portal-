from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import User
from apps.institutions.models import Institution, College, Department, AcademicProgram


class AcademicStructureTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Institution A & Officer A
        self.univ_a = Institution.objects.create(
            name="جامعة صنعاء",
            name_en="Sana'a University",
            code="SNA-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.officer_a = User.objects.create_user(
            username="officer_sanaa",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_a,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # Institution B & Officer B
        self.univ_b = Institution.objects.create(
            name="جامعة عدن",
            name_en="Aden University",
            code="ADN-01",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY
        )
        self.officer_b = User.objects.create_user(
            username="officer_aden",
            password="password123",
            role=User.Roles.INSTITUTION_OFFICER,
            institution=self.univ_b,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # Council Admin
        self.admin = User.objects.create_superuser(
            username="council_admin",
            password="adminpassword123",
            email="admin@caqa.gov.ye",
            role=User.Roles.ADMIN,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # Council Board Member
        self.board_member = User.objects.create_user(
            username="board_member",
            password="password123",
            role=User.Roles.BOARD_MEMBER,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

        # Council Secretariat Staff
        self.council_sec = User.objects.create_user(
            username="council_sec",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY,
            is_staff=True,
            approval_status=User.ApprovalStatus.APPROVED
        )

    def test_institution_officer_can_create_college(self):
        """Institution Officer can create a college within their own institution."""
        self.client.login(username="officer_sanaa", password="password123")
        response = self.client.post(reverse('institutions:college_create', args=[self.univ_a.pk]), {
            'name': 'كلية الهندسة',
            'dean_name': 'أ.د. محمد المهندس',
            'establishment_year': 1990
        })
        self.assertEqual(response.status_code, 302)
        college = College.objects.filter(institution=self.univ_a, name='كلية الهندسة').first()
        self.assertIsNotNone(college)
        self.assertEqual(college.dean_name, 'أ.د. محمد المهندس')

    def test_tenant_isolation_college_creation_forbidden(self):
        """Officer B cannot create a college for Institution A."""
        self.client.login(username="officer_aden", password="password123")
        response = self.client.post(reverse('institutions:college_create', args=[self.univ_a.pk]), {
            'name': 'كلية الطب المتسللة',
            'dean_name': 'د. دخيل'
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(College.objects.filter(institution=self.univ_a, name='كلية الطب المتسللة').exists())

    def test_institution_officer_can_create_department(self):
        """Officer can create a department under a college within their institution."""
        college = College.objects.create(institution=self.univ_a, name="كلية الحاسوب وتكنولوجيا المعلومات")
        self.client.login(username="officer_sanaa", password="password123")

        response = self.client.post(reverse('institutions:department_create', args=[college.pk]), {
            'name': 'قسم علوم الحاسوب',
            'head_name': 'د. هشام الكمبيوتر',
            'establishment_year': 2005
        })
        self.assertEqual(response.status_code, 302)
        dept = Department.objects.filter(college=college, name='قسم علوم الحاسوب').first()
        self.assertIsNotNone(dept)
        self.assertEqual(dept.head_name, 'د. هشام الكمبيوتر')

    def test_program_creation_with_optional_department(self):
        """Programs can be created with or without optional department assignment."""
        college = College.objects.create(institution=self.univ_a, name="كلية العلوم الإدارية")
        dept = Department.objects.create(college=college, name="قسم المحاسبة")
        self.client.login(username="officer_sanaa", password="password123")

        # 1. Program with Department
        response = self.client.post(reverse('institutions:program_create', args=[college.pk]), {
            'department_id': dept.id,
            'name': 'بكالوريوس محاسبة وقانون',
            'degree_level': AcademicProgram.DegreeLevel.BACHELOR,
            'study_system': AcademicProgram.StudySystem.SEMESTER,
            'credit_hours': 136,
            'study_language': 'العربية'
        })
        self.assertEqual(response.status_code, 302)
        prog1 = AcademicProgram.objects.get(name='بكالوريوس محاسبة وقانون')
        self.assertEqual(prog1.college, college)
        self.assertEqual(prog1.department, dept)

        # 2. Program without Department (optional)
        response2 = self.client.post(reverse('institutions:program_create', args=[college.pk]), {
            'department_id': '',
            'name': 'دبلوم إدارة عامة',
            'degree_level': AcademicProgram.DegreeLevel.DIPLOMA,
            'study_system': AcademicProgram.StudySystem.SEMESTER,
            'credit_hours': 68,
            'study_language': 'العربية'
        })
        self.assertEqual(response2.status_code, 302)
        prog2 = AcademicProgram.objects.get(name='دبلوم إدارة عامة')
        self.assertIsNone(prog2.department)

    def test_dependent_structure_api(self):
        """API returns json with colleges, departments and programs for cascading dropdowns."""
        col1 = College.objects.create(institution=self.univ_a, name="كلية الطب")
        dept1 = Department.objects.create(college=col1, name="قسم الجراحة")
        prog1 = AcademicProgram.objects.create(college=col1, department=dept1, name="بكالوريوس طب وجراحة")
        self.client.login(username="officer_sanaa", password="password123")

        # 1. By Institution -> Colleges
        response = self.client.get(reverse('institutions:api_dependent_structure') + f"?institution_id={self.univ_a.pk}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('colleges', data)
        self.assertEqual(len(data['colleges']), 1)
        self.assertEqual(data['colleges'][0]['name'], 'كلية الطب')

        # 2. By College -> Departments & Programs
        response2 = self.client.get(reverse('institutions:api_dependent_structure') + f"?college_id={col1.pk}")
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()
        self.assertIn('departments', data2)
        self.assertEqual(len(data2['departments']), 1)
        self.assertEqual(data2['departments'][0]['name'], 'قسم الجراحة')
        self.assertIn('programs', data2)
        self.assertEqual(len(data2['programs']), 1)
        self.assertEqual(data2['programs'][0]['name'], 'بكالوريوس طب وجراحة')

    def test_board_member_cannot_create_academic_structure(self):
        """Board Member is strictly forbidden from creating colleges, departments, or programs."""
        college = College.objects.create(institution=self.univ_a, name="كلية العلوم الطبية")
        self.client.login(username="board_member", password="password123")

        # 1. College creation forbidden (403)
        res_col = self.client.post(reverse('institutions:college_create', args=[self.univ_a.pk]), {
            'name': 'كلية المجلس المحظورة'
        })
        self.assertEqual(res_col.status_code, 403)
        self.assertFalse(College.objects.filter(name='كلية المجلس المحظورة').exists())

        # 2. Department creation forbidden (403)
        res_dept = self.client.post(reverse('institutions:department_create', args=[college.pk]), {
            'name': 'قسم المجلس المحظور'
        })
        self.assertEqual(res_dept.status_code, 403)
        self.assertFalse(Department.objects.filter(name='قسم المجلس المحظور').exists())

        # 3. Program creation forbidden (403)
        res_prog = self.client.post(reverse('institutions:program_create', args=[college.pk]), {
            'name': 'برنامج المجلس المحظور'
        })
        self.assertEqual(res_prog.status_code, 403)
        self.assertFalse(AcademicProgram.objects.filter(name='برنامج المجلس المحظور').exists())

    def test_secretariat_can_create_academic_structure(self):
        """Secretariat user is authorized to create colleges, departments, and programs on behalf of the ministry."""
        college = College.objects.create(institution=self.univ_a, name="كلية اللغات والترجمة")
        self.client.login(username="council_sec", password="password123")

        # 1. College creation allowed (redirect 302 to detail)
        res_col = self.client.post(reverse('institutions:college_create', args=[self.univ_a.pk]), {
            'name': 'كلية الهندسة والتقنية المعتمدة'
        })
        self.assertEqual(res_col.status_code, 302)
        self.assertTrue(College.objects.filter(name='كلية الهندسة والتقنية المعتمدة').exists())

        # 2. Department creation allowed (redirect 302 to detail)
        res_dept = self.client.post(reverse('institutions:department_create', args=[college.pk]), {
            'name': 'قسم الترجمة الفورية'
        })
        self.assertEqual(res_dept.status_code, 302)
        self.assertTrue(Department.objects.filter(name='قسم الترجمة الفورية').exists())

        # 3. Program creation allowed with decree number (redirect 302 to detail)
        res_prog = self.client.post(reverse('institutions:program_create', args=[college.pk]), {
            'name': 'برنامج اللغة الإنجليزية التطبيقية',
            'degree_level': 'BACHELOR',
            'code': 'ENG-01',
            'study_system': 'SEMESTER',
            'duration_years': 4,
            'ministry_approval_decree': 'قرار وزاري رقم (114) لسنة 2024'
        })
        self.assertEqual(res_prog.status_code, 302)
        prog = AcademicProgram.objects.filter(name='برنامج اللغة الإنجليزية التطبيقية').first()
        self.assertIsNotNone(prog)
        self.assertEqual(prog.ministry_approval_decree, 'قرار وزاري رقم (114) لسنة 2024')

    def test_ui_manage_buttons_hidden_for_board_and_visible_for_secretariat(self):
        """Board users see read-only structure; Secretariat and Institution Officers see management controls."""
        # 1. Board Member view (strictly read-only)
        self.client.login(username="board_member", password="password123")
        res_board = self.client.get(reverse('institutions:detail', args=[self.univ_a.pk]))
        self.assertEqual(res_board.status_code, 200)
        self.assertFalse(res_board.context['can_manage'])
        self.assertNotContains(res_board, "إضافة كلية جديدة")

        # 2. Secretariat view (authorized to manage and license)
        self.client.login(username="council_sec", password="password123")
        res_sec = self.client.get(reverse('institutions:detail', args=[self.univ_a.pk]))
        self.assertEqual(res_sec.status_code, 200)
        self.assertTrue(res_sec.context['can_manage'])
        self.assertContains(res_sec, "إضافة كلية جديدة")

        # 3. Institution Officer view for own institution
        self.client.login(username="officer_sanaa", password="password123")
        res_owner = self.client.get(reverse('institutions:detail', args=[self.univ_a.pk]))
        self.assertEqual(res_owner.status_code, 200)
        self.assertTrue(res_owner.context['can_manage'])
        self.assertContains(res_owner, "إضافة كلية جديدة")


class PublicRegistryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.univ = Institution.objects.create(
            name="جامعة صنعاء الحكومية",
            name_en="Sana'a University",
            code="UNIV-SNA-01",
            governorate="صنعاء",
            institution_type=Institution.InstitutionType.PUBLIC_UNIVERSITY,
            decree_number="قرار جمهوري رقم 1 لسنة 1970"
        )
        self.college = College.objects.create(
            institution=self.univ,
            name="كلية الطب والعلوم الصحية"
        )
        self.program = AcademicProgram.objects.create(
            college=self.college,
            name="دكتور في الطب والجراحة",
            code="MED-MBBS",
            degree_level=AcademicProgram.DegreeLevel.BACHELOR,
            study_duration_years=6.0,
            ministry_approval_decree="قرار وزاري رقم 12 لسنة 1990"
        )

    def test_public_registry_accessible_without_login(self):
        """Unauthenticated student/citizen can access /registry/ without login redirect."""
        res = self.client.get('/registry/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "السجل الوطني")
        self.assertContains(res, "جامعة صنعاء الحكومية")

    def test_public_registry_programs_tab(self):
        """Public programs directory lists academic programs and degrees."""
        res = self.client.get('/registry/?tab=programs')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "دكتور في الطب والجراحة")
        self.assertContains(res, "كلية الطب والعلوم الصحية")

    def test_public_registry_search_filters(self):
        """Public search filters by university name and program name."""
        res_inst = self.client.get('/registry/?tab=institutions&q=صنعاء')
        self.assertEqual(res_inst.status_code, 200)
        self.assertContains(res_inst, "جامعة صنعاء الحكومية")

        res_prog = self.client.get('/registry/?tab=programs&q=جراحة')
        self.assertEqual(res_prog.status_code, 200)
        self.assertContains(res_prog, "دكتور في الطب والجراحة")

    def test_public_institution_and_program_detail(self):
        """Public profile pages are viewable without authentication."""
        res_inst = self.client.get(f'/registry/institutions/{self.univ.pk}/')
        self.assertEqual(res_inst.status_code, 200)
        self.assertContains(res_inst, self.univ.name)
        self.assertContains(res_inst, "كلية الطب والعلوم الصحية")

        res_prog = self.client.get(f'/registry/programs/{self.program.pk}/')
        self.assertEqual(res_prog.status_code, 200)
        self.assertContains(res_prog, self.program.name)
        self.assertContains(res_prog, "إرشادات هامة للطلاب")

    def test_public_verify_search_negative_feedback(self):
        """Searching for non-existent certificate returns fraud prevention alert."""
        res = self.client.get('/registry/?tab=verify&verify_code=FAKE-CERT-9999')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "لم يتم العثور على أي وثيقة اعتماد مطابقة")
        self.assertContains(res, "تنبيه توعوي للطلاب")

    def test_institution_create_by_secretariat(self):
        """Secretariat can register new institutions directly via the portal form."""
        sec_user = User.objects.create_user(
            username="sec_reg_officer",
            password="password123",
            role=User.Roles.COUNCIL_SECRETARY
        )
        self.client.login(username="sec_reg_officer", password="password123")

        # GET form
        res_get = self.client.get(reverse('institutions:create'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "استمارة قيد وترخيص مؤسسة تعليم عالي جديدة")

        # POST create
        res_post = self.client.post(reverse('institutions:create'), {
            'name': 'جامعة المستقبل الأهلية',
            'code': 'FUT-UNIV',
            'institution_type': 'PRIVATE_UNIVERSITY',
            'decree_number': 'قرار جمهوري رقم (320) لسنة 2024',
            'establishment_year': 2024,
            'governorate': 'صنعاء',
            'city': 'صنعاء',
            'official_email': 'info@future.edu.ye',
            'official_phone': '01234567',
            'president_name': 'أ.د. رئيس جامعة المستقبل'
        })
        self.assertEqual(res_post.status_code, 302)
        inst = Institution.objects.filter(code='FUT-UNIV').first()
        self.assertIsNotNone(inst)
        self.assertEqual(inst.name, 'جامعة المستقبل الأهلية')
        self.assertEqual(inst.decree_number, 'قرار جمهوري رقم (320) لسنة 2024')



