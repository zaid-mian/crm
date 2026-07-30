from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from opportunities.models import Opportunity
from payments.models import Payment
from payments.services.activity import PaymentActivityService


class PaymentInvoiceService:
    @staticmethod
    def _validate_opportunity(opportunity: Opportunity) -> None:
        if not opportunity.won:
            raise ValidationError('Invoice can only be generated for won opportunities.')

    @staticmethod
    @transaction.atomic
    def generate_from_opportunity(
        opportunity: Opportunity,
        user=None,
        total_amount: Decimal | None = None,
    ) -> Payment:
        PaymentInvoiceService._validate_opportunity(opportunity)

        existing = Payment.objects.filter(opportunity=opportunity).first()
        if existing:
            return existing

        amount = total_amount if total_amount is not None else opportunity.amount
        if amount <= 0:
            raise ValidationError('Total amount must be greater than zero.')

        payment = Payment.objects.create(
            invoice_number=Payment.generate_invoice_number(),
            company=opportunity.company,
            opportunity=opportunity,
            total_amount=amount,
            assigned_salesperson=opportunity.assigned_salesperson,
        )
        PaymentActivityService.log(
            payment,
            action='INVOICE_GENERATED',
            description=f'Invoice {payment.invoice_number} generated for opportunity {opportunity.name}.',
            user=user,
        )
        PaymentActivityService.log(
            payment,
            action='PAYMENT_PENDING',
            description='Remaining payment pending.',
            user=user,
        )
        return payment
