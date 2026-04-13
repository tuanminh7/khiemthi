import os

from app import create_app


app = create_app()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    app.run(debug=env_flag("FLASK_DEBUG", True))
