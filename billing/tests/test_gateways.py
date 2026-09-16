from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import Organization, OwnerProfile
from roles.models import Role, RolePermission, CRMResource

from billing.models import BillingCustomer, Subscription, Invoice, Payment, PaymentAllocation, WebhookInbox
from billing.services import PaymentService, PaymentAllocationService, WebhookInboxProcessor
from billing.gateways.base import PaymentGatewayBase
from billing.gateways.stripe import StripeGatewayService

User = get_user_model()


from billing.tests.helpers import setup_billing_test_permissions


class StripePaymentGatewayTestCase(TestCase):
    def setUp(self):
        # 1. Setup Roles and permissions
        self.admin_role, _ = Role.objects.get_or_create(
            name='Administrator',
            defaults={'is_system': True, 'description': 'Admin'}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Salesperson',
            defaults={'is_system': True, 'description': 'Salesperson'}
        )

        setup_billing_test_permissions(admin_role=self.admin_role, sales_role=self.sales_role)

        # 3. Create Organizations
        self.org1 = Organization.objects.create(name="Tenant Org 1", is_active=True)
        self.org2 = Organization.objects.create(name="Tenant Org 2", is_active=True)

        # 4. Create Users
        self.user_admin = User.objects.create_user(
            username="admin_user",
            email="admin@tenant1.com",
            password="Password123!",
            is_staff=True,
            is_superuser=True
        )
        if hasattr(self.user_admin, 'profile'):
            self.user_admin.profile.organization = self.org1
            self.user_admin.profile.role = self.admin_role
            self.user_admin.profile.save()

        self.user_sales = User.objects.create_user(
            username="sales_user",
            email="sales@tenant1.com",
            password="Password123!"
        )
        if hasattr(self.user_sales, 'profile'):
            self.user_sales.profile.organization = self.org1
            self.user_sales.profile.role = self.sales_role
            self.user_sales.profile.save()

        self.user_tenant2 = User.objects.create_user(
            username="tenant2_user",
            email="user@tenant2.com",
            password="Password123!"
        )
        if hasattr(self.user_tenant2, 'profile'):
            self.user_tenant2.profile.organization = self.org2
            self.user_tenant2.profile.role = self.sales_role
            self.user_tenant2.profile.save()


        self.customer1 = BillingCustomer.objects.create(
            customer_number="CUST-00001",
            name="Acme Corp",
            email="billing@acme.com",
            organization=self.org1,
            metadata={"created_by_id": self.user_sales.id, "stripe_customer_id": "cus_test_123"}
        )

        self.customer2 = BillingCustomer.objects.create(
            customer_number="CUST-00002",
            name="Beta Inc",
            email="billing@beta.com",
            organization=self.org2,
            metadata={"created_by_id": self.user_tenant2.id, "stripe_customer_id": "cus_test_456"}
        )

        self.invoice1 = Invoice.objects.create(
            invoice_number="INV-2026-00001",
            customer=self.customer1,
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            status="POSTED",
            subtotal=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            discount_total=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            balance=Decimal("100.00")
        )


        self.client = APIClient()

    # -------------------------------------------------------------------------
    # Group 1: Gateway Abstraction Tests
    # -------------------------------------------------------------------------

    def test_gateway_abstraction_interface(self):
        gateway = StripeGatewayService()
        self.assertIsInstance(gateway, PaymentGatewayBase)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_gateway_configuration(self):
        gateway = StripeGatewayService()
        with self.assertRaises(ValueError):
            gateway.attach_payment_method(self.customer1, "pm_test_123")

    @patch('stripe.Customer.create')
    @patch('stripe.PaymentMethod.attach')
    def test_stripe_api_failure_handling(self, mock_attach, mock_create):
        mock_attach.side_effect = Exception("Stripe API Connection Error")
        gateway = StripeGatewayService()
        with self.assertRaises(RuntimeError) as ctx:
            gateway.attach_payment_method(self.customer1, "pm_test_123")
        self.assertIn("Stripe error", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Group 2: Payment Method Tokenization Tests
    # -------------------------------------------------------------------------

    @patch('stripe.Customer.modify')
    @patch('stripe.PaymentMethod.attach')
    def test_attach_valid_payment_method(self, mock_attach, mock_modify):
        mock_attach.return_value = MagicMock(id="pm_test_123")

        self.client.force_authenticate(user=self.user_sales)

        response = self.client.post('/api/v1/billing/payment-methods/attach/', {
            "customer_id": self.customer1.id,
            "payment_method_id": "pm_test_123",
            "set_as_default": True
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["payment_method_id"], "pm_test_123")
        self.customer1.refresh_from_db()
        self.assertEqual(self.customer1.default_payment_method_id, "pm_test_123")


    def test_attach_invalid_payment_method(self):
        self.client.force_authenticate(user=self.user_sales)
        response = self.client.post('/api/v1/billing/payment-methods/attach/', {
            "customer_id": self.customer1.id,
            "payment_method_id": "4111111111111111",  # Raw card number attempt
            "set_as_default": False
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invalid", str(response.data).lower())

    def test_tenant_isolation_payment_method(self):
        self.client.force_authenticate(user=self.user_sales)  # org1
        response = self.client.post('/api/v1/billing/payment-methods/attach/', {
            "customer_id": self.customer2.id,  # org2 customer
            "payment_method_id": "pm_test_456"
        })
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_salesperson_rbac_payment_method(self):
        other_user = User.objects.create_user(username="other_sales", email="other@tenant1.com", password="Password123!")
        if hasattr(other_user, 'profile'):
            other_user.profile.organization = self.org1
            other_user.profile.role = self.sales_role
            other_user.profile.save()


        other_customer = BillingCustomer.objects.create(
            customer_number="CUST-00003",
            name="Gamma Ltd",
            organization=self.org1,
            metadata={"created_by_id": other_user.id}
        )

        self.client.force_authenticate(user=self.user_sales)
        response = self.client.post('/api/v1/billing/payment-methods/attach/', {
            "customer_id": other_customer.id,
            "payment_method_id": "pm_test_999"
        })
        # BillingCustomerPermission enforces OWN scope
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('stripe.Customer.modify')
    @patch('stripe.PaymentMethod.attach')
    def test_sanitized_response_no_secrets(self, mock_attach, mock_modify):
        mock_attach.return_value = MagicMock(id="pm_test_safe")

        self.client.force_authenticate(user=self.user_sales)

        response = self.client.post('/api/v1/billing/payment-methods/attach/', {
            "customer_id": self.customer1.id,
            "payment_method_id": "pm_test_safe"
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resp_str = str(response.data)
        self.assertNotIn("sk_test", resp_str)
        self.assertNotIn("cvv", resp_str.lower())
        self.assertNotIn("card_number", resp_str.lower())

    # -------------------------------------------------------------------------
    # Group 3: Webhook Cryptographic Security Tests
    # -------------------------------------------------------------------------

    @patch('stripe.Webhook.construct_event')
    def test_valid_stripe_signature(self, mock_construct):
        mock_construct.return_value = {
            "id": "evt_test_001",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_test_001"}}
        }

        response = self.client.post(
            '/api/v1/billing/webhooks/stripe/',
            data='{"id":"evt_test_001"}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=valid_sig'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(WebhookInbox.objects.filter(event_id="evt_test_001").exists())

    @patch('stripe.Webhook.construct_event')
    def test_invalid_stripe_signature(self, mock_construct):
        mock_construct.side_effect = Exception("Signature verification failed")

        response = self.client.post(
            '/api/v1/billing/webhooks/stripe/',
            data='{"id":"evt_test_bad"}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=invalid_sig'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification failed", response.data["error"])

    def test_missing_stripe_signature_header(self):
        response = self.client.post(
            '/api/v1/billing/webhooks/stripe/',
            data='{"id":"evt_test_nosig"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Missing", response.data["error"])

    @patch('stripe.Webhook.construct_event')
    def test_malformed_signed_payload(self, mock_construct):
        mock_construct.return_value = {}  # missing id/type

        response = self.client.post(
            '/api/v1/billing/webhooks/stripe/',
            data='invalid json',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=123,v1=valid_sig'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # Group 4: Event Idempotency Tests
    # -------------------------------------------------------------------------

    @patch('stripe.Webhook.construct_event')
    def test_duplicate_event_id_idempotency(self, mock_construct):
        mock_construct.return_value = {
            "id": "evt_duplicate_100",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_100"}}
        }

        # First delivery
        res1 = self.client.post('/api/v1/billing/webhooks/stripe/', data='{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        # Duplicate delivery
        res2 = self.client.post('/api/v1/billing/webhooks/stripe/', data='{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(WebhookInbox.objects.filter(event_id="evt_duplicate_100").count(), 1)

    def test_concurrent_duplicate_delivery(self):
        WebhookInbox.objects.create(
            event_id="evt_race_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={},
            status="PENDING"
        )
        with self.assertRaises(IntegrityError):
            WebhookInbox.objects.create(
                event_id="evt_race_001",
                gateway="STRIPE",
                event_type="payment_intent.succeeded",
                payload={},
                status="PENDING"
            )

    @patch('stripe.Webhook.construct_event')
    def test_no_duplicate_payment(self, mock_construct):
        event_dict = {
            "id": "evt_first_001",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_unique_777",
                    "amount": 5000,
                    "currency": "usd",
                    "customer": "cus_test_123",
                    "metadata": {"invoice_id": str(self.invoice1.id)}
                }
            }
        }
        mock_construct.return_value = event_dict

        # Process first event
        self.client.post('/api/v1/billing/webhooks/stripe/', data='{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')

        # Simulate second event with different event_id for same PaymentIntent
        event_dict_2 = dict(event_dict)
        event_dict_2["id"] = "evt_second_002"
        mock_construct.return_value = event_dict_2

        self.client.post('/api/v1/billing/webhooks/stripe/', data='{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')

        # Verify only 1 Payment record exists for pi_unique_777
        self.assertEqual(Payment.objects.filter(gateway_transaction_id="pi_unique_777").count(), 1)

    def test_no_duplicate_allocation(self):
        payload = {
            "id": "pi_alloc_555",
            "amount": 10000,
            "currency": "usd",
            "customer": "cus_test_123",
            "metadata": {"invoice_id": str(self.invoice1.id)}
        }
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_alloc_555",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={"data": {"object": payload}},
            status="PENDING"
        )

        # Run processor twice
        WebhookInboxProcessor.process_inbox_item(inbox_item)
        WebhookInboxProcessor.process_inbox_item(inbox_item)

        payment = Payment.objects.get(gateway_transaction_id="pi_alloc_555")
        self.assertEqual(PaymentAllocation.objects.filter(payment=payment, invoice=self.invoice1).count(), 1)

    # -------------------------------------------------------------------------
    # Group 5: Financial Ledger & Settlement Tests
    # -------------------------------------------------------------------------

    def test_payment_intent_succeeded(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_succ_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_succ_001",
                        "amount": 10000,
                        "customer": "cus_test_123",
                        "metadata": {"invoice_id": str(self.invoice1.id)}
                    }
                }
            },
            status="PENDING"
        )

        success = WebhookInboxProcessor.process_inbox_item(inbox_item)
        self.assertTrue(success)
        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.status, "PROCESSED")

        payment = Payment.objects.get(gateway_transaction_id="pi_succ_001")
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.customer, self.customer1)

    def test_payment_intent_succeeded_full_allocation(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_full_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_full_001",
                        "amount": 10000,
                        "customer": "cus_test_123",
                        "metadata": {"invoice_id": str(self.invoice1.id)}
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.paid_amount, Decimal("100.00"))
        self.assertEqual(self.invoice1.balance, Decimal("0.00"))
        self.assertEqual(self.invoice1.status, "PAID")

    def test_payment_intent_succeeded_partial_allocation(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_part_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_part_001",
                        "amount": 4000,  # $40.00 paid out of $100.00
                        "customer": "cus_test_123",
                        "metadata": {"invoice_id": str(self.invoice1.id)}
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        self.invoice1.refresh_from_db()
        self.assertEqual(self.invoice1.paid_amount, Decimal("40.00"))
        self.assertEqual(self.invoice1.balance, Decimal("60.00"))
        self.assertEqual(self.invoice1.status, "PARTIALLY_PAID")


    def test_unallocated_payment_fallback(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_unalloc_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_unalloc_001",
                        "amount": 5000,
                        "customer": "cus_test_123",
                        "metadata": {}  # No invoice_id in metadata
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        payment = Payment.objects.get(gateway_transaction_id="pi_unalloc_001")
        self.assertEqual(payment.amount, Decimal("50.00"))
        self.assertEqual(payment.unallocated_amount, Decimal("50.00"))
        self.assertEqual(PaymentAllocation.objects.filter(payment=payment).count(), 0)

    def test_invalid_invoice_fallback(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_invalid_inv_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_invalid_inv_001",
                        "amount": 7500,
                        "customer": "cus_test_123",
                        "metadata": {"invoice_id": "999999"}  # Non-existent invoice
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        payment = Payment.objects.get(gateway_transaction_id="pi_invalid_inv_001")
        self.assertEqual(payment.amount, Decimal("75.00"))
        self.assertEqual(payment.unallocated_amount, Decimal("75.00"))

    def test_cross_customer_and_cross_tenant_invoice_rejection(self):
        invoice_org2 = Invoice.objects.create(
            invoice_number="INV-2026-00002",
            customer=self.customer2,
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            status="POSTED",
            subtotal=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            discount_total=Decimal("0.00"),
            total_amount=Decimal("200.00"),
            paid_amount=Decimal("0.00"),
            balance=Decimal("200.00")
        )

        inbox_item = WebhookInbox.objects.create(
            event_id="evt_cross_tenant_001",
            gateway="STRIPE",
            event_type="payment_intent.succeeded",
            payload={
                "data": {
                    "object": {
                        "id": "pi_cross_tenant_001",
                        "amount": 10000,
                        "customer": "cus_test_123",  # customer1 (org1)
                        "metadata": {"invoice_id": str(invoice_org2.id)}  # invoice from org2 / customer2
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        payment = Payment.objects.get(gateway_transaction_id="pi_cross_tenant_001")
        self.assertEqual(payment.customer, self.customer1)
        self.assertEqual(payment.unallocated_amount, Decimal("100.00"))
        invoice_org2.refresh_from_db()
        self.assertEqual(invoice_org2.paid_amount, Decimal("0.00"))


    # -------------------------------------------------------------------------
    # Group 6: Failed & Unhandled Events Tests
    # -------------------------------------------------------------------------

    def test_payment_intent_payment_failed(self):
        inbox_item = WebhookInbox.objects.create(
            event_id="evt_fail_001",
            gateway="STRIPE",
            event_type="payment_intent.payment_failed",
            payload={
                "data": {
                    "object": {
                        "id": "pi_failed_001",
                        "amount": 5000,
                        "customer": "cus_test_123"
                    }
                }
            },
            status="PENDING"
        )

        WebhookInboxProcessor.process_inbox_item(inbox_item)
        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.status, "PROCESSED")

        payment = Payment.objects.get(gateway_transaction_id="pi_failed_001")
        self.assertEqual(payment.status, "FAILED")


    @patch('stripe.Webhook.construct_event')
    def test_unhandled_stripe_event(self, mock_construct):
        mock_construct.return_value = {
            "id": "evt_unhandled_99",
            "type": "customer.subscription.created",
            "data": {"object": {}}
        }

        response = self.client.post(
            '/api/v1/billing/webhooks/stripe/',
            data='{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inbox_item = WebhookInbox.objects.get(event_id="evt_unhandled_99")
        self.assertIn("unhandled", inbox_item.error_message.lower())


    # -------------------------------------------------------------------------
    # Group 7: Security Audit Tests
    # -------------------------------------------------------------------------

    def test_no_secrets_or_cards_persisted_or_logged(self):
        for item in WebhookInbox.objects.all():
            str_repr = str(item.payload) + str(item.error_message)
            self.assertNotIn("sk_test", str_repr)
            self.assertNotIn("sk_live", str_repr)
            self.assertNotIn("4111111111111111", str_repr)

        for cust in BillingCustomer.objects.all():
            meta_str = str(cust.metadata)
            self.assertNotIn("sk_test", meta_str)
            self.assertNotIn("sk_live", meta_str)
            self.assertNotIn("cvv", meta_str.lower())
