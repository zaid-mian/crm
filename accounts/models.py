from django.db import models
from django.conf import settings

class Organization(models.Model):
    name = models.CharField(max_length=255)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class OwnerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE)
    cnic = models.CharField(max_length=20)
    phone_number = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        full_name = self.user.get_full_name()
        label = full_name if full_name else self.user.username
        return f"{label} - {self.organization.name}"


class RegistrationRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    owner_profile = models.OneToOneField(OwnerProfile, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        email_or_username = self.owner_profile.user.email if self.owner_profile.user.email else self.owner_profile.user.username
        return f"{email_or_username} - {self.status}"
