import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .drive_service import DriveLinkError, build_drive_urls, extract_drive_file_id


class BookValidationError(ValueError):
    pass


@dataclass
class BookStore:
    data_file: Path
    _lock = Lock()

    def __post_init__(self) -> None:
        self.data_file = Path(self.data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            self.data_file.write_text("[]", encoding="utf-8")

    def list_books(self) -> list[dict]:
        books = [self._normalize_book(book) for book in self._load_books()]
        return sorted(books, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_book(self, book_id: str) -> dict | None:
        for book in self._load_books():
            if book.get("id") == book_id:
                return self._normalize_book(book)
        return None

    def add_book(self, payload: dict) -> dict:
        details = self._validate_book_details(payload)
        slug = self._slugify(details["title"])
        book = {
            "id": f"{slug}-{uuid4().hex[:8]}",
            **details,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "audio_status": "not_generated",
            "audio_url": "",
            "audio_error": "",
            "audio_progress": 0,
            "audio_parts": [],
            "audio_completed_parts": 0,
            "audio_total_parts": 0,
            "audio_estimated_minutes": 0,
        }

        with self._lock:
            books = self._load_books_unlocked()
            books.append(book)
            self._save_books_unlocked(books)
        return book

    def update_book_details(self, book_id: str, payload: dict) -> dict:
        with self._lock:
            books = self._load_books_unlocked()
            for index, book in enumerate(books):
                if book.get("id") != book_id:
                    continue

                details = self._validate_book_details(payload, existing=book)
                source_changed = any(
                    details.get(key) != book.get(key)
                    for key in ("source_url", "drive_file_id", "source_type", "language")
                )
                updates = details
                if source_changed:
                    updates = {
                        **updates,
                        "audio_status": "not_generated",
                        "audio_url": "",
                        "audio_error": "",
                        "audio_progress": 0,
                        "audio_parts": [],
                        "audio_completed_parts": 0,
                        "audio_total_parts": 0,
                        "audio_estimated_minutes": 0,
                        "audio_filename": "",
                    }

                merged_book = {**book, **updates}
                books[index] = merged_book
                self._save_books_unlocked(books)
                return self._normalize_book(merged_book)

        raise BookValidationError("Khong tim thay cuon sach can cap nhat.")

    def update_book(self, book_id: str, updates: dict) -> dict:
        with self._lock:
            books = self._load_books_unlocked()
            for index, book in enumerate(books):
                if book.get("id") != book_id:
                    continue

                merged_book = {**book, **updates}
                books[index] = merged_book
                self._save_books_unlocked(books)
                return self._normalize_book(merged_book)

        raise BookValidationError("Khong tim thay cuon sach can cap nhat.")

    def delete_book(self, book_id: str) -> dict:
        with self._lock:
            books = self._load_books_unlocked()
            for index, book in enumerate(books):
                if book.get("id") != book_id:
                    continue

                deleted_book = books.pop(index)
                self._save_books_unlocked(books)
                return self._normalize_book(deleted_book)

        raise BookValidationError("Khong tim thay cuon sach can xoa.")

    def _load_books(self) -> list[dict]:
        with self._lock:
            return self._load_books_unlocked()

    def _load_books_unlocked(self) -> list[dict]:
        try:
            content = self.data_file.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise BookValidationError("Khong doc duoc du lieu sach hien tai.") from exc

        if not isinstance(data, list):
            raise BookValidationError("File du lieu sach khong dung dinh dang.")
        return data

    def _save_books_unlocked(self, books: list[dict]) -> None:
        self.data_file.write_text(
            json.dumps(books, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_book(book: dict) -> dict:
        normalized = {
            "audio_status": "not_generated",
            "audio_url": "",
            "audio_error": "",
            "audio_progress": 0,
            "audio_parts": [],
            "audio_completed_parts": 0,
            "audio_total_parts": 0,
            "audio_estimated_minutes": 0,
            "audio_scope": {"mode": "full", "label": "Toan bo sach"},
            **book,
        }

        source_url = normalized.get("source_url", "")
        if source_url:
            try:
                file_id = normalized.get("drive_file_id") or extract_drive_file_id(source_url)
                normalized.update(build_drive_urls(file_id, source_url))
            except DriveLinkError:
                pass

        return normalized

    @staticmethod
    def _validate_book_details(payload: dict, existing: dict | None = None) -> dict:
        existing = existing or {}
        title = (payload.get("title") or "").strip()
        author = (payload.get("author") or "").strip()
        description = (payload.get("description") or "").strip()
        category = (payload.get("category") or "").strip()
        cover_url = (payload.get("cover_url") or "").strip() or existing.get("cover_url", "")
        drive_url = (payload.get("drive_url") or "").strip() or existing.get("source_url", "")
        source_type = (payload.get("source_type") or existing.get("source_type") or "auto").strip().lower()
        language = (payload.get("language") or existing.get("language") or "vi").strip().lower()

        if not title:
            raise BookValidationError("Tieu de sach la bat buoc.")
        if not drive_url:
            raise BookValidationError("Ban can nhap link Google Drive cho sach.")

        try:
            file_id = extract_drive_file_id(drive_url)
        except DriveLinkError as exc:
            raise BookValidationError(str(exc)) from exc

        return {
            "title": title,
            "author": author or "Dang cap nhat",
            "description": description or "Chua co mo ta cho cuon sach nay.",
            "category": category or "Chua phan loai",
            "cover_url": cover_url or "https://placehold.co/640x900?text=Sach+Noi",
            "source_type": source_type,
            "language": language,
            "source_url": drive_url,
            **build_drive_urls(file_id, drive_url),
        }

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower().strip()
        normalized = re.sub(r"[^a-z0-9\s-]", "", normalized)
        normalized = re.sub(r"[\s_-]+", "-", normalized)
        normalized = re.sub(r"^-+|-+$", "", normalized)
        return normalized or "book"
