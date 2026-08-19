import secrets
import string


SURVEY_CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
SURVEY_CODE_DIGITS = "23456789"
SURVEY_CODE_ALPHABET = SURVEY_CODE_LETTERS + SURVEY_CODE_DIGITS
SURVEY_CODE_LENGTH = 6


def generate_survey_code() -> str:
    """Return a human-readable, case-sensitive code with letters and digits."""
    while True:
        code = "".join(secrets.choice(SURVEY_CODE_ALPHABET) for _ in range(SURVEY_CODE_LENGTH))
        if any(character in SURVEY_CODE_LETTERS for character in code) and any(
            character in SURVEY_CODE_DIGITS for character in code
        ):
            return code


def is_valid_survey_code(value: str) -> bool:
    return (
        len(value) == SURVEY_CODE_LENGTH
        and all(character in SURVEY_CODE_ALPHABET for character in value)
        and any(character in SURVEY_CODE_LETTERS for character in value)
        and any(character in SURVEY_CODE_DIGITS for character in value)
    )
