from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from .services.audio_jobs import queue_audio_generation
from .services.book_store import BookStore, BookValidationError


main_bp = Blueprint("main", __name__)


def get_store() -> BookStore:
    return BookStore(current_app.config["DATA_FILE"])


@main_bp.route("/")
def index():
    books = get_store().list_books()
    return render_template("index.html", books=books)


@main_bp.route("/healthz")
def healthz():
    return {"status": "ok"}


@main_bp.route("/media/audio/<path:filename>")
def media_audio(filename: str):
    return send_from_directory(current_app.config["AUDIO_DIR"], filename)


@main_bp.route("/books/<book_id>")
def book_detail(book_id: str):
    book = get_store().get_book(book_id)
    if not book:
        flash("Khong tim thay cuon sach ban yeu cau.", "error")
        return redirect(url_for("main.index"))

    return render_template("book_detail.html", book=book)


@main_bp.route("/admin/books", methods=["GET", "POST"])
def admin_books():
    store = get_store()

    if request.method == "POST":
        form_data = {
            "title": request.form.get("title", ""),
            "author": request.form.get("author", ""),
            "description": request.form.get("description", ""),
            "category": request.form.get("category", ""),
            "cover_url": request.form.get("cover_url", ""),
            "drive_url": request.form.get("drive_url", ""),
            "source_type": request.form.get("source_type", ""),
            "language": request.form.get("language", ""),
        }

        try:
            book = store.add_book(form_data)
        except BookValidationError as exc:
            flash(str(exc), "error")
        else:
            queue_audio_generation(
                current_app.config["DATA_FILE"],
                current_app.config["AUDIO_DIR"],
                book["id"],
                current_app.config["AUDIO_PUBLIC_URL"],
            )
            flash("Them sach thanh cong. He thong dang tu tao audio trong nen.", "success")
            return redirect(url_for("main.admin_books"))

    books = store.list_books()
    return render_template("admin_books.html", books=books)


@main_bp.route("/books/<book_id>/generate-audio", methods=["POST"])
def generate_audio(book_id: str):
    store = get_store()
    book = store.get_book(book_id)
    if not book:
        flash("Khong tim thay cuon sach de tao audio.", "error")
        return redirect(url_for("main.index"))

    try:
        store.update_book(
            book_id,
            {
                "audio_status": "queued",
                "audio_error": "",
                "audio_progress": 0,
                "audio_parts": [],
                "audio_completed_parts": 0,
                "audio_total_parts": 0,
                "audio_url": "",
                "audio_filename": "",
            },
        )
        queue_audio_generation(
            current_app.config["DATA_FILE"],
            current_app.config["AUDIO_DIR"],
            book_id,
            current_app.config["AUDIO_PUBLIC_URL"],
        )
    except BookValidationError as exc:
        flash(str(exc), "error")
    else:
        flash("Da dua sach vao hang doi tao audio.", "success")

    redirect_target = request.form.get("next") or url_for("main.book_detail", book_id=book_id)
    return redirect(redirect_target)
