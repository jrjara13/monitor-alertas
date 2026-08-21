"""
alertas_telegram.py
Envia a Telegram solo los CAMBIOS de señal, no el estado completo.

Alcance:
  - Watchlist: cualquier cambio de señal.
  - Resto del universo: solo cuando una emisora ENTRA a COMPRA FUERTE.

Guarda el estado previo en estado_senales.json para poder comparar.
En la primera corrida no manda alertas: solo establece la linea base.
"""
import json
import os
import time
from datetime import datetime, timezone
from urllib import request, parse, error

CARPETA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
ARCHIVO_ALERTAS = os.path.join(CARPETA, "alertas.json")
ARCHIVO_ESTADO = os.path.join(CARPETA, "estado_senales.json")
ARCHIVO_WATCHLIST = "watchlist.txt"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

MAX_NUEVAS_COMPRA_FUERTE = 12
LIMITE_TELEGRAM = 3900

EMOJI = {
    "COMPRA FUERTE": "🟢",
    "COMPRA": "🟩",
    "MANTENER / OBSERVAR": "⬜️",
    "VENTA": "🟥",
    "VENTA FUERTE": "🔴",
}
ORDEN = ["VENTA FUERTE", "VENTA", "MANTENER / OBSERVAR", "COMPRA", "COMPRA FUERTE"]


def leer_watchlist() -> set:
    if not os.path.exists(ARCHIVO_WATCHLIST):
        return set()
    with open(ARCHIVO_WATCHLIST, encoding="utf-8") as f:
        return {l.strip().upper() for l in f
                if l.strip() and not l.strip().startswith("#")}


def cargar_json(ruta, defecto):
    if not os.path.exists(ruta):
        return defecto
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠ No se pudo leer {ruta}: {e}")
        return defecto


def enviar(texto: str) -> bool:
    """Envia un mensaje a Telegram. Retorna True si se entrego."""
    if not TOKEN or not CHAT_ID:
        print("⚠ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID. No se envia nada.")
        return False
    datos = parse.urlencode({
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        with request.urlopen(request.Request(url, data=datos), timeout=30) as r:
            respuesta = json.loads(r.read().decode())
            if not respuesta.get("ok"):
                print(f"⚠ Telegram respondio: {respuesta}")
                return False
            return True
    except error.HTTPError as e:
        cuerpo = e.read().decode(errors="replace")[:300]
        print(f"⚠ Error HTTP {e.code} de Telegram: {cuerpo}")
        return False
    except Exception as e:
        print(f"⚠ No se pudo contactar a Telegram: {e}")
        return False


def enviar_por_partes(lineas: list, encabezado: str):
    """Arma mensajes respetando el limite de longitud de Telegram."""
    bloques, actual = [], encabezado
    for linea in lineas:
        if len(actual) + len(linea) + 1 > LIMITE_TELEGRAM:
            bloques.append(actual)
            actual = ""
        actual += "\n" + linea
    if actual.strip():
        bloques.append(actual)
    for i, b in enumerate(bloques):
        sufijo = f"\n\n<i>({i+1} de {len(bloques)})</i>" if len(bloques) > 1 else ""
        if enviar(b + sufijo):
            print(f"  Mensaje {i+1}/{len(bloques)} enviado.")
        time.sleep(1)


def flecha(previa: str, nueva: str) -> str:
    try:
        return "↑" if ORDEN.index(nueva) > ORDEN.index(previa) else "↓"
    except ValueError:
        return "→"


def linea_emisora(t, r, previa=None) -> str:
    c = r["compuesto"]
    sc = c["score_compuesto"]
    signo = "+" if sc >= 0 else ""
    tipo = " [ETF]" if r.get("tipo") == "etf" else ""
    precio = (r.get("tecnico") or {}).get("precio_actual")
    precio_txt = f"${precio:,.2f}" if isinstance(precio, (int, float)) else "—"
    riesgo = (r.get("riesgo") or {}).get("nivel_riesgo", "?")
    cambio = f"  <i>{previa} {flecha(previa, c['señal'])}</i>" if previa else ""
    return (f"{EMOJI.get(c['señal'],'')} <b>{t}</b>{tipo} · {c['señal']}{cambio}\n"
            f"    {precio_txt} · score {signo}{sc} · riesgo {riesgo}")


def main():
    datos = cargar_json(ARCHIVO_ALERTAS, {})
    tickers = datos.get("tickers") or {}
    if not tickers:
        print("No hay datos en alertas.json. Nada que hacer.")
        return

    watch = leer_watchlist()
    previo = cargar_json(ARCHIVO_ESTADO, {})
    estado_previo = previo.get("senales") or {}

    estado_actual = {t: r["compuesto"]["señal"] for t, r in tickers.items()}

    if not estado_previo:
        with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
            json.dump({"actualizado": datetime.now(timezone.utc)
                       .replace(microsecond=0).isoformat(),
                       "senales": estado_actual}, f, ensure_ascii=False)
        print(f"Linea base establecida con {len(estado_actual)} emisoras.")
        enviar("🎯 <b>Cazador de Oportunidades · JARASOFT</b>\n\n"
               "Bot conectado correctamente.\n\n"
               f"Vigilando <b>{len(estado_actual)}</b> emisoras.\n"
               f"Watchlist: <b>{len(watch)}</b>.\n\n"
               "<i>A partir de ahora recibirás avisos solo cuando una señal cambie. "
               "Esta primera corrida solo estableció el punto de partida.</i>")
        return

    cambios_watch, nuevas_fuertes = [], []
    for t, r in tickers.items():
        nueva = r["compuesto"]["señal"]
        previa = estado_previo.get(t)
        if previa is None or previa == nueva:
            continue
        if t in watch:
            cambios_watch.append((t, r, previa))
        elif nueva == "COMPRA FUERTE":
            nuevas_fuertes.append((t, r, previa))

    if not cambios_watch and not nuevas_fuertes:
        print("Sin cambios de señal. No se envia nada.")
    else:
        hora = datetime.now(timezone.utc).replace(microsecond=0)
        lineas = []
        if cambios_watch:
            cambios_watch.sort(key=lambda x: x[1]["compuesto"]["score_compuesto"],
                               reverse=True)
            lineas.append("\n<b>━━ TU WATCHLIST ━━</b>")
            lineas += [linea_emisora(t, r, p) for t, r, p in cambios_watch]
        if nuevas_fuertes:
            nuevas_fuertes.sort(key=lambda x: x[1]["compuesto"]["score_compuesto"],
                                reverse=True)
            total = len(nuevas_fuertes)
            mostrar = nuevas_fuertes[:MAX_NUEVAS_COMPRA_FUERTE]
            lineas.append(f"\n<b>━━ NUEVAS EN COMPRA FUERTE ━━</b>")
            lineas += [linea_emisora(t, r, p) for t, r, p in mostrar]
            if total > len(mostrar):
                lineas.append(f"\n<i>… y {total - len(mostrar)} más. "
                              f"Revisa el panel para verlas todas.</i>")

        encabezado = ("🎯 <b>Cazador de Oportunidades</b>\n"
                      f"<i>{hora.strftime('%d/%m/%Y %H:%M')} UTC</i>")
        pie = ("\n\n<i>Señales de un modelo cuantitativo de reglas fijas. "
               "No constituyen recomendación de inversión.</i>")
        enviar_por_partes(lineas + [pie], encabezado)
        print(f"Enviados: {len(cambios_watch)} de watchlist, "
              f"{len(nuevas_fuertes)} nuevas en compra fuerte.")

    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump({"actualizado": datetime.now(timezone.utc)
                   .replace(microsecond=0).isoformat(),
                   "senales": estado_actual}, f, ensure_ascii=False)
    print(f"Estado guardado con {len(estado_actual)} emisoras.")


if __name__ == "__main__":
    main()
