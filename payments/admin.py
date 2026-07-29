from django.contrib import admin

from payments.models import Payment, PaymentActivityLog, PaymentTransaction


class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    extra = 0


class PaymentActivityLogInline(admin.TabularInline):
    model = PaymentActivityLog
    extra = 0
    readonly_fields = ('action', 'description', 'user', 'created_at')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number',
        'company',
        'opportunity',
        'total_amount',
        'paid_amount',
        'status',
        'payment_date',
    )
    list_filter = ('status', 'payment_date')
    search_fields = ('invoice_number', 'company__name', 'opportunity__name')
    inlines = [PaymentTransactionInline, PaymentActivityLogInline]
