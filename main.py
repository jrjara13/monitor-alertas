"""
main.py
Motor de alertas técnico + fundamental + riesgo.

USO:
    python3 main.py

CONFIGURA tu lista de tickers y umbrales abajo, en TICKERS y PESOS.
Requiere: pip install yfinance pandas numpy --break-system-packages
"""
import json
import traceback

from datos import obtener_datos_ticker
from indicadores import analisis_tecnico, analisis_fundamental, score_riesgo, señal_compuesta
from dashboard import generar_dashboard

# ------------------------------------------------------------------
# CONFIGURACIÓN — ajusta aquí tu universo de tickers
# ------------------------------------------------------------------
TICKERS = [
    "NFLX", "IBM", "OKLO", "GLW", "UBER", "AMD", "MSFT", "AAOI",
    "MELI", "TSM", "CLSK", "ORCL",
]

# Pesos de la señal compuesta (deben sumar 1.0)
PESOS = {"peso_tecnico": 0.45, "peso_fundamental": 0.40, "peso_riesgo": 0.15}

import os

# Si corre dentro de GitHub Actions, guarda en docs/ para que GitHub Pages lo publique.
CARPETA_SALIDA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
os.makedirs(CARPETA_SALIDA, exist_ok=True)
ARCHIVO_SALIDA_HTML = os.path.join(CARPETA_SALIDA, "index.html")
ARCHIVO_SALIDA_JSON = os.path.join(CARPETA_SALIDA, "alertas.json")


def analizar_ticker(ticker: str) -> dict:
    datos = obtener_datos_ticker(ticker, periodo="1y")
    tec = analisis_tecnico(datos["ohlcv"])
    fund = analisis_fundamental(datos["info"])
    riesgo = score_riesgo(datos["ohlcv"], beta=datos["beta"])
    comp = señal_compuesta(tec["score_tecnico"], fund["score_fundamental"],
                            riesgo["score_riesgo"], **PESOS)
    return {"tecnico": tec, "fundamental": fund, "riesgo": riesgo, "compuesto": comp}


def main():
    resultados = {}
    errores = []

    for ticker in TICKERS:
        print(f"Analizando {ticker}...")
        try:
            resultados[ticker] = analizar_ticker(ticker)
        except Exception as e:
            errores.append((ticker, str(e)))
            print(f"  ⚠ Error con {ticker}: {e}")

    if not resultados:
        print("No se pudo analizar ningún ticker. Revisa tu conexión o los símbolos.")
        return

    # --- Alertas en consola, ordenadas por score compuesto ---
    print("\n" + "=" * 60)
    print("ALERTAS")
    print("=" * 60)
    orden = sorted(resultados.items(), key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True)
    for ticker, r in orden:
        c = r["compuesto"]
        print(f"{ticker:>6}  {c['señal']:<20}  score={c['score_compuesto']:>6}  "
              f"riesgo={r['riesgo']['nivel_riesgo']}")

    # --- Guardar JSON ---
    with open(ARCHIVO_SALIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON guardado en {ARCHIVO_SALIDA_JSON}")

    # --- Generar dashboard HTML ---
    html = generar_dashboard(resultados, titulo="Monitor de Oportunidades — Cartera")
    with open(ARCHIVO_SALIDA_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard guardado en {ARCHIVO_SALIDA_HTML} — ábrelo en tu navegador.")

    if errores:
        print(f"\n{len(errores)} ticker(s) con error: {[t for t,_ in errores]}")


if __name__ == "__main__":
    main()
