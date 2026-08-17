"""
rapido.py
Actualización frecuente (cada 5 min en horario de mercado) SOLO para las
emisoras del watchlist. Recalcula precio e indicadores técnicos; no toca
fundamentales (esos vienen del proceso principal, main.py).

Salida: docs/rapido.json — archivo pequeño que el dashboard sobrepone
sobre alertas.json.
"""
import json
import math
import os
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from indicadores import analisis_tecnico, analisis_fundamental, score_riesgo, señal_compuesta

PESOS = {"peso_tecnico": 0.45, "peso_fundamental": 0.40, "peso_riesgo": 0.15}
PERIODO = "1y"
DIAS_SERIE = 150

INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "USDMXN=X": "USD/MXN",
    "GC=F": "Oro",
    "SI=F": "Plata",
    "CL=F": "Petróleo WTI",
}

CARPETA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
os.makedirs(CARPETA, exist_ok=True)
ARCHIVO_RAPIDO = os.path.join(CARPETA, "rapido.json")
ARCHIVO_FUND = os.path.join(CARPETA, "fundamentales.json")
ARCHIVO_WATCHLIST = "watchlist.txt"


def limpiar(o):
    if isinstance(o, dict):
        return {k: limpiar(v) for k, v in o.items()}
    if isinstance(o, list):
        return [limpiar(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def num(v, dec=2):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, dec)
    except (TypeError, ValueError):
        return None


def rendimiento(s, dias):
    if len(s) <= dias:
        return None
    ini, fin = float(s.iloc[-dias - 1]), float(s.iloc[-1])
    return num((fin / ini - 1) * 100, 2) if ini else None


def rendimiento_ytd(s):
    try:
        a = s.index[-1].year
        d = s[s.index.year == a]
        if len(d) < 2:
            return None
        return num((float(d.iloc[-1]) / float(d.iloc[0]) - 1) * 100, 2)
    except Exception:
        return None


def niveles(df):
    try:
        h, l = df["High"], df["Low"]
        return {"s1": num(l.tail(20).min()), "s2": num(l.tail(60).min()),
                "r1": num(h.tail(20).max()), "r2": num(h.tail(60).max()),
                "max52": num(h.max()), "min52": num(l.min())}
    except Exception:
        return {}


def leer_watchlist() -> list:
    """Lee watchlist.txt: un ticker por línea. Ignora vacíos y comentarios (#)."""
    if not os.path.exists(ARCHIVO_WATCHLIST):
        print(f"⚠ No existe {ARCHIVO_WATCHLIST}; nada que actualizar.")
        return []
    with open(ARCHIVO_WATCHLIST, encoding="utf-8") as f:
        tickers = [l.strip().upper() for l in f
                   if l.strip() and not l.strip().startswith("#")]
    vistos, out = set(), []
    for t in tickers:
        if t not in vistos:
            vistos.add(t)
            out.append(t)
    return out


def main():
    inicio = time.time()
    watch = leer_watchlist()
    if not watch:
        return
    print(f"Watchlist: {len(watch)} emisoras — {', '.join(watch)}")

    cache = {}
    if os.path.exists(ARCHIVO_FUND):
        try:
            with open(ARCHIVO_FUND, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception as e:
            print(f"⚠ No se pudo leer el caché de fundamentales: {e}")

    todos = watch + list(INDICES.keys())
    try:
        data = yf.download(todos, period=PERIODO, group_by="ticker",
                            auto_adjust=True, threads=True, progress=False)
    except Exception as e:
        print(f"⚠ Falló la descarga: {e}")
        return

    def sacar(t):
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.dropna(how="all")
            return df if len(df) >= 60 else None
        except Exception:
            return None

    idx_out = {}
    for t, nombre in INDICES.items():
        df = sacar(t)
        if df is None:
            continue
        c = df["Close"].dropna()
        if len(c) < 2:
            continue
        idx_out[t] = {
            "nombre": nombre,
            "precio": num(c.iloc[-1]),
            "cambio_1d": num((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2),
            "cambio_1m": rendimiento(c, 21),
            "ytd": rendimiento_ytd(c),
            "serie": [num(x) for x in c.tail(60).tolist()],
        }

    sp = sacar("^GSPC")
    sp3 = rendimiento(sp["Close"].dropna(), 63) if sp is not None else None

    out = {}
    for t in watch:
        df = sacar(t)
        if df is None:
            print(f"  ⚠ Sin datos suficientes para {t}")
            continue
        try:
            fr = cache.get(t, {})
            tec = analisis_tecnico(df)
            if math.isnan(tec["precio_actual"]) or math.isnan(tec["rsi"]):
                continue
            fund = analisis_fundamental(fr)
            rg = score_riesgo(df, beta=fr.get("beta"))
            comp = señal_compuesta(tec["score_tecnico"], fund["score_fundamental"],
                                    rg["score_riesgo"], **PESOS)
            c = df["Close"].dropna()
            r3 = rendimiento(c, 63)
            out[t] = {
                "nombre": fr.get("nombre"),
                "sector": fr.get("sector"),
                "industria": fr.get("industria"),
                "tecnico": {
                    "precio_actual": num(tec["precio_actual"]),
                    "rsi": num(tec["rsi"], 1),
                    "macd_hist": num(tec["macd_hist"], 3),
                    "sma20": num(tec["sma20"]), "sma50": num(tec["sma50"]),
                    "sma200": num(tec["sma200"]),
                    "volumen_relativo": tec["volumen_relativo"],
                    "score_tecnico": tec["score_tecnico"],
                    "señales": tec["señales"],
                },
                "fundamental": {
                    "pe": num(fund["pe"], 2), "peg": num(fund["peg"], 2),
                    "margen_operativo": num(fund["margen_operativo"], 4),
                    "crecimiento_ingresos": num(fund["crecimiento_ingresos"], 4),
                    "roe": num(fund["roe"], 4),
                    "deuda_capital": num(fund["deuda_capital"], 1),
                    "market_cap": fr.get("marketCap"),
                    "dividend_yield": num(fr.get("dividendYield"), 4),
                    "precio_objetivo": num(fr.get("targetMeanPrice")),
                    "num_analistas": fr.get("numeroAnalistas"),
                    "score_fundamental": fund["score_fundamental"],
                    "señales": fund["señales"],
                },
                "riesgo": rg,
                "compuesto": comp,
                "niveles": niveles(df),
                "rendimiento": {
                    "d5": rendimiento(c, 5), "m1": rendimiento(c, 21), "m3": r3,
                    "ytd": rendimiento_ytd(c),
                    "vs_sp500_3m": num(r3 - sp3, 2) if (r3 is not None and sp3 is not None) else None,
                },
                "trimestres": fr.get("trimestres") or [],
                "serie": [num(x) for x in df["Close"].tail(DIAS_SERIE).tolist()],
            }
        except Exception as e:
            print(f"  ⚠ Error con {t}: {e}")

    salida = {
        "actualizado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "watchlist": watch,
        "indices": limpiar(idx_out),
        "tickers": limpiar(out),
    }
    with open(ARCHIVO_RAPIDO, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    kb = os.path.getsize(ARCHIVO_RAPIDO) / 1000
    print(f"{len(out)} emisoras + {len(idx_out)} índices. rapido.json: {kb:.0f} KB "
          f"en {time.time() - inicio:.0f}s")
    for t, r in sorted(out.items(), key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True):
        print(f"  {t:>12}  ${r['tecnico']['precio_actual']:>9}  "
              f"{r['compuesto']['señal']:<20} {r['compuesto']['score_compuesto']:>6}")


if __name__ == "__main__":
    main()
