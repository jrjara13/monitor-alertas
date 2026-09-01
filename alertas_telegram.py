"""
alertas_telegram.py — v2
Ya no avisa por cruzar el umbral de COMPRA FUERTE (generaba demasiado
ruido con un universo grande). Ahora detecta una SEÑAL DE ENTRADA
TECNICA concreta:

  - Cruce alcista de MACD (histograma pasa de negativo a positivo), o
  - RSI y estocastico en sobreventa simultanea (RSI<30 y %K<20)
  - siempre con volumen de apoyo (volumen relativo > 1.2x su promedio)
  - se excluye si la tendencia de fondo es bajista Y el riesgo es alto
    (evita comprar "cuchillos cayendo")

Maximo 5 emisoras por alerta, priorizando las de mejor respaldo
fundamental. Cada emisora que se alerta no se vuelve a incluir en las
siguientes horas (evita reenviar la misma señal cada 30 minutos
mientras la condicion sigue activa).

El watchlist conserva su propio aviso: cualquier cambio de señal
compuesta en las emisoras que sigues de cerca, sin filtro de volumen.
"""
import json
import os
import time
from datetime import datetime, timezone
from urllib import request, parse, error

CARPETA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
ARCHIVO_ALERTAS = os.path.join(CARPETA, "alertas.json")
ARCHIVO_ESTADO = os.path.join(CARPETA, "estado_senales.json")
ARCHIVO_HISTORIAL = os.path.join(CARPETA, "historial_entradas.json")
ARCHIVO_WATCHLIST = "watchlist.txt"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

MAX_POR_ALERTA = 5
HORAS_SIN_REPETIR = 6      # no volver a avisar la misma emisora antes de este tiempo
RSI_SOBREVENTA = 30
STOCH_SOBREVENTA = 20
VOLUMEN_MINIMO = 1.2
LIMITE_TELEGRAM = 3900

EMOJI = {
    "COMPRA FUERTE": "🟢", "COMPRA": "🟩", "MANTENER / OBSERVAR": "⬜️",
    "VENTA": "🟥", "VENTA FUERTE": "🔴",
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
    if not TOKEN or not CHAT_ID:
        print("⚠ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID. No se envia nada.")
        return False
    datos = parse.urlencode({
        "chat_id": CHAT_ID, "text": texto, "parse_mode": "HTML",
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
        print(f"⚠ Error HTTP {e.code} de Telegram: {e.read().decode(errors='replace')[:300]}")
        return False
    except Exception as e:
        print(f"⚠ No se pudo contactar a Telegram: {e}")
        return False


def enviar_por_partes(lineas: list, encabezado: str):
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


# ------------------------------------------------------------------
# SEÑAL DE ENTRADA TECNICA
# ------------------------------------------------------------------
def evaluar_entrada(t: str, r: dict):
    """Retorna el motivo de la señal si califica, o None si no."""
    tc = r.get("tecnico") or {}
    rg = r.get("riesgo") or {}

    vol = tc.get("volumen_relativo")
    if not isinstance(vol, (int, float)) or vol <= VOLUMEN_MINIMO:
        return None

    peligroso = (tc.get("regimen") == "Bajista" and rg.get("nivel_riesgo") == "Alto")
    if peligroso:
        return None

    cruce = bool(tc.get("macd_cruce_alcista"))
    rsi_v = tc.get("rsi")
    k_v = tc.get("estocastico_k")
    rsi_ov = isinstance(rsi_v, (int, float)) and rsi_v < RSI_SOBREVENTA
    stoch_ov = isinstance(k_v, (int, float)) and k_v < STOCH_SOBREVENTA
    osciladores_ov = rsi_ov and stoch_ov

    if cruce and osciladores_ov:
        return "Cruce alcista de MACD + RSI y estocástico en sobreventa"
    if cruce:
        return "Cruce alcista de MACD"
    if osciladores_ov:
        return "RSI y estocástico en sobreventa simultánea"
    return None


def noticia_reciente(ticker: str):
    """Titular mas reciente de Yahoo Finance para esta emisora, si hay."""
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
        for it in items[:3]:
            titulo = (it.get("title") or it.get("content", {}).get("title"))
            if titulo:
                return titulo.strip()
    except Exception:
        pass
    return None


def linea_entrada(t: str, r: dict, motivo: str, con_noticia: bool) -> str:
    tc, fu, rg = r["tecnico"], r["fundamental"], r["riesgo"]
    precio = tc.get("precio_actual")
    precio_txt = f"${precio:,.2f}" if isinstance(precio, (int, float)) else "—"
    tipo = " [ETF]" if r.get("tipo") == "etf" else ""

    partes = [f"🎯 <b>{t}</b>{tipo} — {motivo}",
              f"    {precio_txt} · vol {tc.get('volumen_relativo','—')}x · "
              f"RSI {tc.get('rsi','—')} · %K {tc.get('estocastico_k','—')} · "
              f"riesgo {rg.get('nivel_riesgo','?')}"]

    if r.get("tipo") != "etf":
        pe = fu.get("pe")
        rel = fu.get("pe_relativo_sector")
        cred = fu.get("crecimiento_ingresos")
        bits = []
        if isinstance(pe, (int, float)):
            bits.append(f"P/E {pe:.1f}×" + (f" ({rel:.2f}× sector)" if isinstance(rel, (int, float)) else ""))
        if isinstance(cred, (int, float)):
            bits.append(f"crec. ingresos {cred*100:.1f}%")
        if bits:
            partes.append("    Fundamental: " + " · ".join(bits))

    if con_noticia:
        titular = noticia_reciente(t)
        if titular:
            partes.append(f"    📰 {titular}")

    return "\n".join(partes)


def linea_watchlist(t, r, previa) -> str:
    c = r["compuesto"]
    sc = c["score_compuesto"]
    signo = "+" if sc >= 0 else ""
    precio = (r.get("tecnico") or {}).get("precio_actual")
    precio_txt = f"${precio:,.2f}" if isinstance(precio, (int, float)) else "—"
    riesgo = (r.get("riesgo") or {}).get("nivel_riesgo", "?")
    return (f"{EMOJI.get(c['señal'],'')} <b>{t}</b> · {c['señal']}  "
            f"<i>{previa} {flecha(previa, c['señal'])}</i>\n"
            f"    {precio_txt} · score {signo}{sc} · riesgo {riesgo}")


def _valido(ts, limite_epoch):
    try:
        return datetime.fromisoformat(ts).timestamp() >= limite_epoch
    except Exception:
        return False


def main():
    datos = cargar_json(ARCHIVO_ALERTAS, {})
    tickers = datos.get("tickers") or {}
    if not tickers:
        print("No hay datos en alertas.json. Nada que hacer.")
        return

    watch = leer_watchlist()

    # --- Watchlist: cambios de señal, igual que antes ---
    previo = cargar_json(ARCHIVO_ESTADO, {})
    estado_previo = previo.get("senales") or {}
    estado_actual = {t: r["compuesto"]["señal"] for t, r in tickers.items()}
    es_primera_corrida = not estado_previo

    cambios_watch = []
    if not es_primera_corrida:
        for t in watch:
            r = tickers.get(t)
            if not r:
                continue
            nueva = r["compuesto"]["señal"]
            previa = estado_previo.get(t)
            if previa and previa != nueva:
                cambios_watch.append((t, r, previa))

    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump({"actualizado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                   "senales": estado_actual}, f, ensure_ascii=False)

    # --- Señales de entrada tecnica, en todo el universo ---
    historial = cargar_json(ARCHIVO_HISTORIAL, {})
    ahora = datetime.now(timezone.utc)

    def hace_poco(t):
        ts = historial.get(t)
        if not ts:
            return False
        try:
            return (ahora - datetime.fromisoformat(ts)).total_seconds() < HORAS_SIN_REPETIR * 3600
        except Exception:
            return False

    candidatos = []
    for t, r in tickers.items():
        if hace_poco(t):
            continue
        motivo = evaluar_entrada(t, r)
        if motivo:
            candidatos.append((t, r, motivo))

    candidatos.sort(key=lambda x: (
        x[1]["fundamental"]["score_fundamental"],
        x[1]["compuesto"]["score_compuesto"],
    ), reverse=True)
    elegidos = candidatos[:MAX_POR_ALERTA]

    if es_primera_corrida:
        print(f"Primera corrida: se establece la línea base ({len(estado_actual)} emisoras). "
              f"No se envían señales de entrada todavía.")
        enviar("🎯 <b>Cazador de Oportunidades · JARASOFT</b>\n\n"
               "Bot reconfigurado: ahora avisa señales de entrada técnica "
               "(cruce de MACD, sobreventa RSI+estocástico con volumen de apoyo), "
               f"máximo {MAX_POR_ALERTA} por alerta.\n\n"
               f"Vigilando <b>{len(estado_actual)}</b> emisoras. Watchlist: <b>{len(watch)}</b>.")
        return

    if not cambios_watch and not elegidos:
        print("Sin cambios de watchlist ni señales de entrada nuevas. No se envía nada.")
        return

    hora = ahora.strftime("%d/%m/%Y %H:%M")
    lineas = []
    if cambios_watch:
        lineas.append("\n<b>━━ TU WATCHLIST ━━</b>")
        lineas += [linea_watchlist(t, r, p) for t, r, p in cambios_watch]
    if elegidos:
        extra = f"/{len(candidatos)}" if len(candidatos) > len(elegidos) else ""
        lineas.append(f"\n<b>━━ SEÑALES DE ENTRADA ({len(elegidos)}{extra}) ━━</b>")
        lineas += [linea_entrada(t, r, motivo, con_noticia=True) for t, r, motivo in elegidos]
        if len(candidatos) > len(elegidos):
            lineas.append(f"\n<i>Hay {len(candidatos)-len(elegidos)} candidatas más "
                          f"que no entraron por espacio; revisa el panel para verlas.</i>")

    encabezado = f"🎯 <b>Cazador de Oportunidades</b>\n<i>{hora} UTC</i>"
    pie = ("\n\n<i>Señales de un modelo cuantitativo de reglas fijas. "
           "No constituyen recomendación de inversión.</i>")
    enviar_por_partes(lineas + [pie], encabezado)

    for t, _, _ in elegidos:
        historial[t] = ahora.isoformat()
    limite = ahora.timestamp() - (7 * 86400)
    historial = {t: ts for t, ts in historial.items() if _valido(ts, limite)}
    with open(ARCHIVO_HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False)

    print(f"Enviados: {len(cambios_watch)} de watchlist, {len(elegidos)} señales de entrada "
          f"(de {len(candidatos)} candidatas totales).")


if __name__ == "__main__":
    main()
