from django.urls import path

from .views import ProjectChatWidgetView


urlpatterns = [
	path("dashboard/project-chat/", ProjectChatWidgetView.as_view(), name="project_chat_widget"),
]