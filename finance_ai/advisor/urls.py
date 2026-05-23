from django.urls import path

from .views import ca_chat, clear_chat, get_chat_history


urlpatterns = [
    path("chat/", ca_chat),
    path("clear/", clear_chat),
    path("history/", get_chat_history),
]
