from django.urls import path

from . import participant_views


urlpatterns = [
    path("", participant_views.participant_entry_base, name="entry_base"),
    path("introduction/", participant_views.participant_introduction, name="introduction"),
    path("survey/", participant_views.participant_survey, name="survey"),
    path("question-image/<uuid:question_id>/", participant_views.participant_question_image, name="question_image"),
    path("thank-you/", participant_views.participant_thank_you, name="thank_you"),
    path("<str:entry_token>/", participant_views.participant_entry, name="entry"),
]
