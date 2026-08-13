"""
dashboard.py
Genera un dashboard HTML (tema oscuro) con las alertas de compra/venta
para todos los tickers analizados.
"""
from datetime import datetime

COLOR_SEÑAL = {
    "COMPRA FUERTE": "#22c55e",
    "COMPRA": "#4ade80",
    "MANTENER / OBSERVAR": "#94a3b8",
    "VENTA": "#f87171",
    "VENTA FUERTE": "#ef4444",
}

COLOR_RIESGO = {"Bajo": "#22c55e", "Medio": "#f59e0b", "Alto": "#ef4444"}


def _fmt_pct(v):
    return f"{v*100:.1f}%" if isinstance(v, (int, float)) else "—"


def _fmt(v, dec=2):
    return f"{v:.{dec}f}" if isinstance(v, (int, float)) else "—"


def _tarjeta(ticker: str, resultado: dict) -> str:
    tec = resultado["tecnico"]
    fund = resultado["fundamental"]
    riesgo = resultado["riesgo"]
    comp = resultado["compuesto"]

    color_señal = COLOR_SEÑAL.get(comp["señal"], "#94a3b8")
    color_riesgo = COLOR_RIESGO.get(riesgo["nivel_riesgo"], "#94a3b8")

    return f"""
    <div class="tarjeta">
      <div class="tarjeta-header">
        <div>
          <div class="ticker">{ticker}</div>
          <div class="precio">${_fmt(tec['precio_actual'])}</div>
        </div>
        <div class="señal-badge" style="background:{color_señal}22; color:{color_señal}; border:1px solid {color_señal}55;">
          {comp['señal']}
        </div>
      </div>

      <div class="score-compuesto">
        <div class="score-barra-fondo">
          <div class="score-barra-relleno" style="width:{min(abs(comp['score_compuesto']),100)}%; background:{color_señal}; margin-left:{50 if comp['score_compuesto']>=0 else 50-min(abs(comp['score_compuesto']),100)}%;"></div>
        </div>
        <div class="score-valor">Score compuesto: <b>{comp['score_compuesto']}</b> / ±100</div>
      </div>

      <div class="metricas-grid">
        <div class="metrica-col">
          <div class="metrica-titulo">Técnico</div>
          <div class="metrica-fila"><span>RSI (14)</span><span>{_fmt(tec['rsi'],1)}</span></div>
          <div class="metrica-fila"><span>MACD hist.</span><span>{_fmt(tec['macd_hist'],2)}</span></div>
          <div class="metrica-fila"><span>SMA20 / SMA50</span><span>{_fmt(tec['sma20'],2)} / {_fmt(tec['sma50'],2)}</span></div>
          <div class="metrica-fila"><span>Vol. relativo</span><span>{_fmt(tec['volumen_relativo'],2)}x</span></div>
        </div>
        <div class="metrica-col">
          <div class="metrica-titulo">Fundamental</div>
          <div class="metrica-fila"><span>P/E</span><span>{_fmt(fund['pe'],1)}</span></div>
          <div class="metrica-fila"><span>PEG</span><span>{_fmt(fund['peg'],2)}</span></div>
          <div class="metrica-fila"><span>Margen operativo</span><span>{_fmt_pct(fund['margen_operativo'])}</span></div>
          <div class="metrica-fila"><span>Crec. ingresos</span><span>{_fmt_pct(fund['crecimiento_ingresos'])}</span></div>
        </div>
      </div>

      <div class="riesgo-footer">
        <span class="riesgo-badge" style="background:{color_riesgo}22; color:{color_riesgo}; border:1px solid {color_riesgo}55;">
          Riesgo {riesgo['nivel_riesgo']}
        </span>
        <span class="riesgo-detalle">Vol. anual {_fmt(riesgo['volatilidad_anualizada'],1)}% · Máx. drawdown {_fmt(riesgo['max_drawdown'],1)}% · Beta {_fmt(riesgo['beta'],2)}</span>
      </div>
    </div>
    """


def generar_dashboard(resultados: dict, titulo="Monitor de Oportunidades") -> str:
    """
    resultados: dict {ticker: {"tecnico":..., "fundamental":..., "riesgo":..., "compuesto":...}}
    Retorna el HTML completo como string.
    """
    orden = sorted(resultados.items(), key=lambda kv: kv[1]["compuesto"]["score_compuesto"], reverse=True)
    tarjetas_html = "\n".join(_tarjeta(t, r) for t, r in orden)

    n_compra = sum(1 for _, r in orden if "COMPRA" in r["compuesto"]["señal"])
    n_venta = sum(1 for _, r in orden if "VENTA" in r["compuesto"]["señal"])
    n_mantener = len(orden) - n_compra - n_venta
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{titulo}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0b0f14; color:#e2e8f0;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    padding:32px 24px;
  }}
  .contenedor {{ max-width:1200px; margin:0 auto; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:28px; flex-wrap:wrap; gap:12px; }}
  .header h1 {{ font-size:26px; font-weight:700; letter-spacing:-0.02em; }}
  .header .fecha {{ color:#64748b; font-size:13px; }}
  .resumen {{ display:flex; gap:12px; margin-bottom:28px; flex-wrap:wrap; }}
  .resumen-item {{ background:#131922; border:1px solid #1e2733; border-radius:10px; padding:14px 20px; flex:1; min-width:140px; }}
  .resumen-item .num {{ font-size:24px; font-weight:700; }}
  .resumen-item .lbl {{ font-size:12px; color:#64748b; margin-top:2px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(340px, 1fr)); gap:16px; }}
  .tarjeta {{ background:#131922; border:1px solid #1e2733; border-radius:14px; padding:20px; }}
  .tarjeta-header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }}
  .ticker {{ font-size:19px; font-weight:700; letter-spacing:0.02em; }}
  .precio {{ font-size:14px; color:#94a3b8; margin-top:2px; }}
  .señal-badge {{ font-size:11px; font-weight:700; letter-spacing:0.04em; padding:6px 10px; border-radius:6px; white-space:nowrap; }}
  .score-compuesto {{ margin-bottom:18px; }}
  .score-barra-fondo {{ height:6px; background:#1e2733; border-radius:3px; position:relative; overflow:hidden; }}
  .score-barra-relleno {{ height:100%; border-radius:3px; position:absolute; }}
  .score-valor {{ font-size:12px; color:#64748b; margin-top:6px; }}
  .metricas-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
  .metrica-titulo {{ font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#475569; margin-bottom:8px; font-weight:600; }}
  .metrica-fila {{ display:flex; justify-content:space-between; font-size:13px; padding:4px 0; color:#cbd5e1; }}
  .metrica-fila span:last-child {{ font-weight:600; color:#e2e8f0; }}
  .riesgo-footer {{ display:flex; align-items:center; gap:10px; padding-top:14px; border-top:1px solid #1e2733; flex-wrap:wrap; }}
  .riesgo-badge {{ font-size:11px; font-weight:700; padding:4px 9px; border-radius:6px; }}
  .riesgo-detalle {{ font-size:11px; color:#64748b; }}
  .footer-nota {{ margin-top:32px; font-size:12px; color:#475569; text-align:center; line-height:1.6; }}
</style>
</head>
<body>
  <div class="contenedor">
    <div class="header">
      <h1>{titulo}</h1>
      <div class="fecha">Actualizado: {fecha}</div>
    </div>

    <div class="resumen">
      <div class="resumen-item"><div class="num" style="color:#4ade80">{n_compra}</div><div class="lbl">Señales de compra</div></div>
      <div class="resumen-item"><div class="num" style="color:#94a3b8">{n_mantener}</div><div class="lbl">Mantener / observar</div></div>
      <div class="resumen-item"><div class="num" style="color:#f87171">{n_venta}</div><div class="lbl">Señales de venta</div></div>
      <div class="resumen-item"><div class="num">{len(orden)}</div><div class="lbl">Tickers analizados</div></div>
    </div>

    <div class="grid">
      {tarjetas_html}
    </div>

    <div class="footer-nota">
      Herramienta de apoyo cuantitativo — no constituye recomendación de inversión individualizada.<br>
      Score compuesto = 45% técnico + 40% fundamental − 15% penalización por riesgo.
    </div>
  </div>
</body>
</html>"""
