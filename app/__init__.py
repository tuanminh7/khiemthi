import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .routes import main_bp


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    load_env_file(base_dir / ".env")

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )

    data_file = Path(os.getenv("DATA_FILE", str(base_dir / "data" / "books.json")))
    if not data_file.is_absolute():
        data_file = base_dir / data_file

    audio_dir = Path(os.getenv("AUDIO_DIR", str(base_dir / "static" / "audio")))
    if not audio_dir.is_absolute():
        audio_dir = base_dir / audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret-key-change-me"),
        DATA_FILE=data_file,
        AUDIO_DIR=audio_dir,
        AUDIO_PUBLIC_URL=os.getenv("AUDIO_PUBLIC_URL", "/media/audio").rstrip("/"),
        APP_TITLE=os.getenv("APP_TITLE", "Thu Vien Sach Noi AI"),
        RECOVER_AUDIO_JOBS_ON_STARTUP=env_flag("RECOVER_AUDIO_JOBS_ON_STARTUP", False),
    )

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.register_blueprint(main_bp)
    recover_audio_jobs(app)
    return app


def recover_audio_jobs(app: Flask) -> None:
    if not app.config["RECOVER_AUDIO_JOBS_ON_STARTUP"]:
        return

    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    from .services.audio_jobs import queue_audio_generation
    from .services.book_store import BookStore

    store = BookStore(app.config["DATA_FILE"])
    for book in store.list_books():
        if book.get("audio_status") not in {"queued", "processing"}:
            continue

        store.update_book(book["id"], {"audio_status": "queued", "audio_error": ""})
        queue_audio_generation(
            app.config["DATA_FILE"],
            app.config["AUDIO_DIR"],
            book["id"],
            app.config["AUDIO_PUBLIC_URL"],
        )
