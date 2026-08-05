from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import Organization, OwnerProfile, RegistrationRequest

User = get_user_model()

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'logo', 'is_active', 'created_at']
        read_only_fields = ['is_active', 'created_at']


class OwnerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = OwnerProfile
        fields = ['id', 'cnic', 'phone_number', 'country', 'address']


class RegistrationRequestSerializer(serializers.ModelSerializer):
    owner_profile = OwnerProfileSerializer(read_only=True)
    organization_name = serializers.CharField(source='owner_profile.organization.name', read_only=True)
    owner_email = serializers.CharField(source='owner_profile.user.email', read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = RegistrationRequest
        fields = [
            'id', 'owner_profile', 'organization_name', 'owner_email', 
            'owner_name', 'status', 'rejection_reason', 'submitted_at', 'reviewed_at'
        ]

    def get_owner_name(self, obj):
        full_name = obj.owner_profile.user.get_full_name()
        return full_name if full_name else obj.owner_profile.user.username


class PlatformSignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    company_name = serializers.CharField(max_length=255)
    cnic = serializers.CharField(max_length=20)
    phone_number = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=100)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
            raise serializers.ValidationError("A user with this email address already exists.")
        return email

    def create(self, validated_data):
        email = validated_data['email']
        password = validated_data['password']
        first_name = validated_data['first_name']
        last_name = validated_data['last_name']
        company_name = validated_data['company_name']
        cnic = validated_data['cnic']
        phone_number = validated_data['phone_number']
        country = validated_data['country']
        address = validated_data.get('address', '')

        with transaction.atomic():
            # Create user (inactive until registration request is approved)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=False
            )
            # Create inactive organization
            org = Organization.objects.create(
                name=company_name,
                is_active=False
            )
            # Create owner profile
            profile = OwnerProfile.objects.create(
                user=user,
                organization=org,
                cnic=cnic,
                phone_number=phone_number,
                country=country,
                address=address
            )
            # Create registration request
            RegistrationRequest.objects.create(
                owner_profile=profile,
                status='pending'
            )

        return profile
