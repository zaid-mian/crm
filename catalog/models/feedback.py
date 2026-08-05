from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from catalog.utils import can_user_review

class Feedback(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='feedbacks',
        null=True,
        blank=True
    )
    service = models.ForeignKey(
        'Service',
        on_delete=models.CASCADE,
        related_name='feedbacks',
        null=True,
        blank=True
    )
    rating = models.IntegerField(
        validators=[
            MinValueValidator(1, "Rating must be at least 1."),
            MaxValueValidator(5, "Rating cannot exceed 5.")
        ]
    )
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ('user', 'product'),
            ('user', 'service')
        ]
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        # Exclusivity validation
        if not self.product and not self.service:
            raise ValidationError("Feedback must target either a Product or a Service.")
        if self.product and self.service:
            raise ValidationError("Feedback cannot target both a Product and a Service.")

        # Ownership/Eligibility validation
        target = self.product or self.service
        if not can_user_review(self.user, target):
            raise ValidationError("You must have owned or subscribed to this item to leave feedback.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        target_name = self.product.name if self.product else self.service.name
        return f"Feedback by {self.user.email} on {target_name} ({self.rating}/5)"
