"""
main.py
Motor de alertas técnico + fundamental + riesgo (S&P 500 + NASDAQ-100 + BMV),
más panel de índices y mercados de referencia.
"""
import json
import math
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from universo import construir_universo
from indicadores import analisis_tecnico, analisis_fundamental, score_riesgo, señal_compuesta

PESOS = {"peso_tecnico": 0.45, "peso_fundamental": 0.40, "peso_riesgo": 0.15}

TAMANO_LOTE = 100
DIAS_CACHE_FUND = 7
MAX_FUND_POR_CORRIDA = 60
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
ARCHIVO_ALERTAS = os.path.join(CARPETA, "alertas.json")
ARCHIVO_FUND = os.path.join(CARPETA, "fundamentales.json")


def limpiar(obj):
    """NaN/Infinity -> None (no son JSON válido y rompen JSON.parse)."""
    if isinstance(obj, dict):
        return {k: limpiar(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [limpiar(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def num(v, dec=2):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, dec)
    except (TypeError, ValueError):
        return None


def rendimiento(serie, dias):
    if len(serie) <= dias:
        return None
    ini, fin = float(serie.iloc[-dias - 1]), float(serie.iloc[-1])
    if not ini:
        return None
    return num((fin / ini - 1) * 100, 2)


def rendimiento_ytd(serie):
    try:
        año = serie.index[-1].year
        del_año = serie[serie.index.year == año]
        if len(del_año) < 2:
            return None
        return num((float(del_año.iloc[-1]) / float(del_año.iloc[0]) - 1) * 100, 2)
    except Exception:
        return None


def niveles(df):
    try:
        h, l = df["High"], df["Low"]
        return {
            "s1": num(l.tail(20).min()),
            "s2": num(l.tail(60).min()),
            "r1": num(h.tail(20).max()),
            "r2": num(h.tail(60).max()),
        }
    except Exception:
        return {"s1": None, "s2": None, "r1": None, "r2": None}


def serie_precio(df, n=DIAS_SERIE):
    return [num(c) for c in df["Close"].tail(n).tolist()]


def cargar_cache_fundamentales() -> dict:
    if os.path.exists(ARCHIVO_FUND):
        try:
            with open(ARCHIVO_FUND, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠ No se pudo leer el caché de fundamentales: {e}")
    return {}


def guardar_cache_fundamentales(cache: dict):
    with open(ARCHIVO_FUND, "w", encoding="utf-8") as f:
        json.dump(limpiar(cache), f, ensure_ascii=False, indent=1, allow_nan=False)


def necesita_refresco(entrada: dict) -> bool:
    if not entrada or "actualizado" not in entrada:
        return True
    try:
        ts = datetime.fromisoformat(entrada["actualizado"])
        return (datetime.now(timezone.utc) - ts).days >= DIAS_CACHE_FUND
    except Exception:
        return True


def refrescar_fundamentales(tickers: list, cache: dict) -> dict:
    pendientes = [t for t in tickers if necesita_refresco(cache.get(t))]
    por_hacer = pendientes[:MAX_FUND_POR_CORRIDA]
    if not por_hacer:
        print("Fundamentales: caché al día.")
        return cache

    print(f"Fundamentales: refrescando {len(por_hacer)} de {len(pendientes)} pendientes...")
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for i, t in enumerate(por_hacer, 1):
        try:
            info = yf.Ticker(t).info or {}
            cache[t] = {
                "trailingPE": info.get("trailingPE"),
                "pegRatio": info.get("pegRatio"),
                "operatingMargins": info.get("operatingMargins"),
                "revenueGrowth": info.get("revenueGrowth"),
                "debtToEquity": info.get("debtToEquity"),
                "returnOnEquity": info.get("returnOnEquity"),
                "freeCashflow": info.get("freeCashflow"),
                "marketCap": info.get("marketCap"),
                "dividendYield": info.get("dividendYield"),
                "targetMeanPrice": info.get("targetMeanPrice"),
                "beta": info.get("beta"),
                "sector": info.get("sector"),
                "industria": info.get("industry"),
                "nombre": info.get("shortName") or info.get("longName"),
                "actualizado": ahora,
            }
        except Exception as e:
            print(f"  ⚠ {t}: {e}")
            cache[t] = {"actualizado": ahora}
        if i % 20 == 0:
            print(f"  ...{i}/{len(por_hacer)}")
        time.sleep(0.15)
    return cache


def descargar_precios(tickers: list) -> dict:
    resultado = {}
    for inicio in range(0, len(tickers), TAMANO_LOTE):
        lote = tickers[inicio:inicio + TAMANO_LOTE]
        n_lote = inicio // TAMANO_LOTE + 1
        print(f"Precios: lote {n_lote} ({len(lote)} tickers)...")
        try:
            data = yf.download(lote, period=PERIODO, group_by="ticker",
                                auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print(f"  ⚠ Falló el lote {n_lote}: {e}")
            continue
        for t in lote:
            try:
                df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(how="all")
                if df.empty or len(df) < 60:
                    continue
                resultado[t] = df
            except Exception:
                continue
    return resultado


def main():
    inicio = time.time()
    tickers = construir_universo()
    lista_indices = list(INDICES.keys())

    cache = cargar_cache_fundamentales()
    cache = refrescar_fundamentales(tickers, cache)
    guardar_cache_fundamentales(cache)

    precios = descargar_precios(tickers + lista_indices)
    print(f"Precios obtenidos para {len(precios)} de {len(tickers) + len(lista_indices)}.")

    indices_out = {}
    for t, nombre in INDICES.items():
        df = precios.get(t)
        if df is None or df.empty:
            print(f"  ⚠ Sin datos para el índice {t}")
            continue
        c = df["Close"].dropna()
        if len(c) < 2:
            continue
        indices_out[t] = {
            "nombre": nombre,
            "precio": num(c.iloc[-1]),
            "cambio_1d": num((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2),
            "cambio_1m": rendimiento(c, 21),
            "ytd": rendimiento_ytd(c),
            "serie": [num(x) for x in c.tail(60).tolist()],
        }
    print(f"Índices procesados: {len(indices_out)}")

    sp = precios.get("^GSPC")
    sp_3m = rendimiento(sp["Close"].dropna(), 63) if sp is not None else None

    resultados = {}
    for t in tickers:
        df = precios.get(t)
        if df is None:
            continue
        try:
            fund_raw = cache.get(t, {})
            tec = analisis_tecnico(df)
            if math.isnan(tec["precio_actual"]) or math.isnan(tec["rsi"]):
                continue

            fund = analisis_fundamental(fund_raw)
            riesgo = score_riesgo(df, beta=fund_raw.get("beta"))
            comp = señal_compuesta(tec["score_tecnico"], fund["score_fundamental"],
                                    riesgo["score_riesgo"], **PESOS)

            cierres = df["Close"].dropna()
            ret_3m = rendimiento(cierres, 63)
            rel = num(ret_3m - sp_3m, 2) if (ret_3m is not None and sp_3m is not None) else None

            resultados[t] = {
                "nombre": fund_raw.get("nombre"),
                "sector": fund_raw.get("sector"),
                "industria": fund_raw.get("industria"),
                "tecnico": {
                    "precio_actual": num(tec["precio_actual"]),
                    "rsi": num(tec["rsi"], 1),
                    "macd_hist": num(tec["macd_hist"], 3),
                    "sma20": num(tec["sma20"]),
                    "sma50": num(tec["sma50"]),
                    "sma200": num(tec["sma200"]),
                    "bb_superior": num(tec["bb_superior"]),
                    "bb_inferior": num(tec["bb_inferior"]),
                    "volumen_relativo": tec["volumen_relativo"],
                },
                "fundamental": {
                    "pe": num(fund["pe"], 2),
                    "peg": num(fund["peg"], 2),
                    "margen_operativo": num(fund["margen_operativo"], 4),
                    "crecimiento_ingresos": num(fund["crecimiento_ingresos"], 4),
                    "roe": num(fund["roe"], 4),
                    "deuda_capital": num(fund["deuda_capital"], 1),
                    "market_cap": fund_raw.get("marketCap"),
                    "dividend_yield": num(fund_raw.get("dividendYield"), 4),
                    "precio_objetivo": num(fund_raw.get("targetMeanPrice")),
                },
                "riesgo": riesgo,
                "compuesto": comp,
                "niveles": niveles(df),
                "rendimiento": {
                    "d5": rendimiento(cierres, 5),
                    "m1": rendimiento(cierres, 21),
                    "m3": ret_3m,
                    "ytd": rendimiento_ytd(cierres),
                    "vs_sp500_3m": rel,
                },
                "serie": serie_precio(df),
            }
        except Exception as e:
            print(f"  ⚠ Error analizando {t}: {e}")

    if not resultados:
        print("No se pudo analizar ningún ticker.")
        return

    salida = {
        "actualizado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": len(resultados),
        "indices": limpiar(indices_out),
        "tickers": limpiar(resultados),
    }
    with open(ARCHIVO_ALERTAS, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    tam = os.path.getsize(ARCHIVO_ALERTAS) / 1_000_000
    print(f"\n{len(resultados)} tickers + {len(indices_out)} índices. JSON: {tam:.2f} MB")
    print(f"Tiempo total: {time.time() - inicio:.0f}s")

    orden = sorted(resultados.items(),
                   key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True)
    print("\nTOP 10 COMPRA:")
    for t, r in orden[:10]:
        print(f"  {t:>12}  {r['compuesto']['señal']:<20} {r['compuesto']['score_compuesto']:>6}")


if __name__ == "__main__":
    main()
