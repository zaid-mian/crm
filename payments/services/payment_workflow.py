from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from payments.models import InvoiceStatus, Payment, PaymentTransaction
from payments.services.activity import PaymentActivityService


class PaymentWorkflowService:
    @staticmethod
    def validate_transaction_amount(payment: Payment, amount: Decimal) -> None:
        if amount <= 0:
            raise ValidationError({'amount_received': 'Amount must be greater than zero.'})

        remaining = payment.balance
        if amount > remaining and payment.credit_balance <= 0:
            # Allow overpayment: excess becomes credit_balance on recalculate
            pass

    @staticmethod
    @transaction.atomic
    def add_transaction(payment: Payment, data: dict, user) -> PaymentTransaction:
        amount = data['amount']
        PaymentWorkflowService.validate_transaction_amount(payment, amount)

        txn = PaymentTransaction.objects.create(
            payment=payment,
            amount=amount,
            payment_method=data.get('payment_method'),
            transaction_reference=data.get('transaction_reference', ''),
            payment_date=data.get('payment_date'),
            notes=data.get('notes', ''),
            recorded_by=user,
        )
        payment.recalculate_totals()

        PaymentActivityService.log(
            payment,
            action='PAYMENT_RECEIVED',
            description=f'Payment of {amount} received ({txn.payment_method}).',
            user=user,
        )
        if payment.status == InvoiceStatus.PAID:
            PaymentActivityService.log(
                payment,
                action='PAYMENT_COMPLETED',
                description='Invoice fully paid.',
                user=user,
            )
        elif payment.paid_amount > 0:
            PaymentActivityService.log(
                payment,
                action='PARTIAL_PAYMENT',
                description=f'Partial payment received. Balance: {payment.balance}.',
                user=user,
            )
        return txn

    @staticmethod
    def validate_opportunity_for_payment(opportunity) -> None:
        if not opportunity.won:
            raise ValidationError(
                {'opportunity': 'Payments are only allowed after the opportunity is marked Won.'}
            )
