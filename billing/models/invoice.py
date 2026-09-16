from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError


class Invoice(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('POSTED', 'Posted'),
        ('PAID', 'Paid'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('VOID', 'Void'),
        ('UNCOLLECTIBLE', 'Uncollectible'),
    ]

    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique invoice number (e.g. INV-2026-00001)"
    )
    subscription = models.ForeignKey(
        'Subscription',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='invoices',
        help_text="Source subscription if generated from automated billing"
    )
    customer = models.ForeignKey(
        'BillingCustomer',
        on_delete=models.CASCADE,
        related_name='invoices',
        help_text="Customer billed for this invoice"
    )
    billing_period_start = models.DateField(null=True, blank=True, help_text="Start of coverage period")
    billing_period_end = models.DateField(null=True, blank=True, help_text="End of coverage period")
    issue_date = models.DateField(help_text="Date invoice was issued")
    due_date = models.DateField(help_text="Payment due date")
    paid_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when invoice reached PAID status")
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Sum of line item subtotals before discounts/taxes"
    )
    discount_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total discount deductions"
    )
    tax_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total tax charges"
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Final payable total amount"
    )
    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Cumulative payments allocated to this invoice"
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Remaining unpaid invoice balance"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
        help_text="State of invoice in billing ledger"
    )
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Deterministic key guaranteeing zero duplicate invoices"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issue_date', '-created_at', 'id']
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'

    def clean(self):
        for attr in ['subtotal', 'discount_total', 'tax_total', 'total_amount', 'paid_amount', 'balance']:
            val = getattr(self, attr)
            if val is not None:
                setattr(self, attr, Decimal(str(val)).quantize(Decimal('0.01')))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name} ({self.status})"


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='lines',
        help_text="Parent invoice header"
    )
    subscription_item = models.ForeignKey(
        'SubscriptionItem',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='invoice_lines',
        help_text="Source subscription line item if applicable"
    )
    description = models.CharField(max_length=255, help_text="Human-readable line description")
    quantity = models.PositiveIntegerField(default=1, help_text="Billed quantity")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Unit price snapshot")
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Line subtotal (quantity * unit_price)"
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Line discount amount"
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Line tax amount"
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Line final total"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Invoice Line'
        verbose_name_plural = 'Invoice Lines'

    def clean(self):
        for attr in ['unit_price', 'subtotal', 'discount_amount', 'tax_amount', 'total_amount']:
            val = getattr(self, attr)
            if val is not None:
                setattr(self, attr, Decimal(str(val)).quantize(Decimal('0.01')))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice.invoice_number} line: {self.description}"
