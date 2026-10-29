"""Which engine does the work: offline rules, or hosted models.

A Backend bundles the chat client for detection, the optional speech and vision
clients, and what the engine can do. Nothing here makes a network call when it is
built: hosted clients are created only when the app is started with --live, and
every job then needs a confirmation that its content is synthetic.
"""

from dataclasses import dataclass, field
from typing import Callable

from deid.detect.client import ChatClient, LargerLimitRetry

from .offline import OfflineModel


@dataclass
class Backend:
    name: str                       # "offline", "meta", "custom" (or "scripted" in tests)
    label: str                      # shown on the page
    hosted: bool                    # True when note text leaves this computer
    chat: Callable                  # () -> a chat client (complete(messages))
    speech: Callable | None = None  # () -> a SpeechClient, or None when audio cannot be read
    verify: bool = True             # run the verifier on uncertain spans
    redteam: bool = True            # run the re-identification reviewer
    model_help: bool = False        # can propose column types and read images
    reads_images: bool = False
    notes: list = field(default_factory=list)  # limits to show a person

    @property
    def kinds(self):
        out = ["note", "table"]
        if self.speech:
            out.append("audio")
        if self.reads_images:
            out.append("scan")
        return out

    def describe(self):
        return {"name": self.name, "label": self.label, "hosted": self.hosted, "kinds": self.kinds,
                "verify": self.verify, "redteam": self.redteam, "model_help": self.model_help, "notes": self.notes}


def offline_backend():
    return Backend(
        "offline", "Offline rules (no AI model)", False, OfflineModel, verify=False, redteam=False,
        notes=["Patterns and name cues only: it misses names that have no cue (such as Dr. or Patient:).",
               "No verifier and no re-identification reviewer runs, so risk is shown as not assessed.",
               "Audio and scanned pages need the hosted models (start the app with --live)."])


def live_backend(provider="meta", max_output_tokens=4096, retry_output_tokens=16384):
    """Hosted models: text, and any audio or images, are sent to the provider."""
    from deid.ingest.audio import SpeechClient

    def chat():
        return LargerLimitRetry(ChatClient.from_env(provider, max_output_tokens), retry_output_tokens)

    notes = ["Everything you add is sent to a hosted service. Use synthetic or public data only."]
    speech = SpeechClient.from_env if provider == "meta" else None
    if provider != "meta":
        notes.append("Audio is transcribed only with the Meta Model API; scans use the same chat model.")
    return Backend(provider, f"Hosted model ({provider})", True, chat, speech, True, True, True, provider == "meta", notes)
