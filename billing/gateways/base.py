from abc import ABC, abstractmethod


class PaymentGatewayBase(ABC):
    """
    Abstract base class for payment gateway integrations (Stripe, PayPal, etc.).
    Keeps billing domain services provider-agnostic.
    """

    @abstractmethod
    def attach_payment_method(self, customer, payment_method_id, set_as_default=True):
        """
        Attaches a safe tokenized payment method (e.g. pm_...) to a customer on the gateway
        and saves reference in customer.metadata['stripe_customer_id'].
        """
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload_bytes, sig_header):
        """
        Cryptographically verifies the raw HTTP request body against the webhook signature header.
        Raises ValidationError/ValueError if signature is invalid or header is missing.
        """
        pass

    @abstractmethod
    def parse_webhook_event(self, payload_bytes, sig_header):
        """
        Parses and returns structured event data from the verified webhook payload.
        """
        pass

    @abstractmethod
    def create_payment_intent(self, customer, amount, currency='USD', payment_method_id='', invoice_id=None, description=''):
        """
        Creates an off-session PaymentIntent to charge a saved payment method on the gateway.
        """
        pass

