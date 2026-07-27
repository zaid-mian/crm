from rest_framework import serializers
from pipeline.models import Pipeline, PipelineStage

class PipelineCardSerializer(serializers.Serializer):
    entity_type = serializers.CharField(read_only=True)
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    company_name = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    phone = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    email = serializers.EmailField(read_only=True, allow_blank=True, allow_null=True)
    assigned_salesperson_id = serializers.IntegerField(read_only=True, allow_null=True)
    assigned_salesperson_name = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    stage = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=2, allow_null=True)
    expected_close_date = serializers.DateField(read_only=True, allow_null=True)
    probability = serializers.IntegerField(read_only=True, allow_null=True)
    notes = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    company_id = serializers.IntegerField(read_only=True, allow_null=True)
    primary_contact_id = serializers.IntegerField(read_only=True, allow_null=True)
    pipeline_stage_id = serializers.IntegerField(read_only=True, allow_null=True)

class PipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pipeline
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']

class PipelineStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineStage
        fields = ['id', 'pipeline', 'name', 'entity_type', 'order', 'color', 'stage_type', 'created_at']

    def validate(self, attrs):
        entity_type = attrs.get('entity_type', getattr(self.instance, 'entity_type', None))
        stage_type = attrs.get('stage_type', getattr(self.instance, 'stage_type', None))
        
        if stage_type == 'CONVERSION' and entity_type == 'LEAD':
            raise serializers.ValidationError("CONVERSION stage cannot belong to LEAD.")
        if stage_type == 'NORMAL_LEAD' and entity_type == 'OPPORTUNITY':
            raise serializers.ValidationError("NORMAL_LEAD stage cannot belong to OPPORTUNITY.")
        if stage_type == 'NORMAL_OPPORTUNITY' and entity_type == 'LEAD':
            raise serializers.ValidationError("NORMAL_OPPORTUNITY stage cannot belong to LEAD.")
        if stage_type == 'WON' and entity_type == 'LEAD':
            raise serializers.ValidationError("WON stage cannot belong to LEAD.")

        pipeline = attrs.get('pipeline', getattr(self.instance, 'pipeline', None))
        order = attrs.get('order', getattr(self.instance, 'order', None))
        if pipeline and order is not None:
            qs = PipelineStage.objects.filter(pipeline=pipeline, order=order)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"order": "A stage with this order already exists in the pipeline."})

        return attrs
