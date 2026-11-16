from django.contrib import admin
from .models import StandardVersion, StandardCategory, StandardIndicator

@admin.register(StandardVersion)
class StandardVersionAdmin(admin.ModelAdmin):
    list_display = ('title', 'track', 'version_number', 'status', 'effective_date', 'adoption_decree')
    list_filter = ('track', 'status')
    search_fields = ('title', 'version_number', 'adoption_decree', 'changelog')

class StandardIndicatorInline(admin.StackedInline):
    model = StandardIndicator
    extra = 1

@admin.register(StandardCategory)
class StandardCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'track', 'version', 'weight_percentage', 'order', 'is_active')
    list_filter = ('track', 'version', 'is_active')
    search_fields = ('code', 'title', 'description')
    inlines = [StandardIndicatorInline]

@admin.register(StandardIndicator)
class StandardIndicatorAdmin(admin.ModelAdmin):
    list_display = ('code', 'category', 'title', 'is_core_standard', 'order')
    list_filter = ('category__track', 'is_core_standard', 'category')
    search_fields = ('code', 'title', 'explanation', 'suggested_evidences')
