"""
indicadores.py — v2
Calculo de indicadores tecnicos, fundamentales y de riesgo.

Cambios respecto a la version anterior:
  1. El bloque tecnico ya no suma señales contradictorias. Se separa en
     TENDENCIA, MOMENTUM y TIMING, y el timing se interpreta SEGUN la
     tendencia: una sobreventa dentro de una tendencia alcista es una
     oportunidad de entrada; la misma sobreventa en tendencia bajista
     no lo es (es un cuchillo cayendo).
  2. Se agrega el oscilador estocastico diario (14,3).
  3. El P/E se compara contra la mediana de su sector, no contra un
     umbral fijo igual para todos.
"""
import numpy as np
import pandas as pd


# ============================================================
# INDICADORES TECNICOS
# ============================================================

def rsi(close: pd.Series, periodo: int = 14) -> pd.Series:
    delta = close.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    avg_gain = ganancia.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    avg_loss = perdida.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # Sin perdidas en la ventana el RSI es 100 (no indefinido); sin
    # movimiento alguno, 50. Sin esto, un papel que solo sube devolveria
    # NaN y quedaria descartado del analisis.
    sin_perdidas = (avg_loss == 0) & (avg_gain > 0)
    sin_movimiento = (avg_loss == 0) & (avg_gain == 0)
    out = out.mask(sin_perdidas, 100.0).mask(sin_movimiento, 50.0)
    return out


def macd(close: pd.Series, rapida=12, lenta=26, señal=9):
    ema_rapida = close.ewm(span=rapida, adjust=False).mean()
    ema_lenta = close.ewm(span=lenta, adjust=False).mean()
    linea_macd = ema_rapida - ema_lenta
    linea_señal = linea_macd.ewm(span=señal, adjust=False).mean()
    return linea_macd, linea_señal, linea_macd - linea_señal


def estocastico(high: pd.Series, low: pd.Series, close: pd.Series,
                periodo=14, suavizado=3):
    """
    Oscilador estocastico diario.
    %K = posicion del cierre dentro del rango de las ultimas N sesiones.
    %D = media movil de %K (señal).
    Bajo 20 = sobreventa; sobre 80 = sobrecompra.
    """
    minimo = low.rolling(periodo).min()
    maximo = high.rolling(periodo).max()
    rango = (maximo - minimo).replace(0, np.nan)
    k = (close - minimo) / rango * 100
    k_suave = k.rolling(suavizado).mean()
    d = k_suave.rolling(suavizado).mean()
    return k_suave, d


def medias_moviles(close: pd.Series):
    return {
        "sma20": close.rolling(20).mean(),
        "sma50": close.rolling(50).mean(),
        "sma200": close.rolling(200).mean(),
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
    prom = volume.rolling(periodo).mean().iloc[-1]
    if pd.isna(prom) or prom == 0:
        return 1.0
    return float(volume.iloc[-1] / prom)


def _v(serie, i=-1):
    """Valor de una serie, o None si no es utilizable."""
    try:
        x = float(serie.iloc[i])
        return None if (np.isnan(x) or np.isinf(x)) else x
    except Exception:
        return None


def analisis_tecnico(df: pd.DataFrame) -> dict:
    """
    Retorna valores actuales y tres sub-lecturas independientes:
      tendencia (-2..+2), momentum (-1..+1), timing (-1..+1)
    El score tecnico es su suma, en el mismo rango -4..+4 de antes.
    """
    close, high, low = df["Close"], df["High"], df["Low"]

    rsi_s = rsi(close)
    macd_l, macd_s, macd_h = macd(close)
    medias = medias_moviles(close)
    bb_sup, bb_med, bb_inf = bandas_bollinger(close)
    k, d = estocastico(high, low, close)
    atr_s = atr(high, low, close)

    p = _v(close)
    sma20, sma50, sma200 = _v(medias["sma20"]), _v(medias["sma50"]), _v(medias["sma200"])
    rsi_v = _v(rsi_s)
    hist, hist_prev = _v(macd_h), _v(macd_h, -2)
    k_v, d_v = _v(k), _v(d)
    bb_s, bb_i = _v(bb_sup), _v(bb_inf)

    # ---------- TENDENCIA (-2 a +2) ----------
    tendencia = 0
    if p is not None and sma20 is not None and sma50 is not None:
        if p > sma20 > sma50:
            tendencia += 1
        elif p < sma20 < sma50:
            tendencia -= 1
    if p is not None and sma200 is not None:
        tendencia += 1 if p > sma200 else -1

    alcista = tendencia > 0
    bajista = tendencia < 0

    # ---------- MOMENTUM (-1 a +1) ----------
    momentum = 0
    if hist is not None:
        if hist > 0:
            momentum = 1 if (hist_prev is None or hist >= hist_prev) else 0
        else:
            momentum = -1 if (hist_prev is None or hist <= hist_prev) else 0

    # ---------- TIMING (-1 a +1), leido segun la tendencia ----------
    rango_bb = (bb_s - bb_i) if (bb_s is not None and bb_i is not None and bb_s != bb_i) else None
    pos_bb = ((p - bb_i) / rango_bb) if (rango_bb and p is not None) else None

    sobrevendido = ((rsi_v is not None and rsi_v < 35) or
                    (k_v is not None and k_v < 20) or
                    (pos_bb is not None and pos_bb < 0.15))
    sobrecomprado = ((rsi_v is not None and rsi_v > 70) or
                     (k_v is not None and k_v > 80) or
                     (pos_bb is not None and pos_bb > 0.85))
    cruce_k = (k_v is not None and d_v is not None and k_v > d_v and k_v < 40)

    timing = 0
    if alcista:
        if sobrevendido or cruce_k:
            timing = 1      # retroceso dentro de tendencia alcista: buena entrada
        elif sobrecomprado:
            timing = -1     # extendido: mala entrada, aunque la tendencia sea buena
    elif bajista:
        if sobrecomprado:
            timing = -1     # rebote agotandose dentro de tendencia bajista
        elif sobrevendido:
            timing = 0      # sobreventa en caida NO es señal de compra
    else:
        if sobrevendido and cruce_k:
            timing = 1
        elif sobrecomprado:
            timing = -1

    score = tendencia + momentum + timing

    return {
        "precio_actual": p if p is not None else float("nan"),
        "rsi": rsi_v if rsi_v is not None else float("nan"),
        "macd_hist": hist,
        "estocastico_k": k_v,
        "estocastico_d": d_v,
        "sma20": sma20, "sma50": sma50, "sma200": sma200,
        "bb_superior": bb_s, "bb_inferior": bb_i,
        "posicion_bollinger": round(pos_bb, 2) if pos_bb is not None else None,
        "atr": _v(atr_s),
        "volumen_relativo": round(tendencia_volumen(df["Volume"]), 2),
        "señales": {"tendencia": tendencia, "momentum": momentum, "timing": timing},
        "score_tecnico": int(score),
        "regimen": "Alcista" if alcista else "Bajista" if bajista else "Lateral",
    }


# ============================================================
# INDICADORES FUNDAMENTALES
# ============================================================

def analisis_fundamental(info: dict, mediana_sector: float = None) -> dict:
    """
    info: diccionario del cache (estilo yfinance .info)
    mediana_sector: P/E mediano del sector de esta emisora, si se conoce.
                    Si no, se usan umbrales absolutos como respaldo.
    """
    pe = info.get("trailingPE")
    peg = info.get("pegRatio")
    margen = info.get("operatingMargins")
    crecimiento = info.get("revenueGrowth")
    deuda = info.get("debtToEquity")
    roe = info.get("returnOnEquity")

    señales = {}
    pe_relativo = None

    if pe is not None:
        if pe < 0:
            señales["pe"] = -1
        elif mediana_sector and mediana_sector > 0:
            pe_relativo = round(pe / mediana_sector, 2)
            señales["pe"] = 1 if pe_relativo < 0.80 else -1 if pe_relativo > 1.30 else 0
        else:
            señales["pe"] = 1 if pe < 15 else -1 if pe > 35 else 0

    if peg is not None:
        señales["peg"] = 1 if peg < 1 else -1 if peg > 2 else 0
    if margen is not None:
        señales["margen"] = 1 if margen > 0.20 else -1 if margen < 0.05 else 0
    if crecimiento is not None:
        señales["crecimiento"] = 1 if crecimiento > 0.10 else -1 if crecimiento < 0 else 0
    if roe is not None:
        señales["roe"] = 1 if roe > 0.15 else -1 if roe < 0.05 else 0
    if deuda is not None:
        señales["deuda"] = 1 if deuda < 50 else -1 if deuda > 150 else 0

    return {
        "pe": pe, "peg": peg, "margen_operativo": margen,
        "crecimiento_ingresos": crecimiento, "roe": roe, "deuda_capital": deuda,
        "pe_mediana_sector": round(mediana_sector, 2) if mediana_sector else None,
        "pe_relativo_sector": pe_relativo,
        "señales": señales,
        "score_fundamental": sum(señales.values()),
    }


# ============================================================
# SCORE DE RIESGO
# ============================================================

def score_riesgo(df: pd.DataFrame, beta: float | None) -> dict:
    close = df["Close"]
    retornos = close.pct_change().dropna()
    vol = float(retornos.std() * np.sqrt(252)) if len(retornos) > 1 else 0.0

    acumulado = (1 + retornos).cumprod()
    drawdown = (acumulado - acumulado.cummax()) / acumulado.cummax()
    max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    atr_actual = _v(atr(df["High"], df["Low"], close)) or 0.0
    precio = float(close.iloc[-1]) if len(close) else 0.0
    atr_rel = atr_actual / precio if precio else 0.0
    beta_v = beta if beta is not None else 1.0

    score = (min(vol / 0.60, 1.0) * 100 * 0.35 +
             min(abs(max_dd) / 0.50, 1.0) * 100 * 0.30 +
             min(abs(beta_v) / 2.5, 1.0) * 100 * 0.20 +
             min(atr_rel / 0.06, 1.0) * 100 * 0.15)

    nivel = "Bajo" if score < 33 else "Medio" if score < 66 else "Alto"
    return {
        "volatilidad_anualizada": round(vol * 100, 1),
        "max_drawdown": round(max_dd * 100, 1),
        "beta": round(beta_v, 2),
        "atr_relativo": round(atr_rel * 100, 2),
        "score_riesgo": round(score, 1),
        "nivel_riesgo": nivel,
    }


# ============================================================
# SEÑAL COMPUESTA
# ============================================================

def señal_compuesta(score_tecnico: int, score_fundamental: int, score_riesgo_v: float,
                     peso_tecnico=0.45, peso_fundamental=0.40, peso_riesgo=0.15) -> dict:
    tecnico_norm = (score_tecnico / 4) * 100
    fundamental_norm = (score_fundamental / 6) * 100
    penalizacion = (score_riesgo_v - 50) / 50 * 100

    compuesto = (tecnico_norm * peso_tecnico +
                 fundamental_norm * peso_fundamental -
                 penalizacion * peso_riesgo)

    if compuesto >= 35:
        s = "COMPRA FUERTE"
    elif compuesto >= 15:
        s = "COMPRA"
    elif compuesto <= -35:
        s = "VENTA FUERTE"
    elif compuesto <= -15:
        s = "VENTA"
    else:
        s = "MANTENER / OBSERVAR"
    return {"score_compuesto": round(compuesto, 1), "señal": s}


def medianas_por_sector(cache: dict, minimo_pares: int = 5) -> dict:
    """
    Calcula el P/E mediano de cada sector a partir del cache.
    Solo devuelve sectores con suficientes emisoras para que la mediana
    sea representativa. Descarta P/E negativos y valores extremos.
    """
    por_sector = {}
    for datos in cache.values():
        if not isinstance(datos, dict) or datos.get("es_etf"):
            continue
        sector = datos.get("sector")
        pe = datos.get("trailingPE")
        if not sector or pe is None:
            continue
        try:
            pe = float(pe)
        except (TypeError, ValueError):
            continue
        if pe <= 0 or pe > 200:
            continue
        por_sector.setdefault(sector, []).append(pe)

    return {s: float(np.median(v)) for s, v in por_sector.items()
            if len(v) >= minimo_pares}
