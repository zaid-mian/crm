from django.contrib import admin
from django.utils.html import format_html
from .models import Product, Module, PricingPlan, PlanModule, Service, ServiceFeature, Discount

class PricingPlanInline(admin.TabularInline):
    model = PricingPlan
    extra = 1
    fields = ('name', 'price', 'currency', 'billing_cycle', 'is_active', 'display_order')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'display_order', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description')
    list_filter = ('is_active',)
    fields = ('name', 'slug', 'description', 'image', 'image_preview', 'is_active', 'display_order')
    readonly_fields = ('image_preview',)
    inlines = [PricingPlanInline]

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 200px; max-width: 200px; border-radius: 8px;" />', obj.image.url)
        return "No image uploaded yet."
    image_preview.short_description = 'Image Preview'


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('product', 'name', 'code', 'is_active', 'display_order', 'created_at')
    search_fields = ('name', 'code')
    list_filter = ('product', 'is_active')


class PlanModuleInline(admin.TabularInline):
    model = PlanModule
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "module":
            plan_id = request.resolver_match.kwargs.get('object_id')
            if plan_id:
                try:
                    plan = PricingPlan.objects.get(pk=plan_id)
                    if plan.product:
                        kwargs["queryset"] = db_field.related_model.objects.filter(product=plan.product)
                except PricingPlan.DoesNotExist:
                    pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class DiscountInline(admin.TabularInline):
    model = Discount
    extra = 1
    fields = ('name', 'discount_type', 'value', 'is_active', 'start_date', 'end_date')


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ('product', 'service', 'name', 'price', 'currency', 'billing_cycle', 'is_active', 'display_order')
    list_filter = ('product', 'service', 'billing_cycle', 'is_active')
    inlines = [PlanModuleInline, DiscountInline]


class ServiceFeatureInline(admin.TabularInline):
    model = ServiceFeature
    extra = 1


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'display_order', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'short_description', 'full_description')
    list_filter = ('is_active',)
    fields = ('name', 'slug', 'short_description', 'full_description', 'image', 'image_preview', 'is_active', 'display_order')
    readonly_fields = ('image_preview',)
    inlines = [ServiceFeatureInline, PricingPlanInline]

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 200px; max-width: 200px; border-radius: 8px;" />', obj.image.url)
        return "No image uploaded yet."
    image_preview.short_description = 'Image Preview'


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ('name', 'pricing_plan', 'discount_type', 'value', 'is_active', 'start_date', 'end_date')
    list_filter = ('discount_type', 'is_active', 'pricing_plan')
    search_fields = ('name', 'pricing_plan__name')
