from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Historical audit records are immutable and cannot be updated.")

    def delete(self):
        raise ValidationError("Historical audit records are immutable and cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Historical audit records are immutable and cannot be updated.")


class ImmutableModel(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Historical audit records are immutable and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Historical audit records are immutable and cannot be deleted.")


class SubscriptionAuditLog(ImmutableModel):
    subscription = models.ForeignKey(
        'Subscription',
        on_delete=models.CASCADE,
        related_name='audit_logs',
        help_text="Target subscription"
    )
    actor_id = models.CharField(max_length=255, null=True, blank=True, help_text="User ID or system actor identifier")
    actor_type = models.CharField(max_length=50, default='USER', help_text="Actor type (USER, SYSTEM, API)")
    action = models.CharField(max_length=100, help_text="Action performed (e.g. STATUS_CHANGE, CANCEL)")
    old_state = models.CharField(max_length=50, blank=True, help_text="Previous status")
    new_state = models.CharField(max_length=50, blank=True, help_text="New status")
    reason = models.TextField(blank=True, help_text="Reason for change")
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional audit context")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp', 'id']
        verbose_name = 'Subscription Audit Log'
        verbose_name_plural = 'Subscription Audit Logs'

    def __str__(self):
        return f"Audit {self.subscription.subscription_number}: {self.action} at {self.timestamp}"


class SubscriptionChangeLog(ImmutableModel):
    subscription = models.ForeignKey(
        'Subscription',
        on_delete=models.CASCADE,
        related_name='change_logs',
        help_text="Target subscription"
    )
    change_type = models.CharField(max_length=50, help_text="Type of change (ADD_ITEM, REMOVE_ITEM, QUANTITY_CHANGE, PRORATION)")
    details = models.JSONField(default=dict, blank=True, help_text="Delta details of modification")
    proration_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Calculated proration financial delta"
    )
    effective_date = models.DateField(help_text="Effective date of change")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp', 'id']
        verbose_name = 'Subscription Change Log'
        verbose_name_plural = 'Subscription Change Logs'

    def clean(self):
        if self.proration_amount is not None:
            self.proration_amount = Decimal(str(self.proration_amount)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Change {self.subscription.subscription_number}: {self.change_type} on {self.effective_date}"


class DunningLog(ImmutableModel):
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('SCHEDULED', 'Scheduled'),
        ('EXHAUSTED', 'Exhausted'),
    ]

    subscription = models.ForeignKey(
        'Subscription',
        on_delete=models.CASCADE,
        related_name='dunning_logs',
        help_text="Target subscription undergoing dunning"
    )
    invoice = models.ForeignKey(
        'Invoice',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='dunning_logs',
        help_text="Unpaid invoice associated with dunning retry attempt"
    )
    attempt_number = models.PositiveIntegerField(help_text="Retry sequence attempt number (1, 2, 3...)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, help_text="Result of retry attempt")
    gateway_transaction_id = models.CharField(max_length=255, blank=True, help_text="Stripe PaymentIntent ID (pi_...) associated with retry")
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True, help_text="Deterministic unique key preventing duplicate retry execution")
    error_code = models.CharField(max_length=100, blank=True, help_text="Gateway or processing error code")
    error_message = models.TextField(blank=True, help_text="Human readable failure detail")
    next_retry_at = models.DateTimeField(null=True, blank=True, help_text="Scheduled date/time for next retry attempt")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp', 'id']
        verbose_name = 'Dunning Log'
        verbose_name_plural = 'Dunning Logs'

    def __str__(self):
        return f"Dunning {self.subscription.subscription_number} attempt #{self.attempt_number}: {self.status}"



class WebhookInbox(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSED', 'Processed'),
        ('FAILED', 'Failed'),
    ]

    event_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique gateway event identifier (e.g. evt_...)"
    )
    gateway = models.CharField(max_length=50, default='STRIPE', help_text="Gateway provider name")
    event_type = models.CharField(max_length=100, db_index=True, help_text="Type of event (e.g. payment_intent.succeeded)")
    payload = models.JSONField(help_text="Full verified gateway event JSON payload")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        db_index=True,
        help_text="Processing status of webhook event"
    )
    error_message = models.TextField(blank=True, help_text="Error detail if processing failed")
    processed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when event was processed")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', 'id']
        verbose_name = 'Webhook Inbox'
        verbose_name_plural = 'Webhook Inboxes'

    def __str__(self):
        return f"WebhookInbox {self.event_id} ({self.event_type}) - {self.status}"

