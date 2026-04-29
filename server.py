from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for local SQLite mode
    psycopg = None
    dict_row = None


ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "tasks.db"
BASE_TASKS_PATH = ROOT_DIR / "tasks_base.json"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

STATUS_ALLOWED = {"Pendente", "Em andamento", "Concluído"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def current_month_key() -> str:
    now = datetime.now()
    return f"{now.year:04d}-{now.month:02d}"


def previous_month_key(base_month: str | None = None) -> str:
    if base_month is None:
        base_month = current_month_key()
    year, month = [int(x) for x in base_month.split("-")]
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def next_month_key(month_key: str) -> str:
    year, month = [int(x) for x in month_key.split("-")]
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def reference_month_key() -> str:
    return previous_month_key(current_month_key())


def _sql(query: str) -> str:
    if IS_POSTGRES:
        return query.replace("?", "%s")
    return query


def _row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


def get_conn():
    if IS_POSTGRES:
        if psycopg is None or dict_row is None:
            raise RuntimeError("Dependência psycopg não encontrada para usar DATABASE_URL Postgres")
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        if IS_POSTGRES:
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
                    observacoes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (month_key, task_id),
                    FOREIGN KEY (month_key) REFERENCES months (month_key) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES base_tasks (id)
                )
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS base_tasks (
                    id INTEGER PRIMARY KEY,
                    atividade TEXT NOT NULL,
                    setor TEXT NOT NULL DEFAULT '',
                    observacoes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS months (
                    month_key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS monthly_tasks (
                    month_key TEXT NOT NULL,
                    task_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    observacoes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (month_key, task_id),
                    FOREIGN KEY (month_key) REFERENCES months (month_key) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES base_tasks (id)
                );
                """
            )

        # Compatibilidade com bancos já existentes antes da coluna mensal de observações.
        if IS_POSTGRES:
            conn.execute("ALTER TABLE monthly_tasks ADD COLUMN IF NOT EXISTS observacoes TEXT NOT NULL DEFAULT ''")
        else:
            columns = conn.execute("PRAGMA table_info(monthly_tasks)").fetchall()
            column_names = {str(_row_to_dict(col)["name"]) for col in columns}
            if "observacoes" not in column_names:
                conn.execute("ALTER TABLE monthly_tasks ADD COLUMN observacoes TEXT NOT NULL DEFAULT ''")

        count_row = _row_to_dict(conn.execute("SELECT COUNT(*) AS total FROM base_tasks").fetchone())
        count = int(count_row["total"])

        if count == 0:
            with BASE_TASKS_PATH.open("r", encoding="utf-8") as f:
                tasks = json.load(f)
            rows = [
                (
                    int(task["TaskID"]),
                    str(task.get("Atividade", "")),
                    str(task.get("Setor", "")),
                    str(task.get("Observações", task.get("ObservaÃ§Ãµes", ""))),
                )
                for task in tasks
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    _sql(
                        """
                        INSERT INTO base_tasks (id, atividade, setor, observacoes)
                        VALUES (?, ?, ?, ?)
                        """
                    ),
                    rows,
                )

    ensure_month(reference_month_key())


def ensure_month(month_key: str) -> None:
    with get_conn() as conn:
        month_exists = conn.execute(
            _sql("SELECT 1 FROM months WHERE month_key = ?"),
            (month_key,),
        ).fetchone()
        if month_exists:
            return

        conn.execute(
            _sql("INSERT INTO months (month_key, created_at) VALUES (?, ?)"),
            (month_key, now_iso()),
        )
        conn.execute(
            _sql(
                """
                INSERT INTO monthly_tasks (month_key, task_id, status, updated_at)
                SELECT ?, id, 'Pendente', '', ?
                FROM base_tasks
                ORDER BY id
                """
            ),
            (month_key, now_iso()),
        )


def list_months() -> list[str]:
    ensure_month(reference_month_key())
    with get_conn() as conn:
        rows = conn.execute("SELECT month_key FROM months ORDER BY month_key DESC").fetchall()
    return [_row_to_dict(row)["month_key"] for row in rows]


def create_next_month() -> str:
    months = list_months()
    latest = months[0] if months else reference_month_key()
    new_key = next_month_key(latest)
    ensure_month(new_key)
    return new_key


def get_tasks_for_month(month_key: str) -> list[dict]:
    ensure_month(month_key)
    with get_conn() as conn:
        rows = conn.execute(
            _sql(
                """
                SELECT
                    bt.id,
                    bt.atividade,
                    bt.setor,
                    mt.observacoes,
                    mt.status
                FROM monthly_tasks mt
                JOIN base_tasks bt ON bt.id = mt.task_id
                WHERE mt.month_key = ?
                ORDER BY bt.id
                """
            ),
            (month_key,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def update_task_status(month_key: str, task_id: int, status: str) -> None:
    if status not in STATUS_ALLOWED:
        raise ValueError("Status inválido")

    ensure_month(month_key)
    with get_conn() as conn:
        result = conn.execute(
            _sql(
                """
                UPDATE monthly_tasks
                SET status = ?, updated_at = ?
                WHERE month_key = ? AND task_id = ?
                """
            ),
            (status, now_iso(), month_key, task_id),
        )
        if result.rowcount == 0:
            raise LookupError("Tarefa não encontrada")


def create_base_task(atividade: str, setor: str, observacoes: str = "") -> dict:
    atividade_clean = atividade.strip()
    setor_clean = setor.strip()
    observacoes_clean = observacoes.strip()

    if not atividade_clean:
        raise ValueError("Descrição da tarefa é obrigatória")
    if not setor_clean:
        raise ValueError("Setor da tarefa é obrigatório")

    with get_conn() as conn:
        next_id_row = _row_to_dict(conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM base_tasks").fetchone())
        next_id = int(next_id_row["next_id"])
        conn.execute(
            _sql(
                """
                INSERT INTO base_tasks (id, atividade, setor, observacoes)
                VALUES (?, ?, ?, ?)
                """
            ),
            (next_id, atividade_clean, setor_clean, observacoes_clean),
        )

        if IS_POSTGRES:
            conn.execute(
                _sql(
                    """
                    INSERT INTO monthly_tasks (month_key, task_id, status, observacoes, updated_at)
                    SELECT month_key, ?, 'Pendente', CASE WHEN month_key = ? THEN ? ELSE '' END, ?
                    FROM months
                    WHERE month_key >= ?
                    ORDER BY month_key
                    ON CONFLICT (month_key, task_id) DO NOTHING
                    """
                ),
                (next_id, current_month_key(), observacoes_clean, now_iso(), current_month_key()),
            )
        else:
            conn.execute(
                _sql(
                    """
                    INSERT OR IGNORE INTO monthly_tasks (month_key, task_id, status, observacoes, updated_at)
                    SELECT month_key, ?, 'Pendente', CASE WHEN month_key = ? THEN ? ELSE '' END, ?
                    FROM months
                    WHERE month_key >= ?
                    ORDER BY month_key
                    """
                ),
                (next_id, current_month_key(), observacoes_clean, now_iso(), current_month_key()),
            )

    return {
        "id": next_id,
        "atividade": atividade_clean,
        "setor": setor_clean,
        "observacoes": observacoes_clean,
    }


def update_task_notes(month_key: str, task_id: int, observacoes: str) -> None:
    observacoes_clean = observacoes.strip()
    ensure_month(month_key)
    with get_conn() as conn:
        result = conn.execute(
            _sql(
                """
                UPDATE monthly_tasks
                SET observacoes = ?
                WHERE month_key = ? AND task_id = ?
                """
            ),
            (observacoes_clean, month_key, task_id),
        )
        if result.rowcount == 0:
            raise LookupError("Tarefa não encontrada")


def delete_base_task(task_id: int) -> None:
    with get_conn() as conn:
        exists = conn.execute(_sql("SELECT 1 FROM base_tasks WHERE id = ?"), (task_id,)).fetchone()
        if not exists:
            raise LookupError("Tarefa não encontrada")

        conn.execute(_sql("DELETE FROM monthly_tasks WHERE task_id = ?"), (task_id,))
        conn.execute(_sql("DELETE FROM base_tasks WHERE id = ?"), (task_id,))


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Arquivo não encontrado")
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_file(ROOT_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._send_file(ROOT_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/styles.css":
            self._send_file(ROOT_DIR / "styles.css", "text/css; charset=utf-8")
            return

        if path == "/api/months":
            months = list_months()
            self._send_json(
                HTTPStatus.OK,
                {
                    "months": months,
                    "referenceMonth": reference_month_key(),
                },
            )
            return

        if path == "/api/tasks":
            month = parse_qs(parsed.query).get("month", [reference_month_key()])[0]
            tasks = get_tasks_for_month(month)
            self._send_json(HTTPStatus.OK, {"month": month, "tasks": tasks})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/months/next":
            month_key = create_next_month()
            self._send_json(HTTPStatus.CREATED, {"month": month_key})
            return

        if path == "/api/base-tasks":
            try:
                body = self._read_json_body()
                atividade = str(body.get("atividade", ""))
                setor = str(body.get("setor", ""))
                observacoes = str(body.get("observacoes", ""))
                task = create_base_task(atividade, setor, observacoes)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.CREATED, {"task": task})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/tasks/status":
            try:
                body = self._read_json_body()
                month = str(body.get("month", reference_month_key()))
                task_id = int(body["taskId"])
                status = str(body["status"])
                update_task_status(month, task_id, status)
            except KeyError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Campos taskId e status são obrigatórios"})
                return
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except LookupError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if path == "/api/tasks/notes":
            try:
                body = self._read_json_body()
                month = str(body.get("month", reference_month_key()))
                task_id = int(body["taskId"])
                observacoes = str(body.get("observacoes", ""))
                update_task_notes(month, task_id, observacoes)
            except KeyError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Campo taskId é obrigatório"})
                return
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "ID de tarefa inválido"})
                return
            except LookupError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/base-tasks/"):
            raw_id = path.removeprefix("/api/base-tasks/").strip()
            try:
                task_id = int(raw_id)
                delete_base_task(task_id)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "ID de tarefa inválido"})
                return
            except LookupError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def log_message(self, fmt: str, *args) -> None:
        return


def run() -> None:
    init_db()
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Servidor ativo em http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
