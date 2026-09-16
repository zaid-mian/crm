from decimal import Decimal
from django.db import models


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('CREDIT_CARD', 'Credit Card'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CASH', 'Cash'),
        ('OTHER', 'Other'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCEEDED', 'Succeeded'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    payment_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique payment receipt identifier (e.g. PAY-00001)"
    )
    customer = models.ForeignKey(
        'BillingCustomer',
        on_delete=models.CASCADE,
        related_name='payments',
        help_text="Customer who remitted payment"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total payment amount received")
    currency = models.CharField(max_length=10, default='USD', help_text="Three-letter currency code")
    payment_method = models.CharField(
        max_length=30,
        choices=PAYMENT_METHOD_CHOICES,
        default='CREDIT_CARD',
        help_text="Channel/method used for payment"
    )
    payment_method_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Safe gateway payment method token"
    )
    gateway_transaction_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="External payment gateway transaction reference"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        db_index=True,
        help_text="Status of payment transaction"
    )
    payment_date = models.DateField(help_text="Date funds were collected/cleared")
    unallocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Remaining unallocated credit available to settle invoices"
    )
    notes = models.TextField(blank=True, help_text="Payment notes or reference info")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at', 'id']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def clean(self):
        if self.amount is not None:
            self.amount = Decimal(str(self.amount)).quantize(Decimal('0.01'))
        if self.unallocated_amount is not None:
            self.unallocated_amount = Decimal(str(self.unallocated_amount)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.payment_number} - {self.customer.name} ({self.amount} {self.currency})"


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(
        'Payment',
        on_delete=models.CASCADE,
        related_name='allocations',
        help_text="Source payment record"
    )
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='payment_allocations',
        help_text="Target invoice settled by this allocation"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Allocated settlement amount")
    allocated_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when allocation was applied")
    notes = models.TextField(blank=True, help_text="Allocation notes or context")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-allocated_at', 'id']
        verbose_name = 'Payment Allocation'
        verbose_name_plural = 'Payment Allocations'

    def clean(self):
        if self.amount is not None:
            self.amount = Decimal(str(self.amount)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Allocation {self.amount} from {self.payment.payment_number} to {self.invoice.invoice_number}"
