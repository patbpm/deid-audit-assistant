"""Note templates. {token} placeholders become labeled spans (see resolver.py);
<name> placeholders are filled with plain, unlabeled text before rendering."""

from datetime import timedelta

from . import clinical


def _fill(text, values):
    for key, value in values.items():
        text = text.replace(f"<{key}>", str(value))
    return text


def _scenario(patient):
    return clinical.SCENARIOS[patient.scenario % len(clinical.SCENARIOS)]


def _common_values(rng, patient):
    s = _scenario(patient)
    values = dict(clinical.pronouns(patient.person.sex))
    for key in ("dx", "cc", "hpi", "exam", "labs", "imaging", "plan", "progress", "course"):
        values[key] = _fill(s[key], values)
    values.update(
        age=patient.age,
        pmh=", ".join(s["pmh"]),
        meds="; ".join(s["meds"]),
        followup=s["followup"],
        vitals=clinical.vitals(rng),
        code=rng.choice(clinical.CODES),
        room=f"{rng.randint(2, 6)}{rng.randint(0, 2)}{rng.randint(1, 9)}",
        pain=f"{rng.randint(2, 9)}/10",
    )
    return values


def note_dates(rng, patient, kind):
    """Date for this note, plus the dict of dates the resolver may print."""
    stay = (patient.discharge - patient.admit).days
    if kind == "history_and_physical":
        note = patient.admit
    elif kind == "progress_note":
        note = patient.admit + timedelta(days=rng.randint(1, stay - 1))
    elif kind == "discharge_summary":
        note = patient.discharge
    elif kind == "radiology_report":
        note = patient.admit + timedelta(days=rng.randint(0, 1))
    elif kind == "telephone_encounter":
        note = patient.discharge + timedelta(days=rng.randint(2, 6))
    else:
        raise ValueError(f"unknown note kind: {kind}")
    dates = {
        "dob": patient.dob, "admit": patient.admit, "dc": patient.discharge,
        "prior": patient.prior, "followup": patient.followup,
        "note": note, "sign": note + timedelta(days=rng.randint(0, 1)),
    }
    return note, dates


def history_and_physical(rng, patient):
    v = _common_values(rng, patient)
    lines = [
        "HISTORY AND PHYSICAL",
        "",
        "Patient: {pt_lf}",
        "MRN: {mrn}    Account: {acct}",
        "DOB: {d_dob}    Date of admission: {d_admit}",
        "Attending: {attending_title}",
        "PCP: {pcp_sig}",
    ]
    if rng.random() < 0.7:
        lines.append("Insurance ID: {ins_id}")
    if rng.random() < 0.15:
        lines.append("SSN on face sheet: {ssn}")
    lines += [
        "",
        "CHIEF COMPLAINT: <cc>.",
        "",
        "HISTORY OF PRESENT ILLNESS:",
        ("{pt_title}" if rng.random() < 0.6 else "{pt_full}")
        + " is a <age>-year-old <sexword> with a history of <pmh> who presents with <cc>. <hpi>",
    ]
    if patient.spouse and rng.random() < 0.6:
        lines.append("<His> spouse, {spouse_first}, accompanied <him> and helped provide the history.")
    lines += [
        "",
        "PAST MEDICAL HISTORY: <pmh>. Prior related evaluation on {d_prior}.",
        "MEDICATIONS: <meds>.",
        "",
        "SOCIAL HISTORY: " + ("Lives in {town}." if rng.random() < 0.35 else "Lives at {addr}.")
        + (" Lives with {spouse_first}." if patient.spouse else "")
        + " Emergency contact is {kin_full}, reachable at {phone_kin}. Patient's cell phone is {phone_cell}.",
        "",
        "OBJECTIVE: <vitals>. Pain <pain>. <exam>",
        "LABS: <labs>",
        "IMAGING: <imaging>",
        "",
        "ASSESSMENT AND PLAN: <dx> (ICD-10 <code>). <plan>",
        "Discussed with {consultant_title} ({consultant_specialty}); {consultant_title} recommends outpatient follow-up with <followup>.",
        "Admitted to room <room>.",
        "",
        "Electronically signed by {resident_sig} on {d_sign}.",
    ]
    return _fill("\n".join(lines), v)


def progress_note(rng, patient):
    v = _common_values(rng, patient)
    lines = [
        "PROGRESS NOTE",
        "Date: {d_note}    Admitted: {d_admit}",
        "Patient: {pt_full}    MRN: {mrn}    DOB: {d_dob}",
        "",
        "SUBJECTIVE: {pt_first} reports feeling better today. Pain <pain>. <progress>",
    ]
    if rng.random() < 0.5:
        lines.append("Spoke with {kin_first} by phone at {phone_kin} to update the family.")
    lines += [
        "",
        "OBJECTIVE: <vitals>.",
        "<exam> Labs this morning: <labs>",
    ]
    if rng.random() < 0.4:
        lines.append("Foley catheter removed without difficulty. Glasgow Coma Scale 15.")
    lines += [
        "",
        "ASSESSMENT/PLAN: <dx> (ICD-10 <code>), improving. Continue the following: <plan>",
        "Seen and discussed with {attending_title}. Case reviewed with {consultant_sig}.",
    ]
    if rng.random() < 0.2:
        lines.append("Patient requested that results be sent to {pt_email}.")
    lines += ["", "{resident_sig}"]
    return _fill("\n".join(lines), v)


def discharge_summary(rng, patient):
    v = _common_values(rng, patient)
    lines = [
        "DISCHARGE SUMMARY",
        "",
        "Patient: {pt_lf}    DOB: {d_dob}    MRN: {mrn}",
        "Admission date: {d_admit}    Discharge date: {d_dc}",
        "Attending: {attending_sig}",
        "",
        "DIAGNOSIS: <dx> (ICD-10 <code>).",
        "HOSPITAL COURSE: {pt_title} presented with <cc>. <course> Last prior evaluation was on {d_prior}.",
        "DISCHARGE MEDICATIONS: <meds>.",
        "CONDITION AT DISCHARGE: Stable. <vitals>.",
        "",
        "FOLLOW-UP: Appointment with {pcp_title} on {d_followup} at {clinic_addr}.",
        "Call {phone_clinic} (fax {phone_fax}) with questions, or contact {pt_first} at {phone_home}.",
        "Discharge instructions mailed to {addr}." if rng.random() < 0.6 else "Discharged home to {town}.",
    ]
    if rng.random() < 0.4:
        lines.append("Patient portal email on file: {pt_email}.")
    lines += [
        "",
        "cc: {pcp_sig}",
        "Dictated by {attending_lf} on {d_sign}.",
    ]
    return _fill("\n".join(lines), v)


def radiology_report(rng, patient):
    v = _common_values(rng, patient)
    lines = [
        "RADIOLOGY REPORT",
        "Accession: {accession}",
        "Patient: {pt_lf}    DOB: {d_dob}    MRN: {mrn}",
        "Exam date: {d_note}",
        "Ordering provider: {attending_lf}",
        "",
        "INDICATION: <cc>.",
        "COMPARISON: Study dated {d_prior}.",
        "FINDINGS: <imaging>",
        "IMPRESSION: Findings above are consistent with <dx>. Clinical correlation recommended.",
        "",
        "Electronically signed by {radiologist_sig} on {d_sign}. Questions may be directed to {phone_clinic}.",
    ]
    return _fill("\n".join(lines), v)


def telephone_encounter(rng, patient):
    v = _common_values(rng, patient)
    reason = rng.choice(clinical.PHONE_REASONS)
    lines = [
        "TELEPHONE ENCOUNTER",
        "Date: {d_note}",
        "Patient: {pt_full}    DOB: {d_dob}    MRN: {mrn}",
        "",
        "Called {pt_title} at {phone_cell}; "
        + ("left a voicemail at {phone_home}." if rng.random() < 0.4 else "reached the patient directly."),
        "{pt_first} " + reason + ".",
        "Recent discharge for <dx> on {d_dc}. Follow-up visit with {pcp_title} remains scheduled for {d_followup}.",
        "Family contact {kin_full} ({phone_kin}) was notified with permission.",
        "",
        "Documented by {resident_sig}.",
    ]
    return _fill("\n".join(lines), v)


BUILDERS = {
    "history_and_physical": history_and_physical,
    "progress_note": progress_note,
    "discharge_summary": discharge_summary,
    "radiology_report": radiology_report,
    "telephone_encounter": telephone_encounter,
}
