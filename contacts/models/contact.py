from django.db import models
from django.conf import settings

class ContactStatus(models.TextChoices):
    ACTIVE = 'Active', 'Active'
    INACTIVE = 'Inactive', 'Inactive'


class Contact(models.Model):
    """
    Contact model representing contact records in the CRM system.
    """
    full_name = models.CharField(max_length=255, db_index=True)
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.PROTECT,
        related_name='contacts'
    )

    @property
    def company_name(self):
        return self.company.name if self.company else ""

    @company_name.setter
    def company_name(self, value):
        if value:
            from companies.models import Company
            company, _ = Company.objects.get_or_create(
                name=value.strip()
            )
            self.company = company
    designation = models.CharField(max_length=255, blank=True, default='', help_text="Job title or designation.")
    phone_number = models.CharField(max_length=20, db_index=True, help_text="Primary phone number.")
    email = models.EmailField(blank=True, null=True, db_index=True)
    whatsapp = models.CharField(max_length=20, blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    country = models.CharField(max_length=100, blank=True, default='')
    
    assigned_salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_contacts',
        help_text="Salesperson assigned to manage this contact."
    )
    
    status = models.CharField(
        max_length=20,
        choices=ContactStatus.choices,
        default=ContactStatus.ACTIVE,
        db_index=True
    )
    
    notes = models.TextField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    # Audit Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        indexes = [
            models.Index(fields=['assigned_salesperson', 'status', 'is_deleted']),
            models.Index(fields=['phone_number', 'email', 'is_deleted']),
        ]

    def __str__(self):
        return f"{self.contact_code} - {self.full_name}"

    @property
    def contact_code(self):
        """Generates a human-readable identifier based on the DB ID, e.g. CT001"""
        if self.id:
            return f"CT{self.id:03d}"
        return None

    @property
    def phone(self):
        return self.phone_number

    def save(self, *args, **kwargs):
        if not hasattr(self, 'company') or self.company is None:
            from companies.models import Company
            company, _ = Company.objects.get_or_create(
                name="Default Company",
                defaults={"website": "https://default.com"}
            )
            self.company = company
        super().save(*args, **kwargs)

    def soft_delete(self):
        """Soft deletes the contact record."""
        self.is_deleted = True
        self.save(update_fields=['is_deleted', 'updated_at'])

