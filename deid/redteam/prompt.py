"""The red-team prompt. Bump PROMPT_VERSION whenever the wording changes.

The model sees a masked view of the cleaned note: every value the replacement
engine changed is shown as a tag such as [NAME], so a name, date, number or place
written in plain text is something the detector missed. Surrogate values are
never shown, because a made-up name cannot be told apart from a real one.
"""

from deid.eval import TYPES

PROMPT_VERSION = "rt1"

CATEGORIES = (
    "LEFTOVER",          # an identifier written in plain text that should have been removed
    "RARE_CONDITION",    # a condition or event so uncommon it narrows the field
    "OCCUPATION",        # a job or role that few people hold
    "EMPLOYER_OR_SCHOOL",
    "SMALL_PLACE",       # a place small enough to narrow the field
    "PUBLIC_EVENT",      # an event covered in the news or known locally
    "FAMILY",            # unusual family circumstances
    "OTHER",
)
RISK_LEVELS = ("low", "medium", "high")

SYSTEM = """You are a privacy reviewer for a de-identification tool. The note below is synthetic and has already been cleaned: each removed identifier is shown as a tag such as [NAME], [DATE], [ID], [PHONE], [EMAIL] or [ADDRESS]. You are not giving medical advice, and you must not try to name the person.

Your job is to judge how easily someone who knows the patient, or who can search news and public records, could still work out who this note is about. List the clues that make that easier.

Clue categories:
- LEFTOVER: an identifier written in plain text that should have been replaced by a tag: a person's name, a full or partial date, a record or account number, a phone number, an email address, a street address, or a town. Give "type" as one of NAME, DATE, ID, PHONE, EMAIL, ADDRESS. Titles (Dr., Mrs.), ages under 90, room numbers, lab values, doses, blood pressures and diagnosis codes are not leftovers.
- RARE_CONDITION: a very uncommon condition or event, or a statement that the case is unusual or one of few.
- OCCUPATION: a job or role few people hold (an elected office, a unique local position).
- EMPLOYER_OR_SCHOOL: a named or clearly identifiable employer, school or team.
- SMALL_PLACE: a place small or specific enough to narrow the field.
- PUBLIC_EVENT: an event the news or a community would remember.
- FAMILY: unusual family circumstances.
- OTHER: anything else that narrows the field.
Ordinary common conditions, medications, vital signs and the usual clinical story are not clues.

Risk level:
- low: nothing beyond ordinary clinical detail.
- medium: one or more details that narrow the person to a small group.
- high: a leftover direct identifier, or a detail or combination that could single out one person.

Rules:
- Copy each clue's text exactly as written in the note, character for character. Quote only the shortest phrase that carries the clue.
- Do not list tags such as [NAME] as clues.
- "why" is one short sentence.

Reply with JSON only, no other text, in this form:
{"risk": "<low|medium|high>", "clues": [{"text": "<exact phrase>", "category": "<category>", "type": "<identifier type for LEFTOVER, otherwise empty>", "why": "<short reason>"}]}
If there are no clues, reply {"risk": "low", "clues": []}."""

USER_TEMPLATE = "Cleaned note:\n<<<\n{text}\n>>>"


def build_messages(masked_text):
    """Chat messages for one cleaned note. Only the masked view is sent."""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(text=masked_text)},
    ]


assert all(c in SYSTEM for c in CATEGORIES), "prompt must mention every category"
assert all(t in SYSTEM for t in TYPES), "prompt must mention every identifier type"
