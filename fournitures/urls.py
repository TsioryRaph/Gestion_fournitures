from django.urls import path
from . import views

urlpatterns = [
    # Tableau de bord
    path('', views.dashboard, name='dashboard'),
    # Statistiques
    path('statistiques/', views.statistiques, name='statistiques'),

    # Gestion du stock
    path('stock/', views.liste_stock, name='liste_stock'),
    path('stock/ajouter/', views.ajouter_fourniture, name='ajouter_fourniture'),
    path('stock/modifier/<int:id>/', views.modifier_fourniture, name='modifier_fourniture'),
    path('stock/supprimer/<int:id>/', views.supprimer_fourniture, name='supprimer_fourniture'),
    path('stock/<int:id>/', views.detail_fourniture, name='detail_fourniture'),
    path('stock/ajuster/<int:id>/', views.ajuster_stock, name='ajuster_stock'),

    # Mouvements de stock
    path('mouvement/', views.mouvement, name='mouvement'),

    # Commandes (avec un préfixe clair)
    path('commandes/', views.commande, name='commande'),
    path('commandes/liste/', views.liste_commande, name='liste_commande'),
    path('commandes/historique/', views.historique_commandes, name='historique_commandes'),
    path('commandes/valider/<int:id>/', views.valider_commande, name='valider_commande'),
    path('commandes/recevoir/<int:id>/', views.recevoir_commande, name='recevoir_commande'),
    path('commandes/annuler/<int:id>/', views.annuler_commande, name='annuler_commande'),
    path('commandes/supprimer/<int:id>/', views.supprimer_commande, name='supprimer_commande'),
    path('commandes/mettre-en-cours/<int:id>/', views.mettre_en_cours_commande, name='mettre_en_cours_commande'),

    # Types de fournitures
    path('types/', views.gestion_types, name='gestion_types'),
    path('types/supprimer/<int:id>/', views.supprimer_type, name='supprimer_type'),

    # Import/Export
    path('importer/', views.importer_csv, name='importer_csv'),
    path('exporter/', views.exporter_csv, name='exporter_csv'),

    # API/JSON
    path('api/produit/<int:produit_id>/info/', views.get_produit_info, name='api_produit_info'),
    path('api/types/ajouter/', views.ajouter_type_fourniture_ajax, name='ajouter_type_fourniture_ajax'),
]