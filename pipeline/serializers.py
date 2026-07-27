from rest_framework import serializers

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
