from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q, F  # AJOUTER 'F' ici
from django.utils import timezone
from datetime import timedelta
from .models import Fourniture, Mouvement, Commande, TypeFourniture
from .forms import MouvementForm, FournitureForm, CommandeForm, TypeFournitureForm
from django.db import models
import json


@login_required
def dashboard(request):
    """Tableau de bord principal"""
    # Statistiques
    total_fournitures = Fourniture.objects.count()
    fournitures_alerte = Fourniture.objects.filter(stock__lte=F('seuil_alerte')).count()  # CHANGER ici

    # Mouvements récents (7 derniers jours)
    date_limite = timezone.now() - timedelta(days=7)
    mouvements_recents = Mouvement.objects.filter(date__gte=date_limite).order_by('-date')[:10]

    # Fournitures en alerte
    produits_alerte = Fourniture.objects.filter(stock__lte=F('seuil_alerte')).order_by('stock')  # CHANGER ici

    # Commandes en attente
    commandes_attente = Commande.objects.filter(status='EN_ATTENTE')

    # Statistiques par type
    stats_type = Fourniture.objects.values('type__nom').annotate(
        total=Count('id'),
        en_alerte=Count('id', filter=Q(stock__lte=F('seuil_alerte')))  # CHANGER ici
    )

    context = {
        'total_fournitures': total_fournitures,
        'fournitures_alerte': fournitures_alerte,
        'produits_alerte': produits_alerte,
        'mouvements_recents': mouvements_recents,
        'commandes_attente': commandes_attente,
        'stats_type': stats_type,
    }
    return render(request, 'fournitures/dashboard.html', context)


@login_required
def liste_stock(request):
    """Liste de toutes les fournitures"""
    fournitures = Fourniture.objects.all().order_by('type', 'reference')

    # Filtres
    type_filter = request.GET.get('type')
    alerte_filter = request.GET.get('alerte')

    if type_filter:
        fournitures = fournitures.filter(type_id=type_filter)

    if alerte_filter == 'oui':
        fournitures = fournitures.filter(stock__lte=F('seuil_alerte'))  # CHANGER ici

    types = TypeFourniture.objects.all()

    context = {
        'fournitures': fournitures,
        'types': types,
        'type_filter': type_filter,
        'alerte_filter': alerte_filter,
    }
    return render(request, 'fournitures/liste_stock.html', context)


@login_required
def detail_fourniture(request, id):
    """Détail d'une fourniture avec historique"""
    fourniture = get_object_or_404(Fourniture, id=id)
    mouvements = fourniture.mouvements.all().order_by('-date')

    context = {
        'fourniture': fourniture,
        'mouvements': mouvements,
    }
    return render(request, 'fournitures/detail_fourniture.html', context)


@login_required
def mouvement(request):
    """Gestion des mouvements de stock"""
    if request.method == 'POST':
        form = MouvementForm(request.POST)
        if form.is_valid():
            mouvement = form.save(commit=False)
            mouvement.utilisateur = request.user

            # Mettre à jour le stock
            produit = mouvement.produit
            if mouvement.type_mouvement == 'ENTREE':
                produit.stock += mouvement.quantite
            else:  # SORTIE
                produit.stock -= mouvement.quantite

            produit.save()
            mouvement.save()

            messages.success(request, 'Mouvement enregistré avec succès!')
            return redirect('liste_stock')
    else:
        form = MouvementForm()

    context = {
        'form': form,
    }
    return render(request, 'fournitures/mouvement.html', context)


@login_required
def commande(request):
    """Gestion des commandes"""
    if request.method == 'POST':
        form = CommandeForm(request.POST)
        if form.is_valid():
            commande = form.save(commit=False)
            commande.status = 'EN_ATTENTE'
            commande.save()
            messages.success(request, 'Commande créée avec succès!')
            return redirect('commande')  # CHANGER de 'liste_commande' à 'commande'
    else:
        form = CommandeForm()

    # Liste des produits à commander (suggestion automatique)
    produits_a_commander = []
    for fourniture in Fourniture.objects.filter(stock__lte=F('seuil_alerte')):  # CHANGER ici
        quantite = fourniture.quantite_a_commander()
        if quantite > 0:
            produits_a_commander.append({
                'fourniture': fourniture,
                'quantite': quantite
            })

    # Commandes en attente
    commandes_attente = Commande.objects.filter(status='EN_ATTENTE')

    context = {
        'form': form,
        'produits_a_commander': produits_a_commander,
        'commandes_attente': commandes_attente,
    }
    return render(request, 'fournitures/commande.html', context)


@login_required
def liste_commande(request):
    """Liste des commandes"""
    commandes = Commande.objects.all().order_by('-date_creation')

    context = {
        'commandes': commandes,
    }
    return render(request, 'fournitures/liste_commande.html', context)


@login_required
def valider_commande(request, id):
    """Valider une commande"""
    commande = get_object_or_404(Commande, id=id)

    if request.method == 'POST':
        commande.status = 'VALIDEE'
        commande.date_validation = timezone.now()
        commande.save()
        messages.success(request, 'Commande validée avec succès!')

    return redirect('liste_commande')


@login_required
def recevoir_commande(request, id):
    """Marquer une commande comme reçue"""
    commande = get_object_or_404(Commande, id=id)

    if request.method == 'POST':
        # Créer un mouvement d'entrée
        Mouvement.objects.create(
            produit=commande.produit,
            type_mouvement='ENTREE',
            quantite=commande.quantite,
            utilisateur=request.user,
            notes=f"Réception commande #{commande.id}"
        )

        # Mettre à jour le stock
        commande.produit.stock += commande.quantite
        commande.produit.save()

        # Mettre à jour la commande
        commande.status = 'RECUE'
        commande.save()

        messages.success(request, 'Commande reçue! Stock mis à jour.')

    return redirect('liste_commande')


@login_required
def ajouter_fourniture(request):
    """Ajouter une nouvelle fourniture"""
    if request.method == 'POST':
        form = FournitureForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fourniture ajoutée avec succès!')
            return redirect('liste_stock')
    else:
        form = FournitureForm()

    context = {
        'form': form,
    }
    return render(request, 'fournitures/ajouter_fourniture.html', context)


@login_required
def modifier_fourniture(request, id):
    """Modifier une fourniture"""
    fourniture = get_object_or_404(Fourniture, id=id)

    if request.method == 'POST':
        form = FournitureForm(request.POST, instance=fourniture)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fourniture modifiée avec succès!')
            return redirect('liste_stock')
    else:
        form = FournitureForm(instance=fourniture)

    context = {
        'form': form,
        'fourniture': fourniture,
    }
    return render(request, 'fournitures/modifier_fourniture.html', context)


@login_required
def gestion_types(request):
    """Gérer les types de fournitures"""
    if request.method == 'POST':
        form = TypeFournitureForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Type ajouté avec succès!')
            return redirect('gestion_types')
    else:
        form = TypeFournitureForm()

    types = TypeFourniture.objects.all()

    context = {
        'form': form,
        'types': types,
    }
    return render(request, 'fournitures/gestion_types.html', context)


@login_required
@login_required
def statistiques(request):
    # Données de base
    total_fournitures = Fourniture.objects.count()
    valeur_stock = Fourniture.objects.aggregate(total=Sum('stock'))['total'] or 0

    # Produits en alerte
    produits_en_alerte = Fourniture.objects.filter(stock__lte=F('seuil_alerte')).count()
    produits_bas_stock = Fourniture.objects.filter(stock__lte=F('seuil_alerte')).order_by('stock')[:10]

    # Mouvements des 30 derniers jours
    date_limite = timezone.now() - timedelta(days=30)
    mouvements = Mouvement.objects.filter(date__gte=date_limite)
    total_mouvements = mouvements.count()
    total_entrees = mouvements.filter(type_mouvement='ENTREE').count()
    total_sorties = mouvements.filter(type_mouvement='SORTIE').count()

    # Top 10 des produits les plus utilisés
    top_sorties = Mouvement.objects.filter(type_mouvement='SORTIE') \
        .values('produit__designation', 'produit__type__nom') \
        .annotate(total=Sum('quantite')) \
        .order_by('-total')[:10]

    # Types de fournitures (pour les graphiques et l'affichage)
    types = TypeFourniture.objects.annotate(count=Count('fournitures')).order_by('-count')

    # Données pour le graphique par type
    types_labels = [t.nom for t in types]  # Liste Python
    types_data = [t.count for t in types]  # Liste Python

    # Données pour le graphique des mouvements (7 derniers jours)
    mouvement_labels = []
    mouvement_entrees_data = []
    mouvement_sorties_data = []

    for i in range(6, -1, -1):
        date = timezone.now() - timedelta(days=i)
        date_str = date.strftime('%d/%m')
        mouvement_labels.append(date_str)

        # Entrées du jour
        entrees = Mouvement.objects.filter(
            date__date=date.date(),
            type_mouvement='ENTREE'
        ).aggregate(total=Sum('quantite'))['total'] or 0
        mouvement_entrees_data.append(entrees)

        # Sorties du jour
        sorties = Mouvement.objects.filter(
            date__date=date.date(),
            type_mouvement='SORTIE'
        ).aggregate(total=Sum('quantite'))['total'] or 0
        mouvement_sorties_data.append(sorties)

    # Calcul des ratios
    ratio_entrees_sorties = f"{total_entrees}:{total_sorties}" if total_sorties > 0 else "N/A"
    activite_moyenne_jour = round(total_mouvements / 30, 1) if total_mouvements > 0 else 0
    taux_alerte = round((produits_en_alerte / total_fournitures * 100), 1) if total_fournitures > 0 else 0

    context = {
        'total_fournitures': total_fournitures,
        'valeur_stock': valeur_stock,
        'produits_en_alerte': produits_en_alerte,
        'total_mouvements': total_mouvements,
        'total_entrees': total_entrees,
        'total_sorties': total_sorties,
        'top_sorties': top_sorties,
        'produits_bas_stock': produits_bas_stock,
        'types': types,  # ← AJOUTEZ CETTE LIGNE
        'types_labels': types_labels,
        'types_data': types_data,
        'mouvement_labels': mouvement_labels,
        'mouvement_entrees_data': mouvement_entrees_data,
        'mouvement_sorties_data': mouvement_sorties_data,
        'ratio_entrees_sorties': ratio_entrees_sorties,
        'activite_moyenne_jour': activite_moyenne_jour,
        'taux_alerte': taux_alerte,
    }

    return render(request, 'fournitures/statistiques.html', context)