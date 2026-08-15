from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

class Lead(models.Model):
    """
    Lead model representing the entry point of the leads.
    Designed for simplicity, using default Django BigAutoField and keeping
    business logic decoupled.
    """

    # Enums using Django TextChoices
    class LeadStatus(models.TextChoices):
        NEW = 'NEW', 'New'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        CONTACTED = 'CONTACTED', 'Contacted'
        QUALIFIED = 'QUALIFIED', 'Qualified'
        DEMO_SCHEDULED = 'DEMO_SCHEDULED', 'Demo Scheduled'
        PROPOSAL_SENT = 'PROPOSAL_SENT', 'Proposal Sent'
        CONVERTED = 'CONVERTED', 'Converted'
        LOST = 'LOST', 'Lost'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'

    class LeadSource(models.TextChoices):
        WEBSITE = 'WEBSITE', 'Website'
        FACEBOOK = 'FACEBOOK', 'Facebook'
        GOOGLE_ADS = 'GOOGLE_ADS', 'Google Ads'
        REFERRAL = 'REFERRAL', 'Referral'
        WALK_IN = 'WALK_IN', 'Walk-in'
        PHONE_CALL = 'PHONE_CALL', 'Phone Call'
        EMAIL_CAMPAIGN = 'EMAIL_CAMPAIGN', 'Email Campaign'
        OTHER = 'OTHER', 'Other'

    class LostReason(models.TextChoices):
        BUDGET_TOO_HIGH = 'BUDGET_TOO_HIGH', 'Budget Too High'
        NOT_INTERESTED = 'NOT_INTERESTED', 'Not Interested'
        COMPETITOR_CHOSEN = 'COMPETITOR_CHOSEN', 'Competitor Chosen'
        NO_RESPONSE = 'NO_RESPONSE', 'No Response'
        WRONG_CONTACT = 'WRONG_CONTACT', 'Wrong Contact'
        PROJECT_POSTPONED = 'PROJECT_POSTPONED', 'Project Postponed'
        DUPLICATE_LEAD = 'DUPLICATE_LEAD', 'Duplicate Lead'
        OTHER = 'OTHER', 'Other'

    # Core Fields
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='leads')
    full_name = models.CharField(max_length=255, db_index=True)
    phone = models.CharField(max_length=20, db_index=True, blank=True, default='', help_text="Phone number for the lead.")
    email = models.EmailField(blank=True, null=True, db_index=True)
    company_name = models.CharField(max_length=255, help_text="Prospect company name as text.")
    website = models.URLField(blank=True, default='', help_text="Company website URL.")
    industry = models.CharField(max_length=50, blank=True, default='OTHER', help_text="Industry of the company.")
    employee_count = models.IntegerField(null=True, blank=True, help_text="Number of employees.")
    annual_revenue = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Annual revenue.")
    
    # Metadata & Categorization
    source = models.CharField(
        max_length=50,
        choices=LeadSource.choices,
        default=LeadSource.OTHER,
        db_index=True
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True
    )
    status = models.CharField(
        max_length=30,
        choices=LeadStatus.choices,
        default=LeadStatus.NEW,
        db_index=True
    )
    pipeline = models.ForeignKey(
        'pipeline.Pipeline',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads'
    )
    pipeline_stage = models.ForeignKey(
        'pipeline.PipelineStage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads'
    )

    # Assignment
    assigned_salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads',
        help_text="The salesperson assigned to this lead."
    )

    # Engagement Tracking
    notes = models.TextField(blank=True, null=True)
    last_contact_date = models.DateTimeField(null=True, blank=True)
    contact_attempts = models.PositiveIntegerField(default=0)

    # Conversion Flag
    is_converted = models.BooleanField(default=False, db_index=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_company = models.ForeignKey(
        'companies.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='converted_leads'
    )
    converted_contact = models.ForeignKey(
        'contacts.Contact',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='converted_leads'
    )
    converted_opportunity = models.ForeignKey(
        'opportunities.Opportunity',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='converted_leads'
    )

    # Lost Details
    lost_reason = models.CharField(
        max_length=50,
        choices=LostReason.choices,
        null=True,
        blank=True
    )
    lost_notes = models.TextField(blank=True, null=True)

    # Audit Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        indexes = [
            # Compound index for active leads assigned to salesperson
            models.Index(fields=['assigned_salesperson', 'status', 'is_converted']),
        ]

    def __str__(self):
        return f"{self.lead_code} - {self.full_name}"

    @property
    def lead_code(self):
        """Generates a human-readable identifier based on the DB ID, e.g. LD-000001"""
        if self.id:
            return f"LD-{self.id:06d}"
        return None

    def clean(self):
        super().clean()
        
        # Basic validation: ensure lost reason exists if status is Lost
        if self.status == self.LeadStatus.LOST:
            if not self.lost_reason:
                raise ValidationError(
                    {"lost_reason": "A lost reason must be provided when a lead is marked as 'Lost'."}
                )
        else:
            if self.lost_reason or self.lost_notes:
                raise ValidationError(
                    "Lost reason and lost notes can only be set when status is 'Lost'."
                )
        
        if self.pipeline and self.pipeline_stage and self.pipeline_stage.pipeline_id != self.pipeline_id:
            raise ValidationError(
                {"pipeline_stage": "Pipeline stage does not belong to the selected pipeline."}
            )

    def save(self, *args, **kwargs):
        if self.pipeline_stage and not self.pipeline:
            self.pipeline = self.pipeline_stage.pipeline
        if self.pipeline and self.pipeline_stage and self.pipeline_stage.pipeline_id != self.pipeline_id:
            raise ValidationError(
                "Pipeline stage does not belong to the selected pipeline."
            )
        super().save(*args, **kwargs)


from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()

class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('ADMIN', 'Admin'),
        ('USER', 'User'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='USER')
    role = models.ForeignKey('roles.Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='profiles')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='user_profiles')

    def __str__(self):
        return f"{self.user.username} - {self.user_type}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        from roles.services import RoleService
        u_type = 'ADMIN' if instance.is_superuser or instance.is_staff else 'USER'
        role_name = 'Administrator' if u_type == 'ADMIN' else 'Salesperson'
        role_obj = RoleService.get_default_role(role_name)
        UserProfile.objects.create(user=instance, user_type=u_type, role=role_obj)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        from roles.services import RoleService
        u_type = 'ADMIN' if instance.is_superuser or instance.is_staff else 'USER'
        role_name = 'Administrator' if u_type == 'ADMIN' else 'Salesperson'
        role_obj = RoleService.get_default_role(role_name)
        UserProfile.objects.create(user=instance, user_type=u_type, role=role_obj)
    else:
        instance.profile.save()
