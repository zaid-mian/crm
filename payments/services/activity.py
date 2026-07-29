from payments.models import Payment, PaymentActivityLog


class PaymentActivityService:
    @staticmethod
    def log(payment: Payment, action: str, description: str, user=None) -> PaymentActivityLog:
        return PaymentActivityLog.objects.create(
            payment=payment,
            action=action,
            description=description,
            user=user,
        )
