from django.contrib import admin
from django.urls import include, path

# Transaction APIs
from transactions.views import (
    upload_csv,
    add_transaction,
    set_budget,
    set_alert,
    dashboard,
    audit_logs,
    category_transactions
)

# AI Advisor (Chatbot + Auth)
from advisor.views import (
    get_me,
    signup,
    login
)
from rest_framework_simplejwt.views import TokenRefreshView


urlpatterns = [
    # -------------------------------
    # Admin
    # -------------------------------
    path('admin/', admin.site.urls),

    # -------------------------------
    # Authentication
    # -------------------------------
    path('signup/', signup),
    path('login/', login),
    path('me/', get_me),
    path('token/refresh/', TokenRefreshView.as_view()),
    path('advisor/', include('advisor.urls')),

    # -------------------------------
    # Data Input
    # -------------------------------
    path('upload/', upload_csv),
    path('add/', add_transaction),
    path('set-budget/', set_budget),
    path('set-alert/', set_alert),

    # -------------------------------
    # Analytics
    # -------------------------------
    path('dashboard/', dashboard),
    path('audit/', audit_logs),
    path('category-transactions/', category_transactions),

]