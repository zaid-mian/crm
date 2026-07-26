from django.urls import path, include

from config.views import PaymentsBoardView, home_redirect

urlpatterns = [
    path('', home_redirect, name='home'),
    path('payments/', PaymentsBoardView.as_view(), name='crm_payments'),
    path('api/', include('leads.urls')),
    path('api/', include('contacts.urls')),
    path('api/', include('opportunities.urls')),
    path('api/', include('companies.urls')),
    path('api/', include('pipeline.urls')),
    path('api/', include('payments.urls')),
]
