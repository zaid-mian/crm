from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from companies.models import Company
from opportunities.models import Opportunity


class InvoiceStatus(models.TextChoices):
    UNPAID = 'UNPAID', 'Unpaid'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    PAID = 'PAID', 'Paid'


class PaymentMethod(models.TextChoices):
    CASH = 'CASH', 'Cash'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    CREDIT_CARD = 'CREDIT_CARD', 'Credit Card'
    OTHER = 'OTHER', 'Other'


class Payment(models.Model):
    """
    Invoice-level payment record tied to a won opportunity.
    Individual receipts are stored as PaymentTransaction rows.
    """
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='payments')
    invoice_number = models.CharField(max_length=32, unique=True, db_index=True)
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(
        max_length=32,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.UNPAID,
        db_index=True,
    )
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True, default='')
    assigned_salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_payments',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f'{self.invoice_number} - {self.total_amount} {self.currency}'

    @property
    def balance(self) -> Decimal:
        remaining = self.total_amount - self.paid_amount
        return remaining if remaining > 0 else Decimal('0.00')

    def recalculate_totals(self, save=True):
        aggregate = self.transactions.aggregate(total=Sum('amount'))
        paid = aggregate['total'] or Decimal('0.00')
        self.paid_amount = paid
        self.credit_balance = max(paid - self.total_amount, Decimal('0.00'))

        if paid <= 0:
            self.status = InvoiceStatus.UNPAID
        elif paid < self.total_amount:
            self.status = InvoiceStatus.PARTIALLY_PAID
        else:
            self.status = InvoiceStatus.PAID

        latest = self.transactions.order_by('-payment_date', '-created_at').first()
        self.payment_date = latest.payment_date if latest else None

        if save:
            self.save(
                update_fields=[
                    'paid_amount',
                    'credit_balance',
                    'status',
                    'payment_date',
                    'updated_at',
                ]
            )

    @staticmethod
    def generate_invoice_number() -> str:
        last = Payment.objects.order_by('-id').first()
        next_id = (last.id + 1) if last else 1
        return f'INV-{next_id:03d}'


class PaymentTransaction(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='transactions',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(
        max_length=50,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    transaction_reference = models.CharField(max_length=100, blank=True, default='')
    payment_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True, default='')
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_payment_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f'{self.payment.invoice_number} - {self.amount}'


class PaymentActivityLog(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='activity_logs',
    )
    action = models.CharField(max_length=64, db_index=True)
    description = models.TextField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
