from rest_framework import serializers
from django.contrib.auth import get_user_model
from leads.models import Lead

User = get_user_model()

class LeadListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing leads.
    """
    lead_code = serializers.CharField(read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id',
            'lead_code',
            'full_name',
            'phone',
            'email',
            'company_name',
            'source',
            'priority',
            'status',
            'pipeline',
            'pipeline_stage',
            'assigned_salesperson',
            'is_converted',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class LeadDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for retrieving detailed lead information.
    Includes engagement activities and tasks (empty by default).
    """
    lead_code = serializers.CharField(read_only=True)
    activities = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id',
            'lead_code',
            'full_name',
            'phone',
            'email',
            'company_name',
            'source',
            'priority',
            'status',
            'pipeline',
            'pipeline_stage',
            'assigned_salesperson',
            'notes',
            'last_contact_date',
            'contact_attempts',
            'is_converted',
            'converted_at',
            'lost_reason',
            'lost_notes',
            'created_at',
            'updated_at',
            'activities',
            'tasks',
        ]
        read_only_fields = fields

    def get_activities(self, obj):
        # Placeholder for future Activities module integration
        return []

    def get_tasks(self, obj):
        # Placeholder for future Tasks module integration
        return []


class LeadCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new lead.
    Restricts input to basic ingestion fields.
    """
    lead_code = serializers.CharField(read_only=True)
    phone = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = Lead
        fields = [
            'id',
            'lead_code',
            'full_name',
            'phone',
            'email',
            'company_name',
            'source',
            'priority',
            'notes',
            'pipeline',
            'pipeline_stage',
            'assigned_salesperson',
        ]
        read_only_fields = ['id', 'lead_code', 'pipeline_stage']

    def validate(self, attrs):
        # Default priority to MEDIUM on the backend when not provided
        if not attrs.get('priority'):
            attrs['priority'] = Lead.Priority.MEDIUM

        email = attrs.get('email')
        phone = attrs.get('phone')
        if not email and not phone:
            raise serializers.ValidationError("At least one contact method (email or phone) must be provided.")

        from pipeline.models import Pipeline, PipelineStage

        pipeline = attrs.get('pipeline')
        if not pipeline:
            pipeline = Pipeline.objects.filter(is_default=True).first()
            if not pipeline:
                pipeline = Pipeline.objects.first()
            if not pipeline:
                pipeline = Pipeline.objects.create(name="Default Pipeline", is_default=True)

        first_stage = PipelineStage.objects.filter(pipeline=pipeline).order_by('order').first()
        if not first_stage:
            raise serializers.ValidationError(
                {"pipeline": "The selected pipeline has no active stages configured."}
            )

        attrs['pipeline'] = pipeline
        attrs['pipeline_stage'] = first_stage

        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            from leads.permissions import is_manager_or_admin
            if not is_manager_or_admin(request.user):
                attrs['assigned_salesperson'] = request.user

        return attrs

    def create(self, validated_data):
        return super().create(validated_data)

    def validate_phone(self, value):
        """
        Validate phone is unique among active (non-converted) leads.
        Note: This duplicate check may be extended to support archive/soft-delete later.
        """
        if not value:
            return value
        if Lead.objects.filter(phone=value, is_converted=False).exists():
            raise serializers.ValidationError("A lead with this phone number already exists.")
        return value

    def validate_email(self, value):
        """
        Validate email is unique among active (non-converted) leads.
        Note: This duplicate check may be extended to support archive/soft-delete later.
        """
        if not value:
            return value
        if Lead.objects.filter(email=value, is_converted=False).exists():
            raise serializers.ValidationError("A lead with this email address already exists.")
        return value


class LeadUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an existing lead.
    Restricts updates to workflow-related state (status, salesperson, is_converted, lost_reason, etc.)
    which are handled by dedicated action endpoints.
    """
    lead_code = serializers.CharField(read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id',
            'lead_code',
            'full_name',
            'phone',
            'email',
            'company_name',
            'source',
            'priority',
            'notes',
            'last_contact_date',
            'contact_attempts',
            'pipeline',
            'pipeline_stage',
        ]
        read_only_fields = ['id', 'lead_code']

    def validate(self, attrs):
        email = attrs.get('email', self.instance.email if self.instance else None)
        phone = attrs.get('phone', self.instance.phone if self.instance else None)
        if not email and not phone:
            raise serializers.ValidationError("At least one contact method (email or phone) must be provided.")
            
        is_pipeline_changing = 'pipeline' in attrs and attrs['pipeline'] != self.instance.pipeline
        if not is_pipeline_changing or 'pipeline_stage' in attrs:
            pipeline = attrs.get('pipeline', self.instance.pipeline if self.instance else None)
            pipeline_stage = attrs.get('pipeline_stage', self.instance.pipeline_stage if self.instance else None)
            
            if pipeline and pipeline_stage and pipeline_stage.pipeline != pipeline:
                raise serializers.ValidationError({"pipeline_stage": "The selected stage does not belong to the selected pipeline."})
            
        return attrs

    def update(self, instance, validated_data):
        from pipeline.models import PipelineStage
        new_pipeline = validated_data.get('pipeline', instance.pipeline)
        
        if new_pipeline != instance.pipeline:
            first_stage = PipelineStage.objects.filter(
                pipeline=new_pipeline,
                entity_type='LEAD'
            ).order_by('order').first()
            
            if not first_stage:
                first_stage = PipelineStage.objects.create(
                    pipeline=new_pipeline,
                    name="New",
                    entity_type='LEAD',
                    order=0,
                    stage_type='NORMAL_LEAD'
                )
            validated_data['pipeline_stage'] = first_stage
            
        return super().update(instance, validated_data)

    def validate_phone(self, value):
        """
        Validate phone is unique among active (non-converted) leads.
        Note: This duplicate check may be extended to support archive/soft-delete later.
        """
        if not value:
            return value
        queryset = Lead.objects.filter(phone=value, is_converted=False)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A lead with this phone number already exists.")
        return value



    def validate_email(self, value):
        """
        Validate email is unique among active (non-converted) leads.
        Note: This duplicate check may be extended to support archive/soft-delete later.
        """
        if not value:
            return value
        queryset = Lead.objects.filter(email=value, is_converted=False)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A lead with this email address already exists.")
        return value


class LeadAssignSerializer(serializers.Serializer):
    """
    Serializer for assigning a lead to a salesperson.
    """
    assigned_salesperson = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=True,
        error_messages={
            'does_not_exist': 'The selected salesperson does not exist.'
        }
    )


class LeadLostSerializer(serializers.Serializer):
    """
    Serializer for marking a lead as Lost.
    """
    lost_reason = serializers.ChoiceField(
        choices=Lead.LostReason.choices,
        required=True,
        error_messages={
            'invalid_choice': 'Select a valid lost reason.'
        }
    )
    lost_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
