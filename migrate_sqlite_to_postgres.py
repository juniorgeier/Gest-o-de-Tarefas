from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT_DIR = Path(__file__).resolve().parent
SQLITE_PATH = ROOT_DIR / "tasks.db"


def normalize_database_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def ensure_postgres_schema(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS base_tasks (
            id INTEGER PRIMARY KEY,
            atividade TEXT NOT NULL,
            setor TEXT NOT NULL DEFAULT '',
            observacoes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS months (
            month_key TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_tasks (
            month_key TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (month_key, task_id),
            FOREIGN KEY (month_key) REFERENCES months (month_key) ON DELETE CASCADE,
            FOREIGN KEY (task_id) REFERENCES base_tasks (id)
        )
        """
    )


def load_sqlite_data(sqlite_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Arquivo SQLite não encontrado: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        base_tasks = [dict(row) for row in conn.execute("SELECT id, atividade, setor, observacoes FROM base_tasks")]
        months = [dict(row) for row in conn.execute("SELECT month_key, created_at FROM months")]
        monthly_tasks = [
            dict(row)
            for row in conn.execute("SELECT month_key, task_id, status, updated_at FROM monthly_tasks")
        ]
    finally:
        conn.close()

    return base_tasks, months, monthly_tasks


def migrate(sqlite_path: Path, database_url: str) -> None:
    base_tasks, months, monthly_tasks = load_sqlite_data(sqlite_path)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        ensure_postgres_schema(conn)

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO base_tasks (id, atividade, setor, observacoes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET atividade = EXCLUDED.atividade,
                    setor = EXCLUDED.setor,
                    observacoes = EXCLUDED.observacoes
                """,
                [
                    (
                        int(row["id"]),
                        str(row.get("atividade", "")),
                        str(row.get("setor", "")),
                        str(row.get("observacoes", "")),
                    )
                    for row in base_tasks
                ],
            )

            cur.executemany(
                """
                INSERT INTO months (month_key, created_at)
                VALUES (%s, %s)
                ON CONFLICT (month_key) DO UPDATE
                SET created_at = EXCLUDED.created_at
                """,
                [
                    (
                        str(row["month_key"]),
                        str(row.get("created_at", "")),
                    )
                    for row in months
                ],
            )

            cur.executemany(
                """
                INSERT INTO monthly_tasks (month_key, task_id, status, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (month_key, task_id) DO UPDATE
                SET status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                [
                    (
                        str(row["month_key"]),
                        int(row["task_id"]),
                        str(row.get("status", "Pendente")),
                        str(row.get("updated_at", "")),
                    )
                    for row in monthly_tasks
                ],
            )

        conn.commit()

    print("Migração concluída com sucesso.")
    print(f"base_tasks: {len(base_tasks)}")
    print(f"months: {len(months)}")
    print(f"monthly_tasks: {len(monthly_tasks)}")


def main() -> None:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError("Defina a variável de ambiente DATABASE_URL com a conexão do Postgres.")

    migrate(SQLITE_PATH, database_url)


if __name__ == "__main__":
    main()
