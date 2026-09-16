from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError


class Subscription(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('FUTURE', 'Future'),
        ('TRIAL', 'Trial'),
        ('LIVE', 'Live'),
        ('PAST_DUE', 'Past Due'),
        ('UNPAID', 'Unpaid'),
        ('CANCELLED', 'Cancelled'),
        ('NON_RENEWING', 'Non Renewing'),
        ('PAUSED', 'Paused'),
    ]

    COLLECTION_METHOD_CHOICES = [
        ('CHARGE_AUTOMATIC', 'Charge Automatic'),
        ('SEND_INVOICE', 'Send Invoice'),
    ]

    subscription_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique subscription agreement identifier (e.g. SUB-00001)"
    )
    customer = models.ForeignKey(
        'BillingCustomer',
        on_delete=models.CASCADE,
        related_name='subscriptions',
        help_text="Customer holding this subscription"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
        help_text="Current commercial state of the subscription"
    )
    currency = models.CharField(max_length=10, default='USD', help_text="Three-letter currency code")
    collection_method = models.CharField(
        max_length=30,
        choices=COLLECTION_METHOD_CHOICES,
        default='CHARGE_AUTOMATIC',
        help_text="Payment collection method"
    )
    payment_terms_days = models.PositiveIntegerField(
        default=0,
        help_text="Payment grace period in days for invoices (Net 0, Net 30, etc.)"
    )
    current_term_start = models.DateField(null=True, blank=True, help_text="Start date of current billing term")
    current_term_end = models.DateField(null=True, blank=True, help_text="End date of current billing term")
    trial_start = models.DateField(null=True, blank=True, help_text="Start date of trial period")
    trial_end = models.DateField(null=True, blank=True, help_text="End date of trial period")
    next_billing_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Next scheduled invoice date"
    )
    pause_date = models.DateField(null=True, blank=True, help_text="Date billing was paused")
    resume_date = models.DateField(null=True, blank=True, help_text="Date billing is scheduled to resume")
    cancelled_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of cancellation")
    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text="Designates if subscription cancels at end of current term"
    )
    cached_mrr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Cached Monthly Recurring Revenue"
    )
    cached_arr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Cached Annual Recurring Revenue"
    )
    metadata = models.JSONField(default=dict, blank=True, help_text="Arbitrary agreement metadata")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'id']
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'

    def clean(self):
        if self.cached_mrr is not None:
            self.cached_mrr = Decimal(str(self.cached_mrr)).quantize(Decimal('0.01'))
        if self.cached_arr is not None:
            self.cached_arr = Decimal(str(self.cached_arr)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subscription_number} - {self.customer.name} ({self.status})"


class SubscriptionItem(models.Model):
    ITEM_TYPE_CHOICES = [
        ('PLAN', 'Plan'),
        ('ADDON', 'Addon'),
    ]

    subscription = models.ForeignKey(
        'Subscription',
        on_delete=models.CASCADE,
        related_name='items',
        help_text="Parent subscription header"
    )
    item_type = models.CharField(
        max_length=10,
        choices=ITEM_TYPE_CHOICES,
        help_text="Type of line item (PLAN or ADDON)"
    )
    plan = models.ForeignKey(
        'catalog.PricingPlan',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='subscription_items',
        help_text="Catalog pricing plan (if item_type is PLAN)"
    )
    addon = models.ForeignKey(
        'AddOn',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='subscription_items',
        help_text="Catalog add-on (if item_type is ADDON)"
    )
    quantity = models.PositiveIntegerField(default=1, help_text="Item quantity / seat count")
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Historical price snapshot at time of subscription/amendment"
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Fixed discount amount applied to line item"
    )
    start_date = models.DateField(null=True, blank=True, help_text="Effective start date for item")
    end_date = models.DateField(null=True, blank=True, help_text="Effective end date co-terminated with subscription")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Subscription Item'
        verbose_name_plural = 'Subscription Items'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(item_type='PLAN', plan__isnull=False, addon__isnull=True) |
                    models.Q(item_type='ADDON', plan__isnull=True, addon__isnull=False)
                ),
                name='subscription_item_plan_or_addon_check'
            )
        ]

    def clean(self):
        if self.unit_price is not None:
            self.unit_price = Decimal(str(self.unit_price)).quantize(Decimal('0.01'))
        if self.discount_amount is not None:
            self.discount_amount = Decimal(str(self.discount_amount)).quantize(Decimal('0.01'))

        if self.item_type == 'PLAN' and (not self.plan or self.addon):
            raise ValidationError("Subscription item of type 'PLAN' must have a valid plan and no addon.")
        if self.item_type == 'ADDON' and (not self.addon or self.plan):
            raise ValidationError("Subscription item of type 'ADDON' must have a valid addon and no plan.")

        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        label = self.plan.name if self.plan else (self.addon.name if self.addon else "Unknown")
        return f"{self.subscription.subscription_number} - {self.item_type}: {label} (x{self.quantity})"
