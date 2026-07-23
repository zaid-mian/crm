from rest_framework import serializers
from companies.models import Company
from contacts.models import Contact
from opportunities.models import Opportunity

class CompanyDetailContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ['id', 'full_name', 'email', 'phone_number', 'designation']


class CompanyDetailOpportunitySerializer(serializers.ModelSerializer):
    value = serializers.DecimalField(source='amount', max_digits=12, decimal_places=2)

    class Meta:
        model = Opportunity
        fields = ['id', 'name', 'stage', 'value', 'expected_close_date']


class CompanyListSerializer(serializers.ModelSerializer):
    company_code = serializers.CharField(read_only=True)
    assigned_salesperson_name = serializers.CharField(source='assigned_salesperson.username', read_only=True, default='')

    class Meta:
        model = Company
        fields = [
            'id',
            'company_code',
            'name',
            'type',
            'rating',
            'industry',
            'email',
            'phone',
            'assigned_salesperson_name',
            'created_at'
        ]


class CompanyDetailSerializer(serializers.ModelSerializer):
    company_code = serializers.CharField(read_only=True)
    assigned_salesperson_name = serializers.CharField(source='assigned_salesperson.username', read_only=True, default='')
    summary = serializers.SerializerMethodField()
    contacts = CompanyDetailContactSerializer(many=True, read_only=True)
    opportunities = CompanyDetailOpportunitySerializer(many=True, read_only=True)

    class Meta:
        model = Company
        fields = [
            'id',
            'company_code',
            'name',
            'email',
            'type',
            'rating',
            'industry',
            'annual_revenue',
            'employee_count',
            'lead_source',
            'website',
            'phone',
            'billing_address',
            'shipping_address',
            'description',
            'parent_company',
            'assigned_salesperson',
            'assigned_salesperson_name',
            'created_at',
            'updated_at',
            'summary',
            'contacts',
            'opportunities'
        ]

    def get_summary(self, obj):
        from opportunities.models import OpportunityStage
        from django.db.models import Sum

        contacts_count = obj.contacts.count()
        opps = obj.opportunities.all()

        open_opps_count = opps.exclude(stage__in=[OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST]).count()
        won_opps_count = opps.filter(stage=OpportunityStage.CLOSED_WON).count()
        total_revenue = opps.filter(stage=OpportunityStage.CLOSED_WON).aggregate(total=Sum('amount'))['total'] or 0.00

        return {
            "total_contacts": contacts_count,
            "open_opportunities": open_opps_count,
            "won_opportunities": won_opps_count,
            "total_revenue": float(total_revenue)
        }


class CompanyCreateUpdateSerializer(serializers.ModelSerializer):
    company_code = serializers.CharField(read_only=True)

    class Meta:
        model = Company
        fields = [
            'id',
            'company_code',
            'name',
            'email',
            'type',
            'rating',
            'industry',
            'annual_revenue',
            'employee_count',
            'lead_source',
            'website',
            'phone',
            'billing_address',
            'shipping_address',
            'description',
            'parent_company',
            'assigned_salesperson',
        ]
        read_only_fields = ['id', 'company_code']

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Company name is required.")
        qs = Company.objects.filter(name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A company with this name already exists.")
        return value

    def validate_website(self, value):
        if value:
            import re
            url_regex = re.compile(
                r'^(https?://)?'
                r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
                r'localhost|'
                r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
                r'(?::\d+)?'
                r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            if not url_regex.match(value):
                raise serializers.ValidationError("Enter a valid website URL.")
        return value

    def validate_annual_revenue(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Annual revenue must be greater than or equal to 0.")
        return value

    def validate_employee_count(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Employee count must be greater than or equal to 0.")
        return value
