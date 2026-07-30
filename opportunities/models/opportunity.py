from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
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
    pipeline = models.ForeignKey(
        'pipeline.Pipeline',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opportunities'
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
    priority = models.CharField(
        max_length=10,
        choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High')],
        default='MEDIUM',
        db_index=True
    )
    custom_values = models.JSONField(default=dict, blank=True, null=True)
    
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

    def _get_mapped_stage_from_pipeline_stage(self):
        if not self.pipeline_stage:
            return None
        stage_name = self.pipeline_stage.name.upper()
        if 'WON' in stage_name:
            return OpportunityStage.CLOSED_WON
        elif 'LOST' in stage_name:
            return OpportunityStage.CLOSED_LOST
        elif 'PROPOSAL' in stage_name:
            return OpportunityStage.PROPOSAL
        elif 'NEGOTIATION' in stage_name:
            return OpportunityStage.NEGOTIATION
        elif 'DISCOVERY' in stage_name or 'FOLLOW' in stage_name:
            return OpportunityStage.DISCOVERY
        elif 'QUALIFIED' in stage_name or 'QUALIFICATION' in stage_name:
            return OpportunityStage.QUALIFICATION
        
        st = self.pipeline_stage.stage_type
        if st == 'WON':
            return OpportunityStage.CLOSED_WON
        elif st == 'LOST':
            return OpportunityStage.CLOSED_LOST
        elif st == 'CONVERSION':
            return OpportunityStage.QUALIFICATION
        return OpportunityStage.NEGOTIATION

    def _is_stage_in_sync_with_pipeline_stage(self):
        if not self.pipeline_stage:
            return True
        return self.stage == self._get_mapped_stage_from_pipeline_stage()

    @property
    def won(self) -> bool:
        """Determines if the opportunity is won based on the current stage."""
        if not self._is_stage_in_sync_with_pipeline_stage():
            self._sync_pipeline_stage_from_stage()
        if self.pipeline_stage:
            return self.pipeline_stage.stage_type == 'WON'
        return self.stage == OpportunityStage.CLOSED_WON

    @property
    def closed(self) -> bool:
        """Determines if the opportunity is in a terminal stage."""
        if not self._is_stage_in_sync_with_pipeline_stage():
            self._sync_pipeline_stage_from_stage()
        if self.pipeline_stage:
            return self.pipeline_stage.stage_type in ('WON', 'LOST')
        return self.stage in (OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST)

    @property
    def probability(self) -> int:
        """Calculates closing probability dynamically based on pipeline stage."""
        if not self._is_stage_in_sync_with_pipeline_stage():
            self._sync_pipeline_stage_from_stage()
        if self.pipeline_stage:
            if self.pipeline_stage.stage_type == 'WON':
                return 100
            elif self.pipeline_stage.stage_type == 'LOST':
                return 0
            elif self.pipeline_stage.stage_type == 'CONVERSION':
                return 10
            elif 'DISCOVERY' in self.pipeline_stage.name.upper() or 'FOLLOW' in self.pipeline_stage.name.upper():
                return 20
            
            pipeline = self.pipeline or self.pipeline_stage.pipeline
            if pipeline:
                stages = list(pipeline.stages.filter(is_deleted=False).order_by('order'))
                opp_stages = [s for s in stages if s.entity_type == 'OPPORTUNITY' or s.stage_type in ('CONVERSION', 'WON', 'LOST')]
                if self.pipeline_stage in opp_stages:
                    idx = opp_stages.index(self.pipeline_stage)
                    n = len(opp_stages)
                    if n > 2:
                        return int(20 + (idx - 1) * (70 / (n - 2)))
            return 50

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

    def _sync_stage_from_pipeline_stage(self):
        """
        Synchronizes the legacy stage field from the authoritative pipeline_stage.
        For backward compatibility with older components/APIs expecting the legacy stage.
        """
        mapped = self._get_mapped_stage_from_pipeline_stage()
        if mapped:
            self.stage = mapped

    def _sync_pipeline_stage_from_stage(self):
        """
        TEMPORARY/LEGACY FALLBACK: Resolves pipeline_stage from legacy stage.
        Required only for compatibility with legacy tests or APIs that explicitly
        write to the legacy 'stage' field.
        """
        if not self.stage:
            return
        if not self.pipeline:
            from pipeline.models import Pipeline
            self.pipeline = Pipeline.objects.filter(is_default=True).first() or Pipeline.objects.first()
        if not self.pipeline:
            return

        if self.stage == OpportunityStage.CLOSED_WON:
            target = self.pipeline.stages.filter(stage_type='WON', is_deleted=False).first()
        elif self.stage == OpportunityStage.CLOSED_LOST:
            target = self.pipeline.stages.filter(stage_type='LOST', is_deleted=False).first()
        elif self.stage == OpportunityStage.QUALIFICATION:
            target = self.pipeline.stages.filter(stage_type='CONVERSION', is_deleted=False).first()
        elif self.stage == OpportunityStage.DISCOVERY:
            target = self.pipeline.stages.filter(name__icontains='follow', is_deleted=False).first()
            if not target:
                target = self.pipeline.stages.filter(name__icontains='discovery', is_deleted=False).first()
        else:
            name_part = self.stage.lower()
            target = self.pipeline.stages.filter(name__icontains=name_part, is_deleted=False).first()
            if not target:
                target = self.pipeline.stages.filter(stage_type='NORMAL_OPPORTUNITY', is_deleted=False).first()
        
        if target:
            self.pipeline_stage = target

    def clean(self):
        super().clean()
        if self.pipeline and self.pipeline_stage and self.pipeline_stage.pipeline_id != self.pipeline_id:
            raise ValidationError(
                {"pipeline_stage": "Pipeline stage does not belong to the selected pipeline."}
            )

    def save(self, *args, **kwargs):
        # 1. Ensure pipeline is set
        if self.pipeline_stage and not self.pipeline:
            self.pipeline = self.pipeline_stage.pipeline
        if self.pipeline and self.pipeline_stage and self.pipeline_stage.pipeline_id != self.pipeline_id:
            raise ValidationError(
                "Pipeline stage does not belong to the selected pipeline."
            )

        # 2. TEMPORARY/LEGACY FALLBACK:
        # If pipeline_stage is not provided but stage is, OR if this is an existing
        # object and ONLY the legacy stage field is modified, resolve the pipeline_stage.
        if not self.pipeline_stage and self.stage:
            self._sync_pipeline_stage_from_stage()
        elif self.pk:
            db_obj = Opportunity.objects.filter(pk=self.pk).first()
            if db_obj and self.stage != db_obj.stage and self.pipeline_stage == db_obj.pipeline_stage:
                self._sync_pipeline_stage_from_stage()

        # 3. Authoritative Sync: Always ensure legacy stage matches pipeline_stage
        if self.pipeline_stage:
            self._sync_stage_from_pipeline_stage()

        if not hasattr(self, 'company') or self.company is None:
            from companies.models import Company
            company, _ = Company.objects.get_or_create(
                name="Default Company",
                defaults={"website": "https://default.com"}
            )
            self.company = company
        super().save(*args, **kwargs)
