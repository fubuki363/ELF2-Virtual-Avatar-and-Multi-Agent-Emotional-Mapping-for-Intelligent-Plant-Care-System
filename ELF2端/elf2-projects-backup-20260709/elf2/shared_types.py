from dataclasses import dataclass

@dataclass
class VoiceEvent:
    text: str
    timestamp: float

@dataclass
class CommandEvent:
    commands: list[dict]
    source: str  # "voice"
