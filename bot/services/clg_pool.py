from __future__ import annotations

import csv
import re
import sqlite3
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


CODE_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
URL_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
CERTILOGO_TOKEN_RE = re.compile(r"https?://(?:www\.)?certilogo\.com/qr/([a-z0-9]+)", re.IGNORECASE)
MAX_ARCHIVE_IMAGES = 1000
MAX_ARCHIVE_UNPACKED_BYTES = 250 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ClgPair:
    code: str
    url: str


@dataclass(frozen=True)
class ImportResult:
    added: int
    duplicates: int
    invalid: int


class ClgArchiveError(ValueError):
    pass


def read_jpg_archive(data: bytes) -> list[tuple[str, bytes]]:
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as error:
        raise ClgArchiveError("Файл не является корректным ZIP-архивом.") from error

    with archive:
        members = [
            item for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith((".jpg", ".jpeg"))
        ]
        if not members:
            raise ClgArchiveError("В архиве нет JPG/JPEG-файлов.")
        if len(members) > MAX_ARCHIVE_IMAGES:
            raise ClgArchiveError(f"В одном архиве допускается не более {MAX_ARCHIVE_IMAGES} изображений.")
        if any(item.flag_bits & 0x1 for item in members):
            raise ClgArchiveError("Архивы с паролем не поддерживаются.")
        if any(item.file_size > MAX_IMAGE_BYTES for item in members):
            raise ClgArchiveError("Размер одного изображения после распаковки не должен превышать 20 МБ.")
        if sum(item.file_size for item in members) > MAX_ARCHIVE_UNPACKED_BYTES:
            raise ClgArchiveError("Общий размер изображений после распаковки не должен превышать 250 МБ.")

        return [(item.filename, archive.read(item)) for item in members]


def normalize_url(value: str) -> str:
    url = value.strip().rstrip("/).]")
    match = CERTILOGO_TOKEN_RE.fullmatch(url)
    if match:
        return "http://certilogo.com/qr/" + match.group(1).upper()
    return url


def parse_clg_pairs(text: str) -> tuple[list[ClgPair], int]:
    pairs: list[ClgPair] = []
    invalid = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        code_match = CODE_RE.search(line)
        url_match = URL_RE.search(line)
        if not code_match or not url_match:
            invalid += 1
            continue
        pairs.append(ClgPair(code_match.group(1), normalize_url(url_match.group(0))))
    return pairs, invalid


class ClgPool:
    """Persistent CLG inventory with historical duplicate protection."""

    def __init__(self, database_path: str | Path, worked_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.worked_path = Path(worked_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS clg_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    url TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK (status IN ('available', 'reserved', 'used')),
                    reservation_token TEXT,
                    added_at TEXT NOT NULL,
                    used_at TEXT,
                    used_by INTEGER
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_clg_status_id ON clg_items(status, id)"
            )

    def import_pairs(self, pairs: list[ClgPair], invalid: int = 0) -> ImportResult:
        added = 0
        duplicates = 0
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            for pair in pairs:
                try:
                    connection.execute(
                        "INSERT INTO clg_items(code, url, added_at) VALUES (?, ?, ?)",
                        (pair.code, normalize_url(pair.url), now),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    duplicates += 1
        return ImportResult(added=added, duplicates=duplicates, invalid=invalid)

    def import_text(self, text: str) -> ImportResult:
        pairs, invalid = parse_clg_pairs(text)
        return self.import_pairs(pairs, invalid)

    def reserve(self, count: int) -> tuple[str, list[ClgPair]]:
        if count <= 0:
            raise ValueError("Количество должно быть больше нуля")
        token = uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, code, url FROM clg_items WHERE status = 'available' ORDER BY id LIMIT ?",
                (count,),
            ).fetchall()
            if len(rows) != count:
                connection.rollback()
                return "", []
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"UPDATE clg_items SET status='reserved', reservation_token=? WHERE id IN ({placeholders})",
                (token, *ids),
            )
            connection.commit()
        return token, [ClgPair(row["code"], row["url"]) for row in rows]

    def release(self, token: str) -> None:
        if not token:
            return
        with self._connection() as connection:
            connection.execute(
                "UPDATE clg_items SET status='available', reservation_token=NULL "
                "WHERE status='reserved' AND reservation_token=?",
                (token,),
            )

    def consume(self, token: str, user_id: int | None) -> int:
        if not token:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE clg_items SET status='used', reservation_token=NULL, used_at=?, used_by=? "
                "WHERE status='reserved' AND reservation_token=?",
                (now, user_id, token),
            )
            consumed = cursor.rowcount
        self.export_worked()
        return consumed

    def counts(self) -> dict[str, int]:
        result = {"available": 0, "reserved": 0, "used": 0, "total": 0}
        with self._connection() as connection:
            for row in connection.execute("SELECT status, COUNT(*) AS amount FROM clg_items GROUP BY status"):
                result[row["status"]] = row["amount"]
                result["total"] += row["amount"]
        return result

    def export_worked(self) -> Path:
        self.worked_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT code, url, used_at, used_by FROM clg_items WHERE status='used' ORDER BY id"
            ).fetchall()
        with self.worked_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["12_значный_код", "ссылка", "использовано", "telegram_id"])
            writer.writerows((row["code"], row["url"], row["used_at"], row["used_by"] or "") for row in rows)
        return self.worked_path
