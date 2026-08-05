import os
from django.db import models
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from catalog.models.product import validate_product_image

class Service(models.Model):
    name = models.CharField(max_length=255, help_text="Name of the professional service (e.g. CRM Consultation)")
    slug = models.SlugField(unique=True, help_text="Unique slug for URL routing")
    short_description = models.CharField(max_length=500, help_text="Brief summary of the service")
    full_description = models.TextField(blank=True, help_text="Detailed description of the service")
    image = models.ImageField(
        upload_to="services/",
        blank=True,
        null=True,
        validators=[validate_product_image]
    )
    is_active = models.BooleanField(default=True, db_index=True, help_text="Designates whether this service is active and visible")
    display_order = models.PositiveIntegerField(default=0, db_index=True, help_text="Order in which this service is displayed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.name


class ServiceFeature(models.Model):
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='features',
        help_text="The service this feature belongs to"
    )
    name = models.CharField(max_length=255, help_text="Short name/description of the feature (e.g. Email Support)")
    display_order = models.PositiveIntegerField(default=0, db_index=True, help_text="Order in which this feature is displayed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.service.name} - {self.name}"


@receiver(post_delete, sender=Service)
def delete_service_image_on_delete(sender, instance, **kwargs):
    """Deletes image file from filesystem when corresponding Service object is deleted."""
    if instance.image:
        try:
            if os.path.isfile(instance.image.path):
                os.remove(instance.image.path)
        except ValueError:
            pass


@receiver(pre_save, sender=Service)
def delete_service_image_on_change(sender, instance, **kwargs):
    """Deletes old image file from filesystem when corresponding Service object is updated with a new image."""
    if not instance.pk:
        return False

    try:
        old_image = Service.objects.get(pk=instance.pk).image
    except Service.DoesNotExist:
        return False

    new_image = instance.image
    if old_image and old_image != new_image:
        try:
            if os.path.isfile(old_image.path):
                os.remove(old_image.path)
        except ValueError:
            pass
