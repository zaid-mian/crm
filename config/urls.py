from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/', include('leads.urls')),
    path('api/', include('contacts.urls')),
    path('api/', include('opportunities.urls')),
    path('api/', include('companies.urls')),
    path('api/', include('pipeline.urls')),
    path('api/', include('payments.urls')),

    # ADD THESE
    path('api/', include('roles.urls')),
    path('api/', include('dashboard.urls')),
    path('api/', include('catalog.urls')),
    path('api/', include('accounts.urls')),
]