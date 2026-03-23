from django.urls import path

from .views import ProjectChatWidgetView, ProjectMessageAttachmentDownloadView


urlpatterns = [
	path("dashboard/project-chat/", ProjectChatWidgetView.as_view(), name="project_chat_widget"),
	path("dashboard/project-chat/attachments/<int:message_id>/", ProjectMessageAttachmentDownloadView.as_view(), name="project_message_attachment_download"),
]