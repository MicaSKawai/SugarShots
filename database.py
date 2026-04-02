"""
database.py — Armería Bot
Usa la API HTTP de Turso con aiohttp (100% async, compatible con discord.py)
"""
import os
import aiohttp
from datetime import datetime

TURSO_URL   = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")


class Database:
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.base_url = None
        self.headers = None

    async def init(self):
        print(f"🔍 TURSO_DATABASE_URL presente: {'SI -> ' + TURSO_URL if TURSO_URL else 'NO ❌'}")
        print(f"🔍 TURSO_AUTH_TOKEN presente:   {'SI' if TURSO_TOKEN else 'NO ❌'}")

        if not TURSO_URL:
            raise Exception("Falta la variable de entorno TURSO_DATABASE_URL")
        if not TURSO_TOKEN:
            raise Exception("Falta la variable de entorno TURSO_AUTH_TOKEN")

        self.base_url = TURSO_URL.rstrip("/") + "/v2/pipeline"
        self.headers = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        }
        self.session = aiohttp.ClientSession()
        print(f"🔍 Conectando a: {self.base_url}")

        try:
            await self._create_tables()
            print("✅ Base de datos conectada (Turso HTTP)")
        except Exception as e:
            print(f"❌ Error conectando a la DB: {e}")
            raise

    async def close(self):
        if self.session:
            await self.session.close()

    # ── Ejecución ─────────────────────────────────────────────────────────────

    async def _execute(self, statements: list[dict]) -> list:
        payload = {"requests": statements}
        try:
            async with self.session.post(self.base_url, json=payload, headers=self.headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ Turso HTTP {resp.status}: {text}")
                    raise Exception(f"Turso HTTP error {resp.status}: {text}")
                data = await resp.json()
                return data.get("results", [])
        except Exception as e:
            print(f"❌ Error en _execute: {e}")
            raise

    async def _query(self, sql: str, args: list = None) -> list[dict]:
        stmt = {
            "sql": sql,
            "named_args": [],
            "positional_args": [str(a) if a is not None else None for a in (args or [])]
        }
        results = await self._execute([{"type": "execute", "stmt": stmt}])
        result = results[0]
        if result.get("type") == "error":
            print(f"❌ Query error: {result}")
            raise Exception(f"Query error: {result}")
        rows_data = result.get("response", {}).get("result", {})
        cols = [c["name"] for c in rows_data.get("cols", [])]
        rows = rows_data.get("rows", [])
        return [
            {cols[i]: (cell.get("value") if cell.get("type") != "null" else None)
             for i, cell in enumerate(row)}
            for row in rows
        ]

    async def _run(self, sql: str, args: list = None):
        stmt = {
            "sql": sql,
            "named_args": [],
            "positional_args": [str(a) if a is not None else None for a in (args or [])]
        }
        results = await self._execute([{"type": "execute", "stmt": stmt}])
        result = results[0]
        if result.get("type") == "error":
            print(f"❌ Run error: {result}")
            raise Exception(f"Run error: {result}")

    # ── Tablas ────────────────────────────────────────────────────────────────

    async def _create_tables(self):
        # Inventario con columna almacen
        await self._run("""
            CREATE TABLE IF NOT EXISTS inventario (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre    TEXT    NOT NULL,
                categoria TEXT    NOT NULL,
                cantidad  INTEGER NOT NULL DEFAULT 0,
                almacen   TEXT    NOT NULL DEFAULT 'Principal',
                UNIQUE(nombre, almacen)
            )
        """)
        await self._run("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo       TEXT    NOT NULL,
                item       TEXT    NOT NULL,
                categoria  TEXT    NOT NULL,
                cantidad   INTEGER NOT NULL,
                usuario    TEXT    NOT NULL,
                usuario_id INTEGER NOT NULL,
                motivo     TEXT,
                almacen    TEXT    NOT NULL DEFAULT 'Principal',
                fecha      TEXT    NOT NULL
            )
        """)
        await self._run("""
            CREATE TABLE IF NOT EXISTS almacenes (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT    NOT NULL UNIQUE,
                activo INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self._run("""
            CREATE TABLE IF NOT EXISTS config (
                clave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)
        # Almacén por defecto si no existe ninguno
        await self._run("""
            INSERT OR IGNORE INTO almacenes (nombre, activo) VALUES ('Principal', 1)
        """)

    # ── Almacenes ─────────────────────────────────────────────────────────────

    async def get_almacenes(self) -> list[str]:
        rows = await self._query(
            "SELECT nombre FROM almacenes WHERE activo = 1 ORDER BY id"
        )
        return [r["nombre"] for r in rows]

    async def crear_almacen(self, nombre: str):
        await self._run(
            "INSERT OR IGNORE INTO almacenes (nombre, activo) VALUES (?, 1)",
            [nombre]
        )
        # Reactivar si existía pero estaba inactivo
        await self._run(
            "UPDATE almacenes SET activo = 1 WHERE nombre = ?",
            [nombre]
        )

    async def eliminar_almacen(self, nombre: str):
        await self._run(
            "UPDATE almacenes SET activo = 0 WHERE nombre = ?",
            [nombre]
        )

    async def almacen_existe(self, nombre: str) -> bool:
        rows = await self._query(
            "SELECT 1 FROM almacenes WHERE nombre = ? AND activo = 1",
            [nombre]
        )
        return len(rows) > 0

    # ── Inventario ────────────────────────────────────────────────────────────

    async def add_item(self, nombre: str, categoria: str, cantidad: int, almacen: str):
        existing = await self._query(
            "SELECT cantidad FROM inventario WHERE nombre = ? AND almacen = ?",
            [nombre, almacen]
        )
        if existing:
            await self._run(
                "UPDATE inventario SET cantidad = cantidad + ? WHERE nombre = ? AND almacen = ?",
                [cantidad, nombre, almacen]
            )
        else:
            await self._run(
                "INSERT INTO inventario (nombre, categoria, cantidad, almacen) VALUES (?, ?, ?, ?)",
                [nombre, categoria, cantidad, almacen]
            )

    async def remove_item(self, nombre: str, cantidad: int, almacen: str):
        await self._run(
            "UPDATE inventario SET cantidad = MAX(0, cantidad - ?) WHERE nombre = ? AND almacen = ?",
            [cantidad, nombre, almacen]
        )

    async def get_item(self, nombre: str, almacen: str) -> dict | None:
        rows = await self._query(
            "SELECT nombre, categoria, cantidad, almacen FROM inventario WHERE nombre = ? AND almacen = ?",
            [nombre, almacen]
        )
        return rows[0] if rows else None

    async def get_inventario_completo(self, almacen: str) -> list[dict]:
        return await self._query(
            "SELECT nombre, categoria, cantidad FROM inventario WHERE almacen = ?",
            [almacen]
        )

    async def get_inventario_con_stock(self, almacen: str) -> list[dict]:
        return await self._query(
            "SELECT nombre, categoria, cantidad FROM inventario WHERE cantidad > 0 AND almacen = ? ORDER BY categoria, nombre",
            [almacen]
        )

    # ── Movimientos ───────────────────────────────────────────────────────────

    async def log_movimiento(self, tipo, item, categoria, cantidad, usuario, usuario_id, motivo, almacen):
        fecha = datetime.utcnow().isoformat()
        await self._run(
            """INSERT INTO movimientos (tipo, item, categoria, cantidad, usuario, usuario_id, motivo, almacen, fecha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [tipo, item, categoria, cantidad, usuario, usuario_id, motivo, almacen, fecha]
        )

    async def get_historial(self, limit: int = 10, almacen: str = None) -> list[dict]:
        if almacen:
            rows = await self._query(
                "SELECT tipo, item, categoria, cantidad, usuario, motivo, almacen, fecha FROM movimientos WHERE almacen = ? ORDER BY id DESC LIMIT ?",
                [almacen, limit]
            )
        else:
            rows = await self._query(
                "SELECT tipo, item, categoria, cantidad, usuario, motivo, almacen, fecha FROM movimientos ORDER BY id DESC LIMIT ?",
                [limit]
            )
        return rows

    # ── Config ────────────────────────────────────────────────────────────────

    async def get_config(self, clave: str) -> str | None:
        rows = await self._query(
            "SELECT valor FROM config WHERE clave = ?", [clave]
        )
        return rows[0]["valor"] if rows else None

    async def set_config(self, clave: str, valor: str):
        await self._run(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
            [clave, valor]
        )
