from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import ContactMessage, Ticket, TicketReply

class TicketReplyInline(admin.TabularInline):
    model = TicketReply
    extra = 1
    readonly_fields = ('created_at',)
    fields = ('sender', 'message', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('sender', 'message', 'created_at')
        return ('created_at',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'status', 'submitted_at')
    list_filter = ('status', 'submitted_at')
    search_fields = ('name', 'email', 'subject')
    readonly_fields = ('name', 'email', 'subject', 'message', 'submitted_at')
    fields = ('name', 'email', 'subject', 'message', 'status', 'submitted_at')


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number',
        'user',
        'organization',
        'subject',
        'category',
        'priority',
        'status',
        'assigned_to',
        'is_deleted',
        'created_at'
    )
    list_filter = ('status', 'priority', 'category', 'assigned_to', 'is_deleted')
    search_fields = ('ticket_number', 'subject', 'user__email', 'organization__name')
    readonly_fields = (
        'ticket_number',
        'user',
        'organization',
        'subject',
        'category',
        'message',
        'closed_by',
        'closed_at',
        'created_at',
        'updated_at'
    )
    fields = (
        'ticket_number',
        'user',
        'organization',
        'subject',
        'category',
        'priority',
        'status',
        'message',
        'assigned_to',
        'closed_by',
        'closed_at',
        'is_deleted',
        'created_at',
        'updated_at'
    )
    inlines = [TicketReplyInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, TicketReply) and not instance.pk:
                instance.sender = request.user
            instance.save()
        formset.save_m2m()
