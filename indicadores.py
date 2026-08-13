"""
indicadores.py
Cálculo de indicadores técnicos, fundamentales y de riesgo.
No requiere APIs de pago: usa yfinance como fuente de datos.
"""
import numpy as np
import pandas as pd


# ============================================================
# INDICADORES TÉCNICOS
# ============================================================

def rsi(close: pd.Series, periodo: int = 14) -> pd.Series:
    delta = close.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    avg_gain = ganancia.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    avg_loss = perdida.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, rapida=12, lenta=26, señal=9):
    ema_rapida = close.ewm(span=rapida, adjust=False).mean()
    ema_lenta = close.ewm(span=lenta, adjust=False).mean()
    linea_macd = ema_rapida - ema_lenta
    linea_señal = linea_macd.ewm(span=señal, adjust=False).mean()
    histograma = linea_macd - linea_señal
    return linea_macd, linea_señal, histograma


def medias_moviles(close: pd.Series):
    return {
        "sma20": close.rolling(20).mean(),
        "sma50": close.rolling(50).mean(),
        "sma200": close.rolling(200).mean(),
        "ema20": close.ewm(span=20, adjust=False).mean(),
    }


def bandas_bollinger(close: pd.Series, periodo=20, n_std=2):
    media = close.rolling(periodo).mean()
    std = close.rolling(periodo).std()
    return media + n_std * std, media, media - n_std * std


def atr(high: pd.Series, low: pd.Series, close: pd.Series, periodo=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / periodo, min_periods=periodo).mean()


def tendencia_volumen(volume: pd.Series, periodo=20) -> float:
    """Volumen reciente vs promedio (>1 = actividad creciente)."""
    prom = volume.rolling(periodo).mean().iloc[-1]
    if pd.isna(prom) or prom == 0:
        return 1.0
    return float(volume.iloc[-1] / prom)


def analisis_tecnico(df: pd.DataFrame) -> dict:
    """
    df debe tener columnas: Open, High, Low, Close, Volume (formato yfinance)
    Retorna diccionario con valores actuales + señales discretas (-1, 0, 1)
    """
    close = df["Close"]
    rsi_serie = rsi(close)
    macd_l, macd_s, macd_h = macd(close)
    medias = medias_moviles(close)
    bb_sup, bb_media, bb_inf = bandas_bollinger(close)
    atr_serie = atr(df["High"], df["Low"], close)

    precio_actual = float(close.iloc[-1])
    rsi_actual = float(rsi_serie.iloc[-1])
    macd_hist_actual = float(macd_h.iloc[-1])
    macd_hist_prev = float(macd_h.iloc[-2]) if len(macd_h) > 1 else macd_hist_actual
    sma20 = float(medias["sma20"].iloc[-1])
    s
