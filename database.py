import os
import aiohttp
from datetime import datetime

TURSO_URL   = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

class Database:
    def __init__(self):
        self.session = None
        self.base_url = None
        self.headers = None

    def _arg(self, v):
        if v is None:
            return {"type": "null", "value": None}
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": str(v)}
        return {"type": "text", "value": str(v)}

    async def init(self):
        if not TURSO_URL or not TURSO_TOKEN:
            raise Exception("Faltan variables TURSO_DATABASE_URL o TURSO_AUTH_TOKEN")
        self.base_url = TURSO_URL.rstrip("/") + "/v2/pipeline"
        self.headers = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        }
        self.session = aiohttp.ClientSession()
        await self._create_tables()
        print("✅ Base de datos conectada", flush=True)

    async def close(self):
        if self.session:
            await self.session.close()

    async def _execute(self, statements):
        payload = {"requests": statements}
        async with self.session.post(self.base_url, json=payload, headers=self.headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Turso error {resp.status}: {text}")
            data = await resp.json()
            return data.get("results", [])

    async def _query(self, sql, args=None):
        stmt = {
            "type": "execute",
            "stmt": {
                "sql": sql,
                "named_args": [],
                "positional_args": [self._arg(a) for a in (args or [])]
            }
        }
        results = await self._execute([stmt])
        result = results[0]
        if result.get("type") == "error":
            print(f"❌ Query error: {result}", flush=True)
            raise Exception(f"Query error: {result}")
        rows_data = result.get("response", {}).get("result", {})
        cols = [c["name"] for c in rows_data.get("cols", [])]
        rows = rows_data.get("rows", [])
        return [
            {cols[i]: (cell.get("value") if cell.get("type") != "null" else None)
             for i, cell in enumerate(row)}
            for row in rows
        ]

    async def _run(self, sql, args=None):
        stmt = {
            "type": "execute",
            "stmt": {
                "sql": sql,
                "named_args": [],
                "positional_args": [self._arg(a) for a in (args or [])]
            }
        }
        results = await self._execute([stmt])
        result = results[0]
        if result.get("type") == "error":
            print(f"❌ Run error: {result}", flush=True)
            raise Exception(f"Run error: {result}")

    async def _create_tables(self):
        await self._run("CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE, categoria TEXT NOT NULL, cantidad INTEGER NOT NULL DEFAULT 0)")
        await self._run("CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, item TEXT NOT NULL, categoria TEXT NOT NULL, cantidad INTEGER NOT NULL, usuario TEXT NOT NULL, usuario_id INTEGER NOT NULL, motivo TEXT, fecha TEXT NOT NULL)")
        await self._run("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")

    async def add_item(self, nombre, categoria, cantidad):
        existing = await self._query("SELECT cantidad FROM inventario WHERE nombre = ?", [nombre])
        if existing:
            await self._run("UPDATE inventario SET cantidad = cantidad + ? WHERE nombre = ?", [cantidad, nombre])
        else:
            await self._run("INSERT INTO inventario (nombre, categoria, cantidad) VALUES (?, ?, ?)", [nombre, categoria, cantidad])

    async def remove_item(self, nombre, cantidad):
        await self._run("UPDATE inventario SET cantidad = MAX(0, cantidad - ?) WHERE nombre = ?", [cantidad, nombre])

    async def get_item(self, nombre):
        rows = await self._query("SELECT nombre, categoria, cantidad FROM inventario WHERE nombre = ?", [nombre])
        return rows[0] if rows else None

    async def get_inventario_completo(self):
        return await self._query("SELECT nombre, categoria, cantidad FROM inventario")

    async def get_inventario_con_stock(self):
        return await self._query("SELECT nombre, categoria, cantidad FROM inventario WHERE cantidad > 0 ORDER BY categoria, nombre")

    async def log_movimiento(self, tipo, item, categoria, cantidad, usuario, usuario_id, motivo):
        fecha = datetime.utcnow().isoformat()
        await self._run(
            "INSERT INTO movimientos (tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha]
        )

    async def get_historial(self, limit=10):
        return await self._query(
            "SELECT tipo, item, categoria, cantidad, usuario, motivo, fecha FROM movimientos ORDER BY id DESC LIMIT ?",
            [limit]
        )

    async def get_config(self, clave):
        rows = await self._query("SELECT valor FROM config WHERE clave = ?", [clave])
        return rows[0]["valor"] if rows else None

    async def set_config(self, clave, valor):
        await self._run("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", [clave, valor])
