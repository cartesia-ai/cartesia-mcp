import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict):
    file_path: str


