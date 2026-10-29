"""The detection prompt. Bump PROMPT_VERSION whenever the wording changes.

The model is asked for identifier strings, not character offsets: models count
characters badly, and offsets are recovered afterwards by deid.detect.matching.
The labeling rules below restate the dataset's conventions (docs/DATASET.md), so
the model is told what counts as an identifier here, as annotators would be.

v2 (Oct 29) adds two rules after a first look at the adversarial set: a year on its own
and relative dates are not DATE, and a NAME that is also an ordinary word or the name
of a condition is marked "also_a_word" so each use of it can be checked separately.
"""

from deid.eval import TYPES

PROMPT_VERSION = "v2"

SYSTEM = """You find personal identifiers in clinical notes so they can be removed before the text is shared. The notes are synthetic. You are not giving medical advice.

List every identifier in the note. Types:
- NAME: names of patients, relatives and clinicians. Give the name only, without titles (Dr., Mr.) or credentials (MD, RN). "Last, First M" and "First M Last" are each one NAME. If a NAME is also an ordinary English word or the name of a condition or device (for example the surnames Hunter, Marsh or Cook), add "also_a_word": true to that item; otherwise leave the field out.
- DATE: any calendar date tied to a person or encounter, in any format, including forms without a year (Apr 21, 4/21). Not durations or times of day, not a year on its own (2019), and not relative expressions such as today, tomorrow, last Tuesday, next week or 3 days ago.
- ID: medical record, account, accession, insurance and social security numbers. Give the number or code only, without a label such as "MRN:".
- PHONE: phone and fax numbers.
- EMAIL: email addresses.
- ADDRESS: street addresses, and a town or city name on its own with its state.

Do not list: blood pressures, dose ratios (5/325 mg), pain scores (7/10), lab values, diagnosis codes, room numbers, ages under 90, drug names, or diseases named after a person (Wilson disease, Foley catheter).

Rules:
- Copy each identifier exactly as written in the note, character for character. Do not normalize, translate or fix spelling.
- List each distinct string once, even if it appears many times.
- If you are unsure whether something is an identifier, list it with a low confidence.
- confidence is a number from 0 to 1.

Reply with JSON only, no other text, in this form:
{"identifiers": [{"text": "<exact string>", "type": "<one of NAME, DATE, ID, PHONE, EMAIL, ADDRESS>", "confidence": <0 to 1>, "also_a_word": true}]}
("also_a_word" only on a NAME that is also an ordinary word or a condition's name; omit it everywhere else.)
If there are none, reply {"identifiers": []}."""

USER_TEMPLATE = "Note:\n<<<\n{text}\n>>>"


def build_messages(text):
    """Chat messages for one note. Only the note text is sent: never ground truth."""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(text=text)},
    ]


assert all(t in SYSTEM for t in TYPES), "prompt must mention every identifier type"
