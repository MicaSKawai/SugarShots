"""
Armería Bot — Discord
"""
import sys
sys.stdout.reconfigure(line_buffering=True)  # Fuerza prints en tiempo real en Render

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime
from database import Database

from keep_alive import keep_alive
keep_alive()

TOKEN    = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

CHANNEL_INGRESO = 1488351094211088515
CHANNEL_EGRESO  = 1488351273597141012
CHANNEL_ARMERIA = 1488350783471882330

ALLOWED_ROLES = ["Armero", "Admin", "armero", "admin"]

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
_panels_initialized = False
_db_ready = False

def has_permission(member):
    return any(r.name in ALLOWED_ROLES for r in member.roles)

def categoria_de_item(nombre):
    for cat, (_, _, items) in CATEGORIAS.items():
        if nombre in items:
            return cat
    return "arma"

def emoji_de_item(nombre):
    return CATEGORIAS[categoria_de_item(nombre)][0]

# ── Modales ───────────────────────────────────────────────────────────────────
class ModalIngreso(discord.ui.Modal):
    def __init__(self, categoria, item):
        super().__init__(title=f"Ingreso — {item}")
        self.categoria = categoria
        self.item = item
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
            await db.add_item(self.item, self.categoria, cant)
            await db.log_movimiento("ingreso", self.item, self.categoria, cant,
                                    str(interaction.user), interaction.user.id,
                                    self.notas.value or "—")
        except Exception as e:
            print(f"❌ Error en ingreso DB: {e}", flush=True)
            return await interaction.response.send_message("❌ Error al guardar en la base de datos.", ephemeral=True)
        embed = discord.Embed(title="✅ Ingreso Registrado", color=0x2ECC71)
        embed.add_field(name="Ítem",     value=f"{emoji_de_item(self.item)} {self.item}", inline=True)
        embed.add_field(name="Cantidad", value=f"+{cant}",                               inline=True)
        embed.add_field(name="Armero",   value=interaction.user.mention,                 inline=True)
        if self.notas.value:
            embed.add_field(name="Notas", value=self.notas.value, inline=False)
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Sistema de Armería")
        await interaction.response.send_message(embed=embed)


class ModalEgreso(discord.ui.Modal):
    def __init__(self, item, stock_actual):
        super().__init__(title=f"Egreso — {item}")
        self.item = item
        self.stock_actual = stock_actual
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
            await db.remove_item(self.item, cant)
            await db.log_movimiento("egreso", self.item, cat, cant,
                                    str(interaction.user), interaction.user.id, self.motivo.value)
        except Exception as e:
            print(f"❌ Error en egreso DB: {e}", flush=True)
            return await interaction.response.send_message("❌ Error al guardar en la base de datos.", ephemeral=True)
        embed = discord.Embed(title="📤 Egreso Registrado", color=0xE74C3C)
        embed.add_field(name="Ítem",     value=f"{emoji_de_item(self.item)} {self.item}", inline=True)
        embed.add_field(name="Cantidad", value=f"-{cant}",                               inline=True)
        embed.add_field(name="Armero",   value=interaction.user.mention,                 inline=True)
        embed.add_field(name="Motivo",   value=self.motivo.value,                        inline=False)
        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Sistema de Armería")
        await interaction.response.send_message(embed=embed)


# ── Selects ───────────────────────────────────────────────────────────────────
class SelectIngreso(discord.ui.Select):
    def __init__(self, categoria):
        self.cat = categoria
        emoji, label, items = CATEGORIAS[categoria]
        super().__init__(
            placeholder=f"Seleccioná ítem de {label}",
            options=[discord.SelectOption(label=i, value=i, emoji=emoji) for i in items]
        )

    async def callback(self, interaction):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        await interaction.response.send_modal(ModalIngreso(self.cat, self.values[0]))


class SelectEgreso(discord.ui.Select):
    def __init__(self, inventario):
        self.inv = {i["nombre"]: i["cantidad"] for i in inventario}
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
        await interaction.response.send_modal(ModalEgreso(self.values[0], self.inv[self.values[0]]))


# ── Paneles ───────────────────────────────────────────────────────────────────
class PanelIngreso(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Registrar Arma", style=discord.ButtonStyle.danger,
                       emoji="🔫", custom_id="ing_arma")
    async def btn_arma(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        v = discord.ui.View(timeout=60)
        v.add_item(SelectIngreso("arma"))
        await interaction.response.send_message("Seleccioná el arma:", view=v, ephemeral=True)

    @discord.ui.button(label="Registrar Cargador", style=discord.ButtonStyle.primary,
                       emoji="🔄", custom_id="ing_cargador")
    async def btn_carg(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        v = discord.ui.View(timeout=60)
        v.add_item(SelectIngreso("cargador"))
        await interaction.response.send_message("Seleccioná el cargador:", view=v, ephemeral=True)

    @discord.ui.button(label="Registrar Mejora", style=discord.ButtonStyle.secondary,
                       emoji="⚙️", custom_id="ing_mejora")
    async def btn_mej(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        v = discord.ui.View(timeout=60)
        v.add_item(SelectIngreso("mejora"))
        await interaction.response.send_message("Seleccioná la mejora:", view=v, ephemeral=True)


class PanelEgreso(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Retirar Ítem", style=discord.ButtonStyle.danger,
                       emoji="📤", custom_id="egr_item")
    async def btn_egr(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
        if not _db_ready:
            return await interaction.response.send_message("⏳ El bot todavía está iniciando, intentá en unos segundos.", ephemeral=True)
        inv = await db.get_inventario_con_stock()
        if not inv:
            return await interaction.response.send_message("⚠️ Inventario vacío.", ephemeral=True)
        v = discord.ui.View(timeout=60)
        v.add_item(SelectEgreso(inv))
        await interaction.response.send_message("Seleccioná el ítem a retirar:", view=v, ephemeral=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────
dashboard_message_id = None

def build_bar(v, mx=20, ln=8):
    if v == 0: return "░" * ln
    f = min(int((v / mx) * ln), ln)
    return "█" * f + "░" * (ln - f)

def build_embed(inventario, movs):
    embed = discord.Embed(title="🏛️  ARMERÍA — INVENTARIO EN TIEMPO REAL", color=0x1A1A2E)
    embed.add_field(
        name="🔫  ARMAS",
        value="\n".join(f"`{n:<24}` {build_bar(inventario.get(n,0))} **{inventario.get(n,0)}**" for n in ARMAS),
        inline=False
    )
    embed.add_field(
        name="🔄  CARGADORES",
        value="\n".join(f"`{n:<30}` {build_bar(inventario.get(n,0),50)} **{inventario.get(n,0)}**" for n in CARGADORES),
        inline=False
    )
    embed.add_field(
        name="⚙️  MEJORAS",
        value="\n".join(f"`{n:<22}` {build_bar(inventario.get(n,0))} **{inventario.get(n,0)}**" for n in MEJORAS),
        inline=False
    )
    if movs:
        lines = []
        for m in movs[:5]:
            e = "📥" if m["tipo"]=="ingreso" else "📤"
            s = "+" if m["tipo"]=="ingreso" else "-"
            ts = m["fecha"][:16].replace("T"," ")
            lines.append(f"{e} `{ts}` **{m['usuario'].split('#')[0]}** — {m['item']} {s}{m['cantidad']}")
        embed.add_field(name="📋  ÚLTIMOS MOVIMIENTOS", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"Total en stock: {sum(inventario.values())}  •  Actualizado")
    embed.timestamp = datetime.utcnow()
    return embed

@tasks.loop(seconds=30)
async def actualizar_dashboard():
    global dashboard_message_id
    if not _db_ready:
        return
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CHANNEL_ARMERIA)
    if not ch: return
    try:
        raw = await db.get_inventario_completo()
        inv = {r["nombre"]: r["cantidad"] for r in raw}
        movs = await db.get_historial(5)
        embed = build_embed(inv, movs)
        if dashboard_message_id:
            try:
                msg = await ch.fetch_message(dashboard_message_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                dashboard_message_id = None
        await ch.purge(limit=10)
        msg = await ch.send(embed=embed)
        dashboard_message_id = msg.id
        await db.set_config("dashboard_message_id", str(msg.id))
    except Exception as e:
        print(f"⚠️ Error actualizando dashboard: {e}", flush=True)


# ── Slash commands ────────────────────────────────────────────────────────────
@bot.tree.command(name="historial", description="Ver historial de movimientos")
@app_commands.describe(cantidad="Cantidad de registros (máx 20)")
async def cmd_historial(interaction, cantidad: int = 10):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)
    registros = await db.get_historial(min(max(cantidad,1),20))
    if not registros:
        return await interaction.response.send_message("📋 Sin movimientos.", ephemeral=True)
    embed = discord.Embed(title=f"📋 Historial — Últimos {cantidad}", color=0x3498DB)
    lines = []
    for r in registros:
        e = "📥" if r["tipo"]=="ingreso" else "📤"
        s = "+" if r["tipo"]=="ingreso" else "-"
        ts = r["fecha"][:16].replace("T"," ")
        mot = f" | *{r['motivo']}*" if r.get("motivo") and r["motivo"] != "—" else ""
        lines.append(f"{e} `{ts}` **{r['usuario'].split('#')[0]}** — {emoji_de_item(r['item'])} {r['item']} {s}{r['cantidad']}{mot}")
    embed.description = "\n".join(lines)
    embed.set_footer(text="Sistema de Armería")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stock", description="Ver stock de un ítem")
@app_commands.describe(item="Nombre del ítem")
async def cmd_stock(interaction, item: str):
    row = await db.get_item(item)
    if not row:
        return await interaction.response.send_message(f"❌ **{item}** no encontrado.", ephemeral=True)
    embed = discord.Embed(title=f"{emoji_de_item(item)} {item}", color=0x9B59B6)
    embed.add_field(name="Stock", value=str(row["cantidad"]))
    embed.add_field(name="Categoría", value=row["categoria"].capitalize())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="resetpaneles", description="[ADMIN] Resetea los paneles")
async def cmd_reset(interaction):
    if not any(r.name in ["Admin","admin"] for r in interaction.user.roles):
        return await interaction.response.send_message("❌ Solo admins.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    global _panels_initialized
    _panels_initialized = False
    await setup_panels(interaction.guild)
    await interaction.followup.send("✅ Paneles reseteados.", ephemeral=True)


# ── Setup de paneles ──────────────────────────────────────────────────────────
async def setup_panels(guild):
    global _panels_initialized
    ch = guild.get_channel(CHANNEL_INGRESO)
    if ch:
        await ch.purge(limit=10)
        embed = discord.Embed(
            title="📥  PANEL DE INGRESO",
            description=(
                "Registrá nuevos ítems al inventario de la armería.\n\n"
                "**🔫 Registrar Arma** — Pistolas, SMGs y escopetas\n"
                "**🔄 Registrar Cargador** — Todo tipo de cargadores\n"
                "**⚙️ Registrar Mejora** — Accesorios y modificaciones\n\n"
                "*Solo personal con rol **Armero** o **Admin**.*"
            ),
            color=0x2ECC71
        )
        embed.set_footer(text="Sistema de Armería • Panel de Ingreso")
        await ch.send(embed=embed, view=PanelIngreso())

    ch = guild.get_channel(CHANNEL_EGRESO)
    if ch:
        await ch.purge(limit=10)
        embed = discord.Embed(
            title="📤  PANEL DE EGRESO",
            description=(
                "Retirá ítems del inventario de la armería.\n\n"
                "**📤 Retirar Ítem** — Elegí ítem, cantidad y motivo.\n\n"
                "⚠️ *Todos los egresos se registran con usuario y motivo obligatorio.*"
            ),
            color=0xE74C3C
        )
        embed.set_footer(text="Sistema de Armería • Panel de Egreso")
        await ch.send(embed=embed, view=PanelEgreso())

    _panels_initialized = True
    print("✅ Paneles configurados", flush=True)


# ── Inicialización en background ──────────────────────────────────────────────
async def startup():
    global db, dashboard_message_id, _panels_initialized, _db_ready

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
    except Exception as e:
        print(f"⚠️ No se pudo recuperar dashboard_message_id: {e}", flush=True)

    try:
        guild_obj = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        await bot.tree.sync(guild=guild_obj)
        print("✅ Slash commands sincronizados", flush=True)
    except Exception as e:
        print(f"❌ Error sincronizando slash commands: {e}", flush=True)

    if not _panels_initialized:
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
