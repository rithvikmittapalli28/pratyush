from django.urls import path

from .views import ca_chat, clear_chat


urlpatterns = [
    path("chat/", ca_chat),
    path("clear/", clear_chat),
]
