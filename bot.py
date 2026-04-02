"""
Armería Bot — Discord
"""
import sys
sys.stdout.reconfigure(line_buffering=True)

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timezone
from database import Database

from keep_alive import keep_alive
keep_alive()

TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

CHANNEL_INGRESO = 1488351094211088515
CHANNEL_EGRESO  = 1488351273597141012
CHANNEL_ARMERIA = 1488350783471882330
CHANNEL_LOGS    = 1489143935115984976

ALLOWED_ROLES = ["Armero", "Admin", "armero", "admin"]

BANNER_DASHBOARD = "https://i.imgur.com/4esIKj9.png"
BANNER_ACCION    = "https://i.imgur.com/AScCGjU.png"

ARMAS = [
    "Vintage", "SNS", "USP", "AP", "Skorpion",
    "Uzi", "Thompsom", "AK Compacta", "Lugger",
    "Escopeta Cortada", "Escopeta Doble Cañon", "Escopeta Strike"
]
CARGADORES = [
    "Cargador de Asalto (30)", "Cargador de Asalto (32)",
    "Cargador Escopeta",
    "Cargador de Sub (16)", "Cargador de Sub (30)",
    "Cargador de Pistola (12)", "Cargador de Pistola (16)"
]
MEJORAS = ["Cargador Ampliado", "Cargador de Tambor", "Silenciador", "Linterna", "Empuñadura"]

CATEGORIAS = {
    "arma":     ("🔫", "ARMAS",      ARMAS),
    "cargador": ("🔄", "CARGADORES", CARGADORES),
    "mejora":   ("⚙️",  "MEJORAS",    MEJORAS),
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
db: Database = None
_db_ready = False

# Almacén actualmente visible en el dashboard
almacen_activo = "Principal"

def has_permission(member):
    return any(r.name in ALLOWED_ROLES for r in member.roles)

def categoria_de_item(nombre):
    for cat, (_, _, items) in CATEGORIAS.items():
        if nombre in items:
            return cat
    return "arma"

def emoji_de_item(nombre):
    return CATEGORIAS[categoria_de_item(nombre)][0]

def separador():
    return "══════════════════════════════"


# ── Log permanente en #logs ───────────────────────────────────────────────────
async def enviar_log(tipo: str, item: str, cant: int, usuario: discord.Member,
                     almacen: str, motivo: str = None, notas: str = None) -> discord.Message:
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return None
    ch = guild.get_channel(CHANNEL_LOGS)
    if not ch:
        return None

    color  = 0x2ECC71 if tipo == "ingreso" else 0xE74C3C
    titulo = "📥  INGRESO — ARMERÍA" if tipo == "ingreso" else "📤  EGRESO — ARMERÍA"
    accion = f"**+{cant}**" if tipo == "ingreso" else f"**-{cant}**"

    embed = discord.Embed(title=titulo, color=color)
    embed.add_field(name="▸ Responsable", value=usuario.mention,                      inline=False)
    embed.add_field(name="▸ Almacén",     value=f"🏛️ **{almacen}**",                  inline=True)
    embed.add_field(name="▸ Ítem",        value=f"{emoji_de_item(item)} **{item}**",  inline=True)
    embed.add_field(name="▸ Cantidad",    value=accion,                               inline=True)
    if motivo and motivo != "—":
        embed.add_field(name="▸ Motivo", value=f"*{motivo}*", inline=False)
    if notas and notas != "—":
        embed.add_field(name="▸ Notas",  value=f"*{notas}*",  inline=False)
    embed.set_thumbnail(url=usuario.display_avatar.url)
    embed.set_footer(text=f"ID: {usuario.id}  •  Sistema de Armería")
    embed.timestamp = datetime.now(timezone.utc)

    return await ch.send(embed=embed)


# ── Re-flotar panel al fondo ──────────────────────────────────────────────────
async def reflotar_panel(canal_id: int):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(canal_id)
    if not ch:
        return

    if canal_id == CHANNEL_INGRESO:
        config_key = "panel_ingreso_id"
        embed = discord.Embed(
            title="📥  PANEL DE INGRESO",
            description=(
                f"{separador()}\n"
                "Registrá nuevos ítems al inventario de la armería.\n\n"
                "🔫  **Registrar Arma** — Pistolas, SMGs y escopetas\n"
                "🔄  **Registrar Cargador** — Todo tipo de cargadores\n"
                "⚙️  **Registrar Mejora** — Accesorios y modificaciones\n\n"
                f"*Solo personal con rol **Armero** o **Admin**.*\n"
                f"{separador()}"
            ),
            color=0x2ECC71
        )
        embed.set_image(url=BANNER_ACCION)
        embed.set_footer(text="Sistema de Armería  •  Panel de Ingreso")
        view = PanelIngreso()
    else:
        config_key = "panel_egreso_id"
        embed = discord.Embed(
            title="📤  PANEL DE EGRESO",
            description=(
                f"{separador()}\n"
                "Retirá ítems del inventario de la armería.\n\n"
                "📤  **Retirar Ítem** — Elegí ítem, cantidad y motivo.\n\n"
                f"⚠️  *Todos los egresos se registran con usuario y motivo obligatorio.*\n"
                f"{separador()}"
            ),
            color=0xE74C3C
        )
        embed.set_image(url=BANNER_ACCION)
        embed.set_footer(text="Sistema de Armería  •  Panel de Egreso")
        view = PanelEgreso()

    saved_id = await db.get_config(config_key)
    if saved_id:
        try:
            old_msg = await ch.fetch_message(int(saved_id))
            await old_msg.delete()
        except discord.NotFound:
            pass

    new_msg = await ch.send(embed=embed, view=view)
    await db.set_config(config_key, str(new_msg.id))


# ── Modal: Nombre de nuevo almacén ────────────────────────────────────────────
class ModalNuevoAlmacen(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Nueva Armería")
        self.nombre = discord.ui.TextInput(
            label="Nombre de la armería",
            placeholder="Ej: Armería Norte",
            max_length=40
        )
        self.add_item(self.nombre)

    async def on_submit(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        nombre = self.nombre.value.strip()
        if not nombre:
            return await interaction.response.send_message("❌ Nombre inválido.", ephemeral=True)
        if await db.almacen_existe(nombre):
            return await interaction.response.send_message(f"❌ Ya existe una armería llamada **{nombre}**.", ephemeral=True)
        await db.crear_almacen(nombre)
        await interaction.response.send_message(f"✅ Armería **{nombre}** creada correctamente.", ephemeral=True)
        print(f"✅ Almacén creado: {nombre}", flush=True)


# ── Select: Elegir almacén para eliminar ─────────────────────────────────────
class SelectEliminarAlmacen(discord.ui.Select):
    def __init__(self, almacenes: list[str]):
        options = [
            discord.SelectOption(label=a, value=a, emoji="🏛️")
            for a in almacenes
            if a != "Principal"  # No se puede eliminar el principal
        ]
        if not options:
            options = [discord.SelectOption(label="No hay armerías eliminables", value="none")]
        super().__init__(placeholder="Elegí la armería a eliminar", options=options)

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ No hay armerías para eliminar.", ephemeral=True)
        nombre = self.values[0]
        await db.eliminar_almacen(nombre)
        await interaction.response.send_message(f"🗑️ Armería **{nombre}** eliminada.", ephemeral=True)
        print(f"🗑️ Almacén eliminado: {nombre}", flush=True)


# ── Select: Elegir almacén para el dashboard ──────────────────────────────────
class SelectVerAlmacen(discord.ui.Select):
    def __init__(self, almacenes: list[str]):
        options = [
            discord.SelectOption(
                label=a, value=a, emoji="🏛️",
                default=(a == almacen_activo)
            )
            for a in almacenes
        ]
        super().__init__(placeholder="Elegí la armería a ver", options=options[:25])

    async def callback(self, interaction):
        global almacen_activo
        almacen_activo = self.values[0]
        await interaction.response.defer()
        # Forzar actualización inmediata del dashboard
        await forzar_dashboard()


# ── Select: Elegir almacén para ingreso/egreso ────────────────────────────────
class SelectAlmacenIngreso(discord.ui.Select):
    def __init__(self, almacenes: list[str], categoria: str):
        self.categoria = categoria
        options = [discord.SelectOption(label=a, value=a, emoji="🏛️") for a in almacenes]
        super().__init__(placeholder="Elegí la armería", options=options[:25])

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        v = discord.ui.View(timeout=60)
        v.add_item(SelectIngreso(self.categoria, self.values[0]))
        await interaction.response.edit_message(
            content=f"🏛️ **{self.values[0]}** — Seleccioná el ítem:",
            view=v
        )


class SelectAlmacenEgreso(discord.ui.Select):
    def __init__(self, almacenes: list[str]):
        options = [discord.SelectOption(label=a, value=a, emoji="🏛️") for a in almacenes]
        super().__init__(placeholder="Elegí la armería", options=options[:25])

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        almacen = self.values[0]
        inv = await db.get_inventario_con_stock(almacen)
        if not inv:
            return await interaction.response.edit_message(
                content=f"⚠️ **{almacen}** no tiene stock.", view=None
            )
        v = discord.ui.View(timeout=60)
        v.add_item(SelectEgreso(inv, almacen))
        await interaction.response.edit_message(
            content=f"🏛️ **{almacen}** — Seleccioná el ítem a retirar:",
            view=v
        )


# ── Modales de ingreso/egreso ─────────────────────────────────────────────────
class ModalIngreso(discord.ui.Modal):
    def __init__(self, categoria, item, almacen):
        super().__init__(title=f"Ingreso — {item}")
        self.categoria = categoria
        self.item = item
        self.almacen = almacen
        self.cantidad = discord.ui.TextInput(label="Cantidad", placeholder="Ej: 5", max_length=5)
        self.notas = discord.ui.TextInput(label="Notas (opcional)", required=False, max_length=200)
        self.add_item(self.cantidad)
        self.add_item(self.notas)

    async def on_submit(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        try:
            cant = int(self.cantidad.value)
            assert cant > 0
        except:
            return await interaction.response.send_message("❌ Cantidad inválida.", ephemeral=True)
        try:
            await db.add_item(self.item, self.categoria, cant, self.almacen)
            await db.log_movimiento("ingreso", self.item, self.categoria, cant,
                                    str(interaction.user), interaction.user.id,
                                    self.notas.value or "—", self.almacen)
        except Exception as e:
            print(f"❌ Error en ingreso DB: {e}", flush=True)
            return await interaction.response.send_message("❌ Error al guardar en la base de datos.", ephemeral=True)

        log_msg = await enviar_log(
            "ingreso", self.item, cant, interaction.user,
            self.almacen, notas=self.notas.value or None
        )

        logs_ch = bot.get_guild(GUILD_ID).get_channel(CHANNEL_LOGS)
        link = f"[🔗 Ver en #{logs_ch.name}]({log_msg.jump_url})" if log_msg else ""
        embed = discord.Embed(
            description=(
                f"📥  {interaction.user.mention} ingresó "
                f"**{cant}x {emoji_de_item(self.item)} {self.item}**"
                f" en 🏛️ **{self.almacen}**\n{link}"
            ),
            color=0x2ECC71
        )
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed)
        asyncio.create_task(reflotar_panel(CHANNEL_INGRESO))


class ModalEgreso(discord.ui.Modal):
    def __init__(self, item, stock_actual, almacen):
        super().__init__(title=f"Egreso — {item}")
        self.item = item
        self.stock_actual = stock_actual
        self.almacen = almacen
        self.cantidad = discord.ui.TextInput(
            label=f"Cantidad (stock: {stock_actual})", placeholder="Ej: 2", max_length=5)
        self.motivo = discord.ui.TextInput(
            label="Motivo (obligatorio)", placeholder="Ej: Operativo norte", max_length=300)
        self.add_item(self.cantidad)
        self.add_item(self.motivo)

    async def on_submit(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        try:
            cant = int(self.cantidad.value)
            assert cant > 0
        except:
            return await interaction.response.send_message("❌ Cantidad inválida.", ephemeral=True)
        if cant > self.stock_actual:
            return await interaction.response.send_message(
                f"❌ Stock insuficiente. Hay **{self.stock_actual}** unidades.", ephemeral=True)
        cat = categoria_de_item(self.item)
        try:
            await db.remove_item(self.item, cant, self.almacen)
            await db.log_movimiento("egreso", self.item, cat, cant,
                                    str(interaction.user), interaction.user.id,
                                    self.motivo.value, self.almacen)
        except Exception as e:
            print(f"❌ Error en egreso DB: {e}", flush=True)
            return await interaction.response.send_message("❌ Error al guardar en la base de datos.", ephemeral=True)

        log_msg = await enviar_log(
            "egreso", self.item, cant, interaction.user,
            self.almacen, motivo=self.motivo.value
        )

        logs_ch = bot.get_guild(GUILD_ID).get_channel(CHANNEL_LOGS)
        link = f"[🔗 Ver en #{logs_ch.name}]({log_msg.jump_url})" if log_msg else ""
        embed = discord.Embed(
            description=(
                f"📤  {interaction.user.mention} retiró "
                f"**{cant}x {emoji_de_item(self.item)} {self.item}**"
                f" de 🏛️ **{self.almacen}**\n{link}"
            ),
            color=0xE74C3C
        )
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.response.send_message(embed=embed)
        asyncio.create_task(reflotar_panel(CHANNEL_EGRESO))


# ── Selects de ítems ──────────────────────────────────────────────────────────
class SelectIngreso(discord.ui.Select):
    def __init__(self, categoria, almacen):
        self.cat = categoria
        self.almacen = almacen
        emoji, label, items = CATEGORIAS[categoria]
        super().__init__(
            placeholder=f"Seleccioná ítem de {label}",
            options=[discord.SelectOption(label=i, value=i, emoji=emoji) for i in items]
        )

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        await interaction.response.send_modal(ModalIngreso(self.cat, self.values[0], self.almacen))


class SelectEgreso(discord.ui.Select):
    def __init__(self, inventario, almacen):
        self.inv = {i["nombre"]: int(i["cantidad"] or 0) for i in inventario}
        self.almacen = almacen
        options = [
            discord.SelectOption(label=i["nombre"], value=i["nombre"],
                                 description=f"Stock: {i['cantidad']}",
                                 emoji=emoji_de_item(i["nombre"]))
            for i in inventario[:25]
        ] or [discord.SelectOption(label="Sin stock", value="none")]
        super().__init__(placeholder="Seleccioná el ítem a retirar", options=options)

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ No hay stock.", ephemeral=True)
        await interaction.response.send_modal(
            ModalEgreso(self.values[0], self.inv[self.values[0]], self.almacen)
        )


# ── Panel de Ingreso ──────────────────────────────────────────────────────────
class PanelIngreso(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _abrir_con_almacen(self, interaction, categoria):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        almacenes = await db.get_almacenes()
        if len(almacenes) == 1:
            # Si solo hay uno, saltar directo al select de ítems
            v = discord.ui.View(timeout=60)
            v.add_item(SelectIngreso(categoria, almacenes[0]))
            await interaction.response.send_message(
                f"🏛️ **{almacenes[0]}** — Seleccioná el ítem:", view=v, ephemeral=True
            )
        else:
            v = discord.ui.View(timeout=60)
            v.add_item(SelectAlmacenIngreso(almacenes, categoria))
            await interaction.response.send_message("Elegí la armería:", view=v, ephemeral=True)

    @discord.ui.button(label="Registrar Arma", style=discord.ButtonStyle.danger,
                       emoji="🔫", custom_id="ing_arma")
    async def btn_arma(self, interaction, button):
        await self._abrir_con_almacen(interaction, "arma")

    @discord.ui.button(label="Registrar Cargador", style=discord.ButtonStyle.primary,
                       emoji="🔄", custom_id="ing_cargador")
    async def btn_carg(self, interaction, button):
        await self._abrir_con_almacen(interaction, "cargador")

    @discord.ui.button(label="Registrar Mejora", style=discord.ButtonStyle.secondary,
                       emoji="⚙️", custom_id="ing_mejora")
    async def btn_mej(self, interaction, button):
        await self._abrir_con_almacen(interaction, "mejora")

    @discord.ui.button(label="Nueva Armería", style=discord.ButtonStyle.success,
                       emoji="➕", custom_id="ing_nueva_armeria")
    async def btn_nueva(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        await interaction.response.send_modal(ModalNuevoAlmacen())


# ── Panel de Egreso ───────────────────────────────────────────────────────────
class PanelEgreso(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Retirar Ítem", style=discord.ButtonStyle.danger,
                       emoji="📤", custom_id="egr_item")
    async def btn_egr(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        if not _db_ready:
            return await interaction.response.send_message("⏳ El bot todavía está iniciando.", ephemeral=True)
        almacenes = await db.get_almacenes()
        if len(almacenes) == 1:
            inv = await db.get_inventario_con_stock(almacenes[0])
            if not inv:
                return await interaction.response.send_message("⚠️ Inventario vacío.", ephemeral=True)
            v = discord.ui.View(timeout=60)
            v.add_item(SelectEgreso(inv, almacenes[0]))
            await interaction.response.send_message(
                f"🏛️ **{almacenes[0]}** — Seleccioná el ítem:", view=v, ephemeral=True
            )
        else:
            v = discord.ui.View(timeout=60)
            v.add_item(SelectAlmacenEgreso(almacenes))
            await interaction.response.send_message("Elegí la armería:", view=v, ephemeral=True)

    @discord.ui.button(label="Eliminar Armería", style=discord.ButtonStyle.danger,
                       emoji="🗑️", custom_id="egr_eliminar_armeria")
    async def btn_eliminar(self, interaction, button):
        if not any(r.name in ["Admin", "admin"] for r in interaction.user.roles):
            return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
        almacenes = await db.get_almacenes()
        eliminables = [a for a in almacenes if a != "Principal"]
        if not eliminables:
            return await interaction.response.send_message(
                "❌ No hay armerías para eliminar (la Principal no se puede borrar).", ephemeral=True
            )
        v = discord.ui.View(timeout=60)
        v.add_item(SelectEliminarAlmacen(eliminables))
        await interaction.response.send_message("Elegí la armería a eliminar:", view=v, ephemeral=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────
dashboard_message_id = None

class DashboardView(discord.ui.View):
    def __init__(self, almacenes: list[str]):
        super().__init__(timeout=None)
        self.add_item(SelectVerAlmacen(almacenes))

def fmt_stock(n):
    n = int(n or 0)
    if n == 0:
        return "**` 0 `**"
    if n <= 3:
        return f"**`{n:>2}`** ⚠️"
    return f"**`{n:>2}`**"

def build_embed(inventario, movs, almacen_nombre):
    embed = discord.Embed(
        title=f"🏛️  {almacen_nombre.upper()}  —  INVENTARIO",
        description=(
            f"{separador()}\n"
            f"  Sistema de control de stock en tiempo real\n"
            f"{separador()}"
        ),
        color=0x8B0000
    )
    embed.set_image(url=BANNER_DASHBOARD)

    armas_lines = "\n".join(
        f"🔫  `{n:<26}`  {fmt_stock(inventario.get(n, 0))}" for n in ARMAS
    )
    embed.add_field(name="╔══  🔫  ARMAS  ══╗", value=armas_lines, inline=False)
    embed.add_field(name="", value=separador(), inline=False)

    carg_lines = "\n".join(
        f"🔄  `{n:<32}`  {fmt_stock(inventario.get(n, 0))}" for n in CARGADORES
    )
    embed.add_field(name="╔══  🔄  CARGADORES  ══╗", value=carg_lines, inline=False)
    embed.add_field(name="", value=separador(), inline=False)

    mej_lines = "\n".join(
        f"⚙️  `{n:<24}`  {fmt_stock(inventario.get(n, 0))}" for n in MEJORAS
    )
    embed.add_field(name="╔══  ⚙️  MEJORAS  ══╗", value=mej_lines, inline=False)

    if movs:
        embed.add_field(name="", value=separador(), inline=False)
        lines = []
        for m in movs[:5]:
            e = "📥" if m["tipo"] == "ingreso" else "📤"
            s = "+" if m["tipo"] == "ingreso" else "-"
            ts = m["fecha"][:16].replace("T", " ")
            lines.append(
                f"{e}  `{ts}`  **{m['usuario'].split('#')[0]}**  —  "
                f"{emoji_de_item(m['item'])} {m['item']}  `{s}{m['cantidad']}`"
            )
        embed.add_field(name="📋  ÚLTIMOS MOVIMIENTOS", value="\n".join(lines), inline=False)

    total = sum(int(v or 0) for v in inventario.values())
    embed.set_footer(text=f"Total en stock: {total} unidades  •  ⚠️ = stock bajo (≤3)  •  Actualizado")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


async def forzar_dashboard():
    """Actualiza el dashboard inmediatamente con el almacén activo."""
    global dashboard_message_id
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CHANNEL_ARMERIA)
    if not ch: return
    try:
        raw = await db.get_inventario_completo(almacen_activo)
        inv = {r["nombre"]: int(r["cantidad"] or 0) for r in raw}
        movs = await db.get_historial(5, almacen_activo)
        almacenes = await db.get_almacenes()
        embed = build_embed(inv, movs, almacen_activo)
        view = DashboardView(almacenes)
        if dashboard_message_id:
            try:
                msg = await ch.fetch_message(dashboard_message_id)
                await msg.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                dashboard_message_id = None
        await ch.purge(limit=50)
        msg = await ch.send(embed=embed, view=view)
        dashboard_message_id = msg.id
        await db.set_config("dashboard_message_id", str(msg.id))
    except Exception as e:
        print(f"⚠️ Error en forzar_dashboard: {e}", flush=True)


@tasks.loop(seconds=30)
async def actualizar_dashboard():
    if not _db_ready:
        return
    await forzar_dashboard()


# ── Slash commands ────────────────────────────────────────────────────────────
@bot.tree.command(name="historial", description="Ver historial de movimientos")
@app_commands.describe(cantidad="Cantidad de registros (máx 20)", almacen="Filtrar por armería (opcional)")
async def cmd_historial(interaction, cantidad: int = 10, almacen: str = None):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
    registros = await db.get_historial(min(max(cantidad, 1), 20), almacen)
    if not registros:
        return await interaction.response.send_message("📋 Sin movimientos.", ephemeral=True)

    titulo = f"📋  HISTORIAL — {almacen.upper()}" if almacen else "📋  HISTORIAL DE MOVIMIENTOS"
    embed = discord.Embed(title=titulo, description=separador(), color=0x8B0000)
    lines = []
    for r in registros:
        e = "📥" if r["tipo"] == "ingreso" else "📤"
        s = "+" if r["tipo"] == "ingreso" else "-"
        ts = r["fecha"][:16].replace("T", " ")
        alm = f" 🏛️ *{r.get('almacen','?')}*" if not almacen else ""
        mot = f"\n  *↳ {r['motivo']}*" if r.get("motivo") and r["motivo"] != "—" else ""
        lines.append(
            f"{e}  `{ts}`  **{r['usuario'].split('#')[0]}**{alm}\n"
            f"  {emoji_de_item(r['item'])} {r['item']}  `{s}{r['cantidad']}`{mot}"
        )
    embed.description = separador() + "\n\n" + "\n\n".join(lines)
    embed.set_image(url=BANNER_ACCION)
    embed.set_footer(text=f"Sistema de Armería  •  Mostrando últimos {len(registros)} movimientos")
    embed.timestamp = datetime.now(timezone.utc)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stock", description="Ver stock de un ítem en una armería")
@app_commands.describe(item="Nombre del ítem", almacen="Nombre de la armería")
async def cmd_stock(interaction, item: str, almacen: str = "Principal"):
    row = await db.get_item(item, almacen)
    if not row:
        return await interaction.response.send_message(
            f"❌ **{item}** no encontrado en **{almacen}**.", ephemeral=True
        )
    n = int(row["cantidad"] or 0)
    color  = 0xE74C3C if n <= 3 else 0x2ECC71
    estado = "⚠️  Stock bajo" if n <= 3 else "✅  En stock"

    embed = discord.Embed(
        title=f"{emoji_de_item(item)}  {item}",
        description=separador(), color=color
    )
    embed.add_field(name="▸ Armería",   value=f"🏛️ {almacen}", inline=True)
    embed.add_field(name="▸ Stock",     value=f"**{n}** unidades", inline=True)
    embed.add_field(name="▸ Estado",    value=estado, inline=True)
    embed.set_image(url=BANNER_ACCION)
    embed.set_footer(text="Sistema de Armería")
    embed.timestamp = datetime.now(timezone.utc)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="resetpaneles", description="[ADMIN] Resetea los paneles")
async def cmd_reset(interaction):
    if not any(r.name in ["Admin", "admin"] for r in interaction.user.roles):
        return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await setup_panels(interaction.guild, force=True)
    await interaction.followup.send("✅ Paneles reseteados.", ephemeral=True)


# ── Setup de paneles ──────────────────────────────────────────────────────────
async def setup_panels(guild, force=False):
    ch = guild.get_channel(CHANNEL_INGRESO)
    if ch:
        saved_id = await db.get_config("panel_ingreso_id")
        panel_exists = False
        if saved_id and not force:
            try:
                await ch.fetch_message(int(saved_id))
                panel_exists = True
                print("✅ Panel ingreso ya existe", flush=True)
            except discord.NotFound:
                panel_exists = False
        if not panel_exists:
            await ch.purge(limit=50)
            embed = discord.Embed(
                title="📥  PANEL DE INGRESO",
                description=(
                    f"{separador()}\n"
                    "Registrá nuevos ítems al inventario de la armería.\n\n"
                    "🔫  **Registrar Arma** — Pistolas, SMGs y escopetas\n"
                    "🔄  **Registrar Cargador** — Todo tipo de cargadores\n"
                    "⚙️  **Registrar Mejora** — Accesorios y modificaciones\n"
                    "➕  **Nueva Armería** — Crear una nueva armería\n\n"
                    f"*Solo personal con rol **Armero** o **Admin**.*\n"
                    f"{separador()}"
                ),
                color=0x2ECC71
            )
            embed.set_image(url=BANNER_ACCION)
            embed.set_footer(text="Sistema de Armería  •  Panel de Ingreso")
            msg = await ch.send(embed=embed, view=PanelIngreso())
            await db.set_config("panel_ingreso_id", str(msg.id))

    ch = guild.get_channel(CHANNEL_EGRESO)
    if ch:
        saved_id = await db.get_config("panel_egreso_id")
        panel_exists = False
        if saved_id and not force:
            try:
                await ch.fetch_message(int(saved_id))
                panel_exists = True
                print("✅ Panel egreso ya existe", flush=True)
            except discord.NotFound:
                panel_exists = False
        if not panel_exists:
            await ch.purge(limit=50)
            embed = discord.Embed(
                title="📤  PANEL DE EGRESO",
                description=(
                    f"{separador()}\n"
                    "Retirá ítems del inventario de la armería.\n\n"
                    "📤  **Retirar Ítem** — Elegí armería, ítem, cantidad y motivo.\n"
                    "🗑️  **Eliminar Armería** — Solo admins.\n\n"
                    f"⚠️  *Todos los egresos se registran con usuario y motivo obligatorio.*\n"
                    f"{separador()}"
                ),
                color=0xE74C3C
            )
            embed.set_image(url=BANNER_ACCION)
            embed.set_footer(text="Sistema de Armería  •  Panel de Egreso")
            msg = await ch.send(embed=embed, view=PanelEgreso())
            await db.set_config("panel_egreso_id", str(msg.id))

    print("✅ Paneles verificados", flush=True)


# ── Inicialización en background ──────────────────────────────────────────────
async def startup():
    global db, dashboard_message_id, _db_ready, almacen_activo

    print("🔄 Iniciando base de datos...", flush=True)
    try:
        db = Database()
        await db.init()
        _db_ready = True
    except Exception as e:
        print(f"❌ FATAL — No se pudo conectar a la DB: {e}", flush=True)
        return

    try:
        saved = await db.get_config("dashboard_message_id")
        if saved:
            dashboard_message_id = int(saved)
        saved_almacen = await db.get_config("almacen_activo")
        if saved_almacen:
            almacen_activo = saved_almacen
    except Exception as e:
        print(f"⚠️ No se pudo recuperar config: {e}", flush=True)

    try:
        guild_obj = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        await bot.tree.sync(guild=guild_obj)
        print("✅ Slash commands sincronizados", flush=True)
    except Exception as e:
        print(f"❌ Error sincronizando slash commands: {e}", flush=True)

    try:
        real_guild = bot.get_guild(GUILD_ID)
        if real_guild:
            await setup_panels(real_guild)
        else:
            print(f"⚠️ No se encontró el guild con ID {GUILD_ID}", flush=True)
    except Exception as e:
        print(f"❌ Error configurando paneles: {e}", flush=True)

    if not actualizar_dashboard.is_running():
        actualizar_dashboard.start()
        print("✅ Dashboard iniciado", flush=True)


# ── on_ready ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}", flush=True)
    bot.add_view(PanelIngreso())
    bot.add_view(PanelEgreso())
    asyncio.create_task(startup())


bot.run(TOKEN)
