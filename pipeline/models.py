from django.db import models
from django.conf import settings

class Pipeline(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class ActivePipelineStageManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class PipelineStage(models.Model):
    ENTITY_TYPE_CHOICES = [
        ('LEAD', 'Lead'),
        ('OPPORTUNITY', 'Opportunity'),
    ]
    
    STAGE_TYPE_CHOICES = [
        ('NORMAL_LEAD', 'Normal Lead'),
        ('CONVERSION', 'Conversion Stage'),
        ('NORMAL_OPPORTUNITY', 'Normal Opportunity'),
        ('WON', 'Won Stage'),
        ('LOST', 'Lost Stage'),
    ]

    objects = ActivePipelineStageManager()
    all_objects = models.Manager()

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name='stages')
    name = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPE_CHOICES, default='LEAD')
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default='#6c757d') # Hex code color support
    stage_type = models.CharField(max_length=30, choices=STAGE_TYPE_CHOICES, default='NORMAL_LEAD')
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['pipeline', 'order'], name='unique_stage_order_per_pipeline')
        ]

    def __str__(self):
        return f"{self.pipeline.name} - {self.name} ({self.entity_type})"


class CustomForm(models.Model):
    pipeline = models.OneToOneField(Pipeline, on_delete=models.CASCADE, related_name='custom_form')
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Custom Form for {self.pipeline.name}"


class CustomFormField(models.Model):
    FIELD_TYPES = [
        ('TEXT', 'Short Text'),
        ('TEXTAREA', 'Long Text'),
        ('NUMBER', 'Number'),
        ('DATE', 'Date'),
        ('DROPDOWN', 'Dropdown'),
        ('CHECKBOX', 'Checkbox'),
    ]
    form = models.ForeignKey(CustomForm, on_delete=models.CASCADE, related_name='fields')
    label = models.CharField(max_length=100)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True, null=True, help_text="List of options for dropdown fields")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.label} ({self.field_type})"


class PipelineAuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    lead = models.ForeignKey('leads.Lead', on_delete=models.CASCADE, null=True, blank=True)
    opportunity = models.ForeignKey('opportunities.Opportunity', on_delete=models.CASCADE, null=True, blank=True)
    from_stage = models.ForeignKey(PipelineStage, on_delete=models.SET_NULL, null=True, related_name='from_logs')
    to_stage = models.ForeignKey(PipelineStage, on_delete=models.SET_NULL, null=True, related_name='to_logs')
    from_stage_name = models.CharField(max_length=100, blank=True, null=True)
    to_stage_name = models.CharField(max_length=100, blank=True, null=True)
    change_source = models.CharField(
        max_length=50, 
        choices=[
            ('DRAG_AND_DROP', 'Drag and Drop'),
            ('DETAIL_DRAWER', 'Detail Drawer'),
            ('API', 'Direct API Call')
        ], 
        default='API'
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Transition to {self.to_stage_name} on {self.changed_at}"
