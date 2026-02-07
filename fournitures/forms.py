from django import forms
from .models import Fourniture, Mouvement, Commande, TypeFourniture


class MouvementForm(forms.ModelForm):
    class Meta:
        model = Mouvement
        fields = ['produit', 'type_mouvement', 'quantite', 'notes']
        widgets = {
            'produit': forms.Select(attrs={'class': 'form-control'}),
            'type_mouvement': forms.Select(attrs={'class': 'form-control'}),
            'quantite': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_quantite(self):
        quantite = self.cleaned_data.get('quantite')
        if quantite <= 0:
            raise forms.ValidationError("La quantité doit être supérieure à 0")
        return quantite

    def clean(self):
        cleaned_data = super().clean()
        produit = cleaned_data.get('produit')
        type_mouvement = cleaned_data.get('type_mouvement')
        quantite = cleaned_data.get('quantite')

        if produit and type_mouvement and quantite:
            if type_mouvement == 'SORTIE' and quantite > produit.stock:
                raise forms.ValidationError(
                    f"Stock insuffisant! Stock disponible: {produit.stock} {produit.unite}"
                )

        return cleaned_data


class FournitureForm(forms.ModelForm):
    class Meta:
        model = Fourniture
        fields = ['type', 'reference', 'designation', 'unite', 'stock', 'stock_max', 'seuil_alerte']
        widgets = {
            'type': forms.Select(attrs={'class': 'form-control'}),
            'reference': forms.TextInput(attrs={'class': 'form-control'}),
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'unite': forms.Select(attrs={'class': 'form-control'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'stock_max': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'seuil_alerte': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }


class CommandeForm(forms.ModelForm):
    class Meta:
        model = Commande
        fields = ['produit', 'quantite', 'notes']
        widgets = {
            'produit': forms.Select(attrs={'class': 'form-control'}),
            'quantite': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class TypeFournitureForm(forms.ModelForm):
    class Meta:
        model = TypeFourniture
        fields = ['nom']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
        }