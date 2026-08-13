"""
datos.py
Obtiene precios históricos y datos fundamentales vía yfinance.
Requiere conexión a internet y `pip install yfinance --break-system-packages`.
"""
import yfinance as yf
import pandas as pd


def obtener_datos_ticker(ticker: str, periodo="1y") -> dict:
    """
    Retorna dict con:
      - 'ohlcv': DataFrame con Open/High/Low/Close/Volume
      - 'info': dict fundamentales (yfinance .info)
      - 'beta': float o None
    Lanza excepción si el ticker no devuelve datos de precio.
    """
    tk = yf.Ticker(ticker)
    hist = tk.history(period=periodo, auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No se encontraron datos de precio para '{ticker}'. "
                          f"Verifica que el símbolo sea correcto.")

    info = {}
    beta = None
    try:
        info = tk.info or {}
        beta = info.get("beta")
    except Exception:
        # Algunos tickers (ETFs, mercados fuera de EE. UU.) devuelven .info incompleto.
        pass

    return {"ohlcv": hist, "info": info, "beta": beta}
