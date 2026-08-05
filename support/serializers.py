from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ContactMessage, Ticket, TicketReply

User = get_user_model()

class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ['id', 'name', 'email', 'subject', 'message', 'status', 'submitted_at']
        read_only_fields = ['status', 'submitted_at']


class TicketReplySerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_email = serializers.EmailField(source='sender.email', read_only=True)
    is_staff = serializers.BooleanField(source='sender.is_staff', read_only=True)

    class Meta:
        model = TicketReply
        fields = ['id', 'ticket', 'sender', 'sender_name', 'sender_email', 'is_staff', 'message', 'created_at']
        read_only_fields = ['sender', 'created_at']

    def get_sender_name(self, obj):
        full_name = obj.sender.get_full_name()
        return full_name if full_name else obj.sender.username


class TicketSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Ticket
        fields = [
            'id', 'ticket_number', 'subject', 'category', 'priority', 'status', 
            'message', 'user_email', 'user_name', 'assigned_to', 'assigned_to_email', 
            'organization', 'organization_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['ticket_number', 'status', 'assigned_to', 'organization', 'created_at', 'updated_at']

    def get_user_name(self, obj):
        full_name = obj.user.get_full_name()
        return full_name if full_name else obj.user.username


class TicketDetailSerializer(serializers.ModelSerializer):
    replies = TicketReplySerializer(many=True, read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True)
    closed_by_email = serializers.EmailField(source='closed_by.email', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Ticket
        fields = [
            'id', 'ticket_number', 'subject', 'category', 'priority', 'status', 
            'message', 'user_email', 'user_name', 'assigned_to', 'assigned_to_email', 
            'closed_by', 'closed_by_email', 'closed_at', 'organization', 'organization_name', 
            'created_at', 'updated_at', 'replies'
        ]
        read_only_fields = ['ticket_number', 'status', 'assigned_to', 'closed_by', 'closed_at', 'organization', 'created_at', 'updated_at']

    def get_user_name(self, obj):
        full_name = obj.user.get_full_name()
        return full_name if full_name else obj.user.username


class TicketStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ['status']
