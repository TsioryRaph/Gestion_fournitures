from django.db import models
from django.contrib.auth.models import User


class TypeFourniture(models.Model):
    nom = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name = "Type de fourniture"
        verbose_name_plural = "Types de fourniture"


class Fourniture(models.Model):
    UNITE_CHOICES = [
        ('UNITE', 'Unité'),
        ('CARTON', 'Carton'),
        ('BOITE', 'Boîte'),
        ('LOT', 'Lot'),
        ('PAQUET', 'Paquet'),
    ]

    type = models.ForeignKey(TypeFourniture, on_delete=models.CASCADE, related_name='fournitures')
    reference = models.CharField(max_length=20, unique=True, verbose_name="Référence")
    designation = models.CharField(max_length=200, verbose_name="Désignation")
    unite = models.CharField(max_length=20, choices=UNITE_CHOICES, default='UNITE', verbose_name="Unité")
    stock = models.IntegerField(default=0, verbose_name="Stock actuel")
    stock_max = models.IntegerField(default=10, verbose_name="Stock maximum")
    seuil_alerte = models.IntegerField(default=5, verbose_name="Seuil d'alerte")
    date_creation = models.DateTimeField(auto_now_add=True)

    def en_alerte(self):
        """Vérifie si le stock est en dessous du seuil d'alerte"""
        return self.stock <= self.seuil_alerte

    def pourcentage_stock(self):
        """Calcule le pourcentage du stock par rapport au maximum"""
        if self.stock_max > 0:
            return (self.stock / self.stock_max) * 100
        return 0

    def quantite_a_commander(self):
        """Calcule la quantité à commander pour atteindre le stock maximum"""
        return max(0, self.stock_max - self.stock)

    def __str__(self):
        return f"{self.reference} - {self.designation} ({self.stock} {self.unite})"

    class Meta:
        verbose_name = "Fourniture"
        verbose_name_plural = "Fournitures"
        ordering = ['type', 'reference']


class Mouvement(models.Model):
    TYPE_CHOICES = [
        ('ENTREE', 'Entrée'),
        ('SORTIE', 'Sortie'),
    ]

    produit = models.ForeignKey(Fourniture, on_delete=models.CASCADE, related_name='mouvements')
    type_mouvement = models.CharField(max_length=10, choices=TYPE_CHOICES)
    quantite = models.IntegerField()
    date = models.DateTimeField(auto_now_add=True)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.type_mouvement} {self.quantite} {self.produit.reference} - {self.date.strftime('%d/%m/%Y')}"

    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ['-date']


class Commande(models.Model):
    STATUS_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('VALIDEE', 'Validée'),
        ('RECUE', 'Reçue'),
        ('ANNULEE', 'Annulée'),
    ]

    produit = models.ForeignKey(Fourniture, on_delete=models.CASCADE, related_name='commandes')
    quantite = models.IntegerField()
    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EN_ATTENTE')
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Commande {self.produit.reference} - {self.quantite} {self.produit.unite}"

    class Meta:
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        ordering = ['-date_creation']