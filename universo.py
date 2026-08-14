"""
universo.py
Define el universo de tickers a analizar: S&P 500, NASDAQ-100 y BMV (México).
"""
import pandas as pd


# NASDAQ-100 (lista estable, se actualiza anualmente)
NASDAQ_100 = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "PEP", "ADBE", "CSCO", "TMUS", "INTC", "CMCSA", "QCOM", "INTU",
    "TXN", "AMGN", "HON", "AMAT", "ISRG", "BKNG", "SBUX", "VRTX", "GILD", "ADI",
    "MDLZ", "REGN", "ADP", "PANW", "LRCX", "MU", "PYPL", "SNPS", "KLAC", "CDNS",
    "MELI", "MAR", "ORLY", "CSX", "ASML", "ABNB", "CRWD", "FTNT", "CTAS", "MRVL",
    "DASH", "ADSK", "NXPI", "PCAR", "ROP", "MNST", "WDAY", "AEP", "CPRT", "PAYX",
    "MCHP", "ROST", "ODFL", "KDP", "FAST", "EA", "IDXX", "VRSK", "DDOG", "CTSH",
    "EXC", "GEHC", "CCEP", "TTWO", "KHC", "LULU", "CSGP", "AZN", "XEL", "ANSS",
    "ON", "DXCM", "CDW", "BIIB", "TEAM", "ZS", "GFS", "ILMN", "MDB", "WBD",
    "SIRI", "ARM", "SMCI", "TTD", "APP", "LIN", "PDD", "BKR", "FANG", "CEG",
]

# BMV — principales emisoras del IPC y otras líquidas (sufijo .MX en Yahoo Finance)
BMV = [
    "AMXB.MX", "WALMEX.MX", "FEMSAUBD.MX", "GFNORTEO.MX", "GMEXICOB.MX",
    "CEMEXCPO.MX", "TLEVISACPO.MX", "ELEKTRA.MX", "KOFUBL.MX", "ASURB.MX",
    "GAPB.MX", "OMAB.MX", "ALSEA.MX", "BIMBOA.MX", "PINFRA.MX",
    "ORBIA.MX", "GCARSOA1.MX", "PE&OLES.MX", "AC.MX", "LIVEPOLC-1.MX",
    "GRUMAB.MX", "KIMBERA.MX", "CHDRAUIB.MX", "LABB.MX", "MEGACPO.MX",
    "Q.MX", "RA.MX", "VESTA.MX", "FUNO11.MX", "GENTERA.MX",
    "BBAJIOO.MX", "CUERVO.MX", "SITESB-1.MX", "VOLARA.MX", "GCC.MX",
    "ALFAA.MX", "AGUA.MX", "CREAL.MX", "TERRA13.MX", "FIBRAPL14.MX",
]


def obtener_sp500() -> list:
    """
    Descarga la lista actual del S&P 500 desde Wikipedia.
    Si falla, retorna lista vacía (el resto del universo sigue funcionando).
    """
    try:
        tablas = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        simbolos = tablas[0]["Symbol"].astype(str).tolist()
        # Yahoo usa guion en vez de punto: BRK.B -> BRK-B
        return [s.replace(".", "-").strip() for s in simbolos]
    except Exception as e:
        print(f"  ⚠ No se pudo obtener S&P 500 desde Wikipedia: {e}")
        return []


def construir_universo(incluir_sp500=True, incluir_nasdaq=True, incluir_bmv=True) -> list:
    """Retorna la lista completa de tickers, sin duplicados."""
    universo = []
    if incluir_sp500:
        sp = obtener_sp500()
        print(f"S&P 500: {len(sp)} tickers")
        universo += sp
    if incluir_nasdaq:
        print(f"NASDAQ-100: {len(NASDAQ_100)} tickers")
        universo += NASDAQ_100
    if incluir_bmv:
        print(f"BMV: {len(BMV)} tickers")
        universo += BMV

    # Eliminar duplicados preservando orden
    vistos = set()
    unicos = []
    for t in universo:
        if t and t not in vistos:
            vistos.add(t)
            unicos.append(t)
    print(f"Universo total (sin duplicados): {len(unicos)} tickers")
    return unicos
