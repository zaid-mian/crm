from rest_framework import filters

class ContactSearchFilter(filters.SearchFilter):
    """
    Custom search filter searching across full_name, phone_number, email, company_name, and designation.
    """
    search_param = 'search'
