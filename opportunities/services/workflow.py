from rest_framework.exceptions import ValidationError
from django.db import transaction
from opportunities.models import Opportunity, OpportunityStage

class OpportunityWorkflowService:
    @staticmethod
    def get_target_pipeline_stage(opportunity: Opportunity, stage_str: str):
        pipeline = opportunity.pipeline
        if not pipeline:
            from pipeline.models import Pipeline
            pipeline = Pipeline.objects.filter(is_default=True).first() or Pipeline.objects.first()
        if not pipeline:
            return None

        if stage_str == OpportunityStage.CLOSED_WON:
            return pipeline.stages.filter(stage_type='WON', is_deleted=False).first()
        elif stage_str == OpportunityStage.CLOSED_LOST:
            return pipeline.stages.filter(stage_type='LOST', is_deleted=False).first()
        elif stage_str == OpportunityStage.QUALIFICATION:
            return pipeline.stages.filter(stage_type='CONVERSION', is_deleted=False).first()
        elif stage_str == OpportunityStage.DISCOVERY:
            target = pipeline.stages.filter(name__icontains='follow', is_deleted=False).first()
            if not target:
                target = pipeline.stages.filter(name__icontains='discovery', is_deleted=False).first()
            return target
        else:
            name_part = stage_str.lower()
            target = pipeline.stages.filter(name__icontains=name_part, is_deleted=False).first()
            if not target:
                target = pipeline.stages.filter(stage_type='NORMAL_OPPORTUNITY', is_deleted=False).first()
            return target

    @staticmethod
    def validate_stage_transition_dynamic(opportunity: Opportunity, target_stage, user) -> None:
        """
        Validates the transition path of the opportunity stage dynamically using PipelineStage.
        Enforces adjacent sequence movement, terminal stage locking, and pipeline matching.
        """
        current_stage = opportunity.pipeline_stage

        if not current_stage:
            # If there is no current stage, any valid opportunity stage in the pipeline is allowed
            if target_stage.entity_type == 'LEAD' and not ('FOLLOW' in target_stage.name.upper() or 'DISCOVERY' in target_stage.name.upper()):
                raise ValidationError("Opportunities cannot be moved to Lead stages.")
            return

        if current_stage == target_stage:
            return

        # 1. Pipeline mismatch check
        pipeline = opportunity.pipeline or target_stage.pipeline
        if target_stage.pipeline != pipeline:
            raise ValidationError("Target stage does not belong to the opportunity's active pipeline.")

        # 2. Entity type check
        if target_stage.entity_type == 'LEAD' and not ('FOLLOW' in target_stage.name.upper() or 'DISCOVERY' in target_stage.name.upper()):
            raise ValidationError("Opportunities cannot be moved to Lead stages.")

        # 3. Enforce terminal locking: Only Admin (superuser) can reopen Closed Won / Closed Lost
        is_current_terminal = current_stage.stage_type in ('WON', 'LOST')
        if is_current_terminal:
            if not getattr(user, 'is_superuser', False):
                raise ValidationError("Only an Admin can reopen a closed opportunity.")
            # Closed opportunities can only be transitioned to an active opportunity stage
            if target_stage.stage_type in ('WON', 'LOST') or target_stage.entity_type == 'LEAD':
                raise ValidationError("Closed opportunities can only be transitioned to an active opportunity stage.")
            return

        # 4. Sequential transition check: next stage, previous stage, or any LOST stage
        def get_stage_sort_value(s):
            if s.stage_type == 'CONVERSION':
                return 1
            if 'FOLLOW' in s.name.upper() or 'DISCOVERY' in s.name.upper():
                return 2
            if s.stage_type == 'WON':
                return 9998
            if s.stage_type == 'LOST':
                return 9999
            return 100 + s.order

        stages = list(pipeline.stages.filter(is_deleted=False).order_by('order'))
        
        # List 1: including legacy Follow Up / Discovery
        opp_stages_legacy = [s for s in stages if s.entity_type == 'OPPORTUNITY' or 'FOLLOW' in s.name.upper() or 'DISCOVERY' in s.name.upper()]
        opp_stages_legacy = sorted(opp_stages_legacy, key=get_stage_sort_value)
        
        # List 2: strictly OPPORTUNITY stages
        opp_stages_strict = [s for s in stages if s.entity_type == 'OPPORTUNITY']
        opp_stages_strict = sorted(opp_stages_strict, key=lambda s: s.order)

        if target_stage not in opp_stages_legacy and target_stage not in opp_stages_strict:
            raise ValidationError(f"Target stage '{target_stage.name}' is not a valid opportunity stage.")

        # Check adjacency in List 1 (legacy list)
        is_adjacent_legacy = False
        if current_stage in opp_stages_legacy and target_stage in opp_stages_legacy:
            c_idx = opp_stages_legacy.index(current_stage)
            t_idx = opp_stages_legacy.index(target_stage)
            is_adjacent_legacy = abs(t_idx - c_idx) == 1

        # Check adjacency in List 2 (strict opportunity list)
        is_adjacent_strict = False
        if current_stage in opp_stages_strict and target_stage in opp_stages_strict:
            c_idx = opp_stages_strict.index(current_stage)
            t_idx = opp_stages_strict.index(target_stage)
            is_adjacent_strict = abs(t_idx - c_idx) == 1

        is_adjacent = is_adjacent_legacy or is_adjacent_strict
        is_lost = target_stage.stage_type == 'LOST'
        
        if not (is_adjacent or is_lost):
            raise ValidationError(
                f"Invalid stage transition from {current_stage.name} to {target_stage.name}."
            )

    @staticmethod
    def validate_stage_transition(opportunity: Opportunity, new_stage: str, user) -> None:
        """
        Validates the transition path of the opportunity stage (backward compatibility).
        Delegates to the dynamic transition validation method.
        """
        target_stage = OpportunityWorkflowService.get_target_pipeline_stage(opportunity, new_stage)
        if not target_stage:
            raise ValidationError(f"Could not resolve pipeline stage for legacy stage '{new_stage}'.")
        OpportunityWorkflowService.validate_stage_transition_dynamic(opportunity, target_stage, user)

    @staticmethod
    @transaction.atomic
    def change_stage(opportunity: Opportunity, new_stage: str, lost_reason: str, user) -> Opportunity:
        """
        Validates and transitions the opportunity stage.
        Uses pipeline_stage as the single source of truth.
        """
        target_stage = OpportunityWorkflowService.get_target_pipeline_stage(opportunity, new_stage)
        if not target_stage:
            raise ValidationError(f"Could not resolve pipeline stage for legacy stage '{new_stage}'.")

        OpportunityWorkflowService.validate_stage_transition_dynamic(opportunity, target_stage, user)
        
        if target_stage.stage_type == 'LOST':
            if not lost_reason:
                raise ValidationError("A lost reason is required when closing an opportunity as Lost.")
            opportunity.lost_reason = lost_reason
        else:
            opportunity.lost_reason = ""

        opportunity.pipeline_stage = target_stage
        opportunity.pipeline = target_stage.pipeline
        opportunity.save()

        # Trigger invoice generation when target PipelineStage.stage_type == "WON"
        if target_stage.stage_type == 'WON':
            from payments.services.invoice import PaymentInvoiceService
            PaymentInvoiceService.generate_from_opportunity(opportunity, user=user)

        return opportunity

    @staticmethod
    @transaction.atomic
    def update_opportunity_stage(opportunity: Opportunity, target_stage, user=None, change_source='API', lost_reason='') -> Opportunity:
        """
        Transitions the opportunity to the target pipeline_stage.
        """
        OpportunityWorkflowService.validate_stage_transition_dynamic(opportunity, target_stage, user)

        old_stage = opportunity.pipeline_stage
        old_pipeline = opportunity.pipeline

        opportunity.pipeline_stage = target_stage
        opportunity.pipeline = target_stage.pipeline

        if target_stage.stage_type == 'LOST':
            opportunity.lost_reason = lost_reason or opportunity.lost_reason or "Stage changed via pipeline board"
        else:
            opportunity.lost_reason = ""

        opportunity.save()

        # Trigger invoice generation when target PipelineStage.stage_type == "WON"
        if target_stage.stage_type == 'WON':
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
