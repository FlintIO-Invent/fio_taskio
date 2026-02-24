from django import forms
from .models import TaskIOUser

class CustomerForm(forms.ModelForm):
    class Meta:
        model  = TaskIOUser
        exclude = ['id']
        fields = [ "email", "first_name", "last_name", 
                  "date_of_birth", "phone", "address"]      
          
        widgets = { 
                    "date_of_birth" : forms.DateInput(attrs={"class": "form-control", "type": "date"}),
                    "email"         : forms.TextInput(attrs={"class": "form-control"}),
                    "first_name"    : forms.TextInput(attrs={"class": "form-control"}), 
                    "last_name"     : forms.TextInput(attrs={"class": "form-control"}), 
                    "phone"         : forms.TextInput(attrs={"class": "form-control"}), 
                    "address"       : forms.TextInput(attrs={"class": "form-control"}),
                    
                }
    def clean(self):
        cleaned = super().clean()
        return cleaned