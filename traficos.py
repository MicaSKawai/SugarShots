"""
traficos.py — Avisos de actividades HUB
"""
import discord
from discord.ext import tasks
from datetime import datetime
import pytz
import os

CHANNEL_TRAFICOS = 1489507668207861941
ROL_ARMERO_ID    = 1488351409433743450

HUB_TZ = pytz.timezone("Europe/Madrid")

ACTIVIDADES = [
    # ── Barriles a la deriva ── Miercoles(2) y Sabado(5)
    {"nombre": "Barriles a la Deriva",       "dias": [2, 5],    "inicio": (9,  0), "fin": (12, 0), "imagen": "https://i.imgur.com/pmnYk3M.png", "color": 0x1A8CFF},
    {"nombre": "Barriles a la Deriva",       "dias": [2, 5],    "inicio": (16, 0), "fin": (18, 0), "imagen": "https://i.imgur.com/pmnYk3M.png", "color": 0x1A8CFF},

    # ── Tráfico Aéreo Avanzado ── Viernes(4) y Domingo(6)
    {"nombre": "Tráfico Aéreo Avanzado",     "dias": [4, 6],    "inicio": (1,  0), "fin": (3,  0), "imagen": "https://i.imgur.com/J83mr1C.png", "color": 0xF39C12},
    {"nombre": "Tráfico Aéreo Avanzado",     "dias": [4, 6],    "inicio": (10, 0), "fin": (12, 0), "imagen": "https://i.imgur.com/J83mr1C.png", "color": 0xF39C12},
    {"nombre": "Tráfico Aéreo Avanzado",     "dias": [4, 6],    "inicio": (14, 0), "fin": (20, 0), "imagen": "https://i.imgur.com/J83mr1C.png", "color": 0xF39C12},

    # ── Misión de Tráfico Avanzado ── Martes(1), Miercoles(2), Domingo(6)
    {"nombre": "Misión de Tráfico Avanzado", "dias": [1, 2, 6], "inicio": (7,  0), "fin": (10, 0), "imagen": "https://i.imgur.com/G6UDaGU.png", "color": 0x8E44AD},
    {"nombre": "Misión de Tráfico Avanzado", "dias": [1, 2, 6], "inicio": (14, 0), "fin": (20, 0), "imagen": "https://i.imgur.com/G6UDaGU.png", "color": 0x8E44AD},
    {"nombre": "Misión de Tráfico Avanzado", "dias": [1, 2, 6], "inicio": (21, 0), "fin": (22, 0), "imagen": "https://i.imgur.com/G6UDaGU.png", "color": 0x8E44AD},
]

avisos_enviados: set = set()


def get_key(actividad, dia_año, anticipacion):
    h, m = actividad["inicio"]
    return f"{actividad['nombre']}_{dia_año}_{h:02d}{m:02d}_{anticipacion}"


async def mandar_aviso(ch, mencion, act, anticipacion, ahora_hub):
    h_inicio, m_inicio = act["inicio"]
    h_fin, m_fin       = act["fin"]

    if anticipacion == 30:
        titulo   = f"⏰  {act['nombre'].upper()}  —  EN 30 MINUTOS"
        color    = act["color"]
        urgencia = "🟡  Preparate, faltan **30 minutos**."
    else:
        titulo   = f"🚨  {act['nombre'].upper()}  —  EN 10 MINUTOS"
        color    = 0xE74C3C
        urgencia = "🔴  ¡Última llamada! Faltan **10 minutos**."

    embed = discord.Embed(title=titulo, color=color)
    embed.add_field(name="▸ Actividad",   value=f"**{act['nombre']}**",                        inline=True)
    embed.add_field(name="▸ Horario HUB", value=f"**{h_inicio:02d}:{m_inicio:02d}** → **{h_fin:02d}:{m_fin:02d}**", inline=True)
    embed.add_field(name="▸ Estado",      value=urgencia,                                       inline=False)
    embed.set_image(url=act["imagen"])
    embed.set_footer(text=f"Hora HUB actual: {ahora_hub.strftime('%H:%M')}  •  Sistema de Armería")
    embed.timestamp = ahora_hub

    await ch.send(content=mencion, embed=embed)
    print(f"✅ Aviso enviado: {act['nombre']} — {anticipacion}min antes", flush=True)


async def verificar_avisos(bot):
    ahora_hub  = datetime.now(HUB_TZ)
    dia_semana = ahora_hub.weekday()
    hora_actual = ahora_hub.hour
    min_actual  = ahora_hub.minute
    dia_año     = ahora_hub.timetuple().tm_yday

    guild = bot.get_guild(int(os.getenv("GUILD_ID", "0")))
    if not guild: return
    ch = guild.get_channel(CHANNEL_TRAFICOS)
    if not ch: return
    rol = guild.get_role(ROL_ARMERO_ID)
    mencion = rol.mention if rol else "@Armero"

    for act in ACTIVIDADES:
        if dia_semana not in act["dias"]:
            continue
        h_inicio, m_inicio = act["inicio"]
        minutos_inicio = h_inicio * 60 + m_inicio
        minutos_ahora  = hora_actual * 60 + min_actual

        for anticipacion in [30, 10]:
            minutos_aviso = minutos_inicio - anticipacion
            if minutos_aviso < 0:
                continue
            key = get_key(act, dia_año, anticipacion)
            if key in avisos_enviados:
                continue
            if minutos_aviso <= minutos_ahora < minutos_aviso + 1:
                avisos_enviados.add(key)
                await mandar_aviso(ch, mencion, act, anticipacion, ahora_hub)


async def test_aviso(bot, nombre_actividad: str = None):
    """Manda avisos de prueba — si no se especifica actividad, manda las 3."""
    ahora_hub = datetime.now(HUB_TZ)
    guild = bot.get_guild(int(os.getenv("GUILD_ID", "0")))
    if not guild: return False
    ch = guild.get_channel(CHANNEL_TRAFICOS)
    if not ch: return False
    rol = guild.get_role(ROL_ARMERO_ID)
    mencion = rol.mention if rol else "@Armero"

    # Buscar actividades únicas por nombre
    nombres_vistos = set()
    actividades_unicas = []
    for act in ACTIVIDADES:
        if act["nombre"] not in nombres_vistos:
            nombres_vistos.add(act["nombre"])
            actividades_unicas.append(act)

    # Filtrar si se especifica una
    if nombre_actividad:
        actividades_unicas = [a for a in actividades_unicas if nombre_actividad.lower() in a["nombre"].lower()]
        if not actividades_unicas:
            return False

    # Mandar aviso de 30min y 10min de cada actividad
    for act in actividades_unicas:
        await mandar_aviso(ch, mencion, act, 30, ahora_hub)
        await mandar_aviso(ch, mencion, act, 10, ahora_hub)

    return True


def iniciar_traficos(bot):
    @tasks.loop(minutes=1)
    async def loop_traficos():
        try:
            await verificar_avisos(bot)
        except Exception as e:
            print(f"⚠️ Error en traficos: {e}", flush=True)

    loop_traficos.start()
    print("✅ Sistema de tráficos iniciado", flush=True)
