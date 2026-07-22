from django.contrib import admin
from django.urls import path, include
from contacts.views import dashboard_view

urlpatterns = [
    path('', dashboard_view, name='home-contacts'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('contacts-board/', dashboard_view, name='contacts-board'),
    path('contacts/', dashboard_view, name='contacts'),
    path('admin/', admin.site.urls),
    path('api/', include('leads.urls')),
    path('api/', include('contacts.urls')),
]
