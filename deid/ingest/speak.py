"""Speak a synthetic script to a WAV file with the voices that ship with Windows.

Runs offline through System.Speech (David and Zira), so no text leaves the
computer to make the test audio. Output is mono 16-bit PCM at 16 kHz, the format
Muse Voice Transcribe takes. Windows only.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($args[2])
$s.Rate = [int]$args[3]
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($args[1], $fmt)
$s.Speak((Get-Content -Raw -Encoding UTF8 $args[0]))
$s.Dispose()
"""


class SpeechUnavailable(RuntimeError):
    pass


def synthesize(text, wav_path, voice="Microsoft Zira Desktop", rate=0):
    if sys.platform != "win32":
        raise SpeechUnavailable("offline speech synthesis here uses Windows System.Speech")
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        txt, ps1 = Path(tmp) / "script.txt", Path(tmp) / "speak.ps1"
        txt.write_text(text, encoding="utf-8")
        ps1.write_text(SCRIPT, encoding="utf-8")
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
             str(txt), str(wav_path.resolve()), voice, str(rate)],
            capture_output=True, text=True, timeout=300)
    if done.returncode != 0 or not wav_path.exists():
        raise SpeechUnavailable(f"speech synthesis failed: {done.stderr.strip()[:300]}")
    return wav_path
