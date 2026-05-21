from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse

def ping(request):
    return JsonResponse({"status": "ok"})

def debug(request):
    from ai_engine.ai_service import AI_MODEL, REQUEST_TIMEOUT, MAX_RETRIES
    from ai_engine.market_service import _cache, _refresh_thread
    return JsonResponse({
        "ai_model": AI_MODEL,
        "request_timeout": REQUEST_TIMEOUT,
        "max_retries": MAX_RETRIES,
        "market_cache_keys": list(_cache.get("data", {}).keys()) if _cache.get("data") else None,
        "market_thread_alive": _refresh_thread.is_alive() if _refresh_thread else False,
        "version": "lazy_thread_v3"
    })

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
    path('ping/', ping),
    path('debug/', debug),

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