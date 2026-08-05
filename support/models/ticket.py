from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from accounts.models import Organization

class Ticket(models.Model):
    CATEGORY_CHOICES = [
        ('technical', 'Technical'),
        ('billing', 'Billing'),
        ('account', 'Account'),
        ('feature_request', 'Feature Request'),
        ('bug_report', 'Bug Report'),
        ('general', 'General'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    ticket_number = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
        help_text="Tenant organization scoping for this ticket"
    )
    subject = models.CharField(max_length=255)
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='general'
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='open'
    )
    message = models.TextField(help_text="Initial customer issue description.")
    
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tickets'
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_tickets'
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.assigned_to and not self.assigned_to.is_staff:
            is_support = False
            from django.apps import apps
            if apps.is_installed('leads'):
                try:
                    profile = getattr(self.assigned_to, 'profile', None) or getattr(self.assigned_to, 'userprofile', None)
                    if profile:
                        if profile.user_type == 'ADMIN' or (profile.role and profile.role.name in ('Administrator', 'Support Agent', 'Support Manager')):
                            is_support = True
                except Exception:
                    pass
            if not is_support:
                raise ValidationError("Tickets can only be assigned to staff members or support agents.")

    def save(self, *args, **kwargs):
        # Auto closed_at mapping
        if self.status == 'closed':
            if not self.closed_at:
                self.closed_at = timezone.now()
        else:
            self.closed_at = None
            self.closed_by = None

        is_new = self.pk is None
        if is_new and not self.ticket_number:
            # Generate ticket number. unique=True constraint guarantees DB safety.
            max_id = Ticket.objects.aggregate(max_id=models.Max('id'))['max_id'] or 0
            self.ticket_number = f"TKT-{1000 + max_id + 1}"

        super().save(*args, **kwargs)

    def soft_delete(self):
        self.is_deleted = True
        self.save(update_fields=['is_deleted', 'updated_at'])

    def __str__(self):
        return f"{self.ticket_number} - {self.subject} ({self.get_status_display()})"
