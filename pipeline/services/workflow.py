from django.db import transaction
from rest_framework.exceptions import ValidationError
from pipeline.models import PipelineStage
from leads.models import Lead
from opportunities.models import Opportunity

class PipelineWorkflowService:
    @staticmethod
    @transaction.atomic
    def configure_pipeline_behavior(pipeline, conversion_stage_id, won_stage_id=None, lost_stage_id=None):
        """
        Infers and configures stage behaviors based on explicit user anchor selections,
        running strict Universal Boundary Validation checks beforehand.
        """
        # 1. Retrieve anchors
        try:
            conversion_stage = PipelineStage.objects.get(pk=conversion_stage_id, pipeline=pipeline)
        except PipelineStage.DoesNotExist:
            raise ValidationError("Selected conversion stage does not exist in this pipeline.")

        won_stage = None
        if won_stage_id:
            try:
                won_stage = PipelineStage.objects.get(pk=won_stage_id, pipeline=pipeline)
            except PipelineStage.DoesNotExist:
                raise ValidationError("Selected Won stage does not exist in this pipeline.")

        lost_stage = None
        if lost_stage_id:
            try:
                lost_stage = PipelineStage.objects.get(pk=lost_stage_id, pipeline=pipeline)
            except PipelineStage.DoesNotExist:
                raise ValidationError("Selected Lost stage does not exist in this pipeline.")

        # 2. Invariant validations
        if won_stage and conversion_stage.id == won_stage.id:
            raise ValidationError("Conversion stage cannot be the same as the Won stage.")
        if lost_stage and conversion_stage.id == lost_stage.id:
            raise ValidationError("Conversion stage cannot be the same as the Lost stage.")
        if won_stage and lost_stage and won_stage.id == lost_stage.id:
            raise ValidationError("Won stage cannot be the same as the Lost stage.")

        # Retrieve all active stages sorted by order
        stages = list(PipelineStage.objects.filter(pipeline=pipeline).order_by('order'))
        if not stages:
            raise ValidationError("Pipeline has no stages configured.")

        # Ensure conversion is not the first stage
        if stages[0].id == conversion_stage.id:
            raise ValidationError("The conversion stage cannot be the first stage. There must be at least one Lead stage.")

        # Ordering check
        if won_stage and conversion_stage.order >= won_stage.order:
            raise ValidationError("The conversion stage must be ordered before the Won stage.")
        if lost_stage and conversion_stage.order >= lost_stage.order:
            raise ValidationError("The conversion stage must be ordered before the Lost stage.")

        # 3. Compute proposed classifications
        proposed_classifications = {}
        for s in stages:
            if s.id == conversion_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'CONVERSION')
            elif won_stage and s.id == won_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'WON')
            elif lost_stage and s.id == lost_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'LOST')
            elif s.order < conversion_stage.order:
                proposed_classifications[s.id] = ('LEAD', 'NORMAL_LEAD')
            else:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'NORMAL_OPPORTUNITY')

        # 4. Universal Boundary Validation: detect boundary flips on stages with active cards
        for s in stages:
            try:
                original_stage = PipelineStage.all_objects.get(pk=s.id)
                old_entity = original_stage.entity_type
            except PipelineStage.DoesNotExist:
                old_entity = None

            new_entity, new_type = proposed_classifications[s.id]
            if old_entity and old_entity != new_entity:
                if old_entity == 'LEAD':
                    if Lead.objects.filter(pipeline_stage=s, is_converted=False).exists():
                        raise ValidationError(
                            f"Cannot modify pipeline structure: Stage '{s.name}' would change from Lead to Opportunity while containing active Leads. Please move these leads first."
                        )
                else:
                    if Opportunity.objects.filter(pipeline_stage=s).exists():
                        raise ValidationError(
                            f"Cannot modify pipeline structure: Stage '{s.name}' would change from Opportunity to Lead while containing active Opportunities. Please move these opportunities first."
                        )

        # 5. Apply classifications
        for s in stages:
            new_entity, new_type = proposed_classifications[s.id]
            s.entity_type = new_entity
            s.stage_type = new_type
            s.save()

        return stages

    @staticmethod
    @transaction.atomic
    def validate_and_recompute_pipeline_boundaries(pipeline):
        """
        Triggers automatically when stages are created, updated, or reordered to maintain
        consistent boundaries based on the current designated anchors.
        """
        stages = list(PipelineStage.objects.filter(pipeline=pipeline).order_by('order'))
        if not stages:
            return

        conversion_stage = None
        won_stage = None
        lost_stage = None
        for s in stages:
            if s.stage_type == 'CONVERSION':
                conversion_stage = s
            elif s.stage_type == 'WON':
                won_stage = s
            elif s.stage_type == 'LOST':
                lost_stage = s

        # If no conversion stage is designated yet, classify everything as Lead
        if not conversion_stage:
            for s in stages:
                if s.entity_type != 'LEAD' or s.stage_type != 'NORMAL_LEAD':
                    s.entity_type = 'LEAD'
                    s.stage_type = 'NORMAL_LEAD'
                    s.save()
            return

        # Ensure conversion is not the first stage
        if stages[0].id == conversion_stage.id:
            raise ValidationError("The conversion stage cannot be the first stage. There must be at least one Lead stage.")

        # Ordering check
        if won_stage and conversion_stage.order >= won_stage.order:
            raise ValidationError("The conversion stage must be ordered before the Won stage.")
        if lost_stage and conversion_stage.order >= lost_stage.order:
            raise ValidationError("The conversion stage must be ordered before the Lost stage.")

        # Compute proposed classifications
        proposed_classifications = {}
        for s in stages:
            if s.id == conversion_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'CONVERSION')
            elif won_stage and s.id == won_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'WON')
            elif lost_stage and s.id == lost_stage.id:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'LOST')
            elif s.order < conversion_stage.order:
                proposed_classifications[s.id] = ('LEAD', 'NORMAL_LEAD')
            else:
                proposed_classifications[s.id] = ('OPPORTUNITY', 'NORMAL_OPPORTUNITY')

        # Check for boundary flips on stages with active cards
        for s in stages:
            try:
                original_stage = PipelineStage.all_objects.get(pk=s.id)
                old_entity = original_stage.entity_type
            except PipelineStage.DoesNotExist:
                old_entity = None

            new_entity, new_type = proposed_classifications[s.id]
            if old_entity and old_entity != new_entity:
                if old_entity == 'LEAD':
                    if Lead.objects.filter(pipeline_stage=s, is_converted=False).exists():
                        raise ValidationError(
                            f"Cannot modify pipeline structure: Stage '{s.name}' would change from Lead to Opportunity while containing active Leads. Please move these leads first."
                        )
                else:
                    if Opportunity.objects.filter(pipeline_stage=s).exists():
                        raise ValidationError(
                            f"Cannot modify pipeline structure: Stage '{s.name}' would change from Opportunity to Lead while containing active Opportunities. Please move these opportunities first."
                        )

        # Save boundaries
        for s in stages:
            new_entity, new_type = proposed_classifications[s.id]
            if s.entity_type != new_entity or s.stage_type != new_type:
                s.entity_type = new_entity
                s.stage_type = new_type
                s.save()

    @staticmethod
    @transaction.atomic
    def soft_delete_stage(stage, reassign_stage_id=None):
        """
        Soft deletes a PipelineStage and reassigns active cards to target stage.
        """
        # Block deleting anchor stages directly
        is_anchor = stage.stage_type in ['CONVERSION', 'WON', 'LOST']
        if is_anchor:
            raise ValidationError(
                f"Cannot delete anchor stage '{stage.name}' ({stage.stage_type}). Please reassign its role to another stage first."
            )

        active_leads = Lead.objects.filter(pipeline_stage=stage, is_converted=False)
        active_opps = Opportunity.objects.filter(pipeline_stage=stage)
        has_cards = active_leads.exists() or active_opps.exists()

        if has_cards:
            if not reassign_stage_id:
                raise ValidationError(
                    f"Cannot delete stage containing active cards. Please provide a reassign_stage_id. Stage '{stage.name}' contains active cards."
                )
            try:
                target_stage = PipelineStage.objects.get(pk=reassign_stage_id, pipeline=stage.pipeline)
            except PipelineStage.DoesNotExist:
                raise ValidationError("The reassignment stage does not exist in this pipeline.")

            if target_stage.entity_type != stage.entity_type:
                raise ValidationError("The reassignment stage must have the same entity type.")

            active_leads.update(pipeline_stage=target_stage)
            active_opps.update(pipeline_stage=target_stage)

        # Soft delete
        stage.is_deleted = True
        stage.order = 10000 + stage.id
        stage.save()

        # Re-index orders to eliminate gaps
        remaining_stages = PipelineStage.objects.filter(pipeline=stage.pipeline).order_by('order')
        for i, s in enumerate(remaining_stages):
            s.order = i
            s.save()

        # Recompute
        PipelineWorkflowService.validate_and_recompute_pipeline_boundaries(stage.pipeline)
