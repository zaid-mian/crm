from django.db import models
from django.conf import settings

class CompanyType(models.TextChoices):
    PROSPECT = 'PROSPECT', 'Prospect'
    CUSTOMER = 'CUSTOMER', 'Customer'
    PARTNER = 'PARTNER', 'Partner'
    COMPETITOR = 'COMPETITOR', 'Competitor'
    OTHER = 'OTHER', 'Other'


class CompanyRating(models.TextChoices):
    NONE = 'NONE', 'None'
    HOT = 'HOT', 'Hot'
    WARM = 'WARM', 'Warm'
    COLD = 'COLD', 'Cold'


class CompanyIndustry(models.TextChoices):
    TECHNOLOGY = 'TECHNOLOGY', 'Technology'
    FINANCE = 'FINANCE', 'Finance'
    HEALTHCARE = 'HEALTHCARE', 'Healthcare'
    EDUCATION = 'EDUCATION', 'Education'
    RETAIL = 'RETAIL', 'Retail'
    MANUFACTURING = 'MANUFACTURING', 'Manufacturing'
    OTHER = 'OTHER', 'Other'


class Company(models.Model):
    """
    Company model representing Accounts in the CRM system.
    """
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='companies')
    name = models.CharField(max_length=255, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True, db_index=True)
    
    type = models.CharField(
        max_length=50,
        choices=CompanyType.choices,
        default=CompanyType.PROSPECT,
        db_index=True
    )
    
    rating = models.CharField(
        max_length=50,
        choices=CompanyRating.choices,
        default=CompanyRating.NONE,
        db_index=True
    )
    
    industry = models.CharField(
        max_length=50,
        choices=CompanyIndustry.choices,
        default=CompanyIndustry.OTHER,
        db_index=True
    )
    
    annual_revenue = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    employee_count = models.IntegerField(null=True, blank=True)
    lead_source = models.CharField(max_length=50, blank=True, default='')
    website = models.URLField(blank=True, default='', db_index=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    billing_address = models.CharField(max_length=255, blank=True, default='')
    shipping_address = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    
    parent_company = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subsidiaries'
    )
    
    assigned_salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='companies',
        help_text="Salesperson assigned to manage this company."
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self):
        return f"{self.company_code or 'CO_NEW'} - {self.name}"

    @property
    def company_code(self):
        """Generates a human-readable identifier based on the DB ID, e.g. CO001"""
        if self.id:
            return f"CO{self.id:03d}"
        return None
