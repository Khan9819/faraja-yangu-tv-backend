from django.urls import path
from . import views

app_name = 'advertising'

urlpatterns = [
    # Add your URL patterns here
    path('get-carousel-ads/', views.get_carousel_ads, name='get-carousel-ads'),
    path('get-carousel-ad/<int:pk>/', views.get_carousel_ad, name='get-carousel-ad'),
    path('create-carousel-ad/', views.create_carousel_ad, name='create-carousel-ad'),
    path('update-carousel-ad/<int:pk>/', views.update_carousel_ad, name='update-carousel-ad'),
    path('delete-carousel-ad/<int:pk>/', views.delete_carousel_ad, name='delete-carousel-ad'),
    path('claim-reward/', views.claim_reward, name='claim-reward'),
    path('record-view/<int:ad_id>/', views.record_view, name='record-view'),
    path('record-click/<int:ad_id>/', views.record_click, name='record-click'),
]
