"""
seleccion.py
Determina el universo a analizar. Corre una vez al dia.

1. Descarga el directorio oficial de emisoras listadas en EE.UU.
   (NASDAQ Trader publica estos archivos de forma abierta).
2. Descarga 3 meses de precios de todas las candidatas.
3. Filtra por liquidez: volumen promedio operado en dolares.
4. Separa acciones de ETFs (el directorio trae la bandera).
5. Aplica filtro de capitalizacion cuando el cache ya la tiene.

Salida: universo.json — la lista que consume main.py.
"""
import io
import json
import math
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

MIN_VOL_ACCIONES = 5_000_000
MIN_VOL_ETFS = 1_000_000
MIN_CAPITALIZACION = 500_000_000
MAX_ETFS = 400
DIAS_VOLUMEN = 60
TAMANO_LOTE = 200

CABECERAS = {"User-Agent": "MonitorAlertas/1.0 (analisis financiero personal)"}
URL_NASDAQ = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
URL_OTROS = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

CARPETA = "docs" if os.environ.get("GITHUB_ACTIONS") else "."
os.makedirs(CARPETA, exist_ok=True)
ARCHIVO_UNIVERSO = os.path.join(CARPETA, "universo.json")
ARCHIVO_FUND = os.path.join(CARPETA, "fundamentales.json")

BMV = [
    "AMXB.MX", "WALMEX.MX", "FEMSAUBD.MX", "GFNORTEO.MX", "GMEXICOB.MX",
    "CEMEXCPO.MX", "TLEVISACPO.MX", "KOFUBL.MX", "ASURB.MX",
    "GAPB.MX", "OMAB.MX", "ALSEA.MX", "BIMBOA.MX", "PINFRA.MX",
    "ORBIA.MX", "GCARSOA1.MX", "PE&OLES.MX", "AC.MX", "LIVEPOLC-1.MX",
    "GRUMAB.MX", "KIMBERA.MX", "CHDRAUIB.MX", "LABB.MX", "MEGACPO.MX",
    "Q.MX", "RA.MX", "VESTA.MX", "FUNO11.MX", "GENTERA.MX",
    "BBAJIOO.MX", "CUERVO.MX", "VOLARA.MX", "GCC.MX", "AGUA.MX",
    "FIBRAPL14.MX",
]


def limpiar_simbolo(s: str) -> str:
    """Yahoo usa guion donde el directorio usa punto: BRK.B -> BRK-B"""
    return str(s).strip().replace(".", "-").replace("$", "-")


def simbolo_valido(s: str) -> bool:
    """Descarta warrants, unidades, derechos y simbolos con formato raro."""
    if not s or len(s) > 6:
        return False
    if not all(c.isalnum() or c == "-" for c in s):
        return False
    if "-" in s and s.split("-")[-1] in {"W", "WS", "U", "R", "RT"}:
        return False
    return True


def descargar_directorio() -> tuple:
    """Retorna (acciones, etfs) desde el directorio publico de NASDAQ Trader."""
    acciones, etfs = set(), set()

    def procesar(url, col_simbolo, col_etf, col_prueba):
        try:
            r = requests.get(url, headers=CABECERAS, timeout=60)
            r.raise_for_status()
            texto = "\n".join(r.text.splitlines()[:-1])
            df = pd.read_csv(io.StringIO(texto), sep="|")
            df = df[df[col_prueba] != "Y"]
            for _, fila in df.iterrows():
                s = limpiar_simbolo(fila[col_simbolo])
                if not simbolo_valido(s):
                    continue
                if str(fila.get(col_etf, "N")).strip() == "Y":
                    etfs.add(s)
                else:
                    acciones.add(s)
            print(f"  {url.split('/')[-1]}: {len(df)} registros")
        except Exception as e:
            print(f"  ⚠ Falló {url}: {e}")

    print("Descargando directorio de emisoras...")
    procesar(URL_NASDAQ, "Symbol", "ETF", "Test Issue")
    procesar(URL_OTROS, "ACT Symbol", "ETF", "Test Issue")
    return sorted(acciones), sorted(etfs)


def liquidez(tickers: list) -> dict:
    """Retorna {ticker: (volumen_dolares_promedio, ultimo_precio)}."""
    resultado = {}
    total = len(tickers)
    for inicio in range(0, total, TAMANO_LOTE):
        lote = tickers[inicio:inicio + TAMANO_LOTE]
        n = inicio // TAMANO_LOTE + 1
        print(f"  Lote {n} ({inicio + len(lote)}/{total})...")
        try:
            data = yf.download(lote, period="3mo", group_by="ticker",
                                auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print(f"    ⚠ Falló: {e}")
            continue
        for t in lote:
            try:
                df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(how="all")
                if df.empty or len(df) < 30:
                    continue
                cierre = df["Close"].tail(DIAS_VOLUMEN)
                volumen = df["Volume"].tail(DIAS_VOLUMEN)
                dolares = float((cierre * volumen).mean())
                ultimo = float(cierre.iloc[-1])
                if math.isnan(dolares) or math.isnan(ultimo) or ultimo <= 0:
                    continue
                resultado[t] = (dolares, ultimo)
            except Exception:
                continue
        time.sleep(0.5)
    return resultado


def main():
    inicio = time.time()
    acciones, etfs = descargar_directorio()
    print(f"Directorio: {len(acciones)} acciones, {len(etfs)} ETFs")

    if not acciones and not etfs:
        print("No se obtuvo el directorio. Se conserva el universo anterior.")
        return

    cache = {}
    if os.path.exists(ARCHIVO_FUND):
        try:
            with open(ARCHIVO_FUND, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            pass

    print("\nMidiendo liquidez de acciones...")
    liq_acc = liquidez(acciones)
    print(f"  Con datos: {len(liq_acc)}")

    print("\nMidiendo liquidez de ETFs...")
    liq_etf = liquidez(etfs)
    print(f"  Con datos: {len(liq_etf)}")

    sel_acc = []
    for t, (vol, precio) in liq_acc.items():
        if vol < MIN_VOL_ACCIONES:
            continue
        cap = (cache.get(t) or {}).get("marketCap")
        if isinstance(cap, (int, float)) and cap < MIN_CAPITALIZACION:
            continue
        sel_acc.append((t, vol))
    sel_acc.sort(key=lambda x: x[1], reverse=True)

    sel_etf = [(t, v) for t, (v, _) in liq_etf.items() if v >= MIN_VOL_ETFS]
    sel_etf.sort(key=lambda x: x[1], reverse=True)
    sel_etf = sel_etf[:MAX_ETFS]

    lista_acc = [t for t, _ in sel_acc]
    lista_etf = [t for t, _ in sel_etf]

    salida = {
        "actualizado": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "criterios": {
            "min_volumen_acciones_usd": MIN_VOL_ACCIONES,
            "min_volumen_etfs_usd": MIN_VOL_ETFS,
            "min_capitalizacion_usd": MIN_CAPITALIZACION,
            "max_etfs": MAX_ETFS,
        },
        "acciones": lista_acc,
        "etfs": lista_etf,
        "bmv": BMV,
        "total": len(lista_acc) + len(lista_etf) + len(BMV),
    }
    with open(ARCHIVO_UNIVERSO, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    print(f"\n{'='*56}")
    print(f"Acciones seleccionadas: {len(lista_acc)}")
    print(f"ETFs seleccionados:     {len(lista_etf)}")
    print(f"BMV (fijas):            {len(BMV)}")
    print(f"TOTAL:                  {salida['total']}")
    print(f"Tiempo: {time.time() - inicio:.0f}s")
    print("\nTop 10 acciones por volumen operado:")
    for t, v in sel_acc[:10]:
        print(f"  {t:>8}  ${v/1e6:,.0f}M diarios")
    print("\nTop 10 ETFs por volumen operado:")
    for t, v in sel_etf[:10]:
        print(f"  {t:>8}  ${v/1e6:,.0f}M diarios")


if __name__ == "__main__":
    main()
