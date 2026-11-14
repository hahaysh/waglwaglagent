import base64
import binascii
from io import BytesIO
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_IMAGE_BYTES = 8 * 1024 * 1024
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".html", ".css", ".yaml", ".yml", ".xml", ".sql", ".sh", ".ps1",
}
IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=120)
    mime_type: str
    data: str = Field(max_length=4 * ((MAX_FILE_BYTES + 2) // 3), repr=False)

    @model_validator(mode="after")
    def valid_file(self):
        if any(ord(char) < 32 or char in "/\\:" for char in self.name):
            raise ValueError("attachment_invalid")
        try:
            raw = base64.b64decode(self.data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("attachment_invalid") from None
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise ValueError("attachment_too_large")
        if self.mime_type in IMAGE_FORMATS:
            try:
                with Image.open(BytesIO(raw)) as image:
                    if (
                        image.format != IMAGE_FORMATS[self.mime_type]
                        or image.width * image.height > 16_000_000
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise ValueError("attachment_invalid")
                    image.load()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise ValueError("attachment_invalid") from None
        elif (
            self.mime_type == "text/plain"
            and PurePath(self.name).suffix.lower() in TEXT_EXTENSIONS
        ):
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ValueError("attachment_invalid") from None
            if len(raw) > 32768 or "\x00" in text:
                raise ValueError("attachment_invalid")
        else:
            raise ValueError("attachment_unsupported")
        return self


def prepare_messages(messages: list[dict]) -> list[dict]:
    prepared = []
    for message in messages:
        content = message["content"]
        images = []
        for attachment in message.get("attachments", []):
            if attachment["mime_type"] == "text/plain":
                text = base64.b64decode(attachment["data"]).decode("utf-8-sig")
                content += f"\n\n[Attached document: {attachment['name']}]\n{text}\n[End document]"
            else:
                images.extend([
                    {"type": "text", "text": f"Attached image: {attachment['name']}"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{attachment['mime_type']};base64,{attachment['data']}",
                    }},
                ])
        prepared.append({
            "role": message["role"],
            "content": [{"type": "text", "text": content}, *images] if images else content,
        })
    return prepared


def context_size(messages: list[dict]) -> tuple[int, int]:
    text_bytes, image_bytes = 0, 0
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            text_bytes += len(content.encode())
        else:
            for part in content:
                if part["type"] == "text":
                    text_bytes += len(part["text"].encode())
                else:
                    image_bytes += len(base64.b64decode(
                        part["image_url"]["url"].split(",", 1)[1],
                    ))
    return text_bytes, image_bytes
