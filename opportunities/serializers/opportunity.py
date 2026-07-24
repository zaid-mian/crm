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
            'company_name',
            'stage',
            'amount',
            'probability',
            'expected_revenue',
            'won',
            'closed',
            'expected_close_date',
            'assigned_salesperson',
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
                
        if stage is not None and self.instance:
            from opportunities.services import OpportunityWorkflowService
            # Validate stage transition path
            OpportunityWorkflowService.validate_stage_transition(self.instance, stage, user)
            
            # Validate lost_reason if stage is CLOSED_LOST
            if stage == OpportunityStage.CLOSED_LOST and not lost_reason and not self.instance.lost_reason:
                raise serializers.ValidationError({"lost_reason": "A lost reason is required when closing an opportunity as Lost."})
                
        return attrs

    def update(self, instance, validated_data):
        from opportunities.services import OpportunityWorkflowService
        stage = validated_data.pop('stage', None)
        lost_reason = validated_data.pop('lost_reason', '')
        user = self.context['request'].user
        
        instance = super().update(instance, validated_data)
        
        if stage is not None and stage != instance.stage:
            instance = OpportunityWorkflowService.change_stage(instance, stage, lost_reason, user)
            
        return instance
