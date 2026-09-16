from django.urls import path, include
from rest_framework.routers import DefaultRouter
from billing.views import (
    BillingCustomerViewSet,
    SubscriptionViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    CreditNoteViewSet,
    DebitNoteViewSet,
    BillingAuditViewSet,
    PaymentMethodAttachView,
    StripeWebhookView,
    EntitlementCheckViewSet,
    CrmIntegrationViewSet,
    BillingAnalyticsViewSet,
)

router = DefaultRouter()
router.register(r'customers', BillingCustomerViewSet, basename='billing-customer')
router.register(r'subscriptions', SubscriptionViewSet, basename='billing-subscription')
router.register(r'invoices', InvoiceViewSet, basename='billing-invoice')
router.register(r'payments', PaymentViewSet, basename='billing-payment')
router.register(r'credit-notes', CreditNoteViewSet, basename='billing-credit-note')
router.register(r'debit-notes', DebitNoteViewSet, basename='billing-debit-note')
router.register(r'audit', BillingAuditViewSet, basename='billing-audit')
router.register(r'entitlements/check', EntitlementCheckViewSet, basename='billing-entitlements-check')
router.register(r'integrations/crm', CrmIntegrationViewSet, basename='billing-crm-integrations')
router.register(r'analytics', BillingAnalyticsViewSet, basename='billing-analytics')

urlpatterns = [
    path('payment-methods/attach/', PaymentMethodAttachView.as_view(), name='payment-method-attach'),
    path('webhooks/stripe/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('', include(router.urls)),
]


