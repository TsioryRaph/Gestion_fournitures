from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('stock/', views.liste_stock, name='liste_stock'),
    path('stock/<int:id>/', views.detail_fourniture, name='detail_fourniture'),
    path('mouvement/', views.mouvement, name='mouvement'),
    path('commande/', views.commande, name='commande'),
    path('commandes/', views.liste_commande, name='liste_commande'),
    path('ajouter/', views.ajouter_fourniture, name='ajouter_fourniture'),
    path('modifier/<int:id>/', views.modifier_fourniture, name='modifier_fourniture'),
    path('types/', views.gestion_types, name='gestion_types'),
    path('statistiques/', views.statistiques, name='statistiques'),
    path('commande/valider/<int:id>/', views.valider_commande, name='valider_commande'),
    path('commande/recevoir/<int:id>/', views.recevoir_commande, name='recevoir_commande'),
]