"""
main.py
Motor de alertas técnico + fundamental + riesgo, para universo amplio
(S&P 500 + NASDAQ-100 + BMV).

Estrategia:
  - Precios: descarga por lotes (rápido, todos los tickers en cada corrida).
  - Fundamentales: se cachean en docs/fundamentales.json y solo se refrescan
    los que tengan más de DIAS_CACHE_FUND días, con un tope por corrida.
"""
import json
import math
import os
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from universo import construir_universo
from indicadores import analisis_tecnico, analisis_fundamental, score_riesgo, señal_compuesta

# ------------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------------
PESOS = {"peso_tecnico": 0.45, "peso_fundamental": 0.40, "peso_riesgo": 0.15}

TAMANO_LOTE = 100          # tickers por lote de descarga de precios
DIAS_CACHE_FUND = 7        # refrescar fundamentales con más de N días
MAX_FUND_POR_CORRIDA = 60  # tope de fundamentales a refrescar por corrida
PERIODO = "1y"

CARPETA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
os.makedirs(CARPETA, exist_ok=True)
ARCHIVO_ALERTAS = os.path.join(CARPETA, "alertas.json")
ARCHIVO_FUND = os.path.join(CARPETA, "fundamentales.json")


# ------------------------------------------------------------------
# UTILIDADES
# ------------------------------------------------------------------
def limpiar(obj):
    """
    Convierte NaN/Infinity a None. Python los escribe literalmente como
    NaN/Infinity, que NO son JSON válido y rompen JSON.parse del navegador.
    """
    if isinstance(obj, dict):
        return {k: limpiar(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [limpiar(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


# ------------------------------------------------------------------
# CACHÉ DE FUNDAMENTALES
# ------------------------------------------------------------------
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
        edad_dias = (datetime.now(timezone.utc) - ts).days
        return edad_dias >= DIAS_CACHE_FUND
    except Exception:
        return True


def refrescar_fundamentales(tickers: list, cache: dict) -> dict:
    """Refresca hasta MAX_FUND_POR_CORRIDA entradas vencidas del caché."""
    pendientes = [t for t in tickers if necesita_refresco(cache.get(t))]
    por_hacer = pendientes[:MAX_FUND_POR_CORRIDA]
    if not por_hacer:
        print("Fundamentales: caché al día, nada que refrescar.")
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
                "beta": info.get("beta"),
                "sector": info.get("sector"),
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


# ------------------------------------------------------------------
# DESCARGA DE PRECIOS POR LOTES
# ------------------------------------------------------------------
def descargar_precios(tickers: list) -> dict:
    """Retorna {ticker: DataFrame OHLCV}. Omite los que no devuelvan datos."""
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


# ------------------------------------------------------------------
# PRINCIPAL
# ------------------------------------------------------------------
def main():
    inicio = time.time()
    tickers = construir_universo()

    cache = cargar_cache_fundamentales()
    cache = refrescar_fundamentales(tickers, cache)
    guardar_cache_fundamentales(cache)

    precios = descargar_precios(tickers)
    print(f"Precios obtenidos para {len(precios)} de {len(tickers)} tickers.")

    resultados = {}
    for t, df in precios.items():
        try:
            fund_raw = cache.get(t, {})
            tec = analisis_tecnico(df)

            # Si los indicadores base salen NaN, el ticker no es utilizable
            if math.isnan(tec["precio_actual"]) or math.isnan(tec["rsi"]):
                continue

            fund = analisis_fundamental(fund_raw)
            riesgo = score_riesgo(df, beta=fund_raw.get("beta"))
            comp = señal_compuesta(tec["score_tecnico"], fund["score_fundamental"],
                                    riesgo["score_riesgo"], **PESOS)

            resultados[t] = {
                "nombre": fund_raw.get("nombre"),
                "sector": fund_raw.get("sector"),
                "tecnico": {
                    "precio_actual": round(tec["precio_actual"], 2),
                    "rsi": round(tec["rsi"], 1),
                    "macd_hist": round(tec["macd_hist"], 3),
                    "sma20": round(tec["sma20"], 2),
                    "sma50": round(tec["sma50"], 2),
                    "volumen_relativo": tec["volumen_relativo"],
                },
                "fundamental": {
                    "pe": fund["pe"],
                    "peg": fund["peg"],
                    "margen_operativo": fund["margen_operativo"],
                    "crecimiento_ingresos": fund["crecimiento_ingresos"],
                    "roe": fund["roe"],
                    "deuda_capital": fund["deuda_capital"],
                },
                "riesgo": riesgo,
                "compuesto": comp,
            }
        except Exception as e:
            print(f"  ⚠ Error analizando {t}: {e}")

    if not resultados:
        print("No se pudo analizar ningún ticker.")
        return

    salida = {
        # Sin microsegundos: Safari no los parsea.
        "actualizado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": len(resultados),
        "tickers": limpiar(resultados),
    }
    with open(ARCHIVO_ALERTAS, "w", encoding="utf-8") as f:
        # allow_nan=False falla ruidosamente si algún NaN se escapa,
        # en vez de generar JSON inválido silenciosamente.
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    tam_mb = os.path.getsize(ARCHIVO_ALERTAS) / 1_000_000
    print(f"\n{len(resultados)} tickers analizados. JSON: {tam_mb:.2f} MB")
    print(f"Tiempo total: {time.time() - inicio:.0f}s")

    orden = sorted(resultados.items(),
                   key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True)
    print("\nTOP 10 COMPRA:")
    for t, r in orden[:10]:
        print(f"  {t:>12}  {r['compuesto']['señal']:<20} {r['compuesto']['score_compuesto']:>6}")
    print("\nTOP 10 VENTA:")
    for t, r in orden[-10:]:
        print(f"  {t:>12}  {r['compuesto']['señal']:<20} {r['compuesto']['score_compuesto']:>6}")


if __name__ == "__main__":
    main()
