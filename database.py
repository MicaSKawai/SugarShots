import os
import libsql_client as libsql
from datetime import datetime

TURSO_URL   = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

class Database:
    def __init__(self):
        self.conn = None

    async def init(self):
        self.conn = libsql.create_client_sync(
            url=TURSO_URL,
            auth_token=TURSO_TOKEN
        )
        await self._create_tables()
        print("✅ Base de datos conectada")

    async def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS inventario (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre    TEXT    NOT NULL UNIQUE,
                categoria TEXT    NOT NULL,
                cantidad  INTEGER NOT NULL DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo       TEXT    NOT NULL,
                item       TEXT    NOT NULL,
                categoria  TEXT    NOT NULL,
                cantidad   INTEGER NOT NULL,
                usuario    TEXT    NOT NULL,
                usuario_id INTEGER NOT NULL,
                motivo     TEXT,
                fecha      TEXT    NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                clave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)
        self.conn.commit()

    async def add_item(self, nombre, categoria, cantidad):
        existing = self.conn.execute(
            "SELECT cantidad FROM inventario WHERE nombre = ?", [nombre]
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE inventario SET cantidad = cantidad + ? WHERE nombre = ?",
                [cantidad, nombre]
            )
        else:
            self.conn.execute(
                "INSERT INTO inventario (nombre, categoria, cantidad) VALUES (?, ?, ?)",
                [nombre, categoria, cantidad]
            )
        self.conn.commit()

    async def remove_item(self, nombre, cantidad):
        self.conn.execute(
            "UPDATE inventario SET cantidad = MAX(0, cantidad - ?) WHERE nombre = ?",
            [cantidad, nombre]
        )
        self.conn.commit()

    async def get_item(self, nombre):
        row = self.conn.execute(
            "SELECT nombre, categoria, cantidad FROM inventario WHERE nombre = ?",
            [nombre]
        ).fetchone()
        if not row:
            return None
        return {"nombre": row[0], "categoria": row[1], "cantidad": row[2]}

    async def get_inventario_completo(self):
        rows = self.conn.execute(
            "SELECT nombre, categoria, cantidad FROM inventario"
        ).fetchall()
        return [{"nombre": r[0], "categoria": r[1], "cantidad": r[2]} for r in rows]

    async def get_inventario_con_stock(self):
        rows = self.conn.execute(
            "SELECT nombre, categoria, cantidad FROM inventario WHERE cantidad > 0 ORDER BY categoria, nombre"
        ).fetchall()
        return [{"nombre": r[0], "categoria": r[1], "cantidad": r[2]} for r in rows]

    async def log_movimiento(self, tipo, item, categoria, cantidad, usuario, usuario_id, motivo):
        fecha = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT INTO movimientos (tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [tipo, item, categoria, cantidad, usuario, usuario_id, motivo, fecha]
        )
        self.conn.commit()

    async def get_historial(self, limit=10):
        rows = self.conn.execute(
            "SELECT tipo, item, categoria, cantidad, usuario, motivo, fecha FROM movimientos ORDER BY id DESC LIMIT ?",
            [limit]
        ).fetchall()
        return [
            {"tipo": r[0], "item": r[1], "categoria": r[2],
             "cantidad": r[3], "usuario": r[4], "motivo": r[5], "fecha": r[6]}
            for r in rows
        ]

    async def get_config(self, clave):
        row = self.conn.execute(
            "SELECT valor FROM config WHERE clave = ?", [clave]
        ).fetchone()
        return row[0] if row else None

    async def set_config(self, clave, valor):
        self.conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
            [clave, valor]
        )
        self.conn.commit()
```

---

Y el **`requirements.txt`**:
```
discord.py>=2.3.2
libsql-client>=0.3.0
flask>=3.0.0
