from rest_framework.exceptions import ValidationError
from django.db import transaction
from opportunities.models import Opportunity, OpportunityStage

class OpportunityWorkflowService:
    @staticmethod
    def validate_stage_transition(opportunity: Opportunity, new_stage: str, user) -> None:
        """
        Validates the transition path of the opportunity stage.
        Enforces allowed transitions and terminal locking rules.
        """
        current_stage = opportunity.stage

        if current_stage == new_stage:
            return

        # Enforce terminal locking: Only Admin (superuser) can reopen Closed Won / Closed Lost
        if current_stage in (OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST):
            if not getattr(user, 'is_superuser', False):
                raise ValidationError("Only an Admin can reopen a closed opportunity.")
            if new_stage != OpportunityStage.NEGOTIATION:
                raise ValidationError("Closed opportunities can only be transitioned to Negotiation stage.")
            return

        # Sequential transition matrix
        allowed_transitions = {
            OpportunityStage.QUALIFICATION: [OpportunityStage.DISCOVERY, OpportunityStage.CLOSED_LOST],
            OpportunityStage.DISCOVERY: [OpportunityStage.QUALIFICATION, OpportunityStage.PROPOSAL, OpportunityStage.CLOSED_LOST],
            OpportunityStage.PROPOSAL: [OpportunityStage.DISCOVERY, OpportunityStage.NEGOTIATION, OpportunityStage.CLOSED_LOST],
            OpportunityStage.NEGOTIATION: [OpportunityStage.PROPOSAL, OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST],
        }

        valid_targets = allowed_transitions.get(current_stage, [])
        if new_stage not in valid_targets:
            raise ValidationError(f"Invalid stage transition from {current_stage} to {new_stage}.")

    @staticmethod
    @transaction.atomic
    def change_stage(opportunity: Opportunity, new_stage: str, lost_reason: str, user) -> Opportunity:
        """
        Validates and transitions the opportunity stage.
        """
        OpportunityWorkflowService.validate_stage_transition(opportunity, new_stage, user)
        
        if new_stage == OpportunityStage.CLOSED_LOST:
            if not lost_reason:
                raise ValidationError("A lost reason is required when closing an opportunity as Lost.")
            opportunity.lost_reason = lost_reason
        else:
            opportunity.lost_reason = ""

        opportunity.stage = new_stage
        opportunity.save()

        if new_stage == OpportunityStage.CLOSED_WON:
            from payments.services.invoice import PaymentInvoiceService
            PaymentInvoiceService.generate_from_opportunity(opportunity, user=user)

        return opportunity

    @staticmethod
    @transaction.atomic
    def update_opportunity_stage(opportunity: Opportunity, target_stage, user=None, change_source='API') -> Opportunity:
        old_stage = opportunity.pipeline_stage
        old_pipeline = opportunity.pipeline

        # Rule 3: Pipeline switching must never silently convert Lead ↔ Opportunity
        if target_stage.entity_type == 'LEAD':
            raise ValidationError("Opportunities cannot be moved to Lead stages.")

        opportunity.pipeline_stage = target_stage
        opportunity.pipeline = target_stage.pipeline

        if target_stage.stage_type == 'CONVERSION':
            opportunity.stage = 'QUALIFICATION'
        elif target_stage.stage_type == 'NORMAL_OPPORTUNITY':
            if target_stage.order == 4:
                opportunity.stage = 'PROPOSAL'
            else:
                opportunity.stage = 'NEGOTIATION'
        elif target_stage.stage_type == 'WON':
            opportunity.stage = 'CLOSED_WON'
        elif target_stage.stage_type == 'LOST':
            opportunity.stage = 'CLOSED_LOST'

        opportunity.save()

        if opportunity.stage == 'CLOSED_WON':
            from payments.services.invoice import PaymentInvoiceService
            PaymentInvoiceService.generate_from_opportunity(opportunity, user=user)

        if old_stage != target_stage or old_pipeline != target_stage.pipeline:
            from pipeline.models import PipelineAuditLog
            PipelineAuditLog.objects.create(
                user=user,
                opportunity=opportunity,
                from_stage=old_stage,
                to_stage=target_stage,
                from_stage_name=old_stage.name if old_stage else 'None',
                to_stage_name=target_stage.name,
                change_source=change_source
            )
        return opportunity
