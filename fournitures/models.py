from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum, Q, F
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction, connection
import re
import time


class TypeFourniture(models.Model):
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom du type")

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name = "Type de fourniture"
        verbose_name_plural = "Types de fourniture"
        ordering = ['nom']


class Fourniture(models.Model):
    UNITE_CHOICES = [
        ('UNITE', 'Unité'),
        ('unité', 'unité'),
        ('CARTON', 'Carton'),
        ('BOITE', 'Boîte'),
        ('LOT', 'Lot'),
        ('PAQUET', 'Paquet'),
        ('RAMETTE', 'Ramette'),
    ]

    type = models.ForeignKey('TypeFourniture', on_delete=models.CASCADE,
                             related_name='fournitures', verbose_name="Type")
    reference = models.CharField(max_length=20, unique=True,
                                 verbose_name="Référence", blank=True, null=True,
                                 help_text="Doit commencer par 'F' (ex: F001). Laisser vide pour générer automatiquement.")
    designation = models.CharField(max_length=200, verbose_name="Désignation")
    unite = models.CharField(max_length=20, choices=UNITE_CHOICES,
                             default='UNITE', verbose_name="Unité")
    stock = models.IntegerField(default=0, verbose_name="Stock actuel",
                                validators=[MinValueValidator(0)])
    stock_max = models.IntegerField(default=10, verbose_name="Stock maximum",
                                    validators=[MinValueValidator(1)])
    seuil_alerte = models.IntegerField(default=5, verbose_name="Seuil d'alerte",
                                       validators=[MinValueValidator(0)])
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    actif = models.BooleanField(default=True, verbose_name="Actif")

    @property
    def en_alerte(self):
        """Vérifie si le stock est en dessous du seuil d'alerte"""
        return self.stock <= self.seuil_alerte

    @property
    def pourcentage_stock(self):
        """Calcule le pourcentage du stock par rapport au maximum"""
        if self.stock_max and self.stock_max > 0:
            pourcentage = (self.stock / self.stock_max) * 100
            return min(round(pourcentage, 1), 100)
        return 0

    def get_quantite_commandee(self, status_filter=None):
        """Retourne la quantité commandée selon le statut"""
        query = self.commandes.all()
        if status_filter:
            if isinstance(status_filter, list):
                query = query.filter(status__in=status_filter)
            else:
                query = query.filter(status=status_filter)

        result = query.aggregate(total=Sum('quantite'))
        return result['total'] or 0

    @property
    def quantite_commandee_validee(self):
        """Quantité commandée avec statut VALIDEE (non encore reçue)"""
        return self.get_quantite_commandee('VALIDEE')

    @property
    def quantite_commandee_attente(self):
        """Quantité commandée avec statut EN_ATTENTE"""
        return self.get_quantite_commandee('EN_ATTENTE')

    @property
    def quantite_commandee_recue(self):
        """Quantité commandée avec statut RECUE"""
        return self.get_quantite_commandee('RECUE')

    @property
    def quantite_a_commander(self):
        """
        Calcule la quantité à commander pour atteindre le stock maximum
        en tenant compte des commandes validées mais non reçues
        """
        # Quantité déjà validée mais pas encore reçue
        commande_validee = self.quantite_commandee_validee

        # Calcul: stock_max - (stock actuel + commande validée non reçue)
        besoin = max(0, self.stock_max - (self.stock + commande_validee))

        # Si besoin est 0 mais qu'on est en alerte, commander au moins jusqu'au seuil
        if besoin == 0 and self.en_alerte:
            besoin = max(1, self.seuil_alerte - self.stock + 1)

        return besoin

    @property
    def doit_commander(self):
        """Détermine si une commande doit être passée"""
        return self.quantite_a_commander > 0 and self.en_alerte

    def a_commande_en_cours(self):
        """Vérifie s'il y a une commande en cours (EN_ATTENTE ou VALIDEE)"""
        return self.commandes.filter(
            status__in=['EN_ATTENTE', 'VALIDEE']
        ).exists()

    def get_commande_en_cours(self):
        """Récupère la commande en cours si elle existe"""
        return self.commandes.filter(
            status__in=['EN_ATTENTE', 'VALIDEE']
        ).order_by('-date_creation').first()

    def generer_reference(self, force=False):
        """Génère automatiquement la référence - VERSION CORRIGÉE"""
        # Si on a déjà une référence valide, on la garde
        if not force and self.reference and self.reference.startswith('F'):
            return self.reference

        try:
            # Version simplifiée et plus robuste
            # Récupérer la plus haute référence numérique
            last_ref = Fourniture.objects.filter(
                reference__regex=r'^F\d+$'
            ).order_by('-reference').first()

            if last_ref and last_ref.reference:
                # Extraire le numéro
                import re
                match = re.match(r'^F(\d+)$', last_ref.reference)
                if match:
                    next_num = int(match.group(1)) + 1
                else:
                    # Commencer à 1 si pas de référence valide
                    next_num = 1
            else:
                # Première référence
                next_num = 1

            # Formater avec 3 chiffres minimum
            return f"F{next_num:03d}"

        except Exception as e:
            # Fallback: utiliser timestamp
            import time
            timestamp = int(time.time()) % 10000
            return f"F{timestamp:04d}"

    def clean(self):
        """Validation du modèle - VERSION CORRIGÉE"""
        super().clean()

        errors = {}

        # Validations de stock
        if self.stock_max <= 0:
            errors['stock_max'] = "Le stock maximum doit être supérieur à 0"

        if self.seuil_alerte < 0:
            errors['seuil_alerte'] = "Le seuil d'alerte ne peut pas être négatif"

        if self.seuil_alerte >= self.stock_max:
            errors['seuil_alerte'] = "Le seuil d'alerte doit être inférieur au stock maximum"

        if self.stock < 0:
            errors['stock'] = "Le stock ne peut pas être négatif"

        # Validation de la référence
        if self.reference and self.reference.strip():
            ref = self.reference.strip()
            # Vérifier le format
            if not ref.startswith('F'):
                errors['reference'] = "La référence doit commencer par 'F'"
            elif not ref[1:].isdigit():
                errors['reference'] = "La référence doit contenir des chiffres après 'F'"
            else:
                # Vérifier l'unicité (sauf pour l'instance courante)
                qs = Fourniture.objects.filter(reference=ref)
                if self.pk:
                    qs = qs.exclude(pk=self.pk)
                if qs.exists():
                    errors['reference'] = f"La référence '{ref}' existe déjà"

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Sauvegarde du modèle - VERSION CORRIGÉE"""
        # Nettoyer et valider avant de sauvegarder
        self.full_clean()

        # Générer une référence si nécessaire
        if not self.reference or not self.reference.strip():
            self.reference = self.generer_reference()

        # Vérifier que la référence n'est pas vide
        if not self.reference or not self.reference.strip():
            raise ValueError("La référence ne peut pas être vide")

        with transaction.atomic():
            super().save(*args, **kwargs)

    def entree_stock(self, quantite, utilisateur=None, notes=""):
        """Méthode pour entrée de stock"""
        from .models import Mouvement

        if quantite <= 0:
            raise ValidationError("La quantité doit être positive")

        with transaction.atomic():
            # Verrouiller l'enregistrement
            produit = Fourniture.objects.select_for_update().get(pk=self.pk)

            # Calculer le nouveau stock
            nouveau_stock = produit.stock + quantite

            # Vérifier le stock maximum
            if produit.stock_max and nouveau_stock > produit.stock_max:
                raise ValidationError(
                    f"Stock maximum dépassé! Maximum: {produit.stock_max}, "
                    f"serait: {nouveau_stock}"
                )

            # Mettre à jour le stock
            produit.stock = nouveau_stock
            produit.save()

            # Créer le mouvement
            Mouvement.objects.create(
                produit=produit,
                type_mouvement='ENTREE',
                quantite=quantite,
                utilisateur=utilisateur,
                notes=notes or f"Entrée de stock"
            )

        # Rafraîchir l'instance
        self.refresh_from_db()
        return self.stock

    def sortie_stock(self, quantite, utilisateur=None, notes=""):
        """Méthode pour sortie de stock"""
        from .models import Mouvement

        if quantite <= 0:
            raise ValidationError("La quantité doit être positive")

        with transaction.atomic():
            # Verrouiller l'enregistrement
            produit = Fourniture.objects.select_for_update().get(pk=self.pk)

            # Vérifier le stock disponible
            if quantite > produit.stock:
                raise ValidationError(
                    f"Stock insuffisant! Disponible: {produit.stock}, "
                    f"demandé: {quantite}"
                )

            # Calculer le nouveau stock
            nouveau_stock = produit.stock - quantite

            # Mettre à jour le stock
            produit.stock = nouveau_stock
            produit.save()

            # Créer le mouvement
            Mouvement.objects.create(
                produit=produit,
                type_mouvement='SORTIE',
                quantite=quantite,
                utilisateur=utilisateur,
                notes=notes or f"Sortie de stock"
            )

        # Rafraîchir l'instance
        self.refresh_from_db()
        return self.stock

    @classmethod
    def update_stock_safe(cls, produit_id, quantite, type_mouvement):
        """
        Méthode de classe STATIQUE pour mettre à jour le stock
        """
        with transaction.atomic():
            # Récupérer le produit avec verrouillage
            produit = cls.objects.select_for_update().get(id=produit_id)

            if type_mouvement == 'ENTREE':
                # Vérifier le stock maximum
                nouveau_stock = produit.stock + quantite
                if produit.stock_max and nouveau_stock > produit.stock_max:
                    raise ValidationError({
                        "stock": f"Stock maximum dépassé! Maximum: {produit.stock_max}, "
                                 f"serait: {nouveau_stock}"
                    })

                # Mise à jour
                cls.objects.filter(id=produit_id).update(
                    stock=F('stock') + quantite,
                    date_modification=timezone.now()
                )

            else:  # SORTIE
                # Vérifier le stock disponible
                if quantite > produit.stock:
                    raise ValidationError({
                        "stock": f"Stock insuffisant! Disponible: {produit.stock}, "
                                 f"demandé: {quantite}"
                    })

                # Mise à jour
                cls.objects.filter(id=produit_id).update(
                    stock=F('stock') - quantite,
                    date_modification=timezone.now()
                )

            # Récupérer le nouveau stock
            produit.refresh_from_db()
            return produit.stock

    def __str__(self):
        return f"{self.reference if self.reference else 'SANS-REF'} - {self.designation}"

    class Meta:
        verbose_name = "Fourniture"
        verbose_name_plural = "Fournitures"
        ordering = ['type', 'reference']


class Commande(models.Model):
    STATUS_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('VALIDEE', 'Validée'),
        ('EN_COURS', 'En cours de livraison'),
        ('RECUE', 'Reçue'),
        ('ANNULEE', 'Annulée'),
    ]

    produit = models.ForeignKey(Fourniture, on_delete=models.CASCADE,
                                related_name='commandes', verbose_name="Produit")
    quantite = models.IntegerField(verbose_name="Quantité",
                                   validators=[MinValueValidator(1)])
    date_creation = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    date_validation = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation")
    date_en_cours = models.DateTimeField(null=True, blank=True, verbose_name="Date mise en cours")
    date_reception = models.DateTimeField(null=True, blank=True, verbose_name="Date de réception")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='EN_ATTENTE', verbose_name="Statut")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL,
                                    null=True, verbose_name="Créé par")
    utilisateur_validation = models.ForeignKey(User, on_delete=models.SET_NULL,
                                             null=True, blank=True, related_name='commandes_validees',
                                             verbose_name="Validée par")
    numero = models.CharField(max_length=20, unique=True, editable=False,
                              verbose_name="Numéro de commande", blank=True, null=True)

    def generer_numero(self):
        """Génère automatiquement le numéro de commande"""
        if self.numero and self.numero != 'CMD-TEMP':
            return self.numero

        annee = timezone.now().year
        mois_int = timezone.now().month

        try:
            # Chercher le dernier numéro du mois
            derniers_numeros = Commande.objects.filter(
                numero__isnull=False
            ).exclude(numero='CMD-TEMP').values_list('numero', flat=True)

            # Trouver la plus haute séquence pour ce mois
            max_seq = 0
            for num in derniers_numeros:
                if num and isinstance(num, str):
                    match = re.match(r'CMD-(\d{4})-(\d{2})-(\d{3})', num)
                    if match:
                        num_annee, num_mois, seq = match.groups()
                        if int(num_annee) == annee and int(num_mois) == mois_int:
                            max_seq = max(max_seq, int(seq))

            seq = max_seq + 1

        except Exception as e:
            seq = 1

        self.numero = f"CMD-{annee}-{mois_int:02d}-{seq:03d}"
        return self.numero

    def valider(self, utilisateur=None):
        """Valider la commande"""
        if self.status != 'EN_ATTENTE':
            raise ValidationError(
                f"La commande #{self.id} ne peut pas être validée (statut: {self.get_status_display()})"
            )

        with transaction.atomic():
            self.status = 'VALIDEE'
            self.date_validation = timezone.now()
            if utilisateur:
                self.utilisateur_validation = utilisateur
            self.save()

    def mettre_en_cours(self, utilisateur=None):
        """Marquer la commande comme en cours de livraison"""
        if self.status not in ['VALIDEE', 'EN_ATTENTE']:
            raise ValidationError(
                f"La commande #{self.id} ne peut pas être mise en cours (statut: {self.get_status_display()})"
            )

        with transaction.atomic():
            self.status = 'EN_COURS'
            self.date_en_cours = timezone.now()
            self.save()

    def recevoir(self, utilisateur):
        """Marquer la commande comme reçue et mettre à jour le stock"""
        # Accepter les statuts VALIDEE et EN_COURS
        if self.status not in ['VALIDEE', 'EN_COURS']:
            raise ValidationError(
                f"La commande #{self.id} ne peut pas être reçue (statut: {self.get_status_display()})"
            )

        with transaction.atomic():
            # Utiliser la méthode update_stock_safe
            Fourniture.update_stock_safe(
                produit_id=self.produit.id,
                quantite=self.quantite,
                type_mouvement='ENTREE'
            )

            # Créer un mouvement pour l'historique
            from .models import Mouvement
            Mouvement.objects.create(
                produit=self.produit,
                type_mouvement='ENTREE',
                quantite=self.quantite,
                utilisateur=utilisateur,
                notes=f"Réception commande {self.numero}" +
                      (f" - {self.notes}" if self.notes else ""),
                commande=self
            )

            # Mettre à jour le statut de la commande
            self.status = 'RECUE'
            self.date_reception = timezone.now()
            self.save()

    def annuler(self, utilisateur=None):
        """Annuler la commande"""
        if self.status == 'RECUE':
            raise ValidationError("Impossible d'annuler une commande déjà reçue")

        with transaction.atomic():
            self.status = 'ANNULEE'
            self.save()

    @property
    def en_retard(self):
        """Vérifie si la commande est en retard"""
        if self.status == 'VALIDEE' and self.date_validation:
            return (timezone.now() - self.date_validation).days > 7
        elif self.status == 'EN_COURS' and self.date_en_cours:
            return (timezone.now() - self.date_en_cours).days > 3
        return False

    @property
    def peut_etre_validee(self):
        """Vérifie si la commande peut être validée"""
        return self.status == 'EN_ATTENTE'

    @property
    def peut_etre_mise_en_cours(self):
        """Vérifie si la commande peut être mise en cours"""
        return self.status in ['EN_ATTENTE', 'VALIDEE']

    @property
    def peut_etre_recue(self):
        """Vérifie si la commande peut être reçue"""
        return self.status in ['VALIDEE', 'EN_COURS']

    @property
    def peut_etre_annulee(self):
        """Vérifie si la commande peut être annulée"""
        return self.status in ['EN_ATTENTE', 'VALIDEE', 'EN_COURS']

    def clean(self):
        """Validation du modèle"""
        # Validation de la quantité
        if self.quantite is None or self.quantite <= 0:
            raise ValidationError({"quantite": "La quantité doit être supérieure à 0"})

        # Vérifier que le produit existe et est actif
        if hasattr(self, 'produit') and self.produit:
            if not self.produit.actif:
                raise ValidationError({"produit": "Impossible de commander un produit inactif"})

            # Vérifier que la quantité n'est pas excessive
            stock_apres = self.produit.stock + self.quantite
            if self.produit.stock_max and stock_apres > self.produit.stock_max:
                raise ValidationError({
                    "quantite": f"Quantité excessive ! Stock maximum : {self.produit.stock_max} {self.produit.unite}, "
                                f"serait {stock_apres} après réception."
                })

    def save(self, *args, **kwargs):
        """Sauvegarde de la commande"""
        # Générer le numéro si nécessaire
        if not self.numero or self.numero == 'CMD-TEMP':
            self.generer_numero()

        with transaction.atomic():
            super().save(*args, **kwargs)

    def __str__(self):
        if self.numero:
            return f"{self.numero} - {self.produit.reference if hasattr(self, 'produit') and self.produit else 'Produit inconnu'} ({self.quantite}) - {self.get_status_display()}"
        else:
            return f"Commande #{self.id} - {self.get_status_display()}"

    class Meta:
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        ordering = ['-date_creation']


class Mouvement(models.Model):
    TYPE_CHOICES = [
        ('ENTREE', 'Entrée'),
        ('SORTIE', 'Sortie'),
    ]

    produit = models.ForeignKey(
        Fourniture,
        on_delete=models.CASCADE,
        related_name='mouvements',
        verbose_name="Produit"
    )

    type_mouvement = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        verbose_name="Type de mouvement"
    )

    quantite = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Quantité",
        default=0,
        validators=[MinValueValidator(0.01)]
    )

    date = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Utilisateur"
    )

    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Notes"
    )

    commande = models.ForeignKey(
        Commande,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mouvements_lies',
        verbose_name="Commande associée"
    )

    def clean(self):
        """Validation du mouvement"""
        # Validation de base
        if self.quantite is None:
            raise ValidationError({'quantite': 'La quantité est requise'})

        try:
            quantite_value = float(self.quantite)
        except (TypeError, ValueError):
            raise ValidationError({'quantite': 'La quantité doit être un nombre valide'})

        if quantite_value <= 0:
            raise ValidationError({'quantite': 'La quantité doit être positive (supérieure à 0)'})

        # Validation spécifique au produit si disponible
        if hasattr(self, 'produit') and self.produit:
            if self.type_mouvement == 'SORTIE':
                if quantite_value > self.produit.stock:
                    raise ValidationError({
                        'quantite': f'Stock insuffisant. Disponible: {self.produit.stock}, Demandé: {quantite_value}'
                    })

            if self.type_mouvement == 'ENTREE' and self.produit.stock_max:
                nouveau_stock = self.produit.stock + quantite_value
                if nouveau_stock > self.produit.stock_max:
                    raise ValidationError({
                        'quantite': f'Stock maximum dépassé. Max: {self.produit.stock_max}, Nouveau stock serait: {nouveau_stock}'
                    })

    def save(self, *args, **kwargs):
        """Sauvegarde du mouvement"""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if hasattr(self, 'produit') and self.produit:
            return f"{self.type_mouvement} {self.quantite} {self.produit.unite} - {self.produit.designation}"
        return f"{self.type_mouvement} {self.quantite}"

    class Meta:
        verbose_name = "Mouvement"
        verbose_name_plural = "Mouvements"
        ordering = ['-date']