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
    entity_type = serializers.CharField(required=False, default='LEAD')
    stage_type = serializers.CharField(required=False, default='NORMAL_LEAD')
    is_conversion = serializers.SerializerMethodField()
    is_terminal_won = serializers.SerializerMethodField()
    is_terminal_lost = serializers.SerializerMethodField()

    class Meta:
        model = PipelineStage
        fields = [
            'id', 'pipeline', 'name', 'entity_type', 'order', 'color',
            'stage_type', 'is_conversion', 'is_terminal_won', 'is_terminal_lost', 'created_at'
        ]

    def get_is_conversion(self, obj):
        return obj.stage_type == 'CONVERSION'

    def get_is_terminal_won(self, obj):
        return obj.stage_type == 'WON'

    def get_is_terminal_lost(self, obj):
        return obj.stage_type == 'LOST'

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
        
        # Enforce single-anchor invariants
        if pipeline and stage_type in ['CONVERSION', 'WON', 'LOST']:
            anchor_qs = PipelineStage.objects.filter(pipeline=pipeline, stage_type=stage_type)
            if self.instance:
                anchor_qs = anchor_qs.exclude(pk=self.instance.pk)
            if anchor_qs.exists():
                raise serializers.ValidationError({"stage_type": f"Only one {stage_type} stage can exist per pipeline."})

        # Check if order was explicitly passed in the request data as a non-zero value
        order_explicitly_passed = False
        if self.initial_data and 'order' in self.initial_data:
            val = self.initial_data['order']
            try:
                if val is not None and str(val).strip() != '' and int(val) != 0:
                    order_explicitly_passed = True
            except ValueError:
                pass

        if not self.instance:
            if not order_explicitly_passed:
                # Creation mode and order not explicitly supplied: auto-assign max(order) + 1
                if pipeline:
                    from django.db.models import Max
                    max_order = PipelineStage.objects.filter(pipeline=pipeline).aggregate(Max('order'))['order__max']
                    attrs['order'] = (max_order + 1) if max_order is not None else 0
                else:
                    attrs['order'] = 0
            else:
                # Order was explicitly passed, validate uniqueness
                order = attrs.get('order')
                if pipeline and order is not None:
                    if PipelineStage.objects.filter(pipeline=pipeline, order=order).exists():
                        raise serializers.ValidationError({"order": "A stage with this order already exists in the pipeline."})
        else:
            # Update mode: validate order uniqueness if it is being changed
            order = attrs.get('order', getattr(self.instance, 'order', None))
            if pipeline and order is not None:
                qs = PipelineStage.objects.filter(pipeline=pipeline, order=order)
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError({"order": "A stage with this order already exists in the pipeline."})

        return attrs


from django.db import transaction
from pipeline.models import CustomForm, CustomFormField

class CustomFormFieldSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    class Meta:
        model = CustomFormField
        fields = ['id', 'label', 'field_type', 'required', 'options', 'order']

class CustomFormSerializer(serializers.ModelSerializer):
    fields = CustomFormFieldSerializer(many=True, required=False, default=list)

    class Meta:
        model = CustomForm
        fields = ['id', 'pipeline', 'is_active', 'fields', 'created_at', 'updated_at']

    @transaction.atomic
    def update(self, instance, validated_data):
        instance.is_active = validated_data.get('is_active', instance.is_active)
        instance.save()

        fields_data = validated_data.get('fields', [])
        
        # Keep track of existing fields
        existing_fields = {f.id: f for f in instance.fields.all()}
        updated_field_ids = []

        for field_data in fields_data:
            field_id = field_data.get('id')
            if field_id and field_id in existing_fields:
                f = existing_fields[field_id]
                f.label = field_data.get('label', f.label)
                f.field_type = field_data.get('field_type', f.field_type)
                f.required = field_data.get('required', f.required)
                f.options = field_data.get('options', f.options)
                f.order = field_data.get('order', f.order)
                f.save()
                updated_field_ids.append(f.id)
            else:
                f = CustomFormField.objects.create(
                    form=instance,
                    label=field_data.get('label'),
                    field_type=field_data.get('field_type'),
                    required=field_data.get('required', False),
                    options=field_data.get('options', []),
                    order=field_data.get('order', 0)
                )
                updated_field_ids.append(f.id)

        # Delete omitted fields
        for fid, f in existing_fields.items():
            if fid not in updated_field_ids:
                f.delete()

        return instance
