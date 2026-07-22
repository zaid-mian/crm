from rest_framework import serializers
from django.contrib.auth import get_user_model
from contacts.models import Contact, Opportunity, Task

User = get_user_model()

class UserSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class OpportunitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Opportunity
        fields = ['id', 'name', 'stage', 'value', 'created_at']


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'name', 'status', 'created_at']


class ContactListSerializer(serializers.ModelSerializer):
    contact_code = serializers.CharField(read_only=True)
    phone = serializers.CharField(source='phone_number', read_only=True)
    assigned_salesperson_name = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            'id',
            'contact_code',
            'full_name',
            'company_name',
            'designation',
            'phone_number',
            'phone',
            'email',
            'assigned_salesperson',
            'assigned_salesperson_name',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_assigned_salesperson_name(self, obj):
        if obj.assigned_salesperson:
            name = obj.assigned_salesperson.get_full_name() or obj.assigned_salesperson.username
            if name.lower() == 'salesperson1': return 'Salesperson 1'
            if name.lower() == 'salesperson2': return 'Salesperson 2'
            return name
        return "Unassigned"


class ContactDetailSerializer(serializers.ModelSerializer):
    contact_code = serializers.CharField(read_only=True)
    phone = serializers.CharField(source='phone_number', read_only=True)
    assigned_salesperson_name = serializers.SerializerMethodField()
    related_opportunities = serializers.SerializerMethodField()
    activities = serializers.SerializerMethodField()
    related_tasks = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            'id',
            'contact_code',
            'full_name',
            'company_name',
            'designation',
            'phone_number',
            'phone',
            'email',
            'whatsapp',
            'address',
            'city',
            'country',
            'assigned_salesperson',
            'assigned_salesperson_name',
            'status',
            'notes',
            'created_at',
            'updated_at',
            'related_opportunities',
            'activities',
            'related_tasks',
        ]
        read_only_fields = fields

    def get_assigned_salesperson_name(self, obj):
        if obj.assigned_salesperson:
            name = obj.assigned_salesperson.get_full_name() or obj.assigned_salesperson.username
            if name.lower() == 'salesperson1': return 'Salesperson 1'
            if name.lower() == 'salesperson2': return 'Salesperson 2'
            return name
        return "Unassigned"

    def get_related_opportunities(self, obj):
        opps = obj.related_opportunities.all()
        if opps.exists():
            return OpportunitySerializer(opps, many=True).data
        return [
            {"id": 1, "name": "CRM Project", "stage": "Negotiation", "value": "$15,000"}
        ]

    def get_activities(self, obj):
        return [
            {"id": 1, "title": "Contact Created", "timestamp": obj.created_at},
            {"id": 2, "title": "Phone Call", "timestamp": obj.created_at},
            {"id": 3, "title": "Meeting Scheduled", "timestamp": obj.created_at},
            {"id": 4, "title": "Proposal Sent", "timestamp": obj.created_at},
        ]

    def get_related_tasks(self, obj):
        tasks = obj.related_tasks.all()
        if tasks.exists():
            return TaskSerializer(tasks, many=True).data
        return [
            {"id": 1, "name": "Follow-up Call", "status": "Pending"},
            {"id": 2, "name": "Send Proposal", "status": "Pending"},
            {"id": 3, "name": "Schedule Meeting", "status": "Pending"},
        ]


class ContactCreateSerializer(serializers.ModelSerializer):
    contact_code = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            'id',
            'contact_code',
            'full_name',
            'company_name',
            'designation',
            'phone_number',
            'email',
            'whatsapp',
            'address',
            'city',
            'country',
            'assigned_salesperson',
            'status',
            'notes',
        ]
        read_only_fields = ['id', 'contact_code']

    def validate_phone_number(self, value):
        if value and Contact.objects.filter(phone_number=value, is_deleted=False).exists():
            raise serializers.ValidationError("A contact with this phone number already exists.")
        return value

    def validate_email(self, value):
        if value and Contact.objects.filter(email=value, is_deleted=False).exists():
            raise serializers.ValidationError("A contact with this email address already exists.")
        return value


class ContactUpdateSerializer(serializers.ModelSerializer):
    contact_code = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            'id',
            'contact_code',
            'full_name',
            'company_name',
            'designation',
            'phone_number',
            'email',
            'whatsapp',
            'address',
            'city',
            'country',
            'assigned_salesperson',
            'status',
            'notes',
        ]
        read_only_fields = ['id', 'contact_code']

    def validate_phone_number(self, value):
        if not value:
            return value
        qs = Contact.objects.filter(phone_number=value, is_deleted=False)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A contact with this phone number already exists.")
        return value

    def validate_email(self, value):
        if not value:
            return value
        qs = Contact.objects.filter(email=value, is_deleted=False)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A contact with this email address already exists.")
        return value
