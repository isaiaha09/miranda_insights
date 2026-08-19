from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


TEXT_TYPES = {"short_text", "long_text"}
SCALE_TYPES = {"number", "rating", "linear_scale"}
NO_CONFIGURATION_TYPES = {
    "single_choice",
    "multiple_choice",
    "dropdown",
    "yes_no",
    "likert",
    "matrix",
    "ranking",
    "date",
    "heading",
    "description",
    "page_break",
}


def _decimal(value, label):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be numeric.") from exc


def normalize_question_configuration(question_type: str, configuration) -> dict:
    if configuration in (None, ""):
        configuration = {}
    if not isinstance(configuration, dict):
        raise ValidationError("Question configuration must be an object.")

    if question_type in TEXT_TYPES:
        allowed = {"placeholder", "max_length"}
        unknown = set(configuration) - allowed
        if unknown:
            raise ValidationError(f"Unsupported text configuration: {', '.join(sorted(unknown))}.")
        normalized = {}
        placeholder = str(configuration.get("placeholder") or "").strip()
        if placeholder:
            normalized["placeholder"] = placeholder
        maximum = configuration.get("max_length")
        if maximum not in (None, ""):
            try:
                maximum = int(maximum)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Maximum length must be a whole number.") from exc
            if maximum <= 0:
                raise ValidationError("Maximum length must be positive.")
            normalized["max_length"] = maximum
        return normalized

    if question_type == "email":
        unknown = set(configuration) - {"placeholder"}
        if unknown:
            raise ValidationError(f"Unsupported email configuration: {', '.join(sorted(unknown))}.")
        placeholder = str(configuration.get("placeholder") or "").strip()
        return {"placeholder": placeholder} if placeholder else {}

    if question_type in SCALE_TYPES:
        allowed = {"minimum", "maximum", "step", "low_anchor", "high_anchor"}
        unknown = set(configuration) - allowed
        if unknown:
            raise ValidationError(f"Unsupported scale configuration: {', '.join(sorted(unknown))}.")
        defaults = {
            "number": (None, None, None),
            "rating": (Decimal("1"), Decimal("5"), Decimal("1")),
            "linear_scale": (Decimal("0"), Decimal("10"), Decimal("1")),
        }
        default_minimum, default_maximum, default_step = defaults[question_type]
        minimum = _decimal(configuration.get("minimum"), "Minimum")
        maximum = _decimal(configuration.get("maximum"), "Maximum")
        step = _decimal(configuration.get("step"), "Step")
        minimum = default_minimum if minimum is None else minimum
        maximum = default_maximum if maximum is None else maximum
        step = default_step if step is None else step
        if minimum is not None and maximum is not None and maximum <= minimum:
            raise ValidationError("Maximum must be greater than minimum.")
        if step is not None and step <= 0:
            raise ValidationError("Step must be positive.")
        normalized = {}
        for key, value in (("minimum", minimum), ("maximum", maximum), ("step", step)):
            if value is not None:
                normalized[key] = format(value, "f")
        for key in ("low_anchor", "high_anchor"):
            value = str(configuration.get(key) or "").strip()
            if value:
                normalized[key] = value
        return normalized

    if question_type in NO_CONFIGURATION_TYPES:
        if configuration:
            raise ValidationError("This question type does not accept additional configuration.")
        return {}

    raise ValidationError("Unsupported SurveyHQ question type.")
