import os
import aiohttp
from datetime import datetime

TURSO_URL   = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

class Database:
    def __init__(self):
        self.session = None
        self.base_url = None
        self.headers  = None

    async def init(self):
        if not TURSO_URL or not TURSO_TOKEN:
            raise Exception("Faltan variables de Turso")
        url = TURSO_URL.replace("libsql://", "https://").rstrip("/")
        self.base_url = url + "/v2/pipeline"
        self.headers  = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type":  "application/json",
        }
        self.session = aiohttp.ClientSession()
        await self._create_tables()
        print("✅ Base de datos conectada", flush=True)

    async def close(self):
        if self.session:
            await self.session.close()

    async def _run(self, requests):
        async with self.session.post(self.base_url, json={"requests": requests}, headers=self.headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Turso {resp.status}: {text}")
            return await resp.json()

    async def _exec(self, sql, params=None):
        req = {"type": "execute", "stmt": {"sql": sql}}
        if params:
            req["stmt"]["positional_args"] = [
                {"type": "text", "value": str(p)} if not isinstance(p, int)
                else {"type": "integer", "value": str(p)}
                for p in params
            ]
        result = await self._run([req])
        res = result["results"][0]
        if res.get("type") == "error":
            raise Exception(res["error"]["message"])

    async def _fetch(self, sql, params=None):
        req = {"type": "execute", "stmt": {"sql": sql}}
        if params:
            req["stmt"]["positional_args"] = [
                {"type": "text", "value": str(p)} if not isinstance(p, int)
                else {"type": "integer", "value": str(p)}
                for p in params
            ]
        result = await self._run([req])
        res = result["results"][0]
        if res.get("type") == "error":
            raise Exception(res["error"]["message"])
        data = res["response"]["result"]
        cols = [c["name"] for c in data["cols"]]
        return [
            {cols[i]: (row[i]["value"] if row[i]["type"] != "null" else None)
             for i in range(len(cols))}
            for row in data["rows"]
        ]

    async def _create_tables(self):
        await self._exec("""CREATE TABLE IF NOT EXISTS inventario (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT    NOT NULL UNIQUE,
            categoria TEXT    NOT NULL,
            cantidad  INTEGER NOT NULL DEFAULT 0)""")
        await self._exec("""CREATE TABLE IF NOT EXISTS movimientos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo       TEXT    NOT NULL,
            item       TEXT    NOT NULL,
            categoria  TEXT    NOT NULL,
            cantidad   INTEGER NOT NULL,
            usuario    TEXT    NOT NULL,
            usuario_id INTEGER NOT NULL,
            motivo     TEXT,
            fecha      TEXT    NOT NULL)""")
        await self._exec("""CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT)""")

    async def add_item(self, nombre, categoria, cantidad):
        rows = await self._fetch("SELECT cantidad FROM inventario WHERE nombre = ?", [nombre])
        if rows:
            await self._exec("UPDATE inventario SET cantidad = cantidad + ? WHERE nombre = ?", [cantidad, nombre])
        else:
            await self._exec("INSERT INTO inventario (nombre, categoria, cantidad) VALUES (?, ?, ?)", [nombre, categoria, cantidad])

    async def remove_item(self, nombre, cantidad):
        await self._exec("UPDATE inventario SET cantidad = MAX(0, cantidad - ?) WHERE nombre = ?", [cantidad, nombre])

    async def get_item(self, nombre):
        rows = await self._fetch("SELECT nombre, categoria, cantidad FROM inventario WHERE nombre = ?", [nombre])
        return rows[0] if rows else None

    async def get_inventario_completo(self):
        return await self._fetch("SELECT nombre, categoria, cantidad FROM inventario")

    async def get_inventario_con_stock(self):
        return await self._fetch("SELECT nombre, categoria, cantidad FROM inventario WHERE cantidad > 0 ORDER BY categoria, nombre")

    async def log_movimiento(self, tipo, item, categoria, cantidad, usuario, usuario_id, motivo):
        fecha = datetime.utcnow().isoformat()
        await self._exec(
            "INSERT INTO movimientos (tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha]
        )

    async def get_historial(self, limit=10):
        return await self._fetch(
            "SELECT tipo, item, categoria, cantidad, usuario, motivo, fecha FROM movimientos ORDER BY id DESC LIMIT ?",
            [limit]
        )

    async def get_config(self, clave):
        rows = await self._fetch("SELECT valor FROM config WHERE clave = ?", [clave])
        return rows[0]["valor"] if rows else None

    async def set_config(self, clave, valor):
        await self._exec("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", [clave, valor])
