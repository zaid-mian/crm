from contacts.models import Contact

class ContactQueryService:
    """Handles read queries and scopes contact visibility based on user access."""

    @staticmethod
    def get_visible_contacts(user, base_queryset=None):
        if base_queryset is None:
            base_queryset = Contact.objects.filter(is_deleted=False)

        # Optimize query execution by pre-fetching salesperson relation
        base_queryset = base_queryset.select_related('assigned_salesperson')

        from contacts.permissions import is_manager_or_admin
        if not is_manager_or_admin(user):
            # Salesperson sees only assigned contacts
            return base_queryset.filter(assigned_salesperson=user)
        return base_queryset
