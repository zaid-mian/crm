from django.contrib import admin
from contacts.models import Contact

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('contact_code', 'full_name', 'company_name', 'designation', 'phone_number', 'email', 'assigned_salesperson', 'status', 'is_deleted', 'created_at')
    list_filter = ('status', 'is_deleted', 'assigned_salesperson')
    search_fields = ('full_name', 'company_name', 'designation', 'phone_number', 'email')
    readonly_fields = ('created_at', 'updated_at')
