import base64
from dataclasses import dataclass

import requests


DEFAULT_PROMPT = (
    "Ban la tro ly ho tro nguoi khiem thi. "
    "Hay mo ta bang tieng Viet nhung vat the dang co trong anh. "
    "Neu co chu trong anh, hay doc lai phan quan trong. "
    "Neu thay nguy co can luu y thi noi ro ngan gon."
)


class VisionServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class VisionService:
    api_key: str
    model: str = "gemini-2.5-flash"
    timeout_seconds: int = 45

    def analyze_image(self, image_bytes: bytes, mime_type: str, prompt: str | None = None) -> str:
        if not self.api_key:
            raise VisionServiceError("Chua cau hinh GEMINI_API_KEY nen khong the phan tich anh.")

        if not image_bytes:
            raise VisionServiceError("Khong nhan duoc du lieu anh.")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": (prompt or DEFAULT_PROMPT).strip()},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
        }

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )

        if not response.ok:
            message = self._extract_error_message(response)
            raise VisionServiceError(message)

        data = response.json()
        text = self._extract_text(data)
        if not text:
            raise VisionServiceError("Gemini khong tra ve noi dung mo ta tu anh nay.")
        return text

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"Gemini tra ve loi HTTP {response.status_code}."

        error = payload.get("error") or {}
        return error.get("message") or f"Gemini tra ve loi HTTP {response.status_code}."

    @staticmethod
    def _extract_text(payload: dict) -> str:
        chunks: list[str] = []
        for candidate in payload.get("candidates", []):
            content = candidate.get("content") or {}
            for part in content.get("parts", []):
                text = part.get("text")
                if text:
                    chunks.append(text.strip())
        return "\n\n".join(chunk for chunk in chunks if chunk)
