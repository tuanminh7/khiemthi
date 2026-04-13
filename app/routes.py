import base64
import binascii
import re
import shutil
from functools import wraps
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .services.audio_jobs import queue_audio_generation
from .services.book_store import BookStore, BookValidationError
from .services.user_store import UserStore, UserValidationError
from .services.vision_service import VisionService, VisionServiceError


main_bp = Blueprint("main", __name__)
DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>.+)$")
ALLOWED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def get_store() -> BookStore:
    return BookStore(current_app.config["DATA_FILE"])


def get_user_store() -> UserStore:
    return UserStore(current_app.config["USERS_FILE"])


def get_vision_service() -> VisionService:
    return VisionService(
        api_key=current_app.config["GEMINI_API_KEY"],
        model=current_app.config["GEMINI_MODEL"],
    )


def get_current_user() -> dict | None:
    return session.get("auth_user")


def is_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("role") == "admin")


def get_admin_user_record() -> dict:
    return {
        "id": "admin",
        "username": current_app.config["ADMIN_USERNAME"].strip().lower(),
        "display_name": current_app.config["ADMIN_DISPLAY_NAME"],
        "role": "admin",
    }


def is_safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def redirect_to_next(default_endpoint: str, **values):
    next_target = request.values.get("next") or request.args.get("next")
    if is_safe_next_url(next_target):
        return redirect(next_target)
    return redirect(url_for(default_endpoint, **values))


def active_audio_exists(books: list[dict]) -> bool:
    return any(book.get("audio_status") in {"queued", "processing"} for book in books)


@main_bp.app_context_processor
def inject_auth_state():
    user = get_current_user()
    return {
        "current_user": user,
        "is_admin": is_admin_user(user),
    }


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if is_admin_user(user):
            return view_func(*args, **kwargs)

        if user:
            flash("Tai khoan hien tai khong co quyen quan tri. Hay dang nhap bang tai khoan admin.", "error")
        else:
            flash("Vui long dang nhap tai khoan admin de vao khu vuc quan tri.", "error")
        return redirect(url_for("main.login", next=request.path))

    return wrapped


def decode_image_data_url(data_url: str) -> tuple[str, bytes]:
    match = DATA_URL_PATTERN.match(data_url.strip())
    if not match:
        raise VisionServiceError("Anh gui len khong dung dinh dang data URL.")

    mime_type = match.group("mime")
    try:
        image_bytes = base64.b64decode(match.group("data"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VisionServiceError("Khong doc duoc du lieu anh base64.") from exc

    if len(image_bytes) > 10 * 1024 * 1024:
        raise VisionServiceError("Anh qua lon. Hay thu anh nho hon 10 MB.")

    return mime_type, image_bytes


def save_cover_upload(file: FileStorage | None) -> str:
    if not file or not file.filename:
        return ""

    original_name = secure_filename(file.filename)
    suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if suffix not in ALLOWED_COVER_EXTENSIONS:
        raise BookValidationError("Anh bia chi ho tro JPG, PNG, WEBP hoac GIF.")

    filename = f"{uuid4().hex}{suffix}"
    destination = current_app.config["COVER_UPLOAD_DIR"] / filename
    file.save(destination)
    return url_for("static", filename=f"uploads/covers/{filename}")


def is_local_cover_url(cover_url: str) -> bool:
    return cover_url.startswith("/static/uploads/covers/")


def remove_path_within_root(path, root) -> None:
    from pathlib import Path

    root = Path(root).resolve()
    target = Path(path).resolve()
    if target != root and root not in target.parents:
        raise BookValidationError("Duong dan can xoa nam ngoai thu muc du kien.")

    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink(missing_ok=True)


def delete_cover_asset(cover_url: str) -> None:
    if not is_local_cover_url(cover_url):
        return

    filename = cover_url.rsplit("/", 1)[-1]
    remove_path_within_root(
        current_app.config["COVER_UPLOAD_DIR"] / filename,
        current_app.config["COVER_UPLOAD_DIR"],
    )


def delete_audio_assets(book_id: str) -> None:
    audio_root = current_app.config["AUDIO_DIR"]
    remove_path_within_root(audio_root / book_id, audio_root)
    remove_path_within_root(audio_root / f"{book_id}.mp3", audio_root)


def delete_book_assets(book: dict) -> None:
    delete_audio_assets(book["id"])
    delete_cover_asset(book.get("cover_url", ""))


def build_audio_options_from_request() -> dict:
    label = (request.form.get("audio_label") or "").strip()
    start_raw = (request.form.get("audio_start_page") or "").strip()
    end_raw = (request.form.get("audio_end_page") or "").strip()

    if not start_raw and not end_raw:
        return {"scope": {"mode": "full", "label": label or "Toan bo sach"}, "label": label}

    if not start_raw or not end_raw:
        raise BookValidationError("Hay nhap ca trang bat dau va trang ket thuc.")

    try:
        start_page = int(start_raw)
        end_page = int(end_raw)
    except ValueError as exc:
        raise BookValidationError("Trang bat dau va trang ket thuc phai la so.") from exc

    if start_page < 1 or end_page < start_page:
        raise BookValidationError("Khoang trang khong hop le.")

    return {
        "label": label,
        "page_range": {
            "start_page": start_page,
            "end_page": end_page,
        },
        "scope": {
            "mode": "pages",
            "label": label or f"Trang {start_page}-{end_page}",
            "start_page": start_page,
            "end_page": end_page,
        },
    }


@main_bp.route("/")
def index():
    books = get_store().list_books()
    return render_template(
        "index.html",
        books=books,
        vision_ready=bool(current_app.config["GEMINI_API_KEY"]),
        has_active_audio=active_audio_exists(books),
    )


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        admin_username = current_app.config["ADMIN_USERNAME"].strip().lower()
        if username.lower() == admin_username and password == current_app.config["ADMIN_PASSWORD"]:
            session["auth_user"] = get_admin_user_record()
            flash("Dang nhap admin thanh cong.", "success")
            return redirect_to_next("main.admin_books")

        user = get_user_store().authenticate(username, password)
        if not user:
            flash("Sai ten dang nhap hoac mat khau.", "error")
        else:
            session["auth_user"] = user
            flash("Dang nhap thanh cong.", "success")
            return redirect_to_next("main.index")

    return render_template("login.html", next_target=request.args.get("next", ""))


@main_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "")
        display_name = request.form.get("display_name", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if password != confirm_password:
            flash("Mat khau nhap lai khong khop.", "error")
        else:
            try:
                user = get_user_store().add_user(username=username, password=password, display_name=display_name)
            except UserValidationError as exc:
                flash(str(exc), "error")
            else:
                session["auth_user"] = user
                flash("Tao tai khoan thanh cong. Ban da dang nhap.", "success")
                return redirect(url_for("main.index"))

    return render_template("register.html")


@main_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("auth_user", None)
    flash("Ban da dang xuat.", "success")
    return redirect_to_next("main.index")


@main_bp.route("/healthz")
def healthz():
    return {"status": "ok"}


@main_bp.route("/camera")
def camera():
    return render_template(
        "camera.html",
        vision_ready=bool(current_app.config["GEMINI_API_KEY"]),
        vision_model=current_app.config["GEMINI_MODEL"],
    )


@main_bp.route("/api/vision/analyze", methods=["POST"])
def analyze_camera():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image", "")
    prompt = payload.get("prompt", "")

    if not image_data:
        return jsonify({"ok": False, "error": "Ban can chup anh truoc khi phan tich."}), 400

    try:
        mime_type, image_bytes = decode_image_data_url(image_data)
        analysis = get_vision_service().analyze_image(image_bytes, mime_type, prompt=prompt)
    except VisionServiceError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException:
        return jsonify({"ok": False, "error": "Khong ket noi duoc Gemini. Hay thu lai sau."}), 502

    return jsonify({"ok": True, "analysis": analysis})


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
@admin_required
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
            uploaded_cover_url = save_cover_upload(request.files.get("cover_file"))
            if uploaded_cover_url:
                form_data["cover_url"] = uploaded_cover_url
            book = store.add_book(form_data)
        except BookValidationError as exc:
            flash(str(exc), "error")
        else:
            if current_app.config["AUTO_GENERATE_AUDIO_ON_ADD"]:
                store.update_book(
                    book["id"],
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
                    book["id"],
                    current_app.config["AUDIO_PUBLIC_URL"],
                )
                flash("Them sach thanh cong. He thong dang tu tao audio trong nen.", "success")
            else:
                flash("Them sach thanh cong. Audio se chi duoc tao khi ban bam nut Tao Audio.", "success")
            return redirect(url_for("main.admin_books"))

    books = store.list_books()
    return render_template(
        "admin_books.html",
        books=books,
        editing_book=None,
        form_action=url_for("main.admin_books"),
        has_active_audio=active_audio_exists(books),
    )


@main_bp.route("/admin/books/<book_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_book(book_id: str):
    store = get_store()
    book = store.get_book(book_id)
    if not book:
        flash("Khong tim thay cuon sach can sua.", "error")
        return redirect(url_for("main.admin_books"))

    if request.method == "POST":
        previous_source = book.get("source_url", "")
        previous_source_type = book.get("source_type", "")
        previous_language = book.get("language", "")
        form_data = {
            "title": request.form.get("title", ""),
            "author": request.form.get("author", ""),
            "description": request.form.get("description", ""),
            "category": request.form.get("category", ""),
            "drive_url": request.form.get("drive_url", ""),
            "source_type": request.form.get("source_type", ""),
            "language": request.form.get("language", ""),
        }

        old_cover_url = book.get("cover_url", "")
        try:
            uploaded_cover_url = save_cover_upload(request.files.get("cover_file"))
            if uploaded_cover_url:
                form_data["cover_url"] = uploaded_cover_url
            updated_book = store.update_book_details(book_id, form_data)
        except BookValidationError as exc:
            flash(str(exc), "error")
        else:
            if uploaded_cover_url and old_cover_url != uploaded_cover_url and is_local_cover_url(old_cover_url):
                try:
                    delete_cover_asset(old_cover_url)
                except BookValidationError:
                    pass

            if (
                form_data.get("drive_url", "").strip() != previous_source
                or form_data.get("source_type", "").strip().lower() != previous_source_type
                or form_data.get("language", "").strip().lower() != previous_language
            ):
                try:
                    delete_audio_assets(book_id)
                except BookValidationError:
                    pass

            if updated_book.get("audio_status") == "not_generated":
                flash("Da cap nhat sach. Vi ban da doi nguon hoac ngon ngu, hay bam Tao Audio lai neu can.", "success")
            else:
                flash("Da cap nhat thong tin sach.", "success")
            return redirect(url_for("main.admin_books"))

        books = store.list_books()
        return render_template(
            "admin_books.html",
            books=books,
            editing_book={
                **book,
                **form_data,
                "source_url": form_data.get("drive_url", book.get("source_url", "")),
                "cover_url": form_data.get("cover_url", book.get("cover_url", "")),
            },
            form_action=url_for("main.edit_book", book_id=book_id),
            has_active_audio=active_audio_exists(books),
        )

    books = store.list_books()
    return render_template(
        "admin_books.html",
        books=books,
        editing_book=book,
        form_action=url_for("main.edit_book", book_id=book_id),
        has_active_audio=active_audio_exists(books),
    )


@main_bp.route("/admin/books/<book_id>/delete", methods=["POST"])
@admin_required
def delete_book(book_id: str):
    store = get_store()
    try:
        deleted_book = store.delete_book(book_id)
        delete_book_assets(deleted_book)
    except BookValidationError as exc:
        flash(str(exc), "error")
    else:
        flash(f"Da xoa sach '{deleted_book.get('title', '')}'.", "success")

    return redirect(url_for("main.admin_books"))


@main_bp.route("/books/<book_id>/generate-audio", methods=["POST"])
@admin_required
def generate_audio(book_id: str):
    store = get_store()
    book = store.get_book(book_id)
    if not book:
        flash("Khong tim thay cuon sach de tao audio.", "error")
        return redirect(url_for("main.index"))

    try:
        audio_options = build_audio_options_from_request()
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
                "audio_scope": audio_options["scope"],
            },
        )
        queue_audio_generation(
            current_app.config["DATA_FILE"],
            current_app.config["AUDIO_DIR"],
            book_id,
            current_app.config["AUDIO_PUBLIC_URL"],
            audio_options=audio_options,
        )
    except BookValidationError as exc:
        flash(str(exc), "error")
    else:
        if audio_options["scope"].get("mode") == "pages":
            flash("Da dua khoang trang da chon vao hang doi tao audio.", "success")
        else:
            flash("Da dua sach vao hang doi tao audio.", "success")

    redirect_target = request.form.get("next") or url_for("main.book_detail", book_id=book_id)
    return redirect(redirect_target)
