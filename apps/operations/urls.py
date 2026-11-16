from django.urls import path
from . import views

app_name = 'operations'

urlpatterns = [
    path('training/', views.training_list, name='training_list'),
    path('training/<int:pk>/register/', views.training_register, name='training_register'),
    path('support/', views.support_tickets, name='support_tickets'),
    path('invoices/', views.invoices_list, name='invoices_list'),
    path('invoices/create/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
]
