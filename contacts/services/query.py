from contacts.models import Contact

class ContactQueryService:
    """Handles read queries and scopes contact visibility based on user access."""

    @staticmethod
    def get_visible_contacts(user, base_queryset=None):
        if base_queryset is None:
            base_queryset = Contact.objects.filter(is_deleted=False)

        # Optimize query execution by pre-fetching salesperson relation
        base_queryset = base_queryset.select_related('assigned_salesperson')

        from roles.permissions import get_scoped_queryset
        return get_scoped_queryset(base_queryset, user, resource_codename='contacts', owner_field='assigned_salesperson')
