import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash


class UserValidationError(ValueError):
    pass


@dataclass
class UserStore:
    data_file: Path
    _lock = Lock()

    def __post_init__(self) -> None:
        self.data_file = Path(self.data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            self.data_file.write_text("[]", encoding="utf-8")

    def add_user(self, username: str, password: str, display_name: str = "") -> dict:
        username = self._normalize_username(username)
        display_name = (display_name or username).strip()
        password = password or ""

        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username):
            raise UserValidationError("Ten dang nhap chi gom 3-32 ky tu: chu thuong, so, dau ., _, -.")
        if len(password) < 6:
            raise UserValidationError("Mat khau can it nhat 6 ky tu.")

        user = {
            "id": uuid4().hex[:12],
            "username": username,
            "display_name": display_name[:80] or username,
            "password_hash": generate_password_hash(password),
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            users = self._load_users_unlocked()
            if any(item.get("username") == username for item in users):
                raise UserValidationError("Ten dang nhap nay da ton tai.")
            users.append(user)
            self._save_users_unlocked(users)
        return self._public_user(user)

    def authenticate(self, username: str, password: str) -> dict | None:
        username = self._normalize_username(username)
        with self._lock:
            for user in self._load_users_unlocked():
                if user.get("username") != username:
                    continue
                if check_password_hash(user.get("password_hash", ""), password or ""):
                    return self._public_user(user)
        return None

    def _load_users_unlocked(self) -> list[dict]:
        try:
            content = self.data_file.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise UserValidationError("Khong doc duoc du lieu nguoi dung hien tai.") from exc

        if not isinstance(data, list):
            raise UserValidationError("File du lieu nguoi dung khong dung dinh dang.")
        return data

    def _save_users_unlocked(self, users: list[dict]) -> None:
        self.data_file.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_username(username: str) -> str:
        return (username or "").strip().lower()

    @staticmethod
    def _public_user(user: dict) -> dict:
        return {
            "id": user.get("id", ""),
            "username": user.get("username", ""),
            "display_name": user.get("display_name") or user.get("username", ""),
            "role": user.get("role", "user"),
        }
