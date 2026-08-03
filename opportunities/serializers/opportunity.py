from rest_framework import serializers
from opportunities.models import Opportunity, OpportunityStage

class OpportunityListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing opportunities.
    """
    opportunity_code = serializers.CharField(read_only=True)
    won = serializers.BooleanField(read_only=True)
    closed = serializers.BooleanField(read_only=True)
    probability = serializers.IntegerField(read_only=True)
    expected_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            'id',
            'opportunity_code',
            'name',
            'company',
            'company_name',
            'stage',
            'amount',
            'probability',
            'expected_revenue',
            'won',
            'closed',
            'expected_close_date',
            'assigned_salesperson',
            'pipeline',
            'pipeline_stage',
            'priority',
            'created_at',
        ]
        read_only_fields = fields


class OpportunityDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for retrieving detailed opportunity information.
    """
    opportunity_code = serializers.CharField(read_only=True)
    won = serializers.BooleanField(read_only=True)
    closed = serializers.BooleanField(read_only=True)
    probability = serializers.IntegerField(read_only=True)
    expected_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            'id',
            'opportunity_code',
            'name',
            'company',
            'company_name',
            'source_lead',
            'primary_contact',
            'assigned_salesperson',
            'stage',
            'amount',
            'probability',
            'expected_revenue',
            'expected_close_date',
            'lead_source',
            'description',
            'won',
            'closed',
            'lost_reason',
            'pipeline',
            'pipeline_stage',
            'priority',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class OpportunityUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an existing opportunity.
    Implements transition validations and BANT rules.
    """
    opportunity_code = serializers.CharField(read_only=True)
    won = serializers.BooleanField(read_only=True)
    closed = serializers.BooleanField(read_only=True)
    probability = serializers.IntegerField(read_only=True)
    expected_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            'id',
            'opportunity_code',
            'name',
            'company',
            'company_name',
            'source_lead',
            'primary_contact',
            'assigned_salesperson',
            'stage',
            'amount',
            'probability',
            'expected_revenue',
            'expected_close_date',
            'lead_source',
            'description',
            'won',
            'closed',
            'lost_reason',
            'pipeline',
            'pipeline_stage',
        ]
        read_only_fields = [
            'id',
            'opportunity_code',
            'company',
            'company_name',
            'source_lead',
            'primary_contact',
            'lead_source',
            'won',
            'closed',
            'probability',
            'expected_revenue',
        ]

    def validate(self, attrs):
        stage = attrs.get('stage')
        pipeline_stage = attrs.get('pipeline_stage')
        lost_reason = attrs.get('lost_reason')
        user = self.context['request'].user
        
        # Enforce amount non-negative
        amount = attrs.get('amount')
        if amount is not None and amount < 0:
            raise serializers.ValidationError({"amount": "Amount cannot be negative."})
            
        # Validate close date is not before creation date
        expected_close_date = attrs.get('expected_close_date')
        if expected_close_date is not None and self.instance:
            if expected_close_date < self.instance.created_at.date():
                raise serializers.ValidationError({"expected_close_date": "Expected Close Date cannot be before the creation date."})
        
        # Resolve target_stage: pipeline_stage takes precedence, fallback to mapping from stage
        target_stage = None
        if pipeline_stage:
            target_stage = pipeline_stage
        elif stage:
            from opportunities.services import OpportunityWorkflowService
            target_stage = OpportunityWorkflowService.get_target_pipeline_stage(self.instance, stage)
            if not target_stage:
                raise serializers.ValidationError({"stage": f"Could not resolve pipeline stage for legacy stage '{stage}'."})
            # Put the resolved pipeline_stage into attrs so it gets set during save/update
            attrs['pipeline_stage'] = target_stage

        if target_stage and self.instance:
            from opportunities.services import OpportunityWorkflowService
            # Validate transition dynamically
            OpportunityWorkflowService.validate_stage_transition_dynamic(self.instance, target_stage, user)
            
            # Validate lost_reason if target_stage is LOST type
            if target_stage.stage_type == 'LOST' and not lost_reason and not self.instance.lost_reason:
                raise serializers.ValidationError({"lost_reason": "A lost reason is required when closing an opportunity as Lost."})

        # Ensure pipeline_stage belongs to pipeline
        pipeline = attrs.get('pipeline', self.instance.pipeline if self.instance else None)
        resolved_stage = attrs.get('pipeline_stage', self.instance.pipeline_stage if self.instance else None)
        if pipeline and resolved_stage and resolved_stage.pipeline != pipeline:
            raise serializers.ValidationError({"pipeline_stage": "The selected stage does not belong to the selected pipeline."})

        return attrs

    def update(self, instance, validated_data):
        from opportunities.services import OpportunityWorkflowService
        from pipeline.models import PipelineStage
        
        stage = validated_data.pop('stage', None)
        lost_reason = validated_data.get('lost_reason', '')
        user = self.context['request'].user
        
        new_pipeline = validated_data.get('pipeline', instance.pipeline)
        
        # If pipeline is changed but pipeline_stage is not explicitly provided,
        # set it to the first active opportunity stage of the new pipeline.
        if new_pipeline != instance.pipeline and 'pipeline_stage' not in validated_data:
            first_stage = PipelineStage.objects.filter(
                pipeline=new_pipeline,
                entity_type='OPPORTUNITY'
            ).order_by('order').first()
            
            if not first_stage:
                first_stage = PipelineStage.objects.filter(
                    pipeline=new_pipeline
                ).order_by('order').first()
                
            validated_data['pipeline_stage'] = first_stage

        # Extract target_stage before super().update
        target_stage = validated_data.get('pipeline_stage', instance.pipeline_stage)
        old_stage = instance.pipeline_stage
        
        # Perform standard update first
        instance = super().update(instance, validated_data)
        
        # If target_stage was changed, trigger the workflow services
        if target_stage and target_stage != old_stage:
            instance = OpportunityWorkflowService.update_opportunity_stage(
                opportunity=instance,
                target_stage=target_stage,
                user=user,
                change_source='API',
                lost_reason=lost_reason
            )
            
        return instance
