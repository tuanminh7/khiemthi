from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

from .drive_service import is_google_document_url


class AudioGenerationError(ValueError):
    pass


class AudioService:
    DEFAULT_CHUNK_SIZE = 3500

    def __init__(self, output_dir: Path, public_base_url: str = "/media/audio") -> None:
        self.output_dir = Path(output_dir)
        self.public_base_url = public_base_url.rstrip("/")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_for_book(self, book: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
        text_content = self._extract_text(book)
        normalized_text = self._normalize_text(text_content)
        if len(normalized_text) < 40:
            raise AudioGenerationError("Noi dung trich xuat qua ngan de tao audio co y nghia.")

        chunks = self._chunk_text(normalized_text, self.DEFAULT_CHUNK_SIZE)
        total_parts = len(chunks)
        book_audio_dir = self.output_dir / book["id"]
        if book_audio_dir.exists():
            shutil.rmtree(book_audio_dir)
        book_audio_dir.mkdir(parents=True, exist_ok=True)

        initial_meta = {
            "audio_status": "processing",
            "audio_error": "",
            "audio_progress": 0,
            "audio_parts": [],
            "audio_completed_parts": 0,
            "audio_total_parts": total_parts,
            "audio_estimated_minutes": self._estimate_minutes(normalized_text),
            "audio_url": "",
            "audio_filename": "",
        }
        if progress_callback:
            progress_callback(initial_meta)

        try:
            tts_class = self._get_tts_class()
        except Exception as exc:
            raise AudioGenerationError(
                "Chua cai dat gTTS. Hay chay 'pip install -r requirements.txt'."
            ) from exc

        language = self._map_language(book.get("language", "vi"))
        audio_parts = []
        for index, chunk in enumerate(chunks, start=1):
            output_name = f"part-{index:03d}.mp3"
            output_path = book_audio_dir / output_name
            public_url = f"{self.public_base_url}/{book['id']}/{output_name}"

            try:
                tts = tts_class(text=chunk, lang=language)
                tts.save(str(output_path))
            except Exception as exc:
                raise AudioGenerationError(
                    f"Khong tao duoc audio phan {index}/{total_parts}. Kiem tra mang Internet va gTTS."
                ) from exc

            audio_parts.append(
                {
                    "index": index,
                    "title": f"Phan {index}",
                    "filename": output_name,
                    "url": public_url,
                    "characters": len(chunk),
                }
            )

            if progress_callback:
                progress_callback(
                    {
                        "audio_status": "processing",
                        "audio_error": "",
                        "audio_progress": round(index / total_parts * 100),
                        "audio_parts": audio_parts,
                        "audio_completed_parts": index,
                        "audio_total_parts": total_parts,
                        "audio_url": audio_parts[0]["url"],
                    }
                )

        return {
            "audio_status": "ready",
            "audio_error": "",
            "audio_generated_at": datetime.now(timezone.utc).isoformat(),
            "audio_progress": 100,
            "audio_parts": audio_parts,
            "audio_completed_parts": total_parts,
            "audio_total_parts": total_parts,
            "audio_estimated_minutes": self._estimate_minutes(normalized_text),
            "audio_filename": audio_parts[0]["filename"] if audio_parts else "",
            "audio_url": audio_parts[0]["url"] if audio_parts else "",
        }

    def _extract_text(self, book: dict) -> str:
        source_type = (book.get("source_type") or "pdf").lower()
        file_bytes = self._download_source(book)

        if book.get("source_kind") == "google_doc" or is_google_document_url(book.get("source_url", "")):
            return self._extract_txt(file_bytes)

        for extractor in self._build_extractors(source_type, file_bytes):
            try:
                extracted = extractor(file_bytes).strip()
            except AudioGenerationError:
                continue
            if extracted:
                return extracted

        raise AudioGenerationError(
            "Khong trich duoc noi dung tu tai lieu nay. Hien app uu tien Google Docs, PDF, DOCX va TXT."
        )

    def _download_source(self, book: dict) -> bytes:
        download_url = book.get("drive_download_url")
        if book.get("source_kind") == "google_doc" or is_google_document_url(book.get("source_url", "")):
            download_url = f"https://docs.google.com/document/d/{book.get('drive_file_id')}/export?format=txt"

        if not download_url:
            raise AudioGenerationError("Sach nay chua co link tai xuong hop le.")

        try:
            import requests
        except ImportError as exc:
            raise AudioGenerationError(
                "Chua cai dat requests. Hay chay 'pip install -r requirements.txt'."
            ) from exc

        try:
            response = requests.get(
                download_url,
                timeout=60,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
        except Exception as exc:
            raise AudioGenerationError(
                "Khong tai duoc file tu Google Drive. Kiem tra lai link share cong khai."
            ) from exc

        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type.lower() and urlparse(response.url).netloc in {
            "drive.google.com",
            "docs.google.com",
        }:
            raise AudioGenerationError(
                "Google Drive/Docs dang tra ve trang HTML thay vi file. Kiem tra lai quyen share cong khai cua tai lieu."
            )

        if not response.content:
            raise AudioGenerationError("File tai ve rong, khong the tao audio.")

        return response.content

    @staticmethod
    def _extract_txt(file_bytes: bytes) -> str:
        if file_bytes.startswith(b"%PDF") or AudioService._looks_like_docx(file_bytes):
            raise AudioGenerationError("File nay khong phai TXT thuan.")

        for encoding in ("utf-8-sig", "utf-8", "cp1258"):
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue

        return file_bytes.decode("utf-8", errors="ignore")

    @staticmethod
    def _extract_pdf(file_bytes: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AudioGenerationError(
                "Chua cai dat pypdf. Hay chay 'pip install -r requirements.txt'."
            ) from exc

        try:
            reader = PdfReader(BytesIO(file_bytes))
        except Exception as exc:
            raise AudioGenerationError("Khong mo duoc file PDF de trich text.") from exc

        pages = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted.strip():
                pages.append(extracted)

        text = "\n".join(pages).strip()
        if not text:
            raise AudioGenerationError(
                "PDF nay khong trich duoc text. Co the day la PDF scan, khi do nen dung OCR."
            )
        return text

    @staticmethod
    def _extract_docx(file_bytes: bytes) -> str:
        if not AudioService._looks_like_docx(file_bytes):
            raise AudioGenerationError("Tai lieu nay khong phai DOCX hop le.")

        try:
            from docx import Document
        except ImportError as exc:
            raise AudioGenerationError(
                "Chua cai dat python-docx. Hay chay 'pip install -r requirements.txt'."
            ) from exc

        try:
            document = Document(BytesIO(file_bytes))
        except Exception as exc:
            raise AudioGenerationError("Khong mo duoc file DOCX de trich text.") from exc

        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        text = "\n".join(paragraphs).strip()
        if not text:
            raise AudioGenerationError("DOCX nay khong co noi dung text de doc.")
        return text

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _map_language(language: str) -> str:
        normalized = (language or "vi").strip().lower()
        return "vi" if normalized.startswith("vi") else normalized

    @staticmethod
    def _get_tts_class():
        from gtts import gTTS

        return gTTS

    @staticmethod
    def _chunk_text(text: str, max_chars: int) -> list[str]:
        sentences = re.split(r"(?<=[.!?;:])\s+", text)
        chunks = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > max_chars:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(AudioService._split_long_sentence(sentence, max_chars))
                continue

            candidate = f"{current} {sentence}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())

        return chunks or [text]

    @staticmethod
    def _split_long_sentence(text: str, max_chars: int) -> list[str]:
        words = text.split()
        chunks = []
        current = ""

        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current.strip())
            current = word

        if current:
            chunks.append(current.strip())
        return chunks

    @staticmethod
    def _estimate_minutes(text: str) -> int:
        word_count = len(text.split())
        return max(1, round(word_count / 145))

    @staticmethod
    def _build_extractors(source_type: str, file_bytes: bytes) -> list:
        extractors = {
            "pdf": AudioService._extract_pdf,
            "docx": AudioService._extract_docx,
            "txt": AudioService._extract_txt,
        }

        if source_type == "pdf":
            order = ["pdf", "docx", "txt"]
        elif source_type == "docx":
            order = ["docx", "txt", "pdf"]
        elif source_type == "txt":
            order = ["txt", "docx", "pdf"]
        else:
            order = AudioService._detect_candidates(file_bytes)

        seen = set()
        result = []
        for key in order:
            if key in extractors and key not in seen:
                result.append(extractors[key])
                seen.add(key)
        return result

    @staticmethod
    def _detect_candidates(file_bytes: bytes) -> list[str]:
        if file_bytes.startswith(b"%PDF"):
            return ["pdf", "txt", "docx"]
        if AudioService._looks_like_docx(file_bytes):
            return ["docx", "txt", "pdf"]
        return ["txt", "docx", "pdf"]

    @staticmethod
    def _looks_like_docx(file_bytes: bytes) -> bool:
        try:
            with ZipFile(BytesIO(file_bytes)) as archive:
                return "word/document.xml" in archive.namelist()
        except (BadZipFile, OSError):
            return False
