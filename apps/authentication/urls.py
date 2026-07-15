from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    path('login/', views.login, name='login'),
    path('login/google/', views.login_google, name='login-google'),
    path('login-with-google/', views.login_with_google, name='login-with-google'),
    path('refresh/', views.refresh, name='refresh'),
    path('logout/', views.logout, name='logout'),
    path('register/', views.register, name='register'),
    path('complete-profile/', views.complete_profile, name='complete-profile'),
    path('profile/', views.profile, name='profile'),
    path('verify-user/<int:id>/', views.verify_user, name='verify-user'),
    path('verify-otp/', views.verify_otp, name='verify-otp'),
    path('send-otp/', views.send_otp, name='send-otp'),
    path('verify-email/', views.verify_email, name='verify-email'),
    path('request-verification/', views.request_verification, name='request-verification'),
    path('verify-password-reset-otp/', views.verify_password_reset_otp, name='request-verification'),
    path('reset-password/', views.reset_password, name='request-verification'),
    path('request-password-reset-with-email/', views.request_password_reset_with_email, name='request-password-reset-with-email'),
    path('request-password-reset-with-phone/', views.request_password_reset_with_phone, name='request-password-reset-with-phone'),

    # CMS Profile endpoints
    path('profile/cms/', views.cms_profile, name='cms-profile'),
    path('profile/update/', views.cms_profile_update, name='cms-profile-update'),
    path('change-password/', views.cms_change_password, name='cms-change-password'),
]
