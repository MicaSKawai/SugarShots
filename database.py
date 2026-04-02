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
        print(f"🔍 Conectando a: {self.base_url}", flush=True)
        await self._create_tables()
        print("✅ Base de datos conectada", flush=True)

    async def close(self):
        if self.session:
            await self.session.close()

    def _escape(self, v):
        if v is None:          return "NULL"
        if isinstance(v, int): return str(v)
        if isinstance(v, float): return str(v)
        return "'" + str(v).replace("'", "''") + "'"

    async def _sql(self, sql):
        req = {"type": "execute", "stmt": {"sql": sql}}
        async with self.session.post(self.base_url, json={"requests": [req]}, headers=self.headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Turso {resp.status}: {text}")
            data = await resp.json()
        res = data["results"][0]
        if res.get("type") == "error":
            raise Exception(res["error"]["message"])
        return res

    async def _fetch(self, sql):
        res = await self._sql(sql)
        data = res["response"]["result"]
        cols = [c["name"] for c in data["cols"]]
        return [
            {cols[i]: (row[i]["value"] if row[i]["type"] != "null" else None)
             for i in range(len(cols))}
            for row in data["rows"]
        ]

    async def _create_tables(self):
        e = self._escape
        await self._sql("""CREATE TABLE IF NOT EXISTS inventario (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT    NOT NULL,
            categoria TEXT    NOT NULL,
            cantidad  INTEGER NOT NULL DEFAULT 0,
            almacen   TEXT    NOT NULL DEFAULT 'Principal',
            UNIQUE(nombre, almacen))""")
        await self._sql("""CREATE TABLE IF NOT EXISTS movimientos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo       TEXT    NOT NULL,
            item       TEXT    NOT NULL,
            categoria  TEXT    NOT NULL,
            cantidad   INTEGER NOT NULL,
            usuario    TEXT    NOT NULL,
            usuario_id INTEGER NOT NULL,
            motivo     TEXT,
            almacen    TEXT    NOT NULL DEFAULT 'Principal',
            fecha      TEXT    NOT NULL)""")
        await self._sql("""CREATE TABLE IF NOT EXISTS almacenes (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT    NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1)""")
        await self._sql("""CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT)""")
        await self._sql("INSERT OR IGNORE INTO almacenes (nombre, activo) VALUES ('Principal', 1)")

    # ── Almacenes ─────────────────────────────────────────────────────────────
    async def get_almacenes(self):
        rows = await self._fetch("SELECT nombre FROM almacenes WHERE activo = 1 ORDER BY id")
        return [r["nombre"] for r in rows]

    async def crear_almacen(self, nombre):
        e = self._escape
        await self._sql(f"INSERT OR IGNORE INTO almacenes (nombre, activo) VALUES ({e(nombre)}, 1)")
        await self._sql(f"UPDATE almacenes SET activo = 1 WHERE nombre = {e(nombre)}")

    async def eliminar_almacen(self, nombre):
        e = self._escape
        await self._sql(f"UPDATE almacenes SET activo = 0 WHERE nombre = {e(nombre)}")

    async def almacen_existe(self, nombre):
        e = self._escape
        rows = await self._fetch(f"SELECT 1 FROM almacenes WHERE nombre = {e(nombre)} AND activo = 1")
        return len(rows) > 0

    # ── Inventario ────────────────────────────────────────────────────────────
    async def add_item(self, nombre, categoria, cantidad, almacen="Principal"):
        e = self._escape
        rows = await self._fetch(
            f"SELECT cantidad FROM inventario WHERE nombre = {e(nombre)} AND almacen = {e(almacen)}")
        if rows:
            await self._sql(
                f"UPDATE inventario SET cantidad = cantidad + {e(cantidad)} WHERE nombre = {e(nombre)} AND almacen = {e(almacen)}")
        else:
            await self._sql(
                f"INSERT INTO inventario (nombre, categoria, cantidad, almacen) VALUES ({e(nombre)}, {e(categoria)}, {e(cantidad)}, {e(almacen)})")

    async def remove_item(self, nombre, cantidad, almacen="Principal"):
        e = self._escape
        await self._sql(
            f"UPDATE inventario SET cantidad = MAX(0, cantidad - {e(cantidad)}) WHERE nombre = {e(nombre)} AND almacen = {e(almacen)}")

    async def get_item(self, nombre, almacen="Principal"):
        e = self._escape
        rows = await self._fetch(
            f"SELECT nombre, categoria, cantidad, almacen FROM inventario WHERE nombre = {e(nombre)} AND almacen = {e(almacen)}")
        return rows[0] if rows else None

    async def get_inventario_completo(self, almacen="Principal"):
        e = self._escape
        return await self._fetch(
            f"SELECT nombre, categoria, cantidad FROM inventario WHERE almacen = {e(almacen)}")

    async def get_inventario_con_stock(self, almacen="Principal"):
        e = self._escape
        return await self._fetch(
            f"SELECT nombre, categoria, cantidad FROM inventario WHERE cantidad > 0 AND almacen = {e(almacen)} ORDER BY categoria, nombre")

    # ── Movimientos ───────────────────────────────────────────────────────────
    async def log_movimiento(self, tipo, item, categoria, cantidad, usuario, usuario_id, motivo, almacen="Principal"):
        e = self._escape
        fecha = datetime.utcnow().isoformat()
        await self._sql(
            f"INSERT INTO movimientos (tipo, item, categoria, cantidad, usuario, usuario_id, motivo, almacen, fecha) "
            f"VALUES ({e(tipo)}, {e(item)}, {e(categoria)}, {e(cantidad)}, {e(usuario)}, {e(usuario_id)}, {e(motivo)}, {e(almacen)}, {e(fecha)})")

    async def get_historial(self, limit=10, almacen=None):
        e = self._escape
        if almacen:
            return await self._fetch(
                f"SELECT tipo, item, categoria, cantidad, usuario, motivo, almacen, fecha FROM movimientos WHERE almacen = {e(almacen)} ORDER BY id DESC LIMIT {int(limit)}")
        return await self._fetch(
            f"SELECT tipo, item, categoria, cantidad, usuario, motivo, almacen, fecha FROM movimientos ORDER BY id DESC LIMIT {int(limit)}")

    # ── Config ────────────────────────────────────────────────────────────────
    async def get_config(self, clave):
        e = self._escape
        rows = await self._fetch(f"SELECT valor FROM config WHERE clave = {e(clave)}")
        return rows[0]["valor"] if rows else None

    async def set_config(self, clave, valor):
        e = self._escape
        await self._sql(f"INSERT OR REPLACE INTO config (clave, valor) VALUES ({e(clave)}, {e(valor)})")
