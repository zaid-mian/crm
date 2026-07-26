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
            from rest_framework.exceptions import ValidationError as DRFValidationError
            try:
                PaymentInvoiceService.generate_from_opportunity(opportunity, user=user)
            except DRFValidationError:
                pass

        return opportunity
