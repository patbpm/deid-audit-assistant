"""Synthetic clinical content. Contains no identifiers; some strings are
deliberate lookalikes (blood pressures, dose ratios, eponyms, codes) that a
detector should leave alone."""

SCENARIOS = [
    {
        "dx": "acute decompensated heart failure",
        "cc": "shortness of breath and leg swelling",
        "hpi": "<He> reports three days of worsening dyspnea on exertion, orthopnea requiring three pillows, and bilateral leg swelling. <He> ran out of furosemide 40 mg last week.",
        "pmh": ["heart failure with reduced ejection fraction", "hypertension", "type 2 diabetes mellitus", "chronic kidney disease stage 3"],
        "exam": "JVP elevated to the angle of the jaw. Bibasilar crackles. 2+ pitting edema to the knees.",
        "labs": "BNP 1840 pg/mL, creatinine 1.6 mg/dL, sodium 133, potassium 3.8.",
        "imaging": "Cardiomegaly with pulmonary vascular congestion and small bilateral pleural effusions.",
        "plan": "IV furosemide 40 mg twice daily, daily weights, strict intake and output, 2 g sodium diet.",
        "progress": "Net negative 1.8 L overnight. Dyspnea improved and <he> slept flat. Creatinine stable.",
        "course": "Diuresed with IV furosemide and transitioned to oral torsemide. Euvolemic at discharge.",
        "meds": ["furosemide 40 mg daily", "metoprolol succinate 50 mg daily", "lisinopril 10 mg daily"],
        "followup": "cardiology",
    },
    {
        "dx": "community-acquired pneumonia",
        "cc": "cough and fever",
        "hpi": "<He> reports five days of productive cough, fevers to 101.8 F, and pleuritic chest pain on the right.",
        "pmh": ["asthma", "hypertension", "former tobacco use"],
        "exam": "Crackles and egophony at the right base. No accessory muscle use.",
        "labs": "WBC 14.2, procalcitonin 1.9, lactate 1.4.",
        "imaging": "Right lower lobe airspace opacity consistent with pneumonia. No effusion.",
        "plan": "Ceftriaxone 1 g daily and azithromycin 500 mg daily, supplemental oxygen to keep saturation above 92%.",
        "progress": "Afebrile for 24 hours. Oxygen weaned to room air. Tolerating oral intake.",
        "course": "Treated with ceftriaxone and azithromycin, then transitioned to oral amoxicillin-clavulanate to complete seven days.",
        "meds": ["amoxicillin-clavulanate 875/125 mg twice daily", "albuterol inhaler as needed"],
        "followup": "primary care",
    },
    {
        "dx": "cellulitis of the lower extremity",
        "cc": "red, painful left leg",
        "hpi": "<He> noticed redness and warmth of the left shin four days ago after a scrape while gardening. Redness has spread despite oral cephalexin.",
        "pmh": ["type 2 diabetes mellitus", "obesity", "venous insufficiency"],
        "exam": "Erythema 14 x 9 cm over the left anterior shin, warm and tender, no fluctuance. Pedal pulses intact.",
        "labs": "WBC 12.1, CRP 88, glucose 212.",
        "imaging": "Soft tissue swelling of the left lower leg. No subcutaneous gas or abscess.",
        "plan": "IV vancomycin dosed by pharmacy, leg elevation, margin marked, glucose monitoring.",
        "progress": "Margins of erythema receding. Pain improved. Afebrile.",
        "course": "Improved on IV vancomycin and was transitioned to oral doxycycline 100 mg twice daily.",
        "meds": ["doxycycline 100 mg twice daily", "metformin 1000 mg twice daily"],
        "followup": "primary care",
    },
    {
        "dx": "diabetic ketoacidosis",
        "cc": "nausea, vomiting, and abdominal pain",
        "hpi": "<He> has had two days of vomiting and polyuria after missing insulin doses during a stomach illness.",
        "pmh": ["type 1 diabetes mellitus", "hypothyroidism", "Hashimoto thyroiditis"],
        "exam": "Dry mucous membranes, tachycardic, diffuse mild abdominal tenderness without guarding.",
        "labs": "Glucose 486, bicarbonate 11, anion gap 24, pH 7.12, beta-hydroxybutyrate 6.8.",
        "imaging": "No acute abnormality.",
        "plan": "Insulin infusion per protocol, aggressive IV fluids, potassium replacement, hourly glucose checks.",
        "progress": "Anion gap closed overnight. Transitioned to subcutaneous insulin and eating.",
        "course": "DKA resolved with insulin infusion and fluids. Diabetes educator reviewed sick-day rules.",
        "meds": ["insulin glargine 24 units nightly", "insulin lispro 5/1 sliding scale", "levothyroxine 100 mcg daily"],
        "followup": "endocrinology",
    },
    {
        "dx": "COPD exacerbation",
        "cc": "worsening breathlessness",
        "hpi": "<He> has had increased sputum and wheezing for one week, using the rescue inhaler every two hours.",
        "pmh": ["COPD on home oxygen 2 L", "hypertension", "osteoporosis", "Barrett esophagus"],
        "exam": "Diffuse expiratory wheezes, prolonged expiratory phase, speaking in short sentences.",
        "labs": "Venous pH 7.34, pCO2 54, WBC 11.0.",
        "imaging": "Hyperinflation without focal consolidation.",
        "plan": "Prednisone 40 mg daily for five days, scheduled ipratropium-albuterol nebulizers, BiPAP if worsening.",
        "progress": "Wheezing improved. Sleeping without BiPAP. Ambulating in hallway on 2 L oxygen.",
        "course": "Improved with steroids and bronchodilators and returned to baseline oxygen.",
        "meds": ["prednisone 40 mg daily for 3 more days", "tiotropium 18 mcg daily", "albuterol inhaler as needed"],
        "followup": "pulmonology",
    },
    {
        "dx": "acute appendicitis status post laparoscopic appendectomy",
        "cc": "right lower quadrant pain",
        "hpi": "<He> presented with 18 hours of periumbilical pain that migrated to the right lower quadrant with nausea and anorexia.",
        "pmh": ["no significant past medical history", "Meniere disease"],
        "exam": "Tenderness at McBurney point with rebound. Temperature 100.9 F.",
        "labs": "WBC 15.8, lipase normal, urinalysis negative.",
        "imaging": "CT shows a dilated appendix to 11 mm with periappendiceal fat stranding.",
        "plan": "Laparoscopic appendectomy, perioperative antibiotics, early ambulation.",
        "progress": "Postoperative day 1. Pain controlled with oral analgesics. Tolerating a regular diet and ambulating.",
        "course": "Uncomplicated laparoscopic appendectomy. Pathology showed acute appendicitis without perforation.",
        "meds": ["oxycodone-acetaminophen 5/325 mg every 6 hours as needed", "ibuprofen 600 mg every 8 hours"],
        "followup": "general surgery",
    },
    {
        "dx": "acute pyelonephritis",
        "cc": "fever, flank pain, and dysuria",
        "hpi": "<He> reports three days of burning with urination, then fever and right flank pain with shaking chills.",
        "pmh": ["recurrent urinary tract infections", "nephrolithiasis", "Raynaud phenomenon"],
        "exam": "Right costovertebral angle tenderness, temperature 102.3 F, heart rate 108.",
        "labs": "WBC 16.4, creatinine 1.1, urinalysis with pyuria and bacteria, lactate 1.8.",
        "imaging": "Right renal enlargement with perinephric stranding. No obstructing stone.",
        "plan": "IV ceftriaxone, IV fluids, urine and blood cultures, antiemetics as needed.",
        "progress": "Afebrile for 36 hours. Urine culture growing E. coli sensitive to ciprofloxacin.",
        "course": "Defervesced on ceftriaxone and was switched to ciprofloxacin 500 mg twice daily to complete 10 days.",
        "meds": ["ciprofloxacin 500 mg twice daily for 7 more days"],
        "followup": "primary care",
    },
    {
        "dx": "atrial fibrillation with rapid ventricular response",
        "cc": "palpitations and lightheadedness",
        "hpi": "<He> woke with a racing heartbeat and lightheadedness. Symptoms persisted for several hours before <he> came in.",
        "pmh": ["hypertension", "hyperlipidemia", "obstructive sleep apnea", "Graves disease"],
        "exam": "Irregularly irregular rhythm at 148 beats per minute. Lungs clear.",
        "labs": "TSH 0.9, troponin negative twice, potassium 4.1, magnesium 1.9.",
        "imaging": "Chest radiograph without acute findings.",
        "plan": "Diltiazem for rate control, start apixaban 5 mg twice daily, telemetry, echocardiogram.",
        "progress": "Heart rate 82 to 96 on oral diltiazem. Echocardiogram ordered. Anticoagulation education given.",
        "course": "Rate controlled with diltiazem. Started apixaban after CHA2DS2-VASc scoring.",
        "meds": ["apixaban 5 mg twice daily", "diltiazem ER 180 mg daily", "atorvastatin 40 mg nightly"],
        "followup": "cardiology",
    },
]

# Lookalike strings. None of these is an identifier.
CODES = ["I50.23", "J18.9", "L03.116", "E10.10", "J44.1", "K35.80", "N10", "I48.91"]
NOTE_TYPES = ("history_and_physical", "progress_note", "discharge_summary")

PHONE_REASONS = [
    "asked whether the swelling is expected to persist and was told to keep the leg elevated",
    "reported that <he> is taking medications as prescribed with no side effects",
    "wanted to reschedule the follow-up visit and was offered the next available slot",
    "had questions about the discharge instructions, which were reviewed by phone",
    "reported mild improvement in symptoms and denied fever, chest pain, or new shortness of breath",
]


def pronouns(sex):
    he, his, him = ("she", "her", "her") if sex == "F" else ("he", "his", "him")
    return {
        "he": he, "He": he.capitalize(), "his": his, "His": his.capitalize(), "him": him,
        "sexword": "woman" if sex == "F" else "man",
    }


def vitals(rng):
    return (
        f"BP {rng.randint(98, 168)}/{rng.randint(55, 98)}, HR {rng.randint(58, 124)}, "
        f"RR {rng.randint(12, 26)}, Temp {rng.randint(973, 1021) / 10:.1f} F, "
        f"SpO2 {rng.randint(88, 100)}%"
    )
