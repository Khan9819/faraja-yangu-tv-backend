from rest_framework import serializers
from apps.authentication.models import User


class AdminUserSerializer(serializers.ModelSerializer):
    """Serializer for CMS admin/staff users."""

    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    permission = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'first_name',
            'last_name',
            'username',
            'email',
            'permission',
            'role',
            'is_active',
            'last_login',
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_role(self, obj):
        """Return human-readable role name from the first admin-type role."""
        role = obj.roles.exclude(name='USER').first()
        if role:
            return role.name.replace('_', ' ').title()
        return 'Admin'

    def get_permission(self, obj):
        """Return permission slug from the first admin-type role."""
        role = obj.roles.exclude(name='USER').first()
        if role:
            return role.name.lower()
        return 'admin'


class AdminUserCreateSerializer(serializers.Serializer):
    """Serializer for creating a new admin user."""

    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    username = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=['super_admin', 'admin', 'moderator'])
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value


class AdminUserUpdateSerializer(serializers.Serializer):
    """Serializer for updating an admin user. All fields optional."""

    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    username = serializers.CharField(max_length=150, required=False)
    role = serializers.ChoiceField(choices=['super_admin', 'admin', 'moderator'], required=False)
    password = serializers.CharField(min_length=8, write_only=True, required=False)

    def validate_email(self, value):
        user = self.context.get('user')
        if user and User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        user = self.context.get('user')
        if user and User.objects.filter(username=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value
