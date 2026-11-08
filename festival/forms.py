from django import forms
from django.conf import settings

from .models import Votacion, celular_colombiano
from .services import normalizar_cedula, normalizar_celular


class IdentificacionForm(forms.Form):
    cedula = forms.CharField(
        label="Número de cédula", max_length=15,
        widget=forms.TextInput(attrs={"placeholder": "1.234.567.890", "inputmode": "numeric", "autocomplete": "off"}),
    )
    celular = forms.CharField(
        label="Celular", max_length=16,
        widget=forms.TextInput(attrs={"placeholder": "300 123 4567", "inputmode": "tel", "autocomplete": "off"}),
    )

    def clean_cedula(self):
        cedula = normalizar_cedula(self.cleaned_data["cedula"])
        if not 6 <= len(cedula) <= 10:
            raise forms.ValidationError("La cédula debe tener entre 6 y 10 dígitos.")
        return cedula

    def clean_celular(self):
        celular = normalizar_celular(self.cleaned_data["celular"])
        celular_colombiano(celular)
        return celular


class LoginForm(IdentificacionForm):
    pass


class RegistroForm(IdentificacionForm):
    mayor_edad = forms.BooleanField(label="Confirmo que soy mayor de 18 años.", required=False)
    datos = forms.BooleanField(
        label="Autorizo el tratamiento de mis datos personales (Ley 1581 de 2012).",
        error_messages={"required": "Debes autorizar el tratamiento de datos para registrarte."},
    )
    # Campo trampa para bots: las personas no lo ven ni lo llenan.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if settings.REGISTRO_EXIGE_MAYORIA_EDAD:
            self.fields["mayor_edad"].required = True
            self.fields["mayor_edad"].error_messages["required"] = "Debes confirmar que eres mayor de 18 años."

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Solicitud no válida.")
        return ""


class CodigoForm(forms.Form):
    codigo = forms.CharField(
        label="Código de 6 dígitos", min_length=6, max_length=6,
        widget=forms.TextInput(attrs={"placeholder": "123456", "inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class VotacionForm(forms.ModelForm):
    class Meta:
        model = Votacion
        fields = ["categoria", "titulo", "apertura", "cierre", "peso_jurado", "exigir_mayoria_edad", "votos_por_votante"]
        widgets = {
            "apertura": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "cierre": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, edicion=None, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("apertura", "cierre"):
            self.fields[campo].input_formats = ["%Y-%m-%dT%H:%M"]
        if edicion is not None:
            self.fields["categoria"].queryset = edicion.categorias.all()
