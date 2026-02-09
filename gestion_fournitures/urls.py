"""gestion_fournitures URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.contrib.auth import logout
from django.shortcuts import redirect

def custom_logout(request):
    logout(request)
    return redirect('login')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('fournitures.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='fournitures/login.html'), name='login'),
    path('logout/', custom_logout, name='logout'),  # Utilisez la vue personnalisée
]