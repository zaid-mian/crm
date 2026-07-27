from django.db import models
from django.conf import settings
from leads.models import Lead
from contacts.models import Contact

class OpportunityStage(models.TextChoices):
    QUALIFICATION = 'QUALIFICATION', 'Qualification'
    DISCOVERY = 'DISCOVERY', 'Discovery'
    PROPOSAL = 'PROPOSAL', 'Proposal'
    NEGOTIATION = 'NEGOTIATION', 'Negotiation'
    CLOSED_WON = 'CLOSED_WON', 'Closed Won'
    CLOSED_LOST = 'CLOSED_LOST', 'Closed Lost'


class Opportunity(models.Model):
    """
    Opportunity model representing a qualified sales deal in the CRM system.
    """
    name = models.CharField(max_length=255, db_index=True)
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.PROTECT,
        related_name='opportunities'
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
    source_lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='opportunities')
    primary_contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name='opportunities')
    
    assigned_salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opportunities',
        help_text="Salesperson assigned to manage this opportunity."
    )
    
    stage = models.CharField(
        max_length=50,
        choices=OpportunityStage.choices,
        default=OpportunityStage.QUALIFICATION,
        db_index=True
    )
    pipeline_stage = models.ForeignKey(
        'pipeline.PipelineStage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opportunities'
    )
    
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    expected_close_date = models.DateField()
    lead_source = models.CharField(max_length=50, blank=True, default='')
    description = models.TextField(blank=True, default='')
    lost_reason = models.CharField(max_length=255, blank=True, default='')
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Opportunity"
        verbose_name_plural = "Opportunities"
        indexes = [
            models.Index(fields=['assigned_salesperson', 'stage']),
        ]

    def __str__(self):
        return f"{self.opportunity_code} - {self.name}"

    @property
    def opportunity_code(self):
        """Generates a human-readable identifier based on the DB ID, e.g. OP001"""
        if self.id:
            return f"OP{self.id:03d}"
        return None

    @property
    def won(self) -> bool:
        """Determines if the opportunity is won based on the current stage."""
        return self.stage == OpportunityStage.CLOSED_WON

    @property
    def closed(self) -> bool:
        """Determines if the opportunity is in a terminal stage."""
        return self.stage in (OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST)

    @property
    def probability(self) -> int:
        """Calculates closing probability dynamically based on pipeline stage."""
        mapping = {
            OpportunityStage.QUALIFICATION: 10,
            OpportunityStage.DISCOVERY: 20,
            OpportunityStage.PROPOSAL: 50,
            OpportunityStage.NEGOTIATION: 80,
            OpportunityStage.CLOSED_WON: 100,
            OpportunityStage.CLOSED_LOST: 0,
        }
        return mapping.get(self.stage, 0)

    @property
    def expected_revenue(self):
        """Expected weighted revenue (Amount * Probability / 100)"""
        from decimal import Decimal
        return (self.amount * Decimal(self.probability)) / 100

    def save(self, *args, **kwargs):
        if not hasattr(self, 'company') or self.company is None:
            from companies.models import Company
            company, _ = Company.objects.get_or_create(
                name="Default Company",
                defaults={"website": "https://default.com"}
            )
            self.company = company
        super().save(*args, **kwargs)
