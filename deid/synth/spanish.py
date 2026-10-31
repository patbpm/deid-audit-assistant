"""Spanish-language synthetic clinical notes with exact identifier labels.

    python -m deid.synth.spanish --out data/generated/es

Forty notes for twenty invented patients in the American Southwest, three kinds (follow-up visit, discharge
summary, telephone encounter), written the way a bilingual clinic might: two surnames per person (paternal
and maternal), titles Sr./Sra./Dr./Dra., dates as 04/05/2025 (day first), "12 de abril de 2025" or ISO,
streets as "Calle Los Pinos 1423". Everything is invented by this project: names, places, numbers and
clinical stories (the stories are generic and give no medical advice). Same labeling rules as the English
set (docs/DATASET.md): a label covers only the identifier value, never "Dr." or "MRN:".

Why: the same engine and model can be pointed at notes in another language, and a project that only ever
shows English is untested there. This set tests it on one language, with a model that was not told which
language to expect; it says nothing about other languages or about real Spanish-language notes.
"""

import argparse
import json
import random
from datetime import timedelta
from pathlib import Path

from . import formats, people
from .builder import Piece, plain, render, validate_spans
from .people import Patient, Person, Provider
from .resolver import PROVIDER_ROLES, Resolver

SEED = 20261101
PATIENTS = 20
FEMALE_FIRST = ["María", "Guadalupe", "Carmen", "Rosa", "Ana", "Lucía", "Elena", "Isabel", "Sofía", "Beatriz", "Teresa",
                "Marisol", "Yolanda", "Patricia", "Luz", "Inés", "Dolores", "Alejandra", "Fernanda", "Valeria"]
MALE_FIRST = ["José", "Juan", "Luis", "Carlos", "Miguel", "Jorge", "Alejandro", "Ricardo", "Fernando", "Manuel", "Rafael",
              "Andrés", "Héctor", "Raúl", "Sergio", "Eduardo", "Arturo", "Pablo", "Diego", "Ramón"]
SURNAMES = ["Hernández", "García", "Martínez", "López", "González", "Rodríguez", "Pérez", "Sánchez", "Ramírez", "Torres",
            "Flores", "Rivera", "Gómez", "Díaz", "Cruz", "Morales", "Ortiz", "Gutiérrez", "Chávez", "Ramos", "Mendoza",
            "Vargas", "Castillo", "Jiménez", "Moreno", "Romero", "Herrera", "Medina", "Aguilar", "Vega", "Salazar",
            "Cabrera", "Ibarra", "Navarro", "Domínguez"]
STREETS = ["Olivos", "Nogales", "Mesquite", "Chaparral", "Rosales", "Granados Viejos", "Naranjos", "Encinos", "Colibrí",
           "Zafiro", "Girasol", "Amapolas"]
STREET_TYPES = ["Calle", "Avenida", "Camino", "Paseo"]
TOWNS = [("San Elias", "TX"), ("Villa Rosal", "NM"), ("Los Cerritos", "AZ"), ("Nueva Esperanza", "TX"),
         ("Valle Dorado", "CA"), ("Santa Brigida", "NM"), ("Paso Largo", "TX"), ("Rio Claro", "AZ")]
UNIT_TYPES = ["Apto", "Depto"]
CREDENTIALS = ["MD", "DO", "NP", "PA-C"]
SPECIALTIES = ["medicina interna", "cardiología", "neumología", "endocrinología", "medicina familiar", "nefrología"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]

SCENARIOS = [
    {"dx": "neumonía adquirida en la comunidad", "cc": "tos y fiebre de tres días",
     "hpi": "<pron> refiere tos productiva, fiebre y falta de aire al caminar. Niega dolor en el pecho.",
     "exam": "Crepitantes en la base derecha. Saturación 91 % al aire ambiente.",
     "plan": "Antibiótico por vía oral durante cinco días, hidratación y control en una semana.",
     "meds": "amoxicilina-clavulánico 875 mg dos veces al día; paracetamol 500 mg si hay fiebre"},
    {"dx": "insuficiencia cardíaca descompensada", "cc": "hinchazón de las piernas y falta de aire",
     "hpi": "<pron> nota aumento de peso de tres kilos y dificultad para dormir acostado.",
     "exam": "Edema hasta las rodillas, ingurgitación yugular leve. Pulmones con crepitantes bibasales.",
     "plan": "Aumentar el diurético, pesar a diario, restricción de sal y ecocardiograma.",
     "meds": "furosemida 40 mg al día; carvedilol 12.5 mg dos veces al día; losartán 50 mg al día"},
    {"dx": "diabetes tipo 2 con control irregular", "cc": "sed y orina frecuente",
     "hpi": "<pron> refiere sed intensa, visión borrosa ocasional y olvidos de la medicación.",
     "exam": "Sin signos de deshidratación. Pulsos pedios presentes.",
     "plan": "Ajustar la dosis de metformina, revisar la dieta con nutrición y repetir hemoglobina glicosilada en tres meses.",
     "meds": "metformina 1000 mg dos veces al día; atorvastatina 20 mg por la noche"},
    {"dx": "infección urinaria", "cc": "ardor al orinar",
     "hpi": "<pron> describe ardor y urgencia desde hace dos días, sin fiebre.",
     "exam": "Sensibilidad leve suprapúbica. Sin dolor en los flancos.",
     "plan": "Ciclo corto de antibiótico, abundantes líquidos y regresar si aparece fiebre.",
     "meds": "nitrofurantoína 100 mg dos veces al día por cinco días"},
]
PHONE_REASONS = [
    "preguntó si la hinchazón es esperable y se le indicó mantener la pierna elevada",
    "dijo que toma los medicamentos como se le indicó y sin efectos secundarios",
    "quiso cambiar la cita de control y se le ofreció el próximo turno disponible",
    "tuvo dudas sobre las instrucciones de alta, que se repasaron por teléfono",
]
KINDS = ("consulta_seguimiento", "resumen_alta", "llamada_telefonica")


def make_person(rng, entity, sex=None, last=None):
    sex = sex or rng.choice("FM")
    first = rng.choice(FEMALE_FIRST if sex == "F" else MALE_FIRST)
    middle = rng.choice(FEMALE_FIRST if sex == "F" else MALE_FIRST) if rng.random() < 0.3 else ""
    if last is None:
        a, b = rng.sample(SURNAMES, 2)
        last = f"{a} {b}"
    first = f"{first} {middle}" if middle and middle != first else first
    return Person(entity, first, "", last, sex)


def make_address(rng):
    unit = f"{rng.choice(UNIT_TYPES)} {rng.randint(1, 40)}{rng.choice('ABCD')}" if rng.random() < 0.3 else ""
    town, state = rng.choice(TOWNS)
    return formats.Address(rng.randint(10, 9899), rng.choice(STREETS), rng.choice(STREET_TYPES), unit, town, state,
                           f"{rng.randint(75000, 79999):05d}")


def fmt_address(a):
    out = f"{a.street_type} {a.street} {a.number}" + (f", {a.unit}" if a.unit else "")
    return f"{out}, {a.town}, {a.state} {a.zip_code}"


def make_providers(rng, count=12):
    return [Provider(make_person(rng, f"D{i + 1:02d}"), rng.choice(CREDENTIALS), rng.choice(SPECIALTIES)) for i in range(count)]


def make_patient(rng, index, providers):
    pid = f"P{index:04d}"
    sex = rng.choice("FM")
    person = make_person(rng, pid, sex)
    admit = people.date(2019, 1, 1) + timedelta(days=rng.randint(0, 365 * 7 - 1))
    age = rng.randint(24, 88)
    dob = admit - timedelta(days=age * 365 + rng.randint(0, 364))
    discharge = admit + timedelta(days=rng.randint(3, 9))
    spouse = make_person(rng, f"{pid}:spouse", "M" if sex == "F" else "F", last=person.last) if rng.random() < 0.6 else None
    kin = make_person(rng, f"{pid}:kin", None, last=person.last if rng.random() < 0.7 else None)
    pick = lambda: rng.choice(providers)
    return Patient(
        pid=pid, person=person, dob=dob, age=age, admit=admit, discharge=discharge,
        prior=admit - timedelta(days=rng.randint(30, 700)), followup=discharge + timedelta(days=rng.randint(7, 21)),
        mrn=formats.make_mrn(rng), account=formats.make_account(rng), ssn=formats.make_ssn(rng),
        insurance_id=formats.make_insurance_id(rng), address=make_address(rng), phone_home=formats.make_phone(rng),
        phone_cell=formats.make_phone(rng), email=formats.make_email(rng, "".join(c for c in person.first.split()[0].lower() if c.isascii()), "contacto"),
        spouse=spouse, kin=kin, kin_phone=formats.make_phone(rng), clinic_address=make_address(rng),
        clinic_phone=formats.make_phone(rng), clinic_fax=formats.make_phone(rng), scenario=index,
        attending=pick(), pcp=pick(), consultant=pick(), resident=pick(), radiologist=pick())


DATE_STYLES = ("dmy_slash", "dmy_slash_nopad", "es_long", "iso", "dmy_dash2")
PARTIAL_STYLES = ("es_md", "dm_slash")


def fmt_date(d, style):
    if style == "dmy_slash":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    if style == "dmy_slash_nopad":
        return f"{d.day}/{d.month}/{d.year}"
    if style == "dmy_dash2":
        return f"{d.day:02d}-{d.month:02d}-{d.year}"
    if style == "es_long":
        return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"
    if style == "iso":
        return d.isoformat()
    if style == "es_md":
        return f"{d.day} de {MONTHS_ES[d.month - 1]}"
    if style == "dm_slash":
        return f"{d.day}/{d.month}"
    raise ValueError(style)


class ResolverEs(Resolver):
    """The English resolver with Spanish dates, titles and address order."""

    def __init__(self, rng, patient, dates, accession=""):
        super().__init__(rng, patient, dates, accession)
        self.date_style = rng.choice(DATE_STYLES)

    def _date(self, key):
        d = self.dates[key]
        style = self.date_style
        roll = self.rng.random()
        if roll < 0.2:
            style = self.rng.choice(DATE_STYLES)
        elif roll < 0.3 and key not in ("dob", "sign"):
            style = self.rng.choice(PARTIAL_STYLES)
        return [Piece(fmt_date(d, style), "DATE", key.upper(), "", d.isoformat())]

    def _person(self, person, form, subtype):
        if form == "title":
            return [plain("Sr. " if person.sex == "M" else "Sra. "), self._name_piece(person.last, person, subtype)]
        if form == "lf":
            return [self._name_piece(f"{person.last}, {person.first}", person, subtype)]
        return super()._person(person, form, subtype)

    def _provider(self, provider, form):
        if form == "title":
            return [plain("Dr. " if provider.person.sex == "M" else "Dra. "),
                    self._name_piece(provider.person.last.split()[0], provider.person, "PROVIDER")]
        return super()._provider(provider, form)

    def t_addr(self):
        return [Piece(fmt_address(self.p.address), "ADDRESS", "HOME", self.p.pid)]

    def t_clinic_addr(self):
        return [Piece(fmt_address(self.p.clinic_address), "ADDRESS", "CLINIC", "")]


def pronoun(sex):
    return "Ella" if sex == "F" else "Él"


def fill(text, **values):
    for k, v in values.items():
        text = text.replace(f"<{k}>", str(v))
    return text


def build(kind, rng, patient):
    s = SCENARIOS[patient.scenario % len(SCENARIOS)]
    v = {"pron": pronoun(patient.person.sex), "age": patient.age, "sexword": "mujer" if patient.person.sex == "F" else "hombre",
         "dx": s["dx"], "cc": s["cc"], "hpi": fill(s["hpi"], pron=pronoun(patient.person.sex)), "exam": s["exam"],
         "plan": s["plan"], "meds": s["meds"],
         "vitals": f"PA {rng.randint(98, 168)}/{rng.randint(55, 98)}, FC {rng.randint(58, 124)}, FR {rng.randint(12, 26)}, "
                   f"Temp {rng.randint(973, 1021) / 10:.1f} F"}
    if kind == "consulta_seguimiento":
        lines = ["NOTA DE SEGUIMIENTO", "", "Paciente: {pt_lf}", "MRN: {mrn}    Fecha de nacimiento: {d_dob}",
                 "Fecha de la consulta: {d_note}", "Médico: {pcp_title}", "",
                 "MOTIVO DE CONSULTA: <cc>.", "",
                 "{pt_title} es " + ("una" if patient.person.sex == "F" else "un") + " <sexword> de <age> años. <hpi>"]
        if patient.spouse and rng.random() < 0.6:
            lines.append("Vino acompañado por su cónyuge, {spouse_first}.")
        lines += ["", "EXAMEN: <vitals>. <exam>", "EVALUACIÓN Y PLAN: <dx>. <plan>", "Medicamentos: <meds>.",
                  "Domicilio: {addr}. Teléfono celular: {phone_cell}.",
                  "Contacto de emergencia: {kin_full}, {phone_kin}.", "", "Firmado por {resident_sig} el {d_sign}."]
    elif kind == "resumen_alta":
        lines = ["RESUMEN DE ALTA", "", "Paciente: {pt_lf}    MRN: {mrn}    Fecha de nacimiento: {d_dob}",
                 "Ingreso: {d_admit}    Alta: {d_dc}", "Médico tratante: {attending_title}", "",
                 "DIAGNÓSTICO: <dx>.",
                 "EVOLUCIÓN: {pt_title} ingresó por <cc>. Última evaluación previa el {d_prior}. <exam>",
                 "MEDICAMENTOS AL ALTA: <meds>.", "",
                 "SEGUIMIENTO: cita con {pcp_title} el {d_followup} en {clinic_addr}.",
                 "Para dudas llame al {phone_clinic} (fax {phone_fax}) o al {phone_home}."]
        if rng.random() < 0.5:
            lines.append("Correo del portal del paciente: {pt_email}.")
        lines += ["", "Dictado por {attending_lf} el {d_sign}."]
    else:
        lines = ["ENCUENTRO TELEFÓNICO", "Fecha: {d_note}", "Paciente: {pt_full}    Fecha de nacimiento: {d_dob}    MRN: {mrn}", "",
                 "Se llamó a {pt_title} al {phone_cell}; "
                 + ("se dejó un mensaje en el {phone_home}." if rng.random() < 0.4 else "se habló directamente con el paciente."),
                 "{pt_first} " + rng.choice(PHONE_REASONS) + ".",
                 "Alta reciente por <dx> el {d_dc}. La cita con {pcp_title} sigue programada para el {d_followup}.",
                 "Se avisó a {kin_full} ({phone_kin}) con permiso del paciente.", "", "Documentado por {resident_sig}."]
    return fill("\n".join(lines), **v)


def note_dates(rng, patient, kind):
    stay = (patient.discharge - patient.admit).days
    note = {"consulta_seguimiento": patient.discharge + timedelta(days=rng.randint(7, 14)),
            "resumen_alta": patient.discharge,
            "llamada_telefonica": patient.discharge + timedelta(days=rng.randint(2, 6))}[kind]
    return note, {"dob": patient.dob, "admit": patient.admit, "dc": patient.discharge, "prior": patient.prior,
                  "followup": patient.followup, "note": note, "sign": note + timedelta(days=rng.randint(0, 1))}


def generate_notes(seed=SEED, patients=PATIENTS):
    rng = random.Random(seed)
    providers = make_providers(rng)
    notes = []
    for index in range(1, patients + 1):
        patient = make_patient(rng, index, providers)
        for kind in (KINDS[index % 3], KINDS[(index + 1) % 3]):
            note_date, dates = note_dates(rng, patient, kind)
            template = build(kind, rng, patient)
            text, spans = render(template, ResolverEs(rng, patient, dates))
            validate_spans(text, spans)
            notes.append({"note_id": f"E{len(notes) + 1:04d}", "patient_id": patient.pid, "note_type": kind,
                          "note_date": note_date.isoformat(), "language": "es", "text": text, "spans": spans})
    return notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--patients", type=int, default=PATIENTS)
    parser.add_argument("--out", default="data/generated/es")
    args = parser.parse_args(argv)
    notes = generate_notes(args.seed, args.patients)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "notes.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for n in notes:
            handle.write(json.dumps(n, sort_keys=True, ensure_ascii=False) + "\n")
    by_type = {}
    for n in notes:
        for s in n["spans"]:
            by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    print(f"{len(notes)} notes, {sum(by_type.values())} labeled identifiers {dict(sorted(by_type.items()))} -> {out}")


if __name__ == "__main__":
    main()
