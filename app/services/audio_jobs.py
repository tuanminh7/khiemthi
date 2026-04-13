from __future__ import annotations

from pathlib import Path
from threading import Thread

from .audio_service import AudioGenerationError, AudioService
from .book_store import BookStore, BookValidationError


def queue_audio_generation(
    data_file: Path,
    audio_dir: Path,
    book_id: str,
    audio_public_url: str = "/media/audio",
    audio_options: dict | None = None,
) -> None:
    worker = Thread(
        target=_run_audio_generation,
        args=(Path(data_file), Path(audio_dir), book_id, audio_public_url.rstrip("/"), audio_options or {}),
        daemon=True,
    )
    worker.start()


def _run_audio_generation(
    data_file: Path,
    audio_dir: Path,
    book_id: str,
    audio_public_url: str,
    audio_options: dict | None = None,
) -> None:
    store = BookStore(data_file)
    audio_options = audio_options or {}
    audio_scope = audio_options.get("scope", {"mode": "full", "label": "Toan bo sach"})
    try:
        store.update_book(
            book_id,
            {
                "audio_status": "processing",
                "audio_error": "",
                "audio_progress": 0,
                "audio_completed_parts": 0,
                "audio_total_parts": 0,
                "audio_parts": [],
                "audio_scope": audio_scope,
            },
        )
        book = store.get_book(book_id)
        if not book:
            return

        def report_progress(progress_meta: dict) -> None:
            store.update_book(book_id, progress_meta)

        audio_meta = AudioService(audio_dir, audio_public_url).generate_for_book(
            book,
            progress_callback=report_progress,
            options=audio_options,
        )
        store.update_book(book_id, audio_meta)
    except (AudioGenerationError, BookValidationError) as exc:
        try:
            store.update_book(
                book_id,
                {
                    "audio_status": "error",
                    "audio_error": str(exc),
                    "audio_progress": 0,
                },
            )
        except BookValidationError:
            pass
