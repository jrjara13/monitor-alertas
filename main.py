"""
main.py — v5
Motor de alertas para el universo determinado por seleccion.py:
acciones liquidas de EE.UU., ETFs y emisoras de BMV.
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

TAMANO_LOTE = 100
DIAS_CACHE_FUND = 7
MAX_FUND_POR_CORRIDA = 70
PERIODO = "1y"
DIAS_SERIE = 120

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
ARCHIVO_UNIVERSO = os.path.join(CARPETA, "universo.json")

UNIVERSO_RESPALDO = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "SPY", "QQQ"]


def cargar_universo() -> tuple:
    """Retorna (acciones, etfs). Las de BMV se tratan como acciones."""
    if not os.path.exists(ARCHIVO_UNIVERSO):
        print(f"⚠ No existe {ARCHIVO_UNIVERSO}. Usando lista de respaldo.")
        print("  Corre el workflow 'Seleccion de Universo' para generarlo.")
        return UNIVERSO_RESPALDO, []
    try:
        with open(ARCHIVO_UNIVERSO, encoding="utf-8") as f:
            u = json.load(f)
        acciones = list(u.get("acciones", [])) + list(u.get("bmv", []))
        etfs = list(u.get("etfs", []))
        print(f"Universo: {len(acciones)} acciones (incl. BMV), {len(etfs)} ETFs")
        print(f"  Determinado el {u.get('actualizado','?')}")
        return acciones, etfs
    except Exception as e:
        print(f"⚠ No se pudo leer el universo: {e}. Usando respaldo.")
        return UNIVERSO_RESPALDO, []


def limpiar(obj):
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
            "s1": num(l.tail(20).min()), "s2": num(l.tail(60).min()),
            "r1": num(h.tail(20).max()), "r2": num(h.tail(60).max()),
            "max52": num(h.max()), "min52": num(l.min()),
        }
    except Exception:
        return {}


def serie_precio(df, n=DIAS_SERIE):
    return [num(c) for c in df["Close"].tail(n).tolist()]


def _fila(df, nombres):
    for n in nombres:
        if n in df.index:
            return df.loc[n]
    return None


def trimestrales(tk) -> list:
    try:
        df = tk.quarterly_income_stmt
        if df is None or df.empty:
            return []
        cols = list(df.columns)[:5]
        ingresos = _fila(df, ["Total Revenue", "Operating Revenue"])
        op = _fila(df, ["Operating Income", "Total Operating Income As Reported"])
        neta = _fila(df, ["Net Income", "Net Income Common Stockholders"])
        eps = _fila(df, ["Diluted EPS", "Basic EPS"])
        if ingresos is None:
            return []
        out = []
        for i, c in enumerate(cols[:4]):
            ing = num(ingresos.get(c), 0) if ingresos is not None else None
            opv = num(op.get(c), 0) if op is not None else None
            var = None
            if ingresos is not None and i + 4 < len(df.columns):
                prev = num(ingresos.get(df.columns[i + 4]), 0)
                if prev:
                    var = num((ing / prev - 1) * 100, 1) if ing else None
            out.append({
                "periodo": pd.Timestamp(c).strftime("%d %b %Y"),
                "ingresos": ing, "util_operativa": opv,
                "margen_op": num(opv / ing * 100, 1) if (ing and opv) else None,
                "util_neta": num(neta.get(c), 0) if neta is not None else None,
                "eps": num(eps.get(c), 2) if eps is not None else None,
                "var_ingresos": var,
            })
        return list(reversed(out))
    except Exception:
        return []


def cargar_cache_fundamentales() -> dict:
    if os.path.exists(ARCHIVO_FUND):
        try:
            with open(ARCHIVO_FUND, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠ No se pudo leer el caché: {e}")
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


def refrescar_fundamentales(tickers: list, cache: dict, etfs: set) -> dict:
    pendientes = [t for t in tickers if necesita_refresco(cache.get(t))]
    por_hacer = pendientes[:MAX_FUND_POR_CORRIDA]
    if not por_hacer:
        print("Fundamentales: caché al día.")
        return cache

    print(f"Fundamentales: refrescando {len(por_hacer)} de {len(pendientes)} pendientes...")
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for i, t in enumerate(por_hacer, 1):
        es_etf = t in etfs
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
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
                "numeroAnalistas": info.get("numberOfAnalystOpinions"),
                "beta": info.get("beta"),
                "sector": info.get("sector"),
                "industria": info.get("industry"),
                "bolsa": info.get("exchange"),
                "nombre": info.get("shortName") or info.get("longName"),
                "categoria": info.get("category"),
                "activos": info.get("totalAssets"),
                "familia": info.get("fundFamily"),
                "costo_anual": info.get("annualReportExpenseRatio"),
                "rend_3a": info.get("threeYearAverageReturn"),
                "rend_5a": info.get("fiveYearAverageReturn"),
                "es_etf": es_etf,
                "trimestres": [] if es_etf else trimestrales(tk),
                "actualizado": ahora,
            }
        except Exception as e:
            print(f"  ⚠ {t}: {e}")
            cache[t] = {"actualizado": ahora, "es_etf": es_etf}
        if i % 20 == 0:
            print(f"  ...{i}/{len(por_hacer)}")
        time.sleep(0.2)
    return cache


def descargar_precios(tickers: list) -> dict:
    resultado = {}
    for inicio in range(0, len(tickers), TAMANO_LOTE):
        lote = tickers[inicio:inicio + TAMANO_LOTE]
        n_lote = inicio // TAMANO_LOTE + 1
        print(f"Precios: lote {n_lote} ({inicio + len(lote)}/{len(tickers)})...")
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
    acciones, etfs = cargar_universo()
    set_etfs = set(etfs)
    tickers = acciones + etfs
    lista_indices = list(INDICES.keys())

    cache = cargar_cache_fundamentales()
    cache = refrescar_fundamentales(tickers, cache, set_etfs)
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
            fr = cache.get(t, {})
            tec = analisis_tecnico(df)
            if math.isnan(tec["precio_actual"]) or math.isnan(tec["rsi"]):
                continue

            riesgo = score_riesgo(df, beta=fr.get("beta"))
            es_etf = t in set_etfs

            if es_etf:
                fund = {"pe": None, "peg": None, "margen_operativo": None,
                        "crecimiento_ingresos": None, "roe": None,
                        "deuda_capital": None, "score_fundamental": 0, "señales": {}}
                # Mismos pesos que las acciones: el bloque fundamental aporta 0.
                # Asi los umbrales siguen siendo comparables entre ETFs y acciones.
                comp = señal_compuesta(tec["score_tecnico"], 0,
                                        riesgo["score_riesgo"], **PESOS)
            else:
                fund = analisis_fundamental(fr)
                comp = señal_compuesta(tec["score_tecnico"], fund["score_fundamental"],
                                        riesgo["score_riesgo"], **PESOS)

            cierres = df["Close"].dropna()
            ret_3m = rendimiento(cierres, 63)
            rel = num(ret_3m - sp_3m, 2) if (ret_3m is not None and sp_3m is not None) else None

            resultados[t] = {
                "tipo": "etf" if es_etf else "accion",
                "nombre": fr.get("nombre"),
                "sector": fr.get("categoria") if es_etf else fr.get("sector"),
                "industria": fr.get("familia") if es_etf else fr.get("industria"),
                "bolsa": fr.get("bolsa"),
                "etf": ({"categoria": fr.get("categoria"),
                         "activos": fr.get("activos"),
                         "familia": fr.get("familia"),
                         "costo_anual": num(fr.get("costo_anual"), 4),
                         "rend_3a": num(fr.get("rend_3a"), 4),
                         "rend_5a": num(fr.get("rend_5a"), 4)} if es_etf else None),
                "tecnico": {
                    "precio_actual": num(tec["precio_actual"]),
                    "rsi": num(tec["rsi"], 1),
                    "macd_hist": num(tec["macd_hist"], 3),
                    "sma20": num(tec["sma20"]),
                    "sma50": num(tec["sma50"]),
                    "sma200": num(tec["sma200"]),
                    "volumen_relativo": tec["volumen_relativo"],
                    "score_tecnico": tec["score_tecnico"],
                    "señales": tec["señales"],
                },
                "fundamental": {
                    "pe": num(fund["pe"], 2),
                    "peg": num(fund["peg"], 2),
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
                "trimestres": fr.get("trimestres") or [],
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
    n_etf = sum(1 for r in resultados.values() if r["tipo"] == "etf")
    print(f"\n{len(resultados)} emisoras ({len(resultados)-n_etf} acciones, {n_etf} ETFs)"
          f" + {len(indices_out)} índices. JSON: {tam:.2f} MB")
    print(f"Tiempo total: {time.time() - inicio:.0f}s")

    orden = sorted(resultados.items(),
                   key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True)
    print("\nTOP 10 COMPRA:")
    for t, r in orden[:10]:
        print(f"  {t:>12} [{r['tipo'][:3]}]  {r['compuesto']['señal']:<20} {r['compuesto']['score_compuesto']:>6}")


if __name__ == "__main__":
    main()
