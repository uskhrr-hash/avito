"""SQLite: пользователи (contributor/admin) и журнал баллов."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

ROLE_CONTRIBUTOR = "contributor"
ROLE_ADMIN = "admin"


@dataclass(frozen=True)
class UserRow:
    id: int
    login: str
    role: str
    display_name: str
    active: bool
    created_at: str


@dataclass(frozen=True)
class LedgerRow:
    id: int
    user_id: int
    delta: int
    reason: str
    article: str | None
    photo_index: int | None
    created_at: str
    admin_id: int | None
    login: str = ""
    display_name: str = ""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('contributor', 'admin')),
            display_name TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS point_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            article TEXT,
            photo_index INTEGER,
            created_at TEXT NOT NULL,
            admin_id INTEGER REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_user ON point_ledger(user_id);
        """
    )
    conn.commit()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _row_user(row: sqlite3.Row) -> UserRow:
    return UserRow(
        id=int(row["id"]),
        login=str(row["login"]),
        role=str(row["role"]),
        display_name=str(row["display_name"] or ""),
        active=bool(row["active"]),
        created_at=str(row["created_at"]),
    )


def bootstrap_admin(
    conn: sqlite3.Connection,
    *,
    login: str,
    password: str,
    display_name: str = "Admin",
) -> UserRow | None:
    """Создать admin из secrets, если такого логина ещё нет."""
    login = login.strip()
    password = password.strip()
    if not login or not password:
        return None
    existing = get_user_by_login(conn, login)
    if existing is not None:
        return existing
    return create_user(
        conn,
        login=login,
        password=password,
        role=ROLE_ADMIN,
        display_name=display_name or "Admin",
    )


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> UserRow | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_user(row) if row else None


def get_user_by_login(conn: sqlite3.Connection, login: str) -> UserRow | None:
    row = conn.execute(
        "SELECT * FROM users WHERE login = ? COLLATE NOCASE",
        (login.strip(),),
    ).fetchone()
    return _row_user(row) if row else None


def authenticate_user(
    conn: sqlite3.Connection, login: str, password: str
) -> UserRow | None:
    row = conn.execute(
        "SELECT * FROM users WHERE login = ? COLLATE NOCASE",
        (login.strip(),),
    ).fetchone()
    if row is None:
        return None
    if not row["active"]:
        return None
    if not verify_password(password, str(row["password_hash"])):
        return None
    return _row_user(row)


def create_user(
    conn: sqlite3.Connection,
    *,
    login: str,
    password: str,
    role: str,
    display_name: str = "",
) -> UserRow:
    login = login.strip()
    if not login:
        raise ValueError("Логин пустой")
    if role not in (ROLE_CONTRIBUTOR, ROLE_ADMIN):
        raise ValueError("Неизвестная роль")
    if len(password) < 4:
        raise ValueError("Пароль слишком короткий")
    try:
        cur = conn.execute(
            """
            INSERT INTO users (login, password_hash, role, display_name, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (login, hash_password(password), role, display_name.strip(), _utcnow()),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Логин уже занят: {login}") from exc
    user = get_user_by_id(conn, int(cur.lastrowid))
    assert user is not None
    return user


def set_user_active(conn: sqlite3.Connection, user_id: int, active: bool) -> UserRow:
    conn.execute(
        "UPDATE users SET active = ? WHERE id = ?",
        (1 if active else 0, user_id),
    )
    conn.commit()
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    return user


def reset_password(conn: sqlite3.Connection, user_id: int, password: str) -> UserRow:
    if len(password) < 4:
        raise ValueError("Пароль слишком короткий")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(password), user_id),
    )
    conn.commit()
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    return user


def list_users(
    conn: sqlite3.Connection, *, role: str | None = None
) -> list[UserRow]:
    if role:
        rows = conn.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY login COLLATE NOCASE",
            (role,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY role, login COLLATE NOCASE"
        ).fetchall()
    return [_row_user(r) for r in rows]


def user_balance(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS bal FROM point_ledger WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["bal"]) if row else 0


def add_points(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    delta: int,
    reason: str,
    article: str | None = None,
    photo_index: int | None = None,
    admin_id: int | None = None,
) -> int:
    if delta == 0:
        return user_balance(conn, user_id)
    conn.execute(
        """
        INSERT INTO point_ledger
            (user_id, delta, reason, article, photo_index, created_at, admin_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            int(delta),
            reason.strip(),
            article,
            photo_index,
            _utcnow(),
            admin_id,
        ),
    )
    conn.commit()
    return user_balance(conn, user_id)


def deduct_points(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    amount: int,
    reason: str,
    admin_id: int,
) -> int:
    amount = abs(int(amount))
    if amount <= 0:
        raise ValueError("Сумма списания должна быть > 0")
    bal = user_balance(conn, user_id)
    if amount > bal:
        raise ValueError(f"Недостаточно баллов (баланс {bal})")
    return add_points(
        conn,
        user_id=user_id,
        delta=-amount,
        reason=reason or "Списание админом",
        admin_id=admin_id,
    )


def list_balances(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT u.id, u.login, u.display_name, u.role, u.active,
               COALESCE(SUM(l.delta), 0) AS balance
        FROM users u
        LEFT JOIN point_ledger l ON l.user_id = u.id
        WHERE u.role = ?
        GROUP BY u.id
        ORDER BY balance DESC, u.login COLLATE NOCASE
        """,
        (ROLE_CONTRIBUTOR,),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "login": str(r["login"]),
            "display_name": str(r["display_name"] or ""),
            "role": str(r["role"]),
            "active": bool(r["active"]),
            "balance": int(r["balance"]),
        }
        for r in rows
    ]


def list_ledger(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    limit: int = 100,
) -> list[LedgerRow]:
    limit = max(1, min(int(limit), 500))
    if user_id is not None:
        rows = conn.execute(
            """
            SELECT l.*, u.login, u.display_name
            FROM point_ledger l
            JOIN users u ON u.id = l.user_id
            WHERE l.user_id = ?
            ORDER BY l.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT l.*, u.login, u.display_name
            FROM point_ledger l
            JOIN users u ON u.id = l.user_id
            ORDER BY l.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        LedgerRow(
            id=int(r["id"]),
            user_id=int(r["user_id"]),
            delta=int(r["delta"]),
            reason=str(r["reason"] or ""),
            article=r["article"],
            photo_index=r["photo_index"],
            created_at=str(r["created_at"]),
            admin_id=r["admin_id"],
            login=str(r["login"]),
            display_name=str(r["display_name"] or ""),
        )
        for r in rows
    ]
