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
    sma50 = float(medias["sma50"].iloc[-1])
    sma200 = float(medias["sma200"].iloc[-1]) if not pd.isna(medias["sma200"].iloc[-1]) else None

    señales = {}

    # RSI: sobreventa <30 compra, sobrecompra >70 venta
    if rsi_actual < 30:
        señales["rsi"] = 1
    elif rsi_actual > 70:
        señales["rsi"] = -1
    else:
        señales["rsi"] = 0

    # MACD: cruce del histograma de negativo a positivo = compra
    if macd_hist_prev < 0 and macd_hist_actual > 0:
        señales["macd"] = 1
    elif macd_hist_prev > 0 and macd_hist_actual < 0:
        señales["macd"] = -1
    else:
        señales["macd"] = 1 if macd_hist_actual > 0 else -1 if macd_hist_actual < 0 else 0

    # Medias móviles: precio y SMA20 sobre SMA50 = tendencia alcista
    if precio_actual > sma20 > sma50:
        señales["tendencia"] = 1
    elif precio_actual < sma20 < sma50:
        señales["tendencia"] = -1
    else:
        señales["tendencia"] = 0

    # Bollinger: cerca de banda inferior = posible compra, cerca de superior = posible venta
    bb_sup_v = float(bb_sup.iloc[-1])
    bb_inf_v = float(bb_inf.iloc[-1])
    rango = bb_sup_v - bb_inf_v if bb_sup_v != bb_inf_v else 1
    posicion_bb = (precio_actual - bb_inf_v) / rango  # 0 = banda inferior, 1 = banda superior
    if posicion_bb < 0.15:
        señales["bollinger"] = 1
    elif posicion_bb > 0.85:
        señales["bollinger"] = -1
    else:
        señales["bollinger"] = 0

    vol_rel = tendencia_volumen(df["Volume"])

    return {
        "precio_actual": precio_actual,
        "rsi": rsi_actual,
        "macd_hist": macd_hist_actual,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "bb_superior": bb_sup_v,
        "bb_inferior": bb_inf_v,
        "posicion_bollinger": round(posicion_bb, 2),
        "atr": float(atr_serie.iloc[-1]),
        "volumen_relativo": round(vol_rel, 2),
        "señales": señales,
        "score_tecnico": sum(señales.values()),  # rango -4 a 4
    }


# ============================================================
# INDICADORES FUNDAMENTALES
# ============================================================

def analisis_fundamental(info: dict) -> dict:
    """
    info: diccionario tipo yfinance Ticker.info
    Compara contra rangos razonables genéricos (ajustables por sector).
    """
    pe = info.get("trailingPE")
    peg = info.get("pegRatio")
    margen_operativo = info.get("operatingMargins")
    crecimiento_ingresos = info.get("revenueGrowth")
    deuda_capital = info.get("debtToEquity")
    roe = info.get("returnOnEquity")
    fcf = info.get("freeCashflow")

    señales = {}

    if pe is not None:
        señales["pe"] = 1 if pe < 15 else -1 if pe > 35 else 0
    if peg is not None:
        señales["peg"] = 1 if peg < 1 else -1 if peg > 2 else 0
    if margen_operativo is not None:
        señales["margen"] = 1 if margen_operativo > 0.20 else -1 if margen_operativo < 0.05 else 0
    if crecimiento_ingresos is not None:
        señales["crecimiento"] = 1 if crecimiento_ingresos > 0.10 else -1 if crecimiento_ingresos < 0 else 0
    if roe is not None:
        señales["roe"] = 1 if roe > 0.15 else -1 if roe < 0.05 else 0
    if deuda_capital is not None:
        señales["deuda"] = 1 if deuda_capital < 50 else -1 if deuda_capital > 150 else 0

    return {
        "pe": pe,
        "peg": peg,
        "margen_operativo": margen_operativo,
        "crecimiento_ingresos": crecimiento_ingresos,
        "roe": roe,
        "deuda_capital": deuda_capital,
        "fcf": fcf,
        "señales": señales,
        "score_fundamental": sum(señales.values()),
    }


# ============================================================
# SCORE DE RIESGO
# ============================================================

def score_riesgo(df: pd.DataFrame, beta: float | None) -> dict:
    """
    Riesgo alto = score cercano a 100. Basado en:
    - Volatilidad anualizada de retornos diarios
    - Máximo drawdown en la ventana de datos
    - Beta vs mercado
    - ATR relativo al precio (volatilidad intradía)
    """
    close = df["Close"]
    retornos = close.pct_change().dropna()
    vol_anualizada = float(retornos.std() * np.sqrt(252)) if len(retornos) > 1 else 0.0

    acumulado = (1 + retornos).cumprod()
    max_acumulado = acumulado.cummax()
    drawdown = (acumulado - max_acumulado) / max_acumulado
    max_drawdown = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    atr_actual = float(atr(df["High"], df["Low"], close).iloc[-1])
    atr_relativo = atr_actual / float(close.iloc[-1]) if close.iloc[-1] else 0.0

    beta_v = beta if beta is not None else 1.0

    # Normalizar cada componente a 0-100 y promediar (pesos ajustables)
    componente_vol = min(vol_anualizada / 0.60, 1.0) * 100       # 60% vol anual = riesgo máximo
    componente_dd = min(abs(max_drawdown) / 0.50, 1.0) * 100      # -50% drawdown = riesgo máximo
    componente_beta = min(abs(beta_v) / 2.5, 1.0) * 100           # beta 2.5 = riesgo máximo
    componente_atr = min(atr_relativo / 0.06, 1.0) * 100          # ATR 6% del precio = riesgo máximo

    score = (componente_vol * 0.35 + componente_dd * 0.30 +
             componente_beta * 0.20 + componente_atr * 0.15)

    if score < 33:
        nivel = "Bajo"
    elif score < 66:
        nivel = "Medio"
    else:
        nivel = "Alto"

    return {
        "volatilidad_anualizada": round(vol_anualizada * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "beta": round(beta_v, 2),
        "atr_relativo": round(atr_relativo * 100, 2),
        "score_riesgo": round(score, 1),
        "nivel_riesgo": nivel,
    }


# ============================================================
# SEÑAL COMPUESTA
# ============================================================

def señal_compuesta(score_tecnico: int, score_fundamental: int, score_riesgo_v: float,
                     peso_tecnico=0.45, peso_fundamental=0.40, peso_riesgo=0.15) -> dict:
    """
    Normaliza scores técnico (-4..4) y fundamental (-6..6) a escala -100..100,
    resta penalización por riesgo, y produce señal final.
    """
    tecnico_norm = (score_tecnico / 4) * 100
    fundamental_norm = (score_fundamental / 6) * 100
    penalizacion_riesgo = (score_riesgo_v - 50) / 50 * 100  # riesgo alto penaliza, riesgo bajo bonifica levemente

    compuesto = (tecnico_norm * peso_tecnico +
                 fundamental_norm * peso_fundamental -
                 penalizacion_riesgo * peso_riesgo)

    if compuesto >= 35:
        señal = "COMPRA FUERTE"
    elif compuesto >= 15:
        señal = "COMPRA"
    elif compuesto <= -35:
        señal = "VENTA FUERTE"
    elif compuesto <= -15:
        señal = "VENTA"
    else:
        señal = "MANTENER / OBSERVAR"

    return {
        "score_compuesto": round(compuesto, 1),
        "señal": señal,
    }
