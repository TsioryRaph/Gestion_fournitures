from django.contrib import admin
from .models import TypeFourniture, Fourniture, Mouvement, Commande


@admin.register(TypeFourniture)
class TypeFournitureAdmin(admin.ModelAdmin):
    list_display = ('nom',)
    search_fields = ('nom',)


@admin.register(Fourniture)
class FournitureAdmin(admin.ModelAdmin):
    list_display = ('reference', 'designation', 'type', 'unite', 'stock', 'seuil_alerte', 'stock_max', 'en_alerte')
    list_filter = ('type', 'unite')
    search_fields = ('reference', 'designation')
    list_editable = ('stock',)

    def en_alerte(self, obj):
        return obj.en_alerte()

    en_alerte.boolean = True
    en_alerte.short_description = 'Alerte'


@admin.register(Mouvement)
class MouvementAdmin(admin.ModelAdmin):
    list_display = ('produit', 'type_mouvement', 'quantite', 'date', 'utilisateur')
    list_filter = ('type_mouvement', 'date')
    search_fields = ('produit__reference', 'produit__designation')
    date_hierarchy = 'date'


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ('produit', 'quantite', 'status', 'date_creation')
    list_filter = ('status', 'date_creation')
    search_fields = ('produit__reference', 'produit__designation')
    list_editable = ('status',)