from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q, F, OuterRef, Subquery
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import logout
import json
import traceback
import csv
from io import TextIOWrapper
import re
import time

from .models import Fourniture, Mouvement, Commande, TypeFourniture
from .forms import MouvementForm, FournitureForm, CommandeForm, TypeFournitureForm


# ==================== FONCTIONS UTILITAIRES ====================

def generer_reference_auto():
    """Génère automatiquement une nouvelle référence Fxxx"""
    try:
        # Trouver la plus haute référence numérique existante
        last_ref = Fourniture.objects.filter(
            reference__regex=r'^F\d+$'
        ).order_by('reference').last()

        if last_ref:
            match = re.match(r'^F(\d+)$', last_ref.reference)
            if match:
                next_num = int(match.group(1)) + 1
            else:
                next_num = 1
        else:
            next_num = 1

        # Formater avec 3 chiffres minimum
        return f"F{next_num:03d}"

    except Exception:
        return f"F{int(time.time()) % 1000:03d}"


# ==================== TABLEAU DE BORD ====================

@login_required
def dashboard(request):
    """Tableau de bord principal avec graphiques - VERSION CORRIGÉE"""
    from decimal import Decimal

    def decimal_to_float(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (list, tuple)):
            return [decimal_to_float(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: decimal_to_float(value) for key, value in obj.items()}
        return obj

    # ==================== STATISTIQUES PRINCIPALES ====================

    # Compter TOUTES les fournitures actives
    total_fournitures = Fourniture.objects.filter(actif=True).count()

    # Compter les fournitures en alerte
    fournitures_en_alerte = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).count()

    # Fournitures en alerte CRITIQUE (stock très bas)
    fournitures_alerte_critique = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte') * 0.5,
        actif=True
    ).count()

    # Fournitures en alerte SANS commande en cours
    commandes_en_cours = Commande.objects.filter(
        produit=OuterRef('pk'),
        status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
    ).values('produit')

    fournitures_alerte_sans_commande = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).exclude(
        id__in=Subquery(commandes_en_cours)
    ).count()

    # ==================== STATISTIQUES COMMANDES ====================

    # Commandes par statut - TOUS les statuts
    commandes_attente = Commande.objects.filter(status='EN_ATTENTE').count()
    commandes_validees = Commande.objects.filter(status='VALIDEE').count()
    commandes_en_cours_livraison = Commande.objects.filter(status='EN_COURS').count()
    commandes_recues = Commande.objects.filter(status='RECUE').count()
    commandes_annulees = Commande.objects.filter(status='ANNULEE').count()

    # Commandes en retard (VALIDEE depuis plus de 7 jours)
    commandes_retard = Commande.objects.filter(
        status='VALIDEE',
        date_validation__lt=timezone.now() - timedelta(days=7)
    ).count()

    # Total des commandes actives (non annulées et non reçues)
    commandes_actives = Commande.objects.filter(
        status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
    ).count()

    # ==================== PRODUITS EN ALERTE ====================

    # Produits en alerte avec détails
    produits_alerte = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).select_related('type').order_by('stock')[:10]

    produits_alerte_data = []
    for produit in produits_alerte:
        pourcentage = 0
        if produit.stock_max and produit.stock_max > 0:
            try:
                pourcentage = (float(produit.stock) / float(produit.stock_max)) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                pourcentage = 0

        # Commandes actives pour ce produit
        commandes_actives_produit = produit.commandes.filter(
            status__in=['VALIDEE', 'EN_COURS']
        ).aggregate(total=Sum('quantite'))['total'] or 0

        # Calcul de la quantité à commander
        if produit.stock_max:
            besoin_base = max(0, float(produit.stock_max) - (float(produit.stock) + float(commandes_actives_produit)))

            if besoin_base == 0 and produit.stock <= produit.seuil_alerte:
                quantite_a_commander = max(1, float(produit.seuil_alerte) - float(produit.stock) + 1)
            else:
                quantite_a_commander = besoin_base
        else:
            quantite_a_commander = max(1, float(produit.seuil_alerte) - float(produit.stock) + 1)

        # Vérifier s'il y a une commande en cours
        commande_en_cours = produit.commandes.filter(
            status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
        ).exists()

        # Récupérer la commande en cours si elle existe
        commande_active = produit.commandes.filter(
            status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
        ).order_by('-date_creation').first()

        produit_data = {
            'id': produit.id,
            'reference': produit.reference,
            'designation': produit.designation,
            'type': produit.type.nom if produit.type else "Non spécifié",
            'stock': float(produit.stock),
            'seuil_alerte': float(produit.seuil_alerte),
            'stock_max': float(produit.stock_max) if produit.stock_max else 0,
            'unite': produit.unite,
            'pourcentage_stock': round(pourcentage, 1),
            'quantite_a_commander': round(quantite_a_commander),
            'en_alerte': produit.stock <= produit.seuil_alerte,
            'commande_en_cours': commande_en_cours,
            'commande_active': commande_active,
            'statut_commande': commande_active.status if commande_active else None,
        }
        produits_alerte_data.append(produit_data)

    # ==================== MOUVEMENTS RÉCENTS ====================

    # Mouvements récents (7 derniers jours)
    date_limite = timezone.now() - timedelta(days=7)
    mouvements_recents = Mouvement.objects.filter(
        date__gte=date_limite
    ).select_related('produit', 'utilisateur').order_by('-date')[:10]

    # ==================== COMMANDES RÉCENTES ====================

    # Commandes récentes (tous statuts)
    commandes_recentes = Commande.objects.filter(
        produit__isnull=False,
        produit__actif=True
    ).select_related(
        'produit', 'produit__type', 'utilisateur', 'utilisateur_validation'
    ).order_by('-date_creation')[:5]

    # ==================== STATISTIQUES PAR TYPE ====================

    # Statistiques par type de fourniture
    stats_type = []
    type_stats_data = []

    for type_obj in TypeFourniture.objects.all():
        fournitures_type = Fourniture.objects.filter(type=type_obj, actif=True)
        count = fournitures_type.count()

        if count > 0:
            # Stock total
            stock_total_result = fournitures_type.aggregate(total=Sum('stock'))
            stock_total = float(stock_total_result['total'] or 0)

            # Produits en alerte dans ce type
            en_alerte = fournitures_type.filter(stock__lte=F('seuil_alerte')).count()

            # Valeur en pourcentage
            pourcentage_alerte = (en_alerte / count * 100) if count > 0 else 0

            type_stat = {
                'type__nom': type_obj.nom,
                'type_id': type_obj.id,
                'total': count,
                'en_alerte': en_alerte,
                'stock_total': stock_total,
                'pourcentage_alerte': round(pourcentage_alerte, 1)
            }
            stats_type.append(type_stat)
            type_stats_data.append(type_stat)

    # ==================== DONNÉES POUR GRAPHIQUES ====================

    # Graphique 1: Répartition par type (top 8)
    labels_type = []
    series_type = []
    for stat in sorted(type_stats_data, key=lambda x: x['total'], reverse=True)[:8]:
        labels_type.append(stat['type__nom'])
        series_type.append(stat['total'])

    # Graphique 2: Mouvements des 7 derniers jours
    dates_ordered = []
    entree_by_date = {}
    sortie_by_date = {}

    current_date = timezone.now().date()
    for i in range(6, -1, -1):
        date_calc = current_date - timedelta(days=i)
        date_str = date_calc.strftime('%d/%m')
        dates_ordered.append(date_str)
        entree_by_date[date_str] = 0
        sortie_by_date[date_str] = 0

    mouvements_7jours = Mouvement.objects.filter(
        date__gte=timezone.now() - timedelta(days=7)
    )

    for mouvement in mouvements_7jours:
        date_str = mouvement.date.strftime('%d/%m')
        if date_str in entree_by_date:
            if mouvement.type_mouvement == 'ENTREE':
                entree_by_date[date_str] += float(mouvement.quantite)
            else:
                sortie_by_date[date_str] += float(mouvement.quantite)

    entree_data = [entree_by_date.get(d, 0) for d in dates_ordered]
    sortie_data = [sortie_by_date.get(d, 0) for d in dates_ordered]

    # Graphique 3: Top 5 produits les plus sortis (30 derniers jours)
    date_30jours = timezone.now() - timedelta(days=30)
    top_sorties = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date__gte=date_30jours,
        produit__isnull=False,
        produit__actif=True
    ).values('produit__designation', 'produit__reference').annotate(
        total=Sum('quantite')
    ).order_by('-total')[:5]

    top_labels = []
    top_series = []
    for item in top_sorties:
        designation = item['produit__designation']
        if designation:
            # Tronquer si trop long
            if len(designation) > 20:
                label = designation[:18] + '...'
            else:
                label = designation
            top_labels.append(label)
            top_series.append(float(item['total'] or 0))

    # ==================== CONTEXTE ====================

    context = {
        # Statistiques générales
        'total_fournitures': total_fournitures,
        'fournitures_alerte': fournitures_en_alerte,
        'fournitures_alerte_critique': fournitures_alerte_critique,
        'fournitures_alerte_sans_commande': fournitures_alerte_sans_commande,

        # Statistiques commandes - TOUS LES STATUTS
        'commandes_attente': commandes_attente,
        'commandes_validees': commandes_validees,
        'commandes_en_cours': commandes_en_cours_livraison,
        'commandes_recues': commandes_recues,
        'commandes_annulees': commandes_annulees,
        'commandes_actives': commandes_actives,
        'commandes_retard': commandes_retard,

        # Produits en alerte
        'produits_alerte': produits_alerte_data,

        # Activité récente
        'mouvements_recents': mouvements_recents,
        'commandes_recentes': commandes_recentes,

        # Statistiques par type
        'stats_type': stats_type,

        # Données pour graphiques
        'labels_type_json': json.dumps(labels_type),
        'series_type_json': json.dumps(series_type),
        'dates_mouvements_json': json.dumps(dates_ordered),
        'entree_data_json': json.dumps(entree_data),
        'sortie_data_json': json.dumps(sortie_data),
        'top_labels_json': json.dumps(top_labels),
        'top_series_json': json.dumps(top_series),

        # Variables pour calculs internes
        'total_commandes': commandes_attente + commandes_validees + commandes_en_cours_livraison + commandes_recues + commandes_annulees,
    }

    return render(request, 'fournitures/dashboard.html', context)

# ==================== GESTION DU STOCK ====================

@login_required
def liste_stock(request):
    """Liste de toutes les fournitures - VERSION CORRIGÉE"""
    types = TypeFourniture.objects.all().order_by('nom')

    # Récupérer TOUTES les fournitures actives par défaut
    fournitures_queryset = Fourniture.objects.filter(actif=True).select_related('type').order_by('type__nom',
                                                                                                 'reference')

    # Appliquer les filtres
    type_filter = request.GET.get('type')
    alerte_filter = request.GET.get('alerte')

    if type_filter:
        fournitures_queryset = fournitures_queryset.filter(type_id=type_filter)

    if alerte_filter == 'oui':
        fournitures_queryset = fournitures_queryset.filter(stock__lte=F('seuil_alerte'))
    elif alerte_filter == 'non':
        fournitures_queryset = fournitures_queryset.filter(stock__gt=F('seuil_alerte'))

    # Convertir en liste avec les données calculées
    fournitures_list = []
    for f in fournitures_queryset:
        pourcentage = 0
        if f.stock_max and f.stock_max > 0:
            try:
                pourcentage = (float(f.stock) / float(f.stock_max)) * 100
            except (ZeroDivisionError, TypeError):
                pourcentage = 0

        en_alerte = f.stock <= f.seuil_alerte

        fournitures_list.append({
            'id': f.id,
            'reference': f.reference,
            'designation': f.designation,
            'type': f.type,
            'unite': f.unite,
            'stock': float(f.stock),
            'stock_max': float(f.stock_max),
            'seuil_alerte': float(f.seuil_alerte),
            'pourcentage_stock': round(pourcentage, 1),
            'en_alerte': en_alerte,
            'actif': f.actif,
        })

    # Statistiques
    total_fournitures = fournitures_queryset.count()
    en_alerte_count = fournitures_queryset.filter(stock__lte=F('seuil_alerte')).count()
    stock_total_result = fournitures_queryset.aggregate(total=Sum('stock'))
    stock_total = float(stock_total_result['total'] or 0)

    context = {
        'fournitures': fournitures_list,
        'types': types,
        'type_filter': type_filter,
        'alerte_filter': alerte_filter,
        'stats': {
            'total': total_fournitures,
            'en_alerte': en_alerte_count,
            'stock_total': stock_total,
        },
    }
    return render(request, 'fournitures/liste_stock.html', context)


@login_required
def ajouter_fourniture(request):
    """Ajouter une nouvelle fourniture - VERSION UNIQUE ET CORRIGÉE"""
    if request.method == 'POST':
        form = FournitureForm(request.POST)
        if form.is_valid():
            try:
                # IMPORTANT: Laisser le formulaire gérer TOUTE la sauvegarde
                fourniture = form.save()

                # DEBUG dans la console
                print(f"\n=== DEBUG FOURNITURE AJOUTÉE ===")
                print(f"ID: {fourniture.id}")
                print(f"Référence: {fourniture.reference}")
                print(f"Désignation: {fourniture.designation}")
                print(f"Stock: {fourniture.stock}")
                print(f"Actif: {fourniture.actif}")
                print(f"Type: {fourniture.type.nom if fourniture.type else 'None'}")
                print(f"================================")

                messages.success(request,
                                 f'✅ Fourniture ajoutée avec succès!<br>'
                                 f'<strong>Référence:</strong> {fourniture.reference}<br>'
                                 f'<strong>Désignation:</strong> {fourniture.designation}<br>'
                                 f'<strong>Type:</strong> {fourniture.type.nom if fourniture.type else "Non spécifié"}<br>'
                                 f'<strong>Stock initial:</strong> {fourniture.stock} {fourniture.unite}<br>'
                                 f'<strong>Actif:</strong> {"Oui" if fourniture.actif else "Non"}',
                                 extra_tags='safe')

                # Redirection selon le bouton cliqué
                if 'save_and_add' in request.POST:
                    return redirect('ajouter_fourniture')
                elif 'save_and_edit' in request.POST:
                    return redirect('modifier_fourniture', id=fourniture.id)
                else:
                    return redirect('liste_stock')

            except ValidationError as e:
                messages.error(request,
                               f'❌ Erreur de validation:<br>{str(e)}',
                               extra_tags='safe')
                return render(request, 'fournitures/ajouter_fourniture.html', {'form': form})
            except Exception as e:
                messages.error(request,
                               f'❌ Erreur lors de l\'ajout:<br>{str(e)}',
                               extra_tags='safe')
                traceback.print_exc()
                return render(request, 'fournitures/ajouter_fourniture.html', {'form': form})
        else:
            # Afficher les erreurs du formulaire
            error_messages = []
            for field, errors in form.errors.items():
                if field != '__all__':
                    field_name = form.fields[field].label if field in form.fields else field
                    for error in errors:
                        error_messages.append(f"• <strong>{field_name}:</strong> {error}")

            if '__all__' in form.errors:
                for error in form.errors['__all__']:
                    error_messages.append(f"• {error}")

            if error_messages:
                messages.error(request,
                               "❌ Erreurs dans le formulaire:<br>" + "<br>".join(error_messages),
                               extra_tags='safe')
    else:
        # Formulaire initial
        form = FournitureForm(initial={
            'stock': 0,
            'stock_max': 10,
            'seuil_alerte': 5,
            'actif': True,
            'generer_reference_auto': True,
        })

    context = {
        'form': form,
        'title': 'Ajouter une nouvelle fourniture',
    }
    return render(request, 'fournitures/ajouter_fourniture.html', context)


@login_required
def modifier_fourniture(request, id):
    """Modifier une fourniture"""
    fourniture = get_object_or_404(Fourniture, id=id)

    if request.method == 'POST':
        form = FournitureForm(request.POST, instance=fourniture)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, '✅ Fourniture modifiée avec succès!', extra_tags='safe')
                return redirect('liste_stock')
            except Exception as e:
                messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')
    else:
        form = FournitureForm(instance=fourniture)

    context = {
        'form': form,
        'fourniture': fourniture,
    }
    return render(request, 'fournitures/modifier_fourniture.html', context)


@login_required
def supprimer_fourniture(request, id):
    """Supprimer une fourniture (désactiver)"""
    if request.method == 'POST':
        try:
            fourniture = get_object_or_404(Fourniture, id=id)

            # Vérifier s'il y a du stock
            if fourniture.stock > 0:
                messages.error(request,
                               f'❌ Impossible de supprimer {fourniture.designation} car il reste du stock '
                               f'({fourniture.stock} {fourniture.unite})',
                               extra_tags='safe')
                return redirect('liste_stock')

            # Vérifier s'il y a des commandes en cours
            commandes_en_cours = fourniture.commandes.filter(
                status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
            ).exists()

            if commandes_en_cours:
                messages.error(request,
                               f'❌ Impossible de supprimer {fourniture.designation} car des commandes sont en cours',
                               extra_tags='safe')
                return redirect('liste_stock')

            # Désactiver plutôt que supprimer
            fourniture.actif = False
            fourniture.save()

            messages.success(request, f'✅ Fourniture {fourniture.designation} désactivée avec succès!',
                             extra_tags='safe')

        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('liste_stock')


@login_required
def detail_fourniture(request, id):
    """Détail d'une fourniture avec historique"""
    fourniture = get_object_or_404(Fourniture.objects.select_related('type'), id=id)

    # Mouvements récents (30 derniers jours)
    date_limite = timezone.now() - timedelta(days=30)
    mouvements = fourniture.mouvements.filter(
        date__gte=date_limite
    ).order_by('-date')

    # Commandes en cours
    commandes_cours = fourniture.commandes.filter(
        status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
    ).order_by('-date_creation')

    # Statistiques du produit
    stats_mouvements = {
        'entrees_30j': mouvements.filter(type_mouvement='ENTREE').aggregate(total=Sum('quantite'))['total'] or 0,
        'sorties_30j': mouvements.filter(type_mouvement='SORTIE').aggregate(total=Sum('quantite'))['total'] or 0,
    }

    context = {
        'fourniture': fourniture,
        'mouvements': mouvements,
        'commandes_cours': commandes_cours,
        'stats_mouvements': stats_mouvements,
    }
    return render(request, 'fournitures/detail_fourniture.html', context)


# ==================== MOUVEMENTS ====================

@login_required
def mouvement(request):
    """Gestion des mouvements de stock"""
    if request.method == 'POST':
        form = MouvementForm(request.POST)
        if form.is_valid():
            try:
                mouvement_obj = form.save(commit=False)
                mouvement_obj.utilisateur = request.user
                produit = mouvement_obj.produit

                ancien_stock = produit.stock

                try:
                    if mouvement_obj.type_mouvement == 'ENTREE':
                        nouveau_stock = produit.entree_stock(
                            quantite=float(mouvement_obj.quantite),
                            utilisateur=request.user,
                            notes=mouvement_obj.notes or ""
                        )
                    else:
                        nouveau_stock = produit.sortie_stock(
                            quantite=float(mouvement_obj.quantite),
                            utilisateur=request.user,
                            notes=mouvement_obj.notes or ""
                        )

                    messages.success(request,
                                     f'✅ Mouvement enregistré avec succès!<br>'
                                     f'<strong>Type:</strong> {mouvement_obj.get_type_mouvement_display()}<br>'
                                     f'<strong>Produit:</strong> {produit.designation}<br>'
                                     f'<strong>Référence:</strong> {produit.reference}<br>'
                                     f'<strong>Quantité:</strong> {mouvement_obj.quantite} {produit.unite}<br>'
                                     f'<strong>Ancien stock:</strong> {ancien_stock} {produit.unite}<br>'
                                     f'<strong>Nouveau stock:</strong> {nouveau_stock} {produit.unite}',
                                     extra_tags='safe')

                    produit.refresh_from_db()

                    if 'continuer' in request.POST:
                        form = MouvementForm(initial={
                            'produit': produit,
                            'type_mouvement': mouvement_obj.type_mouvement,
                        })
                        return render(request, 'fournitures/mouvement.html', {'form': form})
                    else:
                        return redirect('dashboard')

                except ValidationError as e:
                    messages.error(request,
                                   f"❌ Erreur de validation:<br>{str(e)}",
                                   extra_tags='safe')
                    return render(request, 'fournitures/mouvement.html', {'form': form})

            except Exception as e:
                messages.error(request,
                               f"❌ Erreur inattendue:<br>{str(e)}<br>"
                               f"Veuillez réessayer ou contacter l'administrateur.",
                               extra_tags='safe')
                traceback.print_exc()
                return render(request, 'fournitures/mouvement.html', {'form': form})
        else:
            error_messages = []
            for field, errors in form.errors.items():
                if field != '__all__':
                    field_name = form.fields[field].label if field in form.fields else field
                    for error in errors:
                        error_messages.append(f"• <strong>{field_name}:</strong> {error}")

            if '__all__' in form.errors:
                for error in form.errors['__all__']:
                    error_messages.append(f"• {error}")

            if error_messages:
                messages.error(request,
                               "❌ Erreurs dans le formulaire:<br>" + "<br>".join(error_messages),
                               extra_tags='safe')
    else:
        form = MouvementForm()

        type_mouvement = request.GET.get('type')
        produit_id = request.GET.get('produit')

        if type_mouvement in ['ENTREE', 'SORTIE']:
            form.fields['type_mouvement'].initial = type_mouvement

        if produit_id:
            try:
                produit = Fourniture.objects.get(id=produit_id, actif=True)
                form.fields['produit'].initial = produit

                if type_mouvement == 'ENTREE':
                    if produit.stock_max:
                        quantite_suggeree = max(1, produit.stock_max - produit.stock)
                        quantite_suggeree = min(quantite_suggeree, 100)
                        form.initial['quantite'] = quantite_suggeree
                    else:
                        form.initial['quantite'] = 1
                elif type_mouvement == 'SORTIE':
                    if produit.stock > 0:
                        quantite_suggeree = min(max(1, produit.stock // 2), 10, produit.stock)
                        form.initial['quantite'] = quantite_suggeree
                    else:
                        form.initial['quantite'] = 0
            except Fourniture.DoesNotExist:
                messages.warning(request, "Le produit spécifié n'existe pas ou est inactif")

    return render(request, 'fournitures/mouvement.html', {'form': form})


# ==================== COMMANDES ====================

@login_required
def commande(request):
    """Vue pour gérer les commandes"""
    if request.method == 'POST':
        action = request.POST.get('action')
        commande_id = request.POST.get('commande_id')

        if action and commande_id:
            try:
                commande_obj = get_object_or_404(Commande, id=commande_id)

                if action == 'valider':
                    commande_obj.valider(request.user)
                    messages.success(request,
                                     f'✅ Commande {commande_obj.numero} validée!',
                                     extra_tags='safe')

                elif action == 'mettre_en_cours':
                    if commande_obj.status != 'VALIDEE':
                        messages.error(request,
                                       f'❌ La commande doit être validée avant d\'être mise en cours',
                                       extra_tags='safe')
                    else:
                        commande_obj.mettre_en_cours(request.user)
                        messages.success(request,
                                         f'✅ Commande {commande_obj.numero} marquée comme en cours de livraison!',
                                         extra_tags='safe')

                elif action == 'recevoir':
                    if commande_obj.status != 'EN_COURS':
                        messages.error(request,
                                       f'❌ La commande doit être "En cours de livraison" pour être reçue<br>'
                                       f'Statut actuel: {commande_obj.get_status_display()}',
                                       extra_tags='safe')
                    else:
                        commande_obj.recevoir(request.user)
                        messages.success(request,
                                         f'✅ Commande {commande_obj.numero} reçue!<br>'
                                         f'Stock de {commande_obj.produit.designation} mis à jour '
                                         f'(+{commande_obj.quantite} {commande_obj.produit.unite})',
                                         extra_tags='safe')

                elif action == 'annuler':
                    commande_obj.annuler(request.user)
                    messages.success(request,
                                     f'⚠️ Commande {commande_obj.numero} annulée!',
                                     extra_tags='safe')

                return redirect('commande')

            except ValidationError as e:
                messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')
            except Exception as e:
                messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

        else:
            form = CommandeForm(request.POST)
            if form.is_valid():
                try:
                    commande_obj = form.save(commit=False)
                    commande_obj.utilisateur = request.user

                    if not commande_obj.produit:
                        messages.error(request, "❌ Erreur : Le produit est requis.", extra_tags='safe')
                        return redirect('commande')

                    if not commande_obj.produit.actif:
                        messages.error(request,
                                       f"❌ Erreur : Le produit {commande_obj.produit.designation} est inactif.",
                                       extra_tags='safe')
                        return redirect('commande')

                    commande_existante = Commande.objects.filter(
                        produit=commande_obj.produit,
                        status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
                    ).exists()

                    if commande_existante:
                        messages.warning(request,
                                         f"⚠️ Une commande est déjà en cours pour {commande_obj.produit.designation}<br>"
                                         f"Veuillez d'abord finaliser la commande existante.",
                                         extra_tags='safe')
                        return redirect('commande')

                    commande_obj.save()

                    messages.success(request,
                                     f"✅ Commande créée avec succès!<br>"
                                     f"<strong>Numéro:</strong> {commande_obj.numero}<br>"
                                     f"<strong>Produit:</strong> {commande_obj.produit.designation}<br>"
                                     f"<strong>Quantité:</strong> {commande_obj.quantite} {commande_obj.produit.unite}<br>"
                                     f"<strong>Statut:</strong> {commande_obj.get_status_display()}<br>"
                                     f"<small>Vous pouvez maintenant valider cette commande.</small>",
                                     extra_tags='safe')
                    return redirect('commande')

                except ValidationError as e:
                    messages.error(request, f"❌ Erreur de validation: {str(e)}", extra_tags='safe')
                except Exception as e:
                    messages.error(request, f"❌ Erreur lors de la création: {str(e)}", extra_tags='safe')
                    traceback.print_exc()
            else:
                error_messages = []
                for field, errors in form.errors.items():
                    if field != '__all__':
                        field_name = form.fields[field].label if field in form.fields else field
                        for error in errors:
                            error_messages.append(f"• <strong>{field_name}:</strong> {error}")

                if '__all__' in form.errors:
                    for error in form.errors['__all__']:
                        error_messages.append(f"• {error}")

                if error_messages:
                    messages.error(request,
                                   "❌ Erreurs dans le formulaire:<br>" + "<br>".join(error_messages),
                                   extra_tags='safe')

    else:
        form = CommandeForm()

        produit_id = request.GET.get('produit')
        if produit_id:
            try:
                produit = Fourniture.objects.get(id=produit_id, actif=True)
                form.fields['produit'].initial = produit

                if produit.stock <= produit.seuil_alerte:
                    commandes_actives = Commande.objects.filter(
                        produit=produit,
                        status__in=['VALIDEE', 'EN_COURS']
                    ).aggregate(total=Sum('quantite'))['total'] or 0

                    besoin_base = max(0, produit.stock_max - (produit.stock + commandes_actives))

                    if besoin_base == 0 and produit.stock <= produit.seuil_alerte:
                        form.initial['quantite'] = max(1, produit.seuil_alerte - produit.stock + 1)
                    else:
                        form.initial['quantite'] = besoin_base
                else:
                    form.initial['quantite'] = max(1, min(10, produit.stock_max - produit.stock))

            except Fourniture.DoesNotExist:
                messages.warning(request, "❌ Le produit spécifié n'existe pas ou est inactif", extra_tags='safe')

    # Récupérer les données pour l'affichage
    commandes_en_attente = Commande.objects.filter(
        status='EN_ATTENTE'
    ).select_related('produit', 'produit__type', 'utilisateur').order_by('-date_creation')

    commandes_validees = Commande.objects.filter(
        status='VALIDEE'
    ).select_related('produit', 'produit__type', 'utilisateur', 'utilisateur_validation').order_by('-date_validation')

    commandes_en_cours = Commande.objects.filter(
        status='EN_COURS'
    ).select_related('produit', 'produit__type', 'utilisateur').order_by('-date_en_cours')

    commandes_recues = Commande.objects.filter(
        status='RECUE'
    ).select_related('produit', 'produit__type', 'utilisateur').order_by('-date_reception')[:10]

    produits_en_alerte = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).select_related('type').order_by('stock')

    produits_alerte_data = []
    for produit in produits_en_alerte:
        commandes_actives_produit = produit.commandes.filter(
            status__in=['EN_ATTENTE', 'VALIDEE', 'EN_COURS']
        )

        commande_active = commandes_actives_produit.first() if commandes_actives_produit.exists() else None

        commandes_actives = produit.commandes.filter(
            status__in=['VALIDEE', 'EN_COURS']
        ).aggregate(total=Sum('quantite'))['total'] or 0

        besoin_base = max(0, produit.stock_max - (produit.stock + commandes_actives))

        if besoin_base == 0 and produit.stock <= produit.seuil_alerte:
            quantite_a_commander = max(1, produit.seuil_alerte - produit.stock + 1)
        else:
            quantite_a_commander = besoin_base

        produit_data = {
            'fourniture': produit,
            'quantite_a_commander': quantite_a_commander,
            'pourcentage': (produit.stock / produit.stock_max * 100) if produit.stock_max > 0 else 0,
            'commande_active': commande_active,
            'statut_commande': commande_active.status if commande_active else 'aucune',
            'quantite_commande': commande_active.quantite if commande_active else 0,
        }
        produits_alerte_data.append(produit_data)

    context = {
        'form': form,
        'produits_en_alerte': produits_alerte_data,
        'commandes_en_attente': commandes_en_attente,
        'commandes_validees': commandes_validees,
        'commandes_en_cours': commandes_en_cours,
        'commandes_recues': commandes_recues,
        'total_alertes': len(produits_alerte_data),
    }

    return render(request, 'fournitures/commande.html', context)


@login_required
def liste_commande(request):
    """Liste de toutes les commandes"""
    commandes = Commande.objects.all().select_related(
        'produit', 'produit__type', 'utilisateur'
    ).order_by('-date_creation')

    status_filter = request.GET.get('status')
    if status_filter:
        commandes = commandes.filter(status=status_filter)

    context = {
        'commandes': commandes,
        'status_filter': status_filter,
    }
    return render(request, 'fournitures/liste_commande.html', context)


@login_required
def valider_commande(request, id):
    """Valider une commande"""
    if request.method == 'POST':
        try:
            commande_obj = get_object_or_404(Commande, id=id)

            if commande_obj.status != 'EN_ATTENTE':
                messages.error(request,
                               f"La commande #{commande_obj.id} ne peut pas être validée "
                               f"(statut: {commande_obj.get_status_display()})")
            else:
                commande_obj.valider(request.user)
                messages.success(request, f'Commande #{commande_obj.id} validée avec succès!')
        except Exception as e:
            messages.error(request, f"Erreur: {str(e)}")

    return redirect('commande')


@login_required
def recevoir_commande(request, id):
    """Recevoir une commande"""
    if request.method == 'POST':
        try:
            commande_obj = get_object_or_404(Commande, id=id)

            if commande_obj.status != 'EN_COURS':
                messages.error(request,
                               f"❌ La commande #{commande_obj.id} ne peut pas être reçue "
                               f"(statut: {commande_obj.get_status_display()})<br>"
                               f"Seules les commandes 'En cours de livraison' peuvent être reçues.",
                               extra_tags='safe')
            else:
                commande_obj.recevoir(request.user)
                messages.success(request,
                                 f'✅ Commande #{commande_obj.id} reçue! '
                                 f'Stock de {commande_obj.produit.designation} mis à jour '
                                 f'(+{commande_obj.quantite} {commande_obj.produit.unite}).',
                                 extra_tags='safe')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('commande')


@login_required
def annuler_commande(request, id):
    """Annuler une commande"""
    if request.method == 'POST':
        try:
            commande_obj = get_object_or_404(Commande, id=id)

            if commande_obj.status not in ['EN_ATTENTE', 'VALIDEE', 'EN_COURS']:
                messages.error(request,
                               f"La commande #{commande_obj.id} ne peut pas être annulée "
                               f"(statut: {commande_obj.get_status_display()})")
            else:
                commande_obj.annuler(request.user)
                messages.success(request, f'Commande #{commande_obj.id} annulée!')
        except Exception as e:
            messages.error(request, f"Erreur: {str(e)}")

    return redirect('commande')


@login_required
def supprimer_commande(request, id):
    """Supprimer une commande"""
    if request.method == 'POST':
        try:
            commande_obj = get_object_or_404(Commande, id=id)

            if commande_obj.status == 'RECUE':
                messages.error(request, '❌ Impossible de supprimer une commande déjà reçue!', extra_tags='safe')
            else:
                commande_obj.delete()
                messages.success(request, '✅ Commande supprimée avec succès!', extra_tags='safe')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('commande')


@login_required
def historique_commandes(request):
    """Historique des commandes"""
    commandes = Commande.objects.all().select_related(
        'produit', 'produit__type', 'utilisateur'
    ).order_by('-date_creation')

    status_filter = request.GET.get('status')
    if status_filter:
        commandes = commandes.filter(status=status_filter)

    stats = {
        'total': commandes.count(),
        'en_attente': commandes.filter(status='EN_ATTENTE').count(),
        'validees': commandes.filter(status='VALIDEE').count(),
        'recues': commandes.filter(status='RECUE').count(),
        'annulees': commandes.filter(status='ANNULEE').count(),
        'en_cours': commandes.filter(status='EN_COURS').count(),
    }

    context = {
        'commandes': commandes,
        'status_filter': status_filter,
        'stats': stats,
    }
    return render(request, 'fournitures/historique_commandes.html', context)


@login_required
def mettre_en_cours_commande(request, id):
    """Marquer une commande comme en cours"""
    if request.method == 'POST':
        try:
            commande_obj = get_object_or_404(Commande, id=id)

            if commande_obj.status != 'VALIDEE':
                messages.error(request,
                               f'❌ La commande doit être validée avant d\'être mise en cours<br>'
                               f'Statut actuel: {commande_obj.get_status_display()}',
                               extra_tags='safe')
            else:
                commande_obj.mettre_en_cours(request.user)
                messages.success(request,
                                 f'✅ Commande {commande_obj.numero} marquée comme en cours de livraison!',
                                 extra_tags='safe')
        except ValidationError as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('commande')


# ==================== TYPES ====================

@login_required
def gestion_types(request):
    """Gérer les types de fournitures"""
    types = TypeFourniture.objects.all().order_by('nom')

    if request.method == 'POST':
        form = TypeFournitureForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, '✅ Type ajouté avec succès!', extra_tags='safe')
                return redirect('gestion_types')
            except Exception as e:
                messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')
    else:
        form = TypeFournitureForm()

    context = {
        'form': form,
        'types': types,
    }
    return render(request, 'fournitures/gestion_types.html', context)


@login_required
def supprimer_type(request, id):
    """Supprimer un type"""
    if request.method == 'POST':
        try:
            type_obj = get_object_or_404(TypeFourniture, id=id)

            if type_obj.fournitures.exists():
                messages.error(request,
                               f'❌ Impossible de supprimer le type "{type_obj.nom}" '
                               f'car il est utilisé par des fournitures.',
                               extra_tags='safe')
            else:
                type_obj.delete()
                messages.success(request, f'✅ Type "{type_obj.nom}" supprimé avec succès!', extra_tags='safe')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('gestion_types')


# ==================== STATISTIQUES ====================

@login_required
def statistiques(request):
    """Page de statistiques"""
    from decimal import Decimal
    from django.core.serializers.json import DjangoJSONEncoder

    def decimal_to_float(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (list, tuple)):
            return [decimal_to_float(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: decimal_to_float(value) for key, value in obj.items()}
        return obj

    total_fournitures = Fourniture.objects.filter(actif=True).count()
    valeur_stock_result = Fourniture.objects.filter(actif=True).aggregate(total=Sum('stock'))
    valeur_stock = float(valeur_stock_result['total'] or 0)
    produits_en_alerte = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).count()

    date_limite = timezone.now() - timedelta(days=30)
    total_mouvements = Mouvement.objects.filter(date__gte=date_limite).count()
    total_entrees = float(Mouvement.objects.filter(
        date__gte=date_limite, type_mouvement='ENTREE'
    ).aggregate(total=Sum('quantite'))['total'] or 0)
    total_sorties = float(Mouvement.objects.filter(
        date__gte=date_limite, type_mouvement='SORTIE'
    ).aggregate(total=Sum('quantite'))['total'] or 0)

    ratio_entrees_sorties = round(total_entrees / max(total_sorties, 1), 2)
    activite_moyenne_jour = round(total_mouvements / 30, 1)
    taux_alerte = round((produits_en_alerte / max(total_fournitures, 1)) * 100, 1)

    produits_bas_stock = Fourniture.objects.filter(
        stock__lte=F('seuil_alerte'),
        actif=True
    ).select_related('type').order_by('stock')[:10]

    top_sorties_raw = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date__gte=date_limite,
        produit__isnull=False,
        produit__actif=True
    ).values('produit__designation', 'produit__type__nom').annotate(
        total=Sum('quantite')
    ).order_by('-total')[:10]

    top_sorties = []
    for item in top_sorties_raw:
        item_dict = {
            'produit__designation': item['produit__designation'],
            'produit__type__nom': item['produit__type__nom'],
            'total': float(item['total'] or 0),
            'moyenne_jour': round(float(item['total'] or 0) / 30, 1)
        }
        top_sorties.append(item_dict)

    types_list = []
    for type_obj in TypeFourniture.objects.all():
        fournitures_type = Fourniture.objects.filter(type=type_obj, actif=True)
        count = fournitures_type.count()
        if count > 0:
            stock_total = float(fournitures_type.aggregate(total=Sum('stock'))['total'] or 0)
            alerte_count = fournitures_type.filter(stock__lte=F('seuil_alerte')).count()
            types_list.append({
                'id': type_obj.id,
                'nom': type_obj.nom,
                'count': count,
                'stock_total': stock_total,
                'alerte_count': alerte_count
            })

    types_list.sort(key=lambda x: x['count'], reverse=True)

    labels_type = [t['nom'] for t in types_list[:8]]
    series_type = [t['count'] for t in types_list[:8]]

    activite_dates = []
    activite_data = []

    for i in range(29, -1, -1):
        date_calc = timezone.now().date() - timedelta(days=i)
        date_str = date_calc.strftime('%d/%m')
        activite_dates.append(date_str)
        count = Mouvement.objects.filter(date__date=date_calc).count()
        activite_data.append(count)

    top_labels = []
    top_series = []
    for item in top_sorties_raw[:5]:
        designation = item['produit__designation']
        if designation:
            top_labels.append(designation[:20] + '...' if len(designation) > 20 else designation)
            top_series.append(float(item['total'] or 0))

    derniere_mouvement = Mouvement.objects.order_by('-date').first()
    derniere_activite = derniere_mouvement.date.strftime('%d/%m/%Y %H:%M') if derniere_mouvement else "Aucune"

    labels_type_json = json.dumps(labels_type, cls=DjangoJSONEncoder)
    series_type_json = json.dumps(series_type, cls=DjangoJSONEncoder)
    activite_dates_json = json.dumps(activite_dates, cls=DjangoJSONEncoder)
    activite_data_json = json.dumps(activite_data, cls=DjangoJSONEncoder)
    top_labels_json = json.dumps(top_labels, cls=DjangoJSONEncoder)
    top_series_json = json.dumps(top_series, cls=DjangoJSONEncoder)

    context = {
        'total_fournitures': total_fournitures,
        'valeur_stock': valeur_stock,
        'produits_en_alerte': produits_en_alerte,
        'total_mouvements': total_mouvements,
        'total_entrees': total_entrees,
        'total_sorties': total_sorties,
        'ratio_entrees_sorties': ratio_entrees_sorties,
        'activite_moyenne_jour': activite_moyenne_jour,
        'taux_alerte': taux_alerte,
        'derniere_activite': derniere_activite,
        'produits_bas_stock': produits_bas_stock,
        'top_sorties': top_sorties,
        'types': types_list,
        'labels_type': labels_type_json,
        'series_type': series_type_json,
        'activite_dates': activite_dates_json,
        'activite_data': activite_data_json,
        'top_labels': top_labels_json,
        'top_series': top_series_json,
    }

    return render(request, 'fournitures/statistiques.html', context)


# ==================== API/JSON ====================

@login_required
def ajouter_type_fourniture_ajax(request):
    """AJAX pour ajouter un type"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if request.method == 'POST':
            nom = request.POST.get('nom', '').strip()

            if not nom:
                return JsonResponse({
                    'success': False,
                    'error': 'Le nom du type est requis'
                })

            if TypeFourniture.objects.filter(nom__iexact=nom).exists():
                return JsonResponse({
                    'success': False,
                    'error': f'Le type "{nom}" existe déjà'
                })

            try:
                nouveau_type = TypeFourniture.objects.create(nom=nom)
                return JsonResponse({
                    'success': True,
                    'id': nouveau_type.id,
                    'nom': nouveau_type.nom
                })
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Erreur: {str(e)}'
                })

    return JsonResponse({
        'success': False,
        'error': 'Requête invalide'
    })


@login_required
def get_produit_info(request, produit_id):
    """API pour info produit"""
    try:
        produit = Fourniture.objects.get(id=produit_id, actif=True)
        return JsonResponse({
            'success': True,
            'id': produit.id,
            'reference': produit.reference,
            'designation': produit.designation,
            'stock': float(produit.stock),
            'stock_max': float(produit.stock_max),
            'seuil_alerte': float(produit.seuil_alerte),
            'unite': produit.unite,
            'pourcentage': (produit.stock / produit.stock_max * 100) if produit.stock_max > 0 else 0,
        })
    except Fourniture.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Produit non trouvé ou inactif'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ==================== IMPORT/EXPORT ====================

@login_required
def importer_csv(request):
    """Importer CSV"""
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']

        if not csv_file.name.endswith('.csv'):
            messages.error(request, "❌ Le fichier doit être au format CSV", extra_tags='safe')
            return redirect('liste_stock')

        try:
            file = TextIOWrapper(csv_file.file, encoding='utf-8')
            reader = csv.DictReader(file, delimiter=';')

            succes_count = 0
            erreur_count = 0

            for row in reader:
                try:
                    existing = Fourniture.objects.filter(
                        reference=row.get('reference', '')
                    ).first()

                    if existing:
                        existing.designation = row.get('designation', '')
                        existing.description = row.get('description', '')
                        existing.stock = float(row.get('stock', 0))
                        existing.seuil_alerte = float(row.get('seuil_alerte', 5))
                        existing.stock_max = float(row.get('stock_max', 10))
                        existing.unite = row.get('unite', 'unité')
                        existing.actif = row.get('actif', 'True').lower() == 'true'

                        type_nom = row.get('type', '')
                        if type_nom:
                            type_obj, created = TypeFourniture.objects.get_or_create(
                                nom=type_nom.strip()
                            )
                            existing.type = type_obj

                        existing.save()
                        succes_count += 1
                    else:
                        fourniture = Fourniture(
                            reference=row.get('reference', f"IMP-{timezone.now().timestamp()}"),
                            designation=row.get('designation', ''),
                            description=row.get('description', ''),
                            stock=float(row.get('stock', 0)),
                            seuil_alerte=float(row.get('seuil_alerte', 5)),
                            stock_max=float(row.get('stock_max', 10)),
                            unite=row.get('unite', 'unité'),
                            actif=row.get('actif', 'True').lower() == 'true'
                        )

                        type_nom = row.get('type', '')
                        if type_nom:
                            type_obj, created = TypeFourniture.objects.get_or_create(
                                nom=type_nom.strip()
                            )
                            fourniture.type = type_obj

                        fourniture.save()
                        succes_count += 1

                except Exception as e:
                    erreur_count += 1
                    print(f"Erreur ligne {reader.line_num}: {str(e)}")

            messages.success(request,
                             f"✅ Import terminé: {succes_count} succès, {erreur_count} erreurs",
                             extra_tags='safe')

        except Exception as e:
            messages.error(request, f"❌ Erreur lors de l'import: {str(e)}", extra_tags='safe')

        return redirect('liste_stock')

    return render(request, 'fournitures/importer_csv.html')


@login_required
def exporter_csv(request):
    """Exporter CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="fournitures.csv"'

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Référence', 'Désignation', 'Description', 'Type',
        'Stock', 'Seuil alerte', 'Stock max', 'Unité', 'Actif'
    ])

    for f in Fourniture.objects.all().select_related('type'):
        writer.writerow([
            f.reference,
            f.designation,
            f.description or '',
            f.type.nom if f.type else '',
            f.stock,
            f.seuil_alerte,
            f.stock_max,
            f.unite,
            'Oui' if f.actif else 'Non'
        ])

    return response


# ==================== AJUSTEMENT STOCK ====================

@login_required
def ajuster_stock(request, id):
    """Ajuster manuellement le stock"""
    fourniture = get_object_or_404(Fourniture, id=id)

    if request.method == 'POST':
        try:
            ancien_stock = fourniture.stock
            nouveau_stock = float(request.POST.get('nouveau_stock', 0))
            raison = request.POST.get('raison', 'Ajustement manuel')

            if nouveau_stock < 0:
                messages.error(request, "❌ Le stock ne peut pas être négatif", extra_tags='safe')
                return redirect('detail_fourniture', id=id)

            difference = nouveau_stock - ancien_stock

            if difference != 0:
                Mouvement.objects.create(
                    produit=fourniture,
                    type_mouvement='ENTREE' if difference > 0 else 'SORTIE',
                    quantite=abs(difference),
                    utilisateur=request.user,
                    notes=f"Ajustement manuel: {raison}"
                )

                fourniture.stock = nouveau_stock
                fourniture.save()

                messages.success(request,
                                 f'✅ Stock ajusté de {ancien_stock} à {nouveau_stock} {fourniture.unite}<br>'
                                 f'Différence: {"+" if difference > 0 else ""}{difference} {fourniture.unite}',
                                 extra_tags='safe')

            return redirect('detail_fourniture', id=id)

        except ValueError:
            messages.error(request, "❌ Valeur de stock invalide", extra_tags='safe')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}", extra_tags='safe')

    return redirect('detail_fourniture', id=id)


# ==================== DEBUG ====================

@login_required
def debug_fournitures(request):
    """Vue de débogage"""
    fournitures = Fourniture.objects.all().order_by('-date_creation')

    print(f"\n=== DEBUG FOURNITURES ===")
    print(f"Total: {fournitures.count()}")
    for f in fournitures:
        print(f"ID: {f.id}, Réf: {f.reference}, Désignation: {f.designation}, "
              f"Stock: {f.stock}, Actif: {f.actif}, Date: {f.date_creation}")
    print(f"=========================\n")

    return render(request, 'fournitures/debug.html', {
        'fournitures': fournitures,
        'total': fournitures.count(),
        'actives': fournitures.filter(actif=True).count(),
        'inactives': fournitures.filter(actif=False).count(),
    })