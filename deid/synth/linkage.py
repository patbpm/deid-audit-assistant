"""Invented patients whose notes are harmless one by one and identifying together, plus controls.

    python -m deid.synth.linkage            # prints the bundles as JSON lines

Twelve patients, three already-cleaned notes each (identifiers shown as tags, as the reviewer sees them).
Six are "planted": each note holds one detail that narrows the field a little (a job, a small place, a
public event) and the three together describe one findable person. Six are "controls": ordinary jobs,
places and conditions. Written by this project without looking at any model's answer, and not changed
after a run. Every person is invented; any resemblance is chance.
"""

import json

PLANTED = {
    "teacher": [
        "[NAME] is a 58-year-old woman seen on [DATE] for fatigue. She teaches high school chemistry. Blood pressure is normal.",
        "Follow-up on [DATE]. She was named her state's teacher of the year last spring. Fatigue is improving with iron.",
        "Labs reviewed on [DATE]. She lives in a farming town of about 900 people and drives 40 minutes to clinic.",
    ],
    "pilot": [
        "[NAME] is a 46-year-old man seen on [DATE] for ear pain after a flight. He is a commercial airline pilot.",
        "Visit on [DATE]. He was briefly off duty after an emergency landing last winter that made the evening news.",
        "Recheck on [DATE]. He flies out of a regional airport with two gates and lives ten minutes away.",
    ],
    "athlete": [
        "[NAME] is a 39-year-old man seen on [DATE] for knee pain. He is a former professional soccer goalkeeper.",
        "Visit on [DATE]. He retired after a knee injury in the 2018 season and had surgery that year.",
        "Follow-up on [DATE]. He now coaches the only high school team in his small town.",
    ],
    "council": [
        "[NAME] is a 63-year-old woman seen on [DATE] for hypertension. She serves on the town council.",
        "Visit on [DATE]. She ran unopposed in November and says the campaign was stressful.",
        "Recheck on [DATE]. Her town has about 700 residents and one stoplight.",
    ],
    "chef": [
        "[NAME] is a 51-year-old man seen on [DATE] for burns to the left hand. He owns a restaurant.",
        "Visit on [DATE]. His restaurant was featured on a national cooking show last year.",
        "Recheck on [DATE]. His is the only restaurant in a mountain village of a few hundred people.",
    ],
    "pastor": [
        "[NAME] is a 55-year-old man seen on [DATE] for insomnia. He is the pastor of a small congregation.",
        "Visit on [DATE]. His congregation has about 40 members and meets in a converted barn.",
        "Recheck on [DATE]. The church building burned in a fire last year, which the local paper covered.",
    ],
}
CONTROLS = {
    "bookkeeper": [
        "[NAME] is a 66-year-old woman seen on [DATE] for hypertension. She is a retired bookkeeper.",
        "Visit on [DATE]. She lives with her husband in a suburb and walks daily.",
        "Recheck on [DATE]. Blood pressure is better on lisinopril. She has two grandchildren.",
    ],
    "office": [
        "[NAME] is a 49-year-old man seen on [DATE] for type 2 diabetes. He works in an office.",
        "Visit on [DATE]. He has two grown children and lives in a mid-sized city.",
        "Recheck on [DATE]. A1c is improving with metformin and diet changes.",
    ],
    "cashier": [
        "[NAME] is a 34-year-old woman seen on [DATE] for asthma. She works as a retail cashier.",
        "Visit on [DATE]. She lives in an apartment in a large city and uses a rescue inhaler twice a week.",
        "Recheck on [DATE]. Symptoms are controlled on a daily inhaled steroid.",
    ],
    "driver": [
        "[NAME] is a 52-year-old man seen on [DATE] for low back pain. He drives a truck for a living.",
        "Visit on [DATE]. He lives in a suburb and is married.",
        "Recheck on [DATE]. Pain is better with stretching and naproxen.",
    ],
    "nurse": [
        "[NAME] is a 41-year-old woman seen on [DATE] for migraine. She works as a nurse.",
        "Visit on [DATE]. She lives in a city and has one child.",
        "Recheck on [DATE]. Headache days fell to two a month on a preventive medicine.",
    ],
    "student": [
        "[NAME] is a 20-year-old man seen on [DATE] for seasonal allergies. He is a college student.",
        "Visit on [DATE]. He lives in a dorm at a large university in a big city.",
        "Recheck on [DATE]. Symptoms are controlled with a daily antihistamine.",
    ],
}


def bundles():
    out = []
    for group, label in ((PLANTED, "planted"), (CONTROLS, "control")):
        for name, notes in group.items():
            out.append({"patient": name, "kind": label, "notes": list(notes)})
    return out


def main():
    for b in bundles():
        print(json.dumps(b))


if __name__ == "__main__":
    main()
