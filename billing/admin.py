from django.contrib import admin
from billing.models import BillingCustomer


@admin.register(BillingCustomer)
class BillingCustomerAdmin(admin.ModelAdmin):
    list_display = ('customer_number', 'name', 'email', 'organization', 'currency', 'is_active', 'created_at')
    list_filter = ('is_active', 'currency', 'organization')
    search_fields = ('customer_number', 'name', 'email', 'tax_id', 'external_reference_id')
    readonly_fields = ('created_at', 'updated_at')
