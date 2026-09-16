from django.db import models


class BillingCustomer(models.Model):
    customer_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique customer identifier (e.g. CUST-00001)"
    )
    name = models.CharField(max_length=255, help_text="Customer legal or display name")
    email = models.EmailField(blank=True, help_text="Primary billing contact email")
    phone = models.CharField(max_length=50, blank=True, help_text="Billing phone number")
    billing_address_line1 = models.CharField(max_length=255, blank=True)
    billing_address_line2 = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=10, default='USD', help_text="Default billing currency code")
    tax_id = models.CharField(max_length=50, blank=True, help_text="Tax registration/VAT number")
    tax_exempt = models.BooleanField(default=False, help_text="Designates whether customer is tax exempt")
    default_payment_method_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Safe gateway payment method token reference"
    )
    external_reference_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="External system reference key for multi-product identity matching"
    )
    organization = models.ForeignKey(
        'accounts.Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='billing_customers',
        help_text="Optional link to AdaptCRM Organization without hard domain coupling"
    )
    metadata = models.JSONField(default=dict, blank=True, help_text="Arbitrary customer metadata")
    is_active = models.BooleanField(default=True, db_index=True, help_text="Designates whether customer account is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'id']
        verbose_name = 'Billing Customer'
        verbose_name_plural = 'Billing Customers'

    def __str__(self):
        return f"{self.customer_number} - {self.name}"
