from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('leads.urls')),
    path('api/', include('contacts.urls')),
    path('api/', include('opportunities.urls')),
    path('api/', include('companies.urls')),
]
