from django.core.exceptions import ValidationError


class SurveyHQError(Exception):
    """Base exception for SurveyHQ domain operations."""


class InvalidLifecycleTransition(SurveyHQError):
    """Raised when a survey lifecycle transition is not permitted."""


class SurveyStructureLocked(ValidationError):
    """Raised when published analytical structure would be changed."""


class SurveyRetentionProtected(SurveyHQError):
    """Raised when retained survey data would be deleted prematurely."""
