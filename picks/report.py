"""Reporte diario: HTML para el celular + texto para Telegram."""
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORTES

TZ = ZoneInfo("America/Guayaquil")
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
NOMBRE_FUENTE = {"mercado": "Mercado", "modelo": "Modelo", "forebet": "Forebet", "apifootball": "API-Football",
                 "ensamble": "Combinado"}
e = html.escape


def _hora(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    return f"{DIAS[dt.weekday()]} {dt:%d %H:%M}"


def _pct(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def _usd(x):
    return f"{'+' if x >= 0 else '-'}${abs(x):.2f}"


def _c(x):
    return "–" if x is None else f"{x:.2f}"


def texto(valor, alta, cfg, res) -> str:
    hoy = datetime.now(TZ).strftime("%d/%m/%Y")
    L = [f"📊 Picks {hoy} — banca ${cfg['banca']:.0f}", ""]
    if not valor:
        L.append("Hoy no hay apuestas de valor con consenso suficiente. No apostar también es ganar.")
    for i, s in enumerate(valor, 1):
        cond = f"cuota Ecuabet {s['cuota_ecuabet']:.2f}" if s["confirmado"] else f"apuesta solo si Ecuabet paga ≥ {s['cuota_minima']:.2f}"
        L += [f"{i}. {s['local']} vs {s['visita']} ({s['liga']}, {_hora(s['inicio'])})",
              f"   ➜ {s['nombre']} | prob {_pct(s['p'])} | {s['acuerdo'] * 100:.0f}% de {s['n_fuentes']} fuentes ven valor",
              f"   ➜ {cond} | monto ${s['monto']:.2f}", ""]
    if alta:
        L += ["🔒 Alta probabilidad (revisa la cuota en Ecuabet):"]
        L += [f"• {s['local']} vs {s['visita']}: {s['nombre']} ({_pct(s['p'])}, mín. {s['cuota_minima']:.2f})"
              for s in alta]
    if res.get("n"):
        L += ["", f"Historial: {res['n']} apuestas | ROI {res['roi'] * 100:+.1f}% | neto {_usd(res['neto'])}"]
    return "\n".join(L)


def _detalle(s) -> str:
    partes = []
    for f, p in sorted(s["detalle"].items(), key=lambda kv: -s["pesos"].get(kv[0], 0)):
        partes.append(f"<span class='src'>{NOMBRE_FUENTE.get(f, f)} <b>{_pct(p)}</b>"
                      f"<i>peso {s['pesos'].get(f, 0) * 100:.0f}%</i></span>")
    return "".join(partes)


def _tarjeta(i, s, tipo):
    if tipo == "valor":
        estado = ("<span class='ok'>Cuota de Ecuabet confirmada</span>" if s.get("confirmado")
                  else f"<span class='warn'>Apostar solo si Ecuabet paga ≥ {s['cuota_minima']:.2f}</span>")
        monto = "según tu banca"      # la banca no va en el HTML; se calcula abajo con la que guardes en el navegador
        meta = (f"Mejor cuota en el mercado: {_c(s['mejor_cuota'])} ({e(s['mejor_casa'] or '–')}) · "
                f"valor {_pct(s['ev'])} · {s['acuerdo'] * 100:.0f}% de las fuentes ven valor")
    else:
        estado = f"<span class='warn'>Apostar solo si Ecuabet paga ≥ {s['cuota_minima']:.2f}</span>"
        monto = "–"
        ref = (f"Mejor cuota en el mercado: {_c(s['mejor_cuota'])} ({e(s['mejor_casa'] or '–')}) · "
               if s.get("mejor_cuota") else "Sin cuota de referencia · ")
        meta = ref + f"desacuerdo entre fuentes ±{s['dispersion'] * 100:.1f} pts"
    return f"""
<div class="card" data-p="{s['p']:.6f}" data-push="{s['p_push']:.6f}">
  <div class="top"><span>#{i} · {e(s['liga'])} · {e(s['mercado'])}</span><span>{_hora(s['inicio'])}</span></div>
  <div class="match">{e(s['local'])} <small>vs</small> {e(s['visita'])}</div>
  <div class="pick">{e(s['nombre'])}</div>
  <div class="grid">
    <div><b>{_pct(s['p'])}</b><small>Probabilidad</small></div>
    <div><b>{_c(s['cuota_justa'])}</b><small>Cuota justa</small></div>
    <div><b>{_c(s['cuota_minima'])}</b><small>Cuota mínima</small></div>
    <div><b>{monto}</b><small>Monto</small></div>
  </div>
  <div class="srcs">{_detalle(s)}</div>
  <div class="meta">{meta}</div>
  {estado}
  <label>Cuota que ves en Ecuabet:
    <input type="number" step="0.01" inputmode="decimal" placeholder="{s['cuota_minima']:.2f}" value="{s.get('cuota_ecuabet') or ''}"></label>
  <div class="calc"></div>
</div>"""


def html_reporte(valor, alta, partidos, cfg, res, calib, creditos) -> str:
    hoy = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    filas = []
    for pa in sorted(partidos, key=lambda x: x["inicio"]):
        g = lambda k: _pct(pa["probs"][k]["p"]) if k in pa["probs"] else "–"  # noqa: E731
        es = pa.get("esperados") or {}
        cor = es.get("corners") or es.get("corners_fb")
        tar = es.get("tarjetas") or es.get("tarjetas_fb")
        xg = f"{pa['xg'][0]:.1f}–{pa['xg'][1]:.1f}" if pa.get("xg") else "–"
        filas.append(f"<tr><td>{_hora(pa['inicio'])}<br><small>{e(pa['liga'])}</small></td>"
                     f"<td>{e(pa['local'])}<br>{e(pa['visita'])}</td><td>{g('1x2:1')}</td><td>{g('1x2:X')}</td>"
                     f"<td>{g('1x2:2')}</td><td>{g('ou:2.5:over')}</td><td>{g('btts:si')}</td>"
                     f"<td>{_c(cor) if cor else '–'}</td><td>{_c(tar) if tar else '–'}</td><td>{xg}</td>"
                     f"<td>{len(pa['fuentes'])}</td></tr>")

    cal = ""
    if calib:
        fams = sorted({f for (_, f) in calib})
        fuentes = sorted({s for (s, _) in calib})
        cab = "".join(f"<th>{e(NOMBRE_FUENTE.get(s, s))}</th>" for s in fuentes)
        cuerpo = ""
        for fam in fams:
            celdas = "".join(
                f"<td>{calib[(s, fam)]['brier']:.3f}<br><small>n={calib[(s, fam)]['n']}</small></td>"
                if (s, fam) in calib else "<td>–</td>" for s in fuentes)
            cuerpo += f"<tr><td>{e(fam)}</td>{celdas}</tr>"
        cal = (f"<h2>Precisión de cada fuente</h2><div class='card' style='overflow-x:auto'><table>"
               f"<tr><th>Mercado</th>{cab}</tr>{cuerpo}</table><p class='meta'>Error Brier: más bajo = mejor. "
               f"Los pesos del combinado se ajustan solos según esta tabla.</p></div>")

    hist = ""
    if res.get("n"):
        # el HTML no muestra dólares (neto/apostado): solo n y ROI. El Telegram privado sí muestra el neto.
        pm = "".join(f"<tr><td>{e(k)}</td><td>{v['n']}</td><td>{(v['neto'] / v['apostado'] * 100 if v.get('apostado') else 0):+.1f}%</td></tr>"
                     for k, v in sorted(res.get("por_mercado", {}).items()))
        hist = f"""<h2>Tu historial</h2><div class="card"><div class="grid">
<div><b>{res['n']}</b><small>Apuestas</small></div><div><b>{(res.get('acierto') or 0) * 100:.0f}%</b><small>Acierto</small></div>
<div><b>{(res.get('roi') or 0) * 100:+.1f}%</b><small>ROI</small></div></div>
<table><tr><th>Mercado</th><th>N</th><th>ROI</th></tr>{pm}</table>
<p class="meta">El ROI solo es confiable a partir de ~200 apuestas.</p></div>"""

    v_html = "".join(_tarjeta(i, s, "valor") for i, s in enumerate(valor, 1)) or \
        "<div class='card'><b>Hoy no hay apuestas de valor con consenso suficiente.</b><br>No apostar también es ganar.</div>"
    a_html = "".join(_tarjeta(i, s, "alta") for i, s in enumerate(alta, 1)) or \
        "<div class='card'>Sin selecciones de alta probabilidad hoy.</div>"
    js_cfg = json.dumps({k: cfg[k] for k in ("fraccion_kelly", "stake_max_pct", "ventaja_minima")})

    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Picks {hoy}</title>
<style>
:root{{--bg:#0f1115;--card:#181b22;--tx:#e8eaed;--mu:#9aa0a6;--ok:#34c759;--bad:#ff453a;--wa:#ffb020;--ac:#4c8dff;--ch:#262a33}}
@media (prefers-color-scheme: light){{:root{{--bg:#f4f5f7;--card:#fff;--tx:#14161a;--mu:#5f6368;--ch:#eef0f3}}}}
body{{margin:0;font:15px/1.4 -apple-system,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx)}}
main{{max-width:720px;margin:auto;padding:16px}} h1{{font-size:22px;margin:4px 0}} h2{{font-size:17px;margin:24px 0 8px}}
.card{{background:var(--card);border-radius:14px;padding:14px;margin:10px 0;box-shadow:0 1px 3px #0003}}
.top{{display:flex;justify-content:space-between;gap:8px;color:var(--mu);font-size:12px}}
.match{{font-size:17px;font-weight:600;margin:6px 0 2px}} .pick{{color:var(--ac);font-weight:700;font-size:16px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:10px 0;text-align:center}}
.grid b{{display:block;font-size:16px}} small{{color:var(--mu);font-size:11px}}
.srcs{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}} .src{{background:var(--ch);border-radius:8px;padding:4px 8px;font-size:12px}}
.src i{{color:var(--mu);font-style:normal;margin-left:4px;font-size:10px}}
.meta{{color:var(--mu);font-size:12px;margin:6px 0}} .ok{{color:var(--ok);font-weight:600}} .warn{{color:var(--wa);font-weight:600}}
label{{display:block;margin-top:10px;font-size:13px}} input{{width:100%;box-sizing:border-box;padding:10px;font-size:16px;border-radius:10px;border:1px solid #8885;background:transparent;color:var(--tx);margin-top:4px}}
.calc{{margin-top:8px;font-weight:600}} table{{width:100%;border-collapse:collapse;font-size:12px}}
td,th{{padding:6px 3px;border-bottom:1px solid #8883;text-align:center}} td:nth-child(2){{text-align:left}}
</style></head><body><main>
<h1>Picks del día</h1><div class="meta">{hoy} (Ecuador) · valor mínimo {cfg['ventaja_minima'] * 100:.0f}% ·
mínimo {cfg['min_fuentes']} fuentes{(' · ' + e(creditos)) if creditos else ''}</div>
<h2>Apuestas de valor</h2>{v_html}
<h2>Alta probabilidad</h2><p class="meta">Mercados donde todas las fuentes coinciden, pero sin cuota de referencia
para medir el valor. Apuesta solo si Ecuabet paga al menos la cuota mínima.</p>{a_html}
<h2>Cómo sacar el código de Ecuabet</h2><div class="card"><ol>
<li>Abre Ecuabet y busca cada partido.</li><li>Si la cuota es menor que la cuota mínima, salta ese pick.</li>
<li>Agrega al cupón los que cumplen. Mejor apuestas simples que combinadas.</li>
<li>Toca "guardar/reservar apuesta": Ecuabet te da el código.</li>
<li>Si tomaste otra cuota, anótala: <code>python main.py registrar ID CUOTA</code>.</li></ol></div>
{hist}{cal}
<h2>Indicadores de todos los partidos</h2><div class="card" style="overflow-x:auto"><table>
<tr><th>Hora</th><th>Partido</th><th>1</th><th>X</th><th>2</th><th>+2.5</th><th>AM</th><th>Córn.</th><th>Tarj.</th><th>xG</th><th>Fts</th></tr>
{''.join(filas) or '<tr><td colspan=11>Sin partidos.</td></tr>'}</table>
<p class="meta">Probabilidades combinadas de todas las fuentes. AM = ambos marcan. Córn./Tarj. = promedio esperado. Fts = fuentes.</p></div>
<p class="meta">Ningún sistema garantiza ganancias. Apuesta solo lo que puedas perder.</p>
</main><script>
const cfg={js_cfg}; cfg.banca=parseFloat(localStorage.getItem('banca'))||0;   // la banca solo vive en tu navegador
document.querySelectorAll('.card[data-p]').forEach(c=>{{
 const p=+c.dataset.p, pp=+c.dataset.push, inp=c.querySelector('input'), out=c.querySelector('.calc');
 const f=()=>{{const o=parseFloat(inp.value); if(!o){{out.textContent='';return}}
  const ev=(1-pp)*(p*o-1), k=Math.max(0,Math.min((1-pp)*(p*o-1)/(o-1)*cfg.fraccion_kelly,cfg.stake_max_pct));
  const m=Math.max(1,Math.round(k*cfg.banca*4)/4), txt=cfg.banca?`$${{m.toFixed(2)}}`:`${{(k*100).toFixed(1)}}% de tu banca`;
  if(ev>=cfg.ventaja_minima){{out.style.color='var(--ok)';out.textContent=`✔ Valor ${{(ev*100).toFixed(1)}}% → apostar ${{txt}}`}}
  else{{out.style.color='var(--bad)';out.textContent=`✘ Valor ${{(ev*100).toFixed(1)}}% → no apostar`}}}};
 inp.addEventListener('input',f); f();}});
</script></body></html>"""


def guardar(valor, alta, partidos, cfg, res, calib, creditos=None):
    fecha = datetime.now(TZ).strftime("%Y-%m-%d")
    h = REPORTES / f"picks_{fecha}.html"
    t = REPORTES / f"picks_{fecha}.txt"
    h.write_text(html_reporte(valor, alta, partidos, cfg, res, calib, creditos), encoding="utf-8")
    t.write_text(texto(valor, alta, cfg, res), encoding="utf-8")
    (REPORTES / "ultimo.html").write_text(h.read_text(encoding="utf-8"), encoding="utf-8")
    return h, t


def texto_niveles(seguras, grandes) -> str:
    L = []
    if seguras:
        L += ["", "✅ Seguras (cuota baja, alta probabilidad):"]
        L += [f"• {s['local']} vs {s['visita']}: {s['nombre']} ({_pct(s['p'])}, cuota ~{s['cuota_est']:.2f})"
              + (" ⚠️" if (s.get('ia') or {}).get('riesgo') == 'medio' else "") for s in seguras]
    for c in grandes:
        L += ["", f"🚀 Combinada: ganancia neta ${c['ganancia'] - c['monto']:.0f} (cobras ${c['ganancia']:.0f}) con ${c['monto']:.0f} (cuota {c['cuota']:.1f}, "
                  f"prob. real {c['p'] * 100:.1f}% ≈ 1 de cada {max(1, round(1 / c['p']))})"]
        L += [f"   - {s['local']} vs {s['visita']}: {s['nombre']} ({_pct(s['p'])})" for s in c["piernas"]]
    return "\n".join(L)
