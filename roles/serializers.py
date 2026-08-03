from rest_framework import serializers
from roles.models import Role, CRMResource, RolePermission

class CRMResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CRMResource
        fields = ['id', 'codename', 'name']


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'description', 'is_system', 'created_at', 'updated_at']
        read_only_fields = ['is_system', 'created_at', 'updated_at']

    def validate_name(self, value):
        # Case-insensitive uniqueness check
        qs = Role.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value


class RolePermissionSerializer(serializers.ModelSerializer):
    resource_codename = serializers.CharField(source='resource.codename')
    resource_name = serializers.CharField(source='resource.name')

    class Meta:
        model = RolePermission
        fields = ['id', 'resource_codename', 'resource_name', 'action', 'scope']


class RolePermissionUpdateSerializer(serializers.Serializer):
    resource_codename = serializers.CharField(max_length=100)
    action = serializers.CharField(max_length=50)
    scope = serializers.CharField(max_length=50)

    def validate_resource_codename(self, value):
        if not CRMResource.objects.filter(codename=value.lower()).exists():
            raise serializers.ValidationError(f"CRMResource with codename '{value}' does not exist.")
        return value.lower()

    def validate_action(self, value):
        valid_actions = {'VIEW', 'CREATE', 'EDIT', 'DELETE', 'EXPORT', 'APPROVE', 'ASSIGN'}
        if value.upper() not in valid_actions:
            raise serializers.ValidationError(f"Invalid action '{value}'. Must be one of {valid_actions}.")
        return value.upper()

    def validate_scope(self, value):
        valid_scopes = {'ALL', 'OWN', 'NONE'}
        if value.upper() not in valid_scopes:
            raise serializers.ValidationError(f"Invalid scope '{value}'. Must be one of {valid_scopes}.")
        return value.upper()
