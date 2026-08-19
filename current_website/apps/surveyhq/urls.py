from django.contrib import admin
from django.urls import path

from . import views


def protected(view):
    return admin.site.admin_view(view)


urlpatterns = [
    path("", protected(views.surveyhq_dashboard), name="dashboard"),
    path("projects/options/", protected(views.project_options), name="project_options"),
    path("surveys/new/", protected(views.survey_create), name="survey_create"),
    path("surveys/<uuid:survey_id>/", protected(views.survey_detail), name="survey_detail"),
    path("surveys/<uuid:survey_id>/edit/", protected(views.survey_edit), name="survey_edit"),
    path("surveys/<uuid:survey_id>/builder/", protected(views.survey_builder), name="survey_builder"),
    path("surveys/<uuid:survey_id>/preview/", protected(views.survey_preview), name="survey_preview"),
    path("surveys/<uuid:survey_id>/publish/", protected(views.survey_publish), name="survey_publish"),
    path("surveys/<uuid:survey_id>/duplicate/", protected(views.survey_duplicate), name="survey_duplicate"),
    path("surveys/<uuid:survey_id>/close/", protected(views.survey_close), name="survey_close"),
    path("surveys/<uuid:survey_id>/reopen/", protected(views.survey_reopen), name="survey_reopen"),
    path("surveys/<uuid:survey_id>/archive/", protected(views.survey_archive), name="survey_archive"),
    path("surveys/<uuid:survey_id>/rotate-code/", protected(views.survey_rotate_code), name="survey_rotate_code"),
    path("surveys/<uuid:survey_id>/delete/", protected(views.survey_delete), name="survey_delete"),
    path("surveys/<uuid:survey_id>/audit/", protected(views.survey_audit), name="survey_audit"),
    path("surveys/<uuid:survey_id>/questions/new/", protected(views.question_create), name="question_create"),
    path("questions/<uuid:question_id>/edit/", protected(views.question_edit), name="question_edit"),
    path("questions/<uuid:question_id>/duplicate/", protected(views.question_duplicate), name="question_duplicate"),
    path("questions/<uuid:question_id>/delete/", protected(views.question_delete), name="question_delete"),
    path("questions/<uuid:question_id>/move/<str:direction>/", protected(views.question_move), name="question_move"),
    path("questions/<uuid:question_id>/choices/new/", protected(views.choice_create), name="choice_create"),
    path("choices/<uuid:choice_id>/edit/", protected(views.choice_edit), name="choice_edit"),
    path("choices/<uuid:choice_id>/delete/", protected(views.choice_delete), name="choice_delete"),
    path("choices/<uuid:choice_id>/move/<str:direction>/", protected(views.choice_move), name="choice_move"),
    path("questions/<uuid:question_id>/rows/new/", protected(views.matrix_row_create), name="matrix_row_create"),
    path("rows/<uuid:row_id>/edit/", protected(views.matrix_row_edit), name="matrix_row_edit"),
    path("rows/<uuid:row_id>/delete/", protected(views.matrix_row_delete), name="matrix_row_delete"),
    path("rows/<uuid:row_id>/move/<str:direction>/", protected(views.matrix_row_move), name="matrix_row_move"),
    path("templates/", protected(views.template_list), name="template_list"),
    path("templates/from-survey/<uuid:survey_id>/", protected(views.template_from_survey), name="template_from_survey"),
    path("templates/<uuid:template_id>/", protected(views.template_detail), name="template_detail"),
    path("templates/<uuid:template_id>/edit/", protected(views.template_edit), name="template_edit"),
    path("templates/<uuid:template_id>/duplicate/", protected(views.template_duplicate), name="template_duplicate"),
    path("templates/<uuid:template_id>/archive/", protected(views.template_archive), name="template_archive"),
    path("templates/<uuid:template_id>/delete/", protected(views.template_delete), name="template_delete"),
    path("templates/<uuid:template_id>/create-survey/", protected(views.survey_from_template), name="survey_from_template"),
    path("audit/", protected(views.audit_log), name="audit_log"),
]
