from django.contrib import admin
from .models import Institution, College, Department, AcademicProgram

class CollegeInline(admin.StackedInline):
    model = College
    extra = 1

class DepartmentInline(admin.TabularInline):
    model = Department
    extra = 1

class AcademicProgramInline(admin.TabularInline):
    model = AcademicProgram
    extra = 1

@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'institution_type', 'governorate', 'president_name', 'quality_center_dean', 'created_at')
    list_filter = ('institution_type', 'governorate')
    search_fields = ('name', 'code', 'president_name', 'quality_center_dean')
    inlines = [CollegeInline]

@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'dean_name', 'establishment_year')
    list_filter = ('institution',)
    search_fields = ('name', 'dean_name')
    inlines = [DepartmentInline, AcademicProgramInline]

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'college', 'head_name', 'establishment_year')
    list_filter = ('college__institution', 'college')
    search_fields = ('name', 'head_name')
    inlines = [AcademicProgramInline]

@admin.register(AcademicProgram)
class AcademicProgramAdmin(admin.ModelAdmin):
    list_display = ('name', 'college', 'department', 'degree_level', 'study_system', 'study_duration_years', 'total_credit_hours')
    list_filter = ('degree_level', 'study_system', 'college__institution')
    search_fields = ('name', 'code', 'department_head')
