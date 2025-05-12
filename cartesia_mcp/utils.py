import os
import datetime
from pathlib import Path
from cartesia_mcp.custom_types import ToolType
from cartesia.voice_changer.types import OutputFormatContainer

def create_output_file(output_directory: str, tool_type: ToolType,
                       extension: OutputFormatContainer) -> Path:
    dir_path = Path(output_directory)

    dir_path.mkdir(parents=True, exist_ok=True)

    if not os.access(dir_path, os.W_OK):
        raise Exception(
            f"Output directory {dir_path} is not writable")

    return dir_path / f"{tool_type}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"
