from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Fourniture, Mouvement, Commande, TypeFourniture
import re
import time


class MouvementForm(forms.ModelForm):
    class Meta:
        model = Mouvement
        fields = ['produit', 'type_mouvement', 'quantite', 'notes']
        widgets = {
            'produit': forms.Select(attrs={
                'class': 'form-control',
                'onchange': 'updateProductInfo()'
            }),
            'type_mouvement': forms.Select(attrs={
                'class': 'form-control',
                'onchange': 'updateValidation()'
            }),
            'quantite': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01',
                'placeholder': 'Quantité'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes optionnelles (motif de la sortie, provenance, etc.)'
            }),
        }
        labels = {
            'produit': 'Fourniture',
            'type_mouvement': 'Type de mouvement',
            'quantite': 'Quantité',
            'notes': 'Notes (optionnel)',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filtrer seulement les produits actifs
        self.fields['produit'].queryset = Fourniture.objects.filter(
            actif=True
        ).select_related('type').order_by('designation')

        # Initialiser les données pour le JS
        if self.instance and self.instance.pk and self.instance.produit:
            produit = self.instance.produit
            self.fields['produit'].initial = produit
            self.fields['produit'].widget.attrs['data-current-stock'] = produit.stock
            self.fields['produit'].widget.attrs['data-stock-max'] = produit.stock_max
            self.fields['produit'].widget.attrs['data-seuil-alerte'] = produit.seuil_alerte
            self.fields['produit'].widget.attrs['data-unite'] = produit.unite

    def clean_quantite(self):
        quantite = self.cleaned_data.get('quantite')
        if quantite is None or quantite <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0.")
        return quantite

    def clean(self):
        cleaned_data = super().clean()
        produit = cleaned_data.get('produit')
        type_mouvement = cleaned_data.get('type_mouvement')
        quantite = cleaned_data.get('quantite')

        if produit and type_mouvement and quantite:
            quantite_value = float(quantite)

            if type_mouvement == 'SORTIE':
                if quantite_value > produit.stock:
                    raise forms.ValidationError({
                        'quantite': f"Stock insuffisant ! Disponible : {produit.stock} {produit.unite}"
                    })

            elif type_mouvement == 'ENTREE':
                stock_apres = produit.stock + quantite_value
                if produit.stock_max and stock_apres > produit.stock_max:
                    raise forms.ValidationError({
                        'quantite': f"Stock maximum dépassé ! Maximum : {produit.stock_max} {produit.unite}, "
                                    f"serait {stock_apres} après l'entrée."
                    })

        return cleaned_data


import re
import time
from django import forms
from .models import Fourniture, TypeFourniture


class FournitureForm(forms.ModelForm):
    # Champ pour la génération automatique de référence
    generer_reference_auto = forms.BooleanField(
        required=False,
        initial=True,
        label="Générer la référence automatiquement",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # Champ pour la référence (optionnel pour création)
    reference = forms.CharField(
        required=False,
        label="Référence",
        help_text="Laisser vide pour générer automatiquement. Doit commencer par 'F' (ex: F001)",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: F001, F002...'
        })
    )

    class Meta:
        model = Fourniture
        fields = ['type', 'designation', 'unite', 'stock', 'stock_max', 'seuil_alerte', 'actif']
        widgets = {
            'type': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'Sélectionnez un type',
                'required': 'required'
            }),
            'designation': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Papier A4 80g',
                'required': 'required'
            }),
            'unite': forms.Select(attrs={
                'class': 'form-control',
                'required': 'required'
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '1',
                'placeholder': '0'
            }),
            'stock_max': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1',
                'placeholder': '10',
                'required': 'required'
            }),
            'seuil_alerte': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '1',
                'placeholder': '5',
                'required': 'required'
            }),
            'actif': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'type': 'Type de fourniture',
            'designation': 'Désignation',
            'unite': 'Unité de mesure',
            'stock': 'Stock initial',
            'stock_max': 'Stock maximum',
            'seuil_alerte': "Seuil d'alerte",
            'actif': "Actif",
        }
        help_texts = {
            'stock': 'Quantité disponible actuellement',
            'stock_max': 'Limite maximale de stockage',
            'seuil_alerte': 'Seuil de réapprovisionnement',
            'actif': 'La fourniture est active et peut être utilisée',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Trier les types par nom
        self.fields['type'].queryset = TypeFourniture.objects.all().order_by('nom')

        # Pour les nouvelles fournitures, actif est True par défaut
        if not self.instance.pk:
            self.fields['actif'].initial = True

        # Pour les modifications, la référence est en lecture seule
        if self.instance and self.instance.pk and self.instance.reference:
            self.fields['reference'].initial = self.instance.reference
            self.fields['reference'].disabled = True
            self.fields['reference'].help_text = "La référence ne peut pas être modifiée après création"

            # Cacher le champ génération auto pour les modifications
            self.fields['generer_reference_auto'].widget = forms.HiddenInput()
            self.fields['generer_reference_auto'].required = False
        else:
            # Pour les nouvelles fournitures, suggérer une référence
            if not self.initial.get('reference'):
                self.initial['reference'] = self.get_suggested_reference()

            # Afficher un message d'aide
            self.fields['reference'].help_text = "Laissez vide pour générer automatiquement (F001, F002...)"

    def get_suggested_reference(self):
        """Génère une référence suggérée pour nouvelle fourniture"""
        try:
            # Récupérer la plus haute référence numérique existante
            last_ref = Fourniture.objects.filter(
                reference__regex=r'^F\d+$'
            ).order_by('reference').last()

            if last_ref and last_ref.reference:
                # Extraire le numéro
                match = re.match(r'^F(\d+)$', last_ref.reference)
                if match:
                    next_num = int(match.group(1)) + 1
                    # Formater avec 3 chiffres minimum
                    return f"F{next_num:03d}"

            # Si aucune référence trouvée, commencer à 1
            return "F001"

        except Exception:
            # Fallback en cas d'erreur
            return "F001"

    def clean_reference(self):
        reference = self.cleaned_data.get('reference', '').strip().upper()

        # Si c'est une modification et la référence est déjà définie, on la garde
        if self.instance and self.instance.pk and self.instance.reference:
            return self.instance.reference

        # Si la référence est vide, c'est OK (sera générée automatiquement)
        if not reference:
            return ''

        # Si une référence est fournie, vérifier son format
        if reference:
            # Vérifier qu'elle commence par F
            if not reference.startswith('F'):
                raise forms.ValidationError("La référence doit commencer par 'F' (ex: F001)")

            # Vérifier que le reste est numérique
            if not reference[1:].isdigit():
                raise forms.ValidationError("La référence doit contenir des chiffres après 'F' (ex: F001)")

            # Vérifier que le numéro est > 0
            num = int(reference[1:])
            if num <= 0:
                raise forms.ValidationError("Le numéro de référence doit être supérieur à 0")

            # Vérifier l'unicité (sauf pour l'instance actuelle)
            qs = Fourniture.objects.filter(reference=reference)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(f"La référence '{reference}' existe déjà")

        return reference

    def clean_stock(self):
        stock = self.cleaned_data.get('stock')
        if stock is None:
            stock = 0

        if stock < 0:
            raise forms.ValidationError("Le stock ne peut pas être négatif.")

        return stock

    def clean_stock_max(self):
        stock_max = self.cleaned_data.get('stock_max')
        if stock_max is None:
            stock_max = 10

        if stock_max <= 0:
            raise forms.ValidationError("Le stock maximum doit être supérieur à 0.")

        return stock_max

    def clean_seuil_alerte(self):
        seuil_alerte = self.cleaned_data.get('seuil_alerte')
        if seuil_alerte is None:
            seuil_alerte = 5

        if seuil_alerte < 0:
            raise forms.ValidationError("Le seuil d'alerte ne peut pas être négatif.")

        return seuil_alerte

    def clean(self):
        cleaned_data = super().clean()

        stock = cleaned_data.get('stock', 0)
        stock_max = cleaned_data.get('stock_max', 10)
        seuil_alerte = cleaned_data.get('seuil_alerte', 5)

        # Vérifier les relations entre les champs
        if stock > stock_max:
            self.add_error('stock',
                           f"Le stock initial ({stock}) ne peut pas dépasser le stock maximum ({stock_max}).")

        if seuil_alerte >= stock_max:
            self.add_error('seuil_alerte',
                           f"Le seuil d'alerte ({seuil_alerte}) doit être inférieur au stock maximum ({stock_max}).")

        # S'assurer que l'actif est bien True par défaut pour les nouvelles fournitures
        if not self.instance.pk and 'actif' not in cleaned_data:
            cleaned_data['actif'] = True

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Gestion de la référence
        reference = self.cleaned_data.get('reference', '').strip().upper()
        generer_reference_auto = self.cleaned_data.get('generer_reference_auto', True)

        # Si c'est une modification, garder la référence existante
        if instance.pk:
            # On ne change pas la référence existante
            if commit:
                instance.save()
            return instance

        # Pour une NOUVELLE fourniture
        if reference:
            # Utiliser la référence fournie par l'utilisateur
            instance.reference = reference
        elif generer_reference_auto:
            # Laisser le modèle générer la référence automatiquement
            instance.reference = None  # Le modèle générera automatiquement
        else:
            # Générer une référence simple
            instance.reference = self.get_suggested_reference()

        # IMPORTANT: S'assurer que la fourniture est active par défaut
        if instance.actif is None:
            instance.actif = True

        if commit:
            try:
                instance.save()
            except Exception as e:
                # Si l'enregistrement échoue, essayer avec une référence générée
                if "reference" in str(e).lower():
                    instance.reference = None  # Laisser le modèle générer
                    instance.save()
                else:
                    raise

        return instance


class CommandeForm(forms.ModelForm):
    # Champ pour calculer la quantité suggérée (affichage seulement)
    quantite_suggeree = forms.IntegerField(
        required=False,
        label="Quantité suggérée",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
            'style': 'background-color: #f8f9fa;',
            'id': 'quantite_suggeree_field'
        })
    )

    class Meta:
        model = Commande
        fields = ['produit', 'quantite', 'notes']
        widgets = {
            'produit': forms.Select(attrs={
                'class': 'form-control',
                'id': 'id_produit_select',
                'onchange': 'updateQuantiteSuggeree()'
            }),
            'quantite': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1',
                'placeholder': 'Quantité à commander',
                'id': 'id_quantite_input'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes optionnelles (fournisseur, urgence, etc.)',
                'id': 'id_notes_textarea'
            }),
        }
        labels = {
            'produit': 'Produit *',
            'quantite': 'Quantité à commander *',
            'notes': 'Notes (optionnel)',
        }
        help_texts = {
            'produit': 'Sélectionnez le produit à commander',
            'quantite': 'Quantité souhaitée',
            'notes': 'Informations supplémentaires',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialiser la quantité suggérée
        self.fields['quantite_suggeree'].initial = 0

        # Filtrer les produits actifs seulement
        self.fields['produit'].queryset = Fourniture.objects.filter(
            actif=True
        ).select_related('type').order_by('designation')

        # Si c'est une modification, désactiver la modification du produit
        if self.instance and self.instance.pk:
            self.fields['produit'].disabled = True
            self.fields['produit'].widget.attrs['class'] += ' bg-light'

            # Calculer la quantité suggérée pour l'affichage
            if self.instance.produit:
                quantite_suggeree = self._calculer_quantite_suggeree(self.instance.produit)
                self.fields['quantite_suggeree'].initial = quantite_suggeree

        # Préparer les données pour JavaScript
        produits_data = {}
        for produit in self.fields['produit'].queryset:
            quantite_a_commander = self._calculer_quantite_suggeree(produit)
            produits_data[produit.id] = {
                'quantite_a_commander': quantite_a_commander,
                'stock': produit.stock,
                'stock_max': produit.stock_max,
                'seuil_alerte': produit.seuil_alerte,
                'unite': produit.unite,
                'en_alerte': produit.stock <= produit.seuil_alerte,
            }

        # Ajouter les données au widget
        self.fields['produit'].widget.attrs['data-produits'] = str(produits_data)

    def _calculer_quantite_suggeree(self, produit):
        """Méthode pour calculer la quantité suggérée"""
        try:
            if hasattr(produit, 'quantite_a_commander'):
                return produit.quantite_a_commander
            else:
                # Calcul manuel
                commande_validee = produit.get_quantite_commandee('VALIDEE')
                besoin = max(0, produit.stock_max - (produit.stock + commande_validee))
                if besoin == 0 and produit.stock <= produit.seuil_alerte:
                    return max(1, produit.seuil_alerte - produit.stock + 1)
                else:
                    return besoin
        except (AttributeError, TypeError, ValueError):
            # Fallback simple
            return max(1, produit.stock_max - produit.stock)

    def clean_quantite(self):
        """Validation de la quantité"""
        quantite = self.cleaned_data.get('quantite')
        if quantite is None or quantite <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0.")
        return quantite

    def clean_produit(self):
        """Validation du produit"""
        produit = self.cleaned_data.get('produit')

        # Vérifier que le produit existe
        if not produit:
            raise forms.ValidationError("Veuillez sélectionner un produit.")

        # Vérifier que le produit est actif
        if not produit.actif:
            raise forms.ValidationError("Impossible de commander un produit inactif.")

        return produit

    def clean(self):
        """Validation complète du formulaire - VERSION SÉCURISÉE"""
        cleaned_data = super().clean()

        produit = cleaned_data.get('produit')
        quantite = cleaned_data.get('quantite')

        # Vérifier que le produit et la quantité existent
        if not produit:
            raise forms.ValidationError({
                'produit': "Veuillez sélectionner un produit."
            })

        if not quantite:
            raise forms.ValidationError({
                'quantite': "Veuillez saisir une quantité."
            })

        # Vérifier que la quantité n'est pas excessive
        if produit and quantite:
            # Calculer le stock actuel + toutes les commandes déjà reçues
            commandes_recues = produit.quantite_commandee_recue
            stock_apres = produit.stock + commandes_recues + quantite

            if stock_apres > produit.stock_max:
                raise forms.ValidationError({
                    'quantite': f"Quantité excessive ! Stock maximum : {produit.stock_max} {produit.unite}, "
                                f"serait {stock_apres} après réception."
                })

        return cleaned_data

    def save(self, commit=True):
        """Sauvegarde de la commande - VERSION SÉCURISÉE"""
        instance = super().save(commit=False)

        # Si c'est une nouvelle commande, générer le numéro
        if not instance.pk:
            instance.generer_numero()

        # CORRECTION : Désactiver la validation automatique du modèle
        # La validation a déjà été faite dans le formulaire
        try:
            if commit:
                instance.save()
        except Exception as e:
            raise forms.ValidationError(f"Erreur lors de la sauvegarde : {str(e)}")

        return instance


class TypeFournitureForm(forms.ModelForm):
    class Meta:
        model = TypeFourniture
        fields = ['nom']
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Papeterie, Informatique, Hygiène, etc.',
                'autofocus': 'autofocus'
            }),
        }
        labels = {
            'nom': 'Nom du type',
        }
        help_texts = {
            'nom': 'Entrez un nom unique pour ce type de fourniture',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ajouter une classe pour la validation en temps réel
        self.fields['nom'].widget.attrs['onblur'] = 'checkTypeExists()'

    def clean_nom(self):
        nom = self.cleaned_data.get('nom')
        if not nom or len(nom.strip()) < 2:
            raise forms.ValidationError("Le nom doit contenir au moins 2 caractères.")

        nom = nom.strip()

        # Vérifier l'unicité (insensible à la casse)
        queryset = TypeFourniture.objects.filter(nom__iexact=nom)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                f"Un type avec le nom '{nom}' existe déjà."
            )

        return nom


class AjustementStockForm(forms.ModelForm):
    nouveau_stock = forms.IntegerField(
        min_value=0,
        label="Nouveau stock",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '1',
            'placeholder': 'Nouveau stock'
        })
    )

    ancien_stock = forms.IntegerField(
        required=False,
        disabled=True,
        label="Stock actuel",
        widget=forms.NumberInput(attrs={
            'class': 'form-control bg-light',
            'readonly': 'readonly'
        })
    )

    class Meta:
        model = Mouvement
        fields = ['produit', 'notes']
        widgets = {
            'produit': forms.Select(attrs={
                'class': 'form-control',
                'onchange': 'updateCurrentStock()'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Motif de l\'ajustement (inventaire, perte, erreur, etc.)'
            }),
        }
        labels = {
            'produit': 'Produit',
            'notes': 'Motif de l\'ajustement',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produit'].queryset = Fourniture.objects.filter(
            actif=True
        ).order_by('designation')

        # Initialiser les valeurs pour ancien_stock
        if self.instance and self.instance.pk and self.instance.produit:
            produit = self.instance.produit
            self.fields['ancien_stock'].initial = produit.stock
            self.fields['nouveau_stock'].initial = produit.stock
        elif 'initial' in kwargs and 'produit' in kwargs['initial']:
            produit = kwargs['initial']['produit']
            self.fields['ancien_stock'].initial = produit.stock
            self.fields['nouveau_stock'].initial = produit.stock

    def clean_nouveau_stock(self):
        nouveau_stock = self.cleaned_data.get('nouveau_stock')
        if nouveau_stock is None or nouveau_stock < 0:
            raise forms.ValidationError("Le stock ne peut pas être négatif.")
        return nouveau_stock

    def clean(self):
        cleaned_data = super().clean()
        produit = cleaned_data.get('produit')
        nouveau_stock = cleaned_data.get('nouveau_stock')

        if produit and nouveau_stock is not None:
            ancien_stock = produit.stock
            difference = nouveau_stock - ancien_stock

            if difference == 0:
                raise forms.ValidationError({
                    'nouveau_stock': 'Le nouveau stock est identique à l\'ancien stock. Aucun ajustement nécessaire.'
                })

            # Vérifier pour les sorties
            if difference < 0 and abs(difference) > produit.stock:
                raise forms.ValidationError({
                    'nouveau_stock': f'Stock insuffisant pour cet ajustement. Stock actuel: {produit.stock}'
                })

            # Vérifier pour les entrées
            if difference > 0 and produit.stock_max and (nouveau_stock > produit.stock_max):
                raise forms.ValidationError({
                    'nouveau_stock': f'Stock maximum dépassé. Maximum: {produit.stock_max}'
                })

            # Déterminer le type de mouvement
            if difference > 0:
                cleaned_data['type_mouvement'] = 'ENTREE'
                cleaned_data['quantite'] = difference
            else:
                cleaned_data['type_mouvement'] = 'SORTIE'
                cleaned_data['quantite'] = abs(difference)

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Définir la quantité et le type de mouvement
        quantite = self.cleaned_data.get('quantite')
        type_mouvement = self.cleaned_data.get('type_mouvement')

        if quantite:
            instance.quantite = quantite
        if type_mouvement:
            instance.type_mouvement = type_mouvement

        # Mettre à jour le stock du produit
        nouveau_stock = self.cleaned_data.get('nouveau_stock')
        if nouveau_stock is not None and instance.produit:
            instance.produit.stock = nouveau_stock
            instance.produit.save()

        if commit:
            instance.save()

        return instance


class CommandeRapideForm(forms.Form):
    produit_id = forms.IntegerField(widget=forms.HiddenInput())
    quantite = forms.IntegerField(
        min_value=1,
        label="Quantité",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'placeholder': 'Quantité'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        produit_id = cleaned_data.get('produit_id')
        quantite = cleaned_data.get('quantite')

        if produit_id and quantite:
            try:
                produit = Fourniture.objects.get(id=int(produit_id), actif=True)

                # Calculer le stock après réception
                commandes_recues = produit.quantite_commandee_recue
                stock_apres = produit.stock + commandes_recues + quantite

                if stock_apres > produit.stock_max:
                    raise forms.ValidationError(
                        f"Quantité excessive ! Stock maximum : {produit.stock_max}. "
                        f"Serait {stock_apres} après réception."
                    )

            except Fourniture.DoesNotExist:
                raise forms.ValidationError("Produit non trouvé ou inactif.")

        return cleaned_data


class RechercheFournitureForm(forms.Form):
    designation = forms.CharField(
        required=False,
        label="Désignation",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher par nom...'
        })
    )

    type = forms.ModelChoiceField(
        required=False,
        queryset=TypeFourniture.objects.all(),
        label="Type",
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )

    en_alerte = forms.BooleanField(
        required=False,
        label="Seulement en alerte",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )


class CommandeDepuisDashboardForm(forms.ModelForm):
    """Formulaire spécial pour créer des commandes depuis le dashboard"""

    class Meta:
        model = Commande
        fields = ['produit', 'quantite', 'notes']
        widgets = {
            'produit': forms.HiddenInput(),
            'quantite': forms.HiddenInput(),
            'notes': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Désactiver la validation automatique
        self.fields['produit'].required = False
        self.fields['quantite'].required = False
        self.fields['notes'].required = False

    def clean(self):
        cleaned_data = super().clean()

        # Récupérer les données depuis POST
        produit_id = self.data.get('produit')
        quantite = self.data.get('quantite')
        notes = self.data.get('notes')

        # Validation manuelle
        if not produit_id:
            raise forms.ValidationError("Le produit est requis.")

        try:
            produit = Fourniture.objects.get(id=int(produit_id), actif=True)
            cleaned_data['produit'] = produit
        except (Fourniture.DoesNotExist, ValueError):
            raise forms.ValidationError("Produit invalide ou inactif.")

        if not quantite or int(quantite) <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0.")

        cleaned_data['quantite'] = int(quantite)
        cleaned_data['notes'] = notes or ""

        # Vérifier la quantité
        commandes_recues = produit.quantite_commandee_recue
        stock_apres = produit.stock + commandes_recues + int(quantite)

        if stock_apres > produit.stock_max:
            raise forms.ValidationError(
                f"Quantité excessive. Stock maximum: {produit.stock_max}. "
                f"Serait {stock_apres} après réception."
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Assigner les valeurs
        instance.produit = self.cleaned_data.get('produit')
        instance.quantite = self.cleaned_data.get('quantite')
        instance.notes = self.cleaned_data.get('notes')

        # Générer le numéro
        instance.generer_numero()

        if commit:
            instance.save()

        return instance