from decimal import Decimal
from django.db import models


class CreditNote(models.Model):
    REASON_CHOICES = [
        ('REFUND', 'Refund'),
        ('DISPUTE', 'Dispute'),
        ('GOODWILL', 'Goodwill'),
        ('CORRECTION', 'Correction'),
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ISSUED', 'Issued'),
        ('VOID', 'Void'),
    ]

    credit_note_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique credit note identifier (e.g. CN-00001)"
    )
    customer = models.ForeignKey(
        'BillingCustomer',
        on_delete=models.CASCADE,
        related_name='credit_notes',
        help_text="Customer issued credit note"
    )
    invoice = models.ForeignKey(
        'Invoice',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_notes',
        help_text="Associated invoice if credited against specific invoice"
    )
    reason = models.CharField(
        max_length=30,
        choices=REASON_CHOICES,
        default='CORRECTION',
        help_text="Commercial reason for credit note issuance"
    )
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Subtotal credit amount before taxes"
    )
    tax_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Tax credit total"
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total credit instrument amount"
    )
    unallocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Unallocated credit balance available for invoice offset"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
        help_text="Status of credit note instrument"
    )
    issued_date = models.DateField(null=True, blank=True, help_text="Date credit note was issued")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'id']
        verbose_name = 'Credit Note'
        verbose_name_plural = 'Credit Notes'

    def clean(self):
        for attr in ['subtotal', 'tax_total', 'total_amount', 'unallocated_amount']:
            val = getattr(self, attr)
            if val is not None:
                setattr(self, attr, Decimal(str(val)).quantize(Decimal('0.01')))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.credit_note_number} - {self.customer.name} ({self.total_amount})"


class CreditNoteAllocation(models.Model):
    credit_note = models.ForeignKey(
        'CreditNote',
        on_delete=models.CASCADE,
        related_name='allocations',
        help_text="Source credit note"
    )
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='credit_note_allocations',
        help_text="Target invoice credited"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Allocated credit amount")
    allocated_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp of allocation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-allocated_at', 'id']
        verbose_name = 'Credit Note Allocation'
        verbose_name_plural = 'Credit Note Allocations'

    def clean(self):
        if self.amount is not None:
            self.amount = Decimal(str(self.amount)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Credit Allocation {self.amount} from {self.credit_note.credit_note_number} to {self.invoice.invoice_number}"


class DebitNote(models.Model):
    debit_note_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique debit note identifier (e.g. DN-00001)"
    )
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.CASCADE,
        related_name='debit_notes',
        help_text="Target invoice adjusted by this debit note"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Additional charge amount")
    reason = models.TextField(blank=True, help_text="Reason for debit adjustment (e.g. penalty fee)")
    issued_date = models.DateField(help_text="Date debit note was issued")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issued_date', '-created_at', 'id']
        verbose_name = 'Debit Note'
        verbose_name_plural = 'Debit Notes'

    def clean(self):
        if self.amount is not None:
            self.amount = Decimal(str(self.amount)).quantize(Decimal('0.01'))
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.debit_note_number} - Invoice {self.invoice.invoice_number} (+{self.amount})"
