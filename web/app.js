"use strict";
// frame-ancestors no funciona por <meta>: framebuster simple (anti-clickjacking del token/registro).
try{ if(top!==self){ document.documentElement.style.display="none"; top.location=self.location } }catch(e){ document.documentElement.style.display="none" }
// ---------------------------------------------------------------- estado
const D = {hoy:null, hist:null, fuentes:null, bt:null, sim:null, offline:false};
const EST = {};   // estado de carga por archivo: "red" | "http" | "vacio" | "json" | "formato"
const LS = {
  get(k, d){ try{ const v = localStorage.getItem("picks."+k); return v===null? d : JSON.parse(v) }catch(e){ return d } },
  set(k, v){ try{ localStorage.setItem("picks."+k, JSON.stringify(v)) }catch(e){} }
};
let ajustes = Object.assign({owner:"", repo:"", token:"", banca:null, ref:"main"}, LS.get("ajustes", {}));
let cuotas = LS.get("cuotas", {});        // tipo|uid|clave -> cuota tecleada
let ticket = LS.get("ticket", {});        // tipo|uid|clave -> true
let hechos = LS.get("hechos", {});        // tipo|uid|clave -> {cuota,monto,estado}: solo si GitHub respondió 204

// <PURAS>
const TZ = "America/Guayaquil";
const DIAS = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = (x,d=0) => (x==null||!isFinite(+x))? "–" : (x*100).toFixed(d)+"%";
const c2 = x => (x==null||!isFinite(+x))? "–" : (+x).toFixed(2);
// cuota tecleada: acepta coma o punto; válida solo entre 1.01 y 30
function num(v){ const n = parseFloat(String(v ?? "").replace(",",".")); return (isFinite(n) && n>=1.01 && n<=30) ? n : null }
const CFG0 = {fraccion_kelly:.25, stake_max_pct:.03, ventaja_minima:.04, stake_minimo:1, seguras_stake_pct:.02, seguras_exposicion_dia_pct:.06};
// Monto de una segura (el backend ya no publica `monto`): max(mínimo, 2% de la banca a múltiplos de 0.25), con tope por pick.
// Si el mínimo supera el tope por pick => banca insuficiente (no entra al lote).
function montoSegura(c){
  const tope = c.stake_max_pct*c.banca;
  if(c.stake_minimo > tope + 1e-9) return {monto:0, insuf:true};
  const m = Math.max(c.stake_minimo, Math.floor(c.banca*c.seguras_stake_pct*4 + 1e-9)/4);
  return {monto:Math.min(m, tope), insuf:false};
}
// Tope diario informativo de seguras: devuelve los días cuya suma supera seguras_exposicion_dia_pct*banca.
function excedeTopeDia(items, c){
  const tope = c.seguras_exposicion_dia_pct*c.banca, por = {};
  for(const x of items) por[x.fecha] = (por[x.fecha]||0) + (+x.monto||0);
  return Object.entries(por).filter(([,t])=>t > tope + 1e-9).map(([fecha,total])=>({fecha, total, tope}));
}
const trocear = (a, n=50) => { const o=[]; for(let i=0;i<a.length;i+=n) o.push(a.slice(i,i+n)); return o };
// owner ≤39, repo ≤100; solo [\w.-]; nunca solo puntos ("." / "..").
const idValido = (s, max) => typeof s==="string" && s.length>0 && s.length<=max && /^[\w.-]+$/.test(s) && !/^\.+$/.test(s);
// Cuota estimada: Seguras (modo seguro) la asumen estimada si falta el campo; Valor solo si viene true.
const esEst = (s, tipo) => tipo==="segura" ? s.cuota_es_estimada!==false : s.cuota_es_estimada===true;
// Un envío ya hecho no se reenvía; "por_confirmar" se puede reintentar pasadas 24 h.
const yaEnviada = (h, now=Date.now()) => !!h && !(h.estado==="por_confirmar" && now-(+h.t||0) > 864e5);
// Estado del run nuevo (id no visto antes) de registrar.yml: esperando | en_curso | success | failure
function estadoRun(runs, previos){
  const r = (runs||[]).find(x=>!previos.has(x.id));
  if(!r) return "esperando";
  if(r.status!=="completed") return "en_curso";
  return r.conclusion==="success" ? "success" : "failure";
}
// fetchRuns() -> {runs} | null (sin permiso/error). Consulta cada stepMs hasta maxMs. -> success|failure|timeout|sinpermiso
async function esperarRun(fetchRuns, previos, sleep, maxMs=180000, stepMs=5000){
  for(let t=0; t<=maxMs; t+=stepMs){
    const r = await fetchRuns();
    if(r===null) return "sinpermiso";
    const e = estadoRun(r.runs, previos);
    if(e==="success"||e==="failure") return e;
    await sleep(stepMs);
  }
  return "timeout";
}
function bancaValida(){ const b = parseFloat(String(ajustes.banca ?? "").replace(",",".")); return (isFinite(b) && b>0) ? b : 100 }
function cfg(){ const c = (D.hoy && D.hoy.config) || {}; return {...CFG0, ...c, banca: bancaValida()} }
// Misma fórmula que picks/seleccion.py: f = (p*o-1)/(o-1) * (1-p_push) * fracción Kelly, tope stake_max_pct.
// Además: EV estrictamente > 0, monto >= stake_minimo y <= tope; si el mínimo supera el tope => banca insuficiente.
function evalCuota(s, o, umbral=0){
  const c = cfg(), pp = +s.p_push||0, p = +s.p;
  if(!(o>1) || !isFinite(p)) return {ev:0, monto:0, ok:false, insuf:false};
  const ev = (1-pp)*(p*o-1);
  const f = Math.max(0, (1-pp)*(p*o-1)/(o-1)*c.fraccion_kelly);
  const tope = c.stake_max_pct*c.banca;
  const apto = ev>0 && ev>=umbral;
  let monto = 0, insuf = false;
  if(apto && f>0){
    if(c.stake_minimo > tope) insuf = true;
    else monto = Math.min(Math.max(Math.round(f*c.banca*4)/4, c.stake_minimo), tope);
  }
  return {ev, monto, ok: apto && !insuf, insuf};
}
const hoyEC = (now=new Date()) => now.toLocaleDateString("en-CA",{timeZone:TZ});
function horasDesde(iso, now=new Date()){ const t = Date.parse(iso); return isFinite(t) ? (now - t)/36e5 : NaN }
function fechasVigentes(fs, hoy){ return (Array.isArray(fs)?fs:[]).filter(f=>typeof f==="string" && f>=hoy) }
function etiquetaFecha(f, hoy){
  const a = Date.parse(f+"T00:00:00Z"), b = Date.parse(hoy+"T00:00:00Z");
  const dd = Math.round((a-b)/864e5);
  if(dd===0) return "Hoy"; if(dd===1) return "Mañana";
  const d = new Date(f+"T12:00:00Z"); return DIAS[d.getUTCDay()]+" "+d.getUTCDate();
}
// </PURAS>

let nivel = LS.get("nivel","seguras");
let fechaSel = null, regionSel = "Todas", ligaSel = "Todas";
const pasaFiltro = x => (regionSel==="Todas" || x.region===regionSel) && (ligaSel==="Todas" || x.liga===ligaSel);
const FUENTE = {mercado:["Mercado","--s1"], modelo:["Modelo","--s2"], forebet:["Forebet","--s3"], apifootball:["API-Football","--s4"], penaltyblog:["penaltyblog","--s5"], ia:["IA (Groq)","--s6"], ensamble:["Combinado","--tx2"]};
const $ = s => document.querySelector(s);
const usdn = x => x==null||!isFinite(+x)? "–" : "$"+(+x).toFixed(2);
const fmtU = x => x==null||!isFinite(+x)? "–" : (x<0?"−":"+")+Math.abs(x).toFixed(2)+" u";
const usd = x => x==null||!isFinite(+x)? "–" : (x<0?"−":"+")+"$"+Math.abs(x).toFixed(2);
const ddmm = s => String(s||"").slice(5).split("-").reverse().join("/");
const tabla = html => `<div class="tw">${html}</div>`;
const key = (s, t) => t+"|"+s.uid+"|"+s.clave;
function hora(iso){
  const d = new Date(iso); if(isNaN(d)) return "–";
  const w = d.toLocaleDateString("es-EC",{weekday:"short",timeZone:TZ}).replace(".","");
  return w.charAt(0).toUpperCase()+w.slice(1)+" "+d.toLocaleTimeString("es-EC",{hour:"2-digit",minute:"2-digit",hour12:false,timeZone:TZ});
}
const yaEmpezo = (s, now=Date.now()) => { const t = Date.parse(s.inicio); return isFinite(t) && t <= now };
function toast(t, err, ms){ const el=$("#toast"); el.textContent=t; el.style.display="block"; clearTimeout(toast.t); toast.t=setTimeout(()=>el.style.display="none", ms||(err?6000:2600)) }

// ------------------------------------------------------------- días y filtros
function dia(){
  const vacio = {valor:[], alta:[], seguras:[], grandes:[], pool:[], combinada:null, ocultos:0};
  if(!D.hoy) return vacio;
  const fs = fechasVigentes(D.hoy.fechas, hoyEC());
  if(!fs.length) return vacio;
  if(!fechaSel || !fs.includes(fechaSel)) fechaSel = fs[0];
  const d = D.hoy.dias[fechaSel]; if(!d) return vacio;
  const now = Date.now(), vivo = x => !yaEmpezo(x, now), f = a => (a||[]).filter(x=>pasaFiltro(x) && vivo(x));
  const ocultos = [].concat(d.valor||[], d.alta||[], d.seguras||[]).filter(x=>yaEmpezo(x, now)).length;
  return {valor:f(d.valor), alta:f(d.alta), seguras:f(d.seguras), pool:f(d.pool), combinada:d.combinada, ocultos,
          grandes:(d.grandes||[]).filter(c=>(c.piernas||[]).length && c.piernas.every(x=>pasaFiltro(x) && vivo(x)))};
}
function barraFiltros(){
  if(!D.hoy) return "";
  const hoy = hoyEC(), fs = fechasVigentes(D.hoy.fechas, hoy);
  if(!fs.length) return "";
  if(!fechaSel || !fs.includes(fechaSel)) fechaSel = fs[0];
  const delDia = D.hoy.partidos.filter(p=>p.fecha===fechaSel);
  const regiones = ["Todas", ...["Europa","Sudamérica","Norteamérica"].filter(r=>delDia.some(p=>p.region===r))];
  const ligas = ["Todas", ...new Set(delDia.filter(p=>regionSel==="Todas"||p.region===regionSel).map(p=>p.liga))];
  if(!ligas.includes(ligaSel)) ligaSel = "Todas";
  return `<div class="chips fechas">${fs.map(f=>`<button aria-pressed="${f===fechaSel}" class="${f===fechaSel?"on":""}" data-fecha="${esc(f)}">${esc(etiquetaFecha(f,hoy))}<small style="display:block;font-size:10px;opacity:.7">${D.hoy.partidos.filter(p=>p.fecha===f).length} partidos</small></button>`).join("")}</div>
    <div class="chips">${regiones.map(r=>`<button aria-pressed="${r===regionSel}" class="${r===regionSel?"on":""}" data-region="${esc(r)}">${r==="Todas"?"Todas las regiones":esc(r)}</button>`).join("")}</div>
    <div class="chips">${ligas.map(l=>`<button aria-pressed="${l===ligaSel}" class="${l===ligaSel?"on":""}" data-ligasel="${esc(l)}">${l==="Todas"?"Todas las ligas":esc(l)}</button>`).join("")}</div>`;
}
function ligarFiltros(el, rerender){
  el.querySelectorAll("[data-fecha]").forEach(b=>b.onclick=()=>{ fechaSel=b.dataset.fecha; ligaSel="Todas"; rerender(); barra() });
  el.querySelectorAll("[data-region]").forEach(b=>b.onclick=()=>{ regionSel=b.dataset.region; ligaSel="Todas"; rerender(); barra() });
  el.querySelectorAll("[data-ligasel]").forEach(b=>b.onclick=()=>{ ligaSel=b.dataset.ligasel; rerender(); barra() });
}

// ------------------------------------------------------------- carga
async function cargar(){
  const t = Date.now(); D.offline = false;
  const get = async n => {
    delete EST[n];
    try{
      const r = await fetch(`data/${n}.json?t=${t}`, {cache:"no-store"});
      if(r.headers.get("X-Desde-Cache")==="1") D.offline = true;
      if(!r.ok){ EST[n] = r.status===404 ? "vacio" : "http"; return null }
      return await r.json();
    }catch(e){ EST[n] = (e instanceof SyntaxError) ? "json" : "red"; return null }
  };
  [D.hoy, D.hist, D.fuentes, D.bt, D.sim] = await Promise.all(["hoy","historial","fuentes","backtest","simulacion30"].map(get));
  if(D.hoy){
    if(Array.isArray(D.hoy.partidos) && D.hoy.dias && typeof D.hoy.dias==="object"){
      if(!Array.isArray(D.hoy.fechas)) D.hoy.fechas = Object.keys(D.hoy.dias).sort();
    }else{ D.hoy = null; EST.hoy = "formato" }
  }
  if(!navigator.onLine) D.offline = true;
  reconciliar();
  const g = D.hoy && new Date(D.hoy.generado);
  $("#sub").textContent = (g && !isNaN(g)) ? `Actualizado ${g.toLocaleDateString("es-EC",{weekday:"long",day:"numeric",month:"short",timeZone:TZ})}, ${g.toLocaleTimeString("es-EC",{hour:"2-digit",minute:"2-digit",timeZone:TZ})}`
    : D.hoy ? "Sin fecha de actualización" : sinDatosCorto();
  renderTodo();
}
// Si historial.json ya trae el pick registrado con cuota tomada, la app lo muestra como registrada.
function reconciliar(){
  const P = D.hist && Array.isArray(D.hist.picks) ? D.hist.picks : []; let ch = false;
  for(const p of P){
    if(p.registrado!==true || p.cuota_tomada==null || p.uid==null) continue;
    const k = key(p, p.tipo), h = hechos[k];
    if(h && (h.estado==="omitida" || h.estado==="registrada")) continue;
    hechos[k] = {cuota:+p.cuota_tomada, monto:h?h.monto:undefined, estado:"registrada", t:Date.now()}; ch = true;
  }
  if(ch) LS.set("hechos", hechos);
}
function sinDatosCorto(){ return EST.hoy==="red" ? "Sin conexión" : EST.hoy==="json"||EST.hoy==="formato" ? "Datos ilegibles" : EST.hoy==="http" ? "Error del servidor" : "Aún no hay datos: corre el análisis desde Ajustes" }
function sinDatosHTML(){
  const m = EST.hoy==="red" ? "Sin conexión y no hay datos guardados.<br>Conéctate a internet y toca ↻."
    : (EST.hoy==="json"||EST.hoy==="formato") ? "Aún no hay datos válidos: los recibidos están dañados o incompletos.<br>Intenta de nuevo con ↻ en unos minutos."
    : EST.hoy==="http" ? "El servidor no respondió bien.<br>Intenta de nuevo con ↻."
    : "Aún no hay datos.<br>Cuando el sistema corra (todos los días 07:00 y 13:00) aparecerán aquí.";
  return `<div class="card empty">${m}</div>`;
}
function avisosHTML(){
  const a = [];
  if(D.offline) a.push(`<div class="banner warn">Modo sin conexión: mostrando datos guardados.</div>`);
  if(D.hoy){
    if(D.hoy.simulacion===true || D.hoy.creditos==="simulación") a.push(`<div class="banner bad">SIMULACIÓN — no son picks reales.</div>`);
    const h = horasDesde(D.hoy.generado), sinFechas = !fechasVigentes(D.hoy.fechas, hoyEC()).length;
    if(sinFechas || h>20){
      const cuando = !isFinite(h) ? "" : h>=48 ? ` (generado hace ${Math.round(h/24)} días)` : ` (generado hace ${Math.round(h)} h)`;
      a.push(`<div class="banner bad">Datos desactualizados${cuando}.${sinFechas?" No hay partidos de hoy en adelante.":""} No apuestes con estos datos.</div>`);
    }
    if(D.hoy.aviso) a.push(`<div class="banner warn">${esc(D.hoy.aviso)}</div>`);
  }
  $("#avisos").innerHTML = a.join("");
}
function renderTodo(){ avisosHTML(); vHoy(); vPartidos(); vRend(); vFuentes(); vAjustes(); barra() }

// ----------------------------------------------------------- HOY
function fuentesHTML(s){
  return Object.entries(s.detalle||{}).sort((a,b)=>((s.pesos||{})[b[0]]||0)-((s.pesos||{})[a[0]]||0)).map(([f,p])=>{
    const [n,v] = FUENTE[f]||[f,"--tx3"];
    return `<span class="src"><span class="dot" style="background:var(${v})"></span>${esc(n)} <b>${pct(p)}</b>${s.pesos&&s.pesos[f]!=null?` <span class="meta">${pct(s.pesos[f])}</span>`:""}</span>`}).join("");
}
function iaHTML(s){
  if(!s.ia) return "";
  const t = {bajo:["ok","Riesgo bajo"], medio:["warn","Riesgo medio"], alto:["bad","Riesgo alto"]}[s.ia.riesgo]||["","IA"];
  return `<div class="ia"><span class="tag ${t[0]}">IA · ${t[1]}</span> ${esc(s.ia.resumen||"")}${(s.ia.alertas||[]).length?`<ul>${s.ia.alertas.map(a=>`<li>${esc(a)}</li>`).join("")}</ul>`:""}</div>`;
}
function umbral(tipo){ return tipo==="valor" ? cfg().ventaja_minima : 0 }
function tarjeta(s, i, tipo){
  const k = key(s,tipo), est = esEst(s,tipo), ms = tipo==="segura" ? montoSegura(cfg()) : null;
  const o = cuotas[k] ?? (est ? "" : (s.cuota_ecuabet ?? ""));
  const h = hechos[k], enT = !!ticket[k];
  const minimo = tipo==="valor" ? s.cuota_minima : s.cuota_justa;
  const estado = est ? `<span class="tag warn">Cuota estimada: apostar solo si Ecuabet paga ≥ ${c2(minimo)}</span>`
              : s.confirmado ? `<span class="tag ok">Cuota de Ecuabet confirmada</span>`
              : `<span class="tag warn">Apostar solo si Ecuabet paga ≥ ${c2(minimo)}</span>`;
  const ref = tipo==="valor"
      ? (s.mejor_cuota ? `Mejor cuota: ${c2(s.mejor_cuota)} (${esc(s.mejor_casa)})${s.ev!=null?` · valor ${pct(s.ev,1)}`:""}` : "Sin cuota de referencia")
      : `Gana ${pct(s.p)} de las veces · ${s.tipo_cuota==="ecuabet"&&!est?"Ecuabet paga":"las casas suelen pagar"} ~${c2(s.cuota_est)}${est?" (estimada)":""}`;
  const cobro = (ms && !ms.insuf && isFinite(ms.monto*minimo)) ? `${est?"Cobrarías ~":"Cobras "}$${(ms.monto*minimo).toFixed(2)}` : "Monto";
  return `<div class="card" data-k="${esc(k)}">
    <div class="row meta"><span>#${i} · ${esc(s.liga)} · ${esc(s.mercado)}</span><span>${hora(s.inicio)}</span></div>
    <div class="match">${esc(s.local)} <small>vs</small> ${esc(s.visita)}</div>
    <div class="pick">${esc(s.nombre)}</div>
    <div class="grid4">
      <div><b>${pct(s.p)}</b><span>Probabilidad</span></div>
      <div><b>${c2(s.cuota_justa)}</b><span>Cuota justa</span></div>
      <div><b>${c2(minimo)}</b><span>Cuota mínima</span></div>
      <div><b>${ms && !ms.insuf ? usdn(ms.monto) : "–"}</b><span>${esc(cobro)}</span></div>
    </div>
    <div class="srcs">${fuentesHTML(s)}</div>
    <div class="meta">${ref}</div>
    ${iaHTML(s)}
    <div style="margin-top:8px">${estado} ${ms&&ms.insuf?`<span class="tag bad">No apostar (banca insuficiente)</span>`:""} ${tagHecho(h)}</div>
    <div class="oddsbox">
      <input type="text" inputmode="decimal" placeholder="Cuota Ecuabet" value="${esc(o)}" data-in="${esc(k)}" data-tipo="${esc(tipo)}" aria-label="Cuota que ves en Ecuabet para ${esc(s.nombre)}" autocomplete="off">
      <button class="btn ${enT?"sel":""}" data-tk="${esc(k)}" aria-pressed="${enT}">${enT?"✓ En ticket":"+ Ticket"}</button>
    </div>
    <div class="calc" data-calc="${esc(k)}" aria-live="polite"></div>
  </div>`;
}
function tagHecho(h){
  if(!h) return "";
  if(h.estado==="omitida") return `<span class="tag ok">Registrada (omitida)</span>`;
  if(h.estado==="por_confirmar") return `<span class="tag warn">Enviada, sin confirmar todavía</span>`;
  return `<span class="tag ok">Registrada${h.monto!=null?" "+esc(usdn(h.monto)):""} @ ${esc(c2(h.cuota))}</span>`;
}
// monto efectivo y si la banca no alcanza; r = resultado de evalCuota (o null sin cuota)
function montoPick(s, r){
  if(s._t==="segura"){ const m = montoSegura(cfg()); return {monto:m.monto, insuf:m.insuf || !!(r&&r.insuf)} }
  return {monto: r ? r.monto : 0, insuf: !!(r&&r.insuf)};
}
let _lista = [], _mapa = new Map(), _paraHoy = null;
function todosPicks(){
  if(!D.hoy){ _lista=[]; _mapa=new Map(); _paraHoy=null; return _lista }
  if(_paraHoy!==D.hoy){
    _paraHoy = D.hoy; _lista = [];
    // todos los días (para que el ticket conserve picks de otras fechas); la clave incluye el tipo
    for(const d of Object.values(D.hoy.dias||{}))
      for(const [t,arr] of [["valor",d.valor],["segura",d.seguras],["alta",d.alta]])
        for(const s of (arr||[])) _lista.push({...s, _t:t, _k:key(s,t)});
    _mapa = new Map(_lista.map(s=>[s._k, s]));
  }
  return _lista;
}
const MSG_CUOTA = "Escribe una cuota válida, p. ej. 1,85";
function pintarCalc(k, tipo){
  todosPicks();
  const s = _mapa.get(k), el = document.querySelector(`[data-calc="${CSS.escape(k)}"]`);
  if(!s||!el||(tipo && s._t!==tipo)) return;
  const raw = cuotas[k] ?? (esEst(s,s._t) ? "" : s.cuota_ecuabet);
  if(raw==null || String(raw).trim()===""){ el.textContent=""; el.className="calc"; return }
  const o = num(raw);
  if(o==null){ el.className="calc bad"; el.textContent=MSG_CUOTA; return }
  const r = evalCuota(s, o, umbral(s._t));
  const mp = montoPick(s, r);
  if(mp.insuf){ el.className="calc bad"; el.textContent="No apostar (banca insuficiente)"; return }
  const monto = mp.monto;
  el.className = "calc " + (r.ok?"ok":"bad");
  el.textContent = r.ok ? `✔ Vale la pena (valor ${(r.ev*100).toFixed(1)}%) → apostar $${monto.toFixed(2)}` : `✘ Paga poco (valor ${(r.ev*100).toFixed(1)}%) → no apostar`;
}

// ---- armador de combinadas (misma lógica que el servidor)
let gMonto = +LS.get("gMonto", 5) > 0 ? +LS.get("gMonto", 5) : 5, gObj = LS.get("gObj", 100);
function armar(pool, objCuota, maxP=8){
  const orden = [...pool].filter(s=>!(s.ia&&s.ia.riesgo==="alto") && isFinite(+s.cuota_est) && +s.cuota_est>1 && isFinite(+s.eficiencia) && isFinite(+s.p))
    .sort((a,b)=>a.eficiencia-b.eficiencia);
  const el=[], usados=new Set(); let c=1;
  for(const s of orden){ if(c>=objCuota||el.length>=maxP) break; if(usados.has(s.uid)) continue; el.push(s); usados.add(s.uid); c*=+s.cuota_est }
  if(c < objCuota*0.97 || !el.length) return null;
  const p = el.reduce((t,s)=>t*s.p,1);
  return {piernas:el, cuota:c, p};
}
function combinadaHTML(c, monto, titulo){
  const m = +monto, cuota = +c.cuota, p = +c.p;
  const neta = (c.ganancia!=null && isFinite(+c.ganancia)) ? +c.ganancia : m*(cuota-1);   // ganancia neta
  const cobro = m + neta;
  const ev = (c.ev_estimado!=null && isFinite(+c.ev_estimado)) ? +c.ev_estimado : (c.ev!=null && isFinite(+c.ev)) ? +c.ev : p*cuota-1;
  const veces = p>0 ? Math.max(1, Math.round(1/p)) : null;
  const txtEv = ev<0 ? `En promedio recuperas ~$${(1+ev).toFixed(2)} por cada $1 apostado: a largo plazo se pierde.`
                     : `Sale positivo solo porque las cuotas son estimadas; no cuentes con ello.`;
  return `<div class="card">
    <div class="row"><span class="meta">${esc(titulo)}</span><span class="tag">${(c.piernas||[]).length} selecciones</span></div>
    <div class="row" style="align-items:flex-end;margin:6px 0"><div><div class="big">$${neta.toFixed(0)}</div><div class="meta">Ganancia si aciertas todas (cobro $${cobro.toFixed(2)} − monto $${m.toFixed(2)}) · cuota ${isFinite(cuota)?cuota.toFixed(2):"–"}</div></div>
      <div style="text-align:right"><b style="font-size:18px">${(p*100).toFixed(1)}%</b><div class="meta">${veces?`≈ 1 de cada ${veces}`:""}</div></div></div>
    <div class="prob-bar" role="img" aria-label="Probabilidad ${(p*100).toFixed(1)}%"><i style="width:${Math.max(2,p*100)}%"></i></div>
    <div style="margin:6px 0"><span class="tag warn">Cuota estimada — Ecuabet puede pagar menos</span></div>
    <div class="meta" style="margin-bottom:6px"><b class="${ev<0?"neg":"pos"}">Valor esperado ≈ ${(ev*100).toFixed(1)}%</b> · ${txtEv}</div>
    ${(c.piernas||[]).map(s=>`<div class="leg"><span><b>${esc(s.nombre)}</b><br><span class="meta">${esc(s.local)} vs ${esc(s.visita)} · ${hora(s.inicio)}</span>${s.ia&&s.ia.riesgo==="medio"?' <span class="tag warn">IA: riesgo medio</span>':""}</span><span style="text-align:right">${pct(s.p)}<br><span class="meta">~${c2(s.cuota_est)} est.</span></span></div>`).join("")}
    <div class="row" style="gap:8px;margin-top:10px;justify-content:flex-start"><button class="btn small" data-copiarcomb='${esc(JSON.stringify((c.piernas||[]).map(s=>`${s.local} vs ${s.visita} — ${s.nombre}`)))}'>Copiar para Ecuabet</button></div>
  </div>`;
}
function vGrandes(){
  const DD = dia();
  let h = `<div class="note">Combinadas para ganar mucho con poco. El sistema elige las selecciones que <b>más probabilidad conservan</b> por cada punto de cuota que suman. Aun así, la mayoría no se gana: mira la probabilidad real de cada una.</div>`;
  h += `<div class="card"><b>Arma la tuya</b>
    <label class="field"><span>Monto a apostar (USD)</span><input type="text" inputmode="decimal" id="g-monto" value="${esc(gMonto)}" autocomplete="off"></label>
    <div class="meta" style="margin-bottom:6px">Quiero cobrar:</div>
    <div class="chips obj">${[50,100,200,500,1000].map(v=>`<button aria-pressed="${v==gObj}" class="${v==gObj?"on":""}" data-obj="${v}">$${v}</button>`).join("")}</div>
    <div id="g-res"></div></div>`;
  if(DD.grandes.length) h += `<h2>Combinadas sugeridas</h2>` + DD.grandes.map(c=>combinadaHTML(c, c.monto, `Objetivo $${c.objetivo}`)).join("");
  h += `<h2>Cómo se comportan</h2><div class="card meta">En la prueba con datos reales de los últimos 30 días, las piernas acertaron lo que el sistema predijo (63% contra 64% esperado), pero las combinadas de $100 y $200 se perdieron todas. Con 7–8 selecciones basta con que falle una. Apuesta en ellas solo lo que estés dispuesto a perder.</div>`;
  return h;
}
function pintarBuilder(){
  const el=$("#g-res"); if(!el) return;
  if(!(gMonto>0)){ el.innerHTML = `<div class="empty">Escribe un monto mayor que 0.</div>`; return }
  const c = armar(dia().pool, gObj/Math.max(0.5,gMonto));
  el.innerHTML = c ? combinadaHTML(c, gMonto, `Para cobrar ~$${gObj}`) : `<div class="empty">Con los partidos de este día no se llega a ese objetivo con ese monto. Sube el monto o baja el objetivo.</div>`;
}
function vHoy(){
  const el = $("#v-hoy");
  if(!D.hoy){ el.innerHTML = sinDatosHTML(); return }
  const DD = dia(), v = DD.valor, a = DD.alta, sg = DD.seguras, gr = DD.grandes;
  const sinFechas = !fechasVigentes(D.hoy.fechas, hoyEC()).length;
  if(sinFechas){ el.innerHTML = `<div class="card empty"><b>Los datos son de fechas pasadas.</b><br>No se muestran picks para no apostar con información vieja. Espera al próximo análisis o corre "Analizar ahora" en Ajustes.</div>`; return }
  const tabs = [["seguras","Seguras",`${sg.length} picks`],["valor","Valor",`${v.length} picks`],["grandes","Grandes",`${gr.length} combinadas`]];
  let h = barraFiltros() + `<div class="seg" role="tablist" aria-label="Nivel de picks">${tabs.map(([n,t,s])=>`<button role="tab" aria-selected="${nivel===n}" class="${nivel===n?"on":""}" data-nivel="${n}">${t}<small>${s}</small></button>`).join("")}</div>`;
  if(DD.ocultos) h += `<div class="meta" style="margin:6px 4px">${DD.ocultos} pick(s) ocultos porque el partido ya empezó.</div>`;
  if(nivel==="seguras"){
    h += `<div class="note">Apuestas pequeñas con alta probabilidad (cuota 1.25–1.60). Escribe la cuota de Ecuabet y te digo si paga lo suficiente.</div>`;
    h += sg.length ? sg.map((s,i)=>tarjeta(s,i+1,"segura")).join("") : `<div class="card empty">No hay selecciones con probabilidad suficiente para este filtro.</div>`;
  } else if(nivel==="valor"){
    h += `<div class="note">Apuestas donde la cuota paga más de lo que vale. Son las más rentables a largo plazo, pero aparecen menos.</div>`;
    h += v.length ? v.map((s,i)=>tarjeta(s,i+1,"valor")).join("") : `<div class="card empty"><b>Hoy no hay apuestas de valor claras.</b><br>Revisa las seguras o escribe cuotas de Ecuabet en "Partidos".</div>`;
    if(a.length) h += `<h2>Alta probabilidad</h2>` + a.map((s,i)=>tarjeta(s,i+1,"alta")).join("");
  } else {
    h += vGrandes();
  }
  h += `<h2>Cómo sacar tu código de Ecuabet</h2><div class="card"><ol style="margin:0;padding-left:20px">
      <li>Toca <b>+ Ticket</b> en los picks que quieres jugar, o <b>Copiar para Ecuabet</b> en una combinada.</li><li>Abre Ecuabet, busca cada partido y escribe aquí la cuota que ves.</li>
      <li>Si sale ✔, agrégalo al cupón de Ecuabet.</li><li>En el cupón toca <b>guardar/reservar apuesta</b>: ese es tu código.</li>
      <li>En <b>Ver ticket</b> toca <b>Registrar apuestas</b> para medir tu rendimiento.</li></ol></div>`;
  el.innerHTML = h;
  ligarFiltros(el, vHoy);
  el.querySelectorAll("[data-nivel]").forEach(b=>b.onclick=()=>{ nivel=b.dataset.nivel; LS.set("nivel",nivel); vHoy(); barra() });
  if(nivel==="grandes"){
    $("#g-monto").oninput=e=>{ const x=parseFloat(String(e.target.value).replace(",",".")); gMonto=isFinite(x)&&x>0?x:0; if(gMonto>0) LS.set("gMonto",gMonto); pintarBuilder() };
    el.querySelectorAll("[data-obj]").forEach(b=>b.onclick=()=>{ gObj=+b.dataset.obj; LS.set("gObj",gObj); el.querySelectorAll("[data-obj]").forEach(x=>{ x.classList.toggle("on",x===b); x.setAttribute("aria-pressed",x===b) }); pintarBuilder() });
    pintarBuilder();
  }
  todosPicks().forEach(s=>pintarCalc(s._k, s._t));
}
document.addEventListener("click", async e=>{
  const b=e.target.closest("[data-copiarcomb]"); if(!b) return;
  try{ await navigator.clipboard.writeText(JSON.parse(b.dataset.copiarcomb).join("\n")); toast("Combinada copiada") }catch(x){ toast("No se pudo copiar") }
});
document.addEventListener("input", e=>{
  const k = e.target.dataset && e.target.dataset.in; if(!k) return;
  cuotas[k] = e.target.value; LS.set("cuotas", cuotas); pintarCalc(k, e.target.dataset.tipo); barra();
});
document.addEventListener("change", e=>{   // al terminar de escribir se guarda la cuota normalizada (punto decimal)
  const k = e.target.dataset && e.target.dataset.in; if(!k) return;
  const n = num(e.target.value); if(n!=null){ cuotas[k] = String(n); LS.set("cuotas", cuotas) }
});
document.addEventListener("click", e=>{
  const b = e.target.closest("[data-tk]"); if(!b) return;
  const k = b.dataset.tk; ticket[k] ? delete ticket[k] : ticket[k]=true; LS.set("ticket", ticket);
  b.classList.toggle("sel", !!ticket[k]); b.setAttribute("aria-pressed", !!ticket[k]); b.textContent = ticket[k] ? "✓ En ticket" : "+ Ticket"; barra();
});

// ---------------------------------------------------------- TICKET
function itemsTicket(){ todosPicks(); const now=Date.now(); return _lista.filter(s=>ticket[s._k] && !yaEmpezo(s,now)) }
function barra(){
  const it = itemsTicket(), bar = $("#ticketbar");
  bar.classList.toggle("show", it.length>0 && !$("#v-hoy").classList.contains("hide"));
  const montoDe = s=>{ const o=num(cuotas[s._k]); return montoPick(s, o? evalCuota(s,o,umbral(s._t)) : null).monto };
  const tot = it.reduce((t,s)=>t+montoDe(s),0);
  $("#tbtxt").textContent = `${it.length} en ticket · $${tot.toFixed(2)}`;
}
let focoPrevio = null;
const BLOQ = ["#appmain","nav","#ticketbar"];
function abrirSheet(){
  focoPrevio = document.activeElement; $("#sheet").classList.add("show");
  BLOQ.forEach(s=>{ const x=$(s); if(x) x.inert = true });
  const c = $("#cerrar"); if(c) c.focus();
}
function cerrarSheet(){
  $("#sheet").classList.remove("show");
  BLOQ.forEach(s=>{ const x=$(s); if(x) x.inert = false });
  if(focoPrevio && focoPrevio.focus) focoPrevio.focus();
}
document.addEventListener("keydown", e=>{
  const s = $("#sheet"); if(!s.classList.contains("show")) return;
  if(e.key==="Escape"){ cerrarSheet(); return }
  if(e.key==="Tab"){
    const f=[...s.querySelectorAll("button:not([disabled])")]; if(!f.length) return;
    const a=f[0], z=f[f.length-1];
    if(e.shiftKey && document.activeElement===a){ e.preventDefault(); z.focus() }
    else if(!e.shiftKey && document.activeElement===z){ e.preventDefault(); a.focus() }
  }
});
$("#vertk").onclick = ()=>{
  const it = itemsTicket();
  const filas = it.map(s=>{
    const o = num(cuotas[s._k]), r = o? evalCuota(s,o,umbral(s._t)) : null;
    const mp = montoPick(s, r), monto = mp.monto, h = hechos[s._k];
    const ya = h ? (h.estado==="por_confirmar" ? ' <span class="tag warn">enviada, sin confirmar</span>' : ' <span class="tag ok">ya registrada</span>') : (mp.insuf ? ' <span class="tag bad">banca insuficiente</span>' : "");
    return `<tr><td><b>${esc(s.nombre)}</b>${ya}<br><span class="meta">${esc(s.local)} vs ${esc(s.visita)} · ${hora(s.inicio)}</span></td>
      <td>${o? c2(o) : `<span class="meta">mín ${c2(s.cuota_minima)}</span>`}</td><td>${monto && !mp.insuf? "$"+monto.toFixed(2):"–"}</td>
      <td>${r? (r.ok && !mp.insuf? '<span class="pos">✔</span>':'<span class="neg">✘</span>') : "·"}</td></tr>`}).join("");
  const c0 = cfg(), expo = excedeTopeDia(it.filter(s=>s._t==="segura" && !hechos[s._k]).map(s=>({fecha:s.fecha||hoyEC(new Date(s.inicio)), monto:montoPick(s,null).monto})), c0);
  const avisoExpo = expo.length ? `<div class="banner warn" role="status">Las seguras de este ticket suman más del ${pct(c0.seguras_exposicion_dia_pct,0)} de tu banca en un día (${expo.map(x=>`${esc(ddmm(x.fecha))}: $${x.total.toFixed(2)} de $${x.tope.toFixed(2)}`).join("; ")}). Es solo un aviso: considera apostar menos.</div>` : "";
  $("#sheetp").innerHTML = `<div class="row"><h1 id="sheet-t" style="font-size:22px">Mi ticket</h1><button class="btn small" id="cerrar">Cerrar</button></div>
    ${avisoExpo}
    ${tabla(`<table><tr><th>Selección</th><th>Cuota</th><th>Monto</th><th><span class="sr">Estado</span></th></tr>${filas}</table>`)}
    <div class="note">Arma este mismo cupón en Ecuabet y toca <b>guardar/reservar apuesta</b> para obtener tu código. Solo se registran los picks marcados con ✔ que no estén ya registrados.</div>
    <div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn" id="copiar">Copiar lista</button>
    <button class="btn pri" id="registrar">Registrar apuestas</button><button class="btn" id="vaciar">Vaciar</button></div>`;
  abrirSheet();
  $("#cerrar").onclick = cerrarSheet;
  $("#vaciar").onclick = ()=>{ ticket={}; LS.set("ticket",ticket); cerrarSheet(); renderTodo() };
  $("#copiar").onclick = async ()=>{
    const txt = it.map(s=>`${s.local} vs ${s.visita} — ${s.nombre} (cuota mín. ${c2(s.cuota_minima)})`).join("\n");
    try{ await navigator.clipboard.writeText(txt); toast("Lista copiada") }catch(e){ toast("No se pudo copiar") }
  };
  $("#registrar").onclick = async ev=>{
    const btn = ev.currentTarget, lote = [], enviados = [];
    for(const s of it){
      const k = s._k; if(yaEnviada(hechos[k])) continue;      // ya registrada / enviada: no se reenvía
      const o = num(cuotas[k]); if(!o) continue;
      const r = evalCuota(s, o, umbral(s._t)); if(!r.ok) continue;
      const mp = montoPick(s, r); if(mp.insuf || !(mp.monto>0)) continue;   // banca insuficiente: no entra al lote
      lote.push({uid:String(s.uid), clave:s.clave, accion:"registrar", cuota:o, monto:mp.monto}); enviados.push([k,o,mp.monto]);
    }
    if(!lote.length){ toast("Escribe la cuota de Ecuabet en cada pick ✔ (y que no estén ya registrados) antes de registrar", true); return }
    btn.disabled = true;
    const res = await registrarLote(lote);        // un estado por ítem: "ok" | "pend" | null (no registrado)
    btn.disabled = false;
    let nOk = 0, nPend = 0;
    enviados.forEach(([k,o,m],i)=>{
      if(res.estados[i]==="ok"){ hechos[k]={cuota:o, monto:m, estado:"registrada", t:Date.now()}; delete ticket[k]; nOk++ }
      else if(res.estados[i]==="pend"){ hechos[k]={cuota:o, monto:m, estado:"por_confirmar", t:Date.now()}; delete ticket[k]; nPend++ }
    });
    LS.set("hechos",hechos); LS.set("ticket",ticket);
    if(nOk||nPend){ cerrarSheet(); renderTodo() }
    toast(res.msg + (nOk&&it.length>lote.length ? " (el resto no tenía cuota válida, valor o ya estaba registrado)" : ""), !!res.error, 8000);
  };
};
$("#sheet").onclick = e=>{ if(e.target.id==="sheet") cerrarSheet() };

const RE_ID = /^[\w.-]+$/, RE_REF = /^[\w./-]+$/;
const ownerOk = o => idValido(o, 39), repoOk = r => idValido(r, 100);
const sleep = ms => new Promise(r=>setTimeout(r, ms));
const GH = {Accept:"application/vnd.github+json"};
// Devuelve true SOLO si GitHub respondió 204 (= encolado; no significa que el registro terminara bien).
async function despachar(wf, inputs){
  const {owner, repo, token} = ajustes, ref = ajustes.ref || "main";
  if(!owner || !repo || !token){ toast("Falta conectar GitHub en Ajustes (usuario, repositorio y token). No se registró nada en el sistema.", true); return false }
  if(!ownerOk(owner) || !repoOk(repo) || !RE_REF.test(ref)){ toast("Usuario, repositorio o rama inválidos en Ajustes.", true); return false }
  try{
    const r = await fetch(`https://api.github.com/repos/${owner}/${repo}/actions/workflows/${encodeURIComponent(wf)}/dispatches`,
      {method:"POST", headers:{...GH, Authorization:`Bearer ${token}`}, body:JSON.stringify({ref, inputs})});
    if(r.status===204) return true;
    const causa = r.status===401 ? "token inválido o vencido" : r.status===403 ? "el token no tiene permiso Actions: Read and write" : r.status===404 ? "repositorio o workflow no encontrado" : r.status===422 ? "rama o datos rechazados" : "código "+r.status;
    toast(`GitHub rechazó la solicitud (${causa}). No se registró nada.`, true); return false;
  }catch(e){ toast("No se pudo contactar a GitHub (¿sin conexión?). No se registró nada.", true); return false }
}
// Últimos runs de workflow_dispatch del workflow. null = sin permiso de lectura de Actions u otro error.
async function runsDe(wf){
  const {owner, repo, token} = ajustes;
  try{
    const r = await fetch(`https://api.github.com/repos/${owner}/${repo}/actions/workflows/${encodeURIComponent(wf)}/runs?event=workflow_dispatch&per_page=5`,
      {headers:{...GH, Authorization:`Bearer ${token}`}, cache:"no-store"});
    if(!r.ok) return null;
    const j = await r.json(); return {runs: Array.isArray(j.workflow_runs) ? j.workflow_runs : []};
  }catch(e){ return null }
}
// Lote en grupos de ≤50, despachados en SERIE. Cada 204 solo es "encolado": se espera al run y solo conclusion==="success" cuenta.
async function registrarLote(lote){
  const grupos = trocear(lote, 50), estados = new Array(lote.length).fill(null);
  let ini = 0, nOk = 0, nPend = 0, falla = false, sinEsperar = false;
  for(let gi=0; gi<grupos.length; gi++){
    const g = grupos[gi], idx = g.map((_,j)=>ini+j); ini += g.length;
    const prev = sinEsperar ? null : await runsDe("registrar.yml");
    const previos = new Set(prev ? prev.runs.map(x=>x.id) : []);
    if(!await despachar("registrar.yml", {lote: JSON.stringify(g)})) return {estados, error:true, msg: nOk||nPend ? `Se detuvo en el grupo ${gi+1} de ${grupos.length}. ${nOk} registrados, ${nPend} sin confirmar.` : "No se registró nada."};
    let e;
    if(prev===null || sinEsperar) e = "sinpermiso";
    else{
      toast(`Registrando… esperando confirmación de GitHub${grupos.length>1?` (grupo ${gi+1} de ${grupos.length})`:""}. Puede tardar 1–3 min.`, false, 190000);
      e = await esperarRun(()=>runsDe("registrar.yml"), previos, sleep);
    }
    if(e==="failure"){ falla = true; break }
    if(e==="success"){ idx.forEach(i=>estados[i]="ok"); nOk += g.length }
    else{ idx.forEach(i=>estados[i]="pend"); nPend += g.length; sinEsperar = true }   // timeout o sin permiso: enviado, sin confirmar
  }
  if(falla) return {estados, error:true, msg:"El registro falló o fue parcial: revisa la pestaña Actions de GitHub. No se marcó como registrado."};
  if(nPend) return {estados, error:false, msg:`Enviado, sin confirmar todavía (${nPend} picks${nOk?`; ${nOk} confirmados`:""}). Revisa Actions o recarga en unos minutos.`};
  return {estados, error:false, msg:`${nOk} picks registrados y confirmados`};
}

// -------------------------------------------------------- PARTIDOS
let busca = "";
const PRINCIPALES = [["1x2:1","1"],["1x2:X","X"],["1x2:2","2"],["dc:1X","1X"],["dc:X2","X2"],["btts:si","Ambos marcan"],
  ["ou:1.5:over","+1.5 goles"],["ou:2.5:over","+2.5 goles"],["ou:3.5:over","+3.5 goles"],["ht1x2:X","Empate al descanso"],
  ["corners:9.5:over","+9.5 córners"],["cards:4.5:over","+4.5 tarjetas"]];
function vPartidos(){
  const el = $("#v-partidos");
  if(!D.hoy){ el.innerHTML = sinDatosHTML(); return }
  const filtros = barraFiltros();
  const ps = D.hoy.partidos.filter(p=>p.fecha===fechaSel && pasaFiltro(p) && (`${p.local} ${p.visita}`.toLowerCase().includes(busca)));
  const w = x => Math.max(0, Math.min(100, (+x||0)*100));
  el.innerHTML = filtros + `<label class="sr" for="busca">Buscar equipo</label><input class="search" placeholder="Buscar equipo…" value="${esc(busca)}" id="busca" autocomplete="off">
    <div class="meta" style="margin:0 2px 6px">${ps.length} partidos</div>
    ${ps.map(p=>{
      const pr=p.probs||{}, e=p.esperados||{}, fuentes=p.fuentes||[], sel=p.selecciones||[];
      const cor = e.corners||e.corners_fb, tar = e.tarjetas||e.tarjetas_fb;
      const xg = Array.isArray(p.xg) && p.xg.length>=2 && isFinite(+p.xg[0]) && isFinite(+p.xg[1]) ? `xG ${(+p.xg[0]).toFixed(2)} – ${(+p.xg[1]).toFixed(2)} · ` : "";
      return `<details class="m"><summary>
        <div class="row meta"><span>${esc(p.liga)}</span><span>${hora(p.inicio)}</span></div>
        <div class="match">${esc(p.local)} <small>vs</small> ${esc(p.visita)}</div>
        <div class="bar3" role="img" aria-label="Local ${pct(pr["1x2:1"])}, empate ${pct(pr["1x2:X"])}, visita ${pct(pr["1x2:2"])}">
          <i style="width:${w(pr["1x2:1"])}%;background:var(--s1)"></i><i style="width:${w(pr["1x2:X"])}%;background:var(--tx3)"></i><i style="width:${w(pr["1x2:2"])}%;background:var(--s2)"></i></div>
        <div class="row meta" style="margin-top:4px"><span>1 ${pct(pr["1x2:1"])}</span><span>X ${pct(pr["1x2:X"])}</span><span>2 ${pct(pr["1x2:2"])}</span></div>
      </summary><div class="body">
        <div class="probs">${PRINCIPALES.filter(([k])=>pr[k]!=null).map(([k,n])=>`<div class="pb">${esc(n)}<b>${pct(pr[k])}</b></div>`).join("")}</div>
        <div class="meta">${xg}${cor&&isFinite(+cor)?`córners esperados ${(+cor).toFixed(1)} · `:""}${tar&&isFinite(+tar)?`tarjetas esperadas ${(+tar).toFixed(1)} · `:""}fuentes: ${fuentes.map(f=>esc((FUENTE[f]||[f])[0])).join(", ")}</div>
        ${tabla(`<table style="margin-top:8px"><tr><th>Mejores selecciones</th><th>Prob.</th><th>Mín.</th><th>Valor</th></tr>
        ${sel.slice(0,8).map(s=>`<tr><td>${esc(s.nombre)}<br><span class="meta">${esc(s.mercado)} · ${esc(s.n_fuentes)} fuentes</span></td><td>${pct(s.p)}</td><td>${c2(s.cuota_minima)}</td><td class="${(s.ev||0)>0?"pos":"neg"}">${s.ev==null?"–":pct(s.ev,1)}</td></tr>`).join("")}</table>`)}
      </div></details>`}).join("") || `<div class="card empty">Sin partidos con ese filtro.</div>`}`;
  ligarFiltros(el, vPartidos);
  $("#busca").oninput = e=>{ busca=e.target.value.toLowerCase(); const pos=e.target.selectionStart; vPartidos(); const b=$("#busca"); b.focus(); b.setSelectionRange(pos,pos) };
}

// ------------------------------------------------------------ gráfico
function lineChart(cont, series, opts={}){
  const W=Math.max(300, Math.round(cont.clientWidth||680)), H=Math.round(Math.min(240, Math.max(180, W*.5))), m={l:44,r:14,t:12,b:26};
  const all = series.flatMap(s=>s.pts); if(!all.length){ cont.innerHTML=`<div class="empty">Sin datos todavía.</div>`; return }
  const xs = [...new Set(all.map(p=>p.f))].sort(), xi = Object.fromEntries(xs.map((x,i)=>[x,i]));
  let lo=Math.min(0,...all.map(p=>p.u)), hi=Math.max(0,...all.map(p=>p.u)); if(hi===lo) hi=lo+1;
  const pad=(hi-lo)*.08; lo-=pad; hi+=pad;
  const X=i=>m.l+(xs.length<2?0.5:i/(xs.length-1))*(W-m.l-m.r), Y=v=>m.t+(1-(v-lo)/(hi-lo))*(H-m.t-m.b);
  const ticks=[]; const step=Math.pow(10,Math.floor(Math.log10((hi-lo)/3))); const st=[1,2,5,10].map(k=>k*step).find(s=>(hi-lo)/s<=5);
  for(let v=Math.ceil(lo/st)*st; v<=hi; v+=st) ticks.push(+v.toFixed(6));
  let g = ticks.map(v=>`<line x1="${m.l}" x2="${W-m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="1" ${v===0?'':'stroke-dasharray="2 4"'}/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" font-size="11" fill="var(--tx3)">${opts.fmt?opts.fmt(v):v}</text>`).join("");
  const xl=[0,Math.floor((xs.length-1)/2),xs.length-1].filter((v,i,a)=>a.indexOf(v)===i);
  g += xl.map(i=>`<text x="${X(i)}" y="${H-6}" text-anchor="middle" font-size="11" fill="var(--tx3)">${xs[i].slice(5).split("-").reverse().join("/")}</text>`).join("");
  g += series.map(s=>`<path d="${s.pts.map((p,j)=>(j?"L":"M")+X(xi[p.f]).toFixed(1)+" "+Y(p.u).toFixed(1)).join("")}" fill="none" stroke="var(${s.color})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`).join("");
  if(series.length>1) g += series.map(s=>{ const p=s.pts[s.pts.length-1]; return `<text x="${X(xi[p.f])-4}" y="${Y(p.u)-8}" text-anchor="end" font-size="11.5" font-weight="650" fill="var(--tx2)">${esc(s.name)}</text>` }).join("");
  cont.innerHTML = (series.length>1? `<div class="legend">${series.map(s=>`<span><span class="dot" style="background:var(${s.color})"></span> ${esc(s.name)}</span>`).join("")}</div>`:"")
    + `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label||"Gráfico")}">${g}<line class="cx" y1="${m.t}" y2="${H-m.b}" stroke="var(--tx3)" stroke-width="1" visibility="hidden"/>${series.map((s,i)=>`<circle class="cd${i}" r="4.5" fill="var(${s.color})" stroke="var(--raised)" stroke-width="2" visibility="hidden"/>`).join("")}<rect x="${m.l}" y="0" width="${W-m.l-m.r}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip"></div></div>`;
  const svg=cont.querySelector("svg"), tip=cont.querySelector(".tip"), cx=svg.querySelector(".cx");
  const mover = ev=>{
    const r=svg.getBoundingClientRect(), t=(ev.touches?ev.touches[0]:ev), vx=(t.clientX-r.left)/r.width*W;
    const i=Math.max(0,Math.min(xs.length-1,Math.round((vx-m.l)/(W-m.l-m.r)*(xs.length-1)))), f=xs[i];
    cx.setAttribute("x1",X(i)); cx.setAttribute("x2",X(i)); cx.setAttribute("visibility","visible");
    const filas=series.map((s,j)=>{ const p=[...s.pts].reverse().find(p=>p.f<=f); const c=svg.querySelector(".cd"+j);
      if(p&&p.f===f){ c.setAttribute("cx",X(i)); c.setAttribute("cy",Y(p.u)); c.setAttribute("visibility","visible") } else c.setAttribute("visibility","hidden");
      return p? `${series.length>1?esc(s.name)+": ":""}${opts.fmt?opts.fmt(p.u):p.u}`:"" }).filter(Boolean);
    tip.innerHTML=`${f.split("-").reverse().join("/")}<br><b>${filas.join("<br>")}</b>`; tip.style.display="block";
    tip.style.left=(X(i)/W*r.width)+"px"; tip.style.top=(m.t/H*r.height+18)+"px";
  };
  svg.addEventListener("mousemove",mover); svg.addEventListener("touchmove",mover,{passive:true}); svg.addEventListener("touchstart",mover,{passive:true});
  svg.addEventListener("mouseleave",()=>{ tip.style.display="none"; cx.setAttribute("visibility","hidden"); svg.querySelectorAll("circle").forEach(c=>c.setAttribute("visibility","hidden")) });
}

// ------------------------------------------------------- RENDIMIENTO
// Contrato nuevo: el historial público NO trae dólares; trae `u` (unidades de apuesta) y roi como fracción.
const roiDe = v => v==null ? null : v.roi!=null ? +v.roi : (v.apostado ? v.neto/v.apostado : null);
const clsN = x => x==null ? "" : x>=0 ? "pos" : "neg";
function vRend(){
  const el=$("#v-rend"), H=D.hist, r=H&&H.resumen, curva=(H&&Array.isArray(H.curva))?H.curva:[];
  let h = `<h2 style="margin-top:4px">Tus apuestas</h2>`;
  if(!r||!r.n){ h += `<div class="card empty">${!H && EST.historial==="red" ? "Sin conexión: no se pudo cargar el historial." : "Aún no hay apuestas liquidadas. Los resultados se actualizan solos cada mañana."}</div>` }
  else{
    const uni = r.unidades!=null ? +r.unidades : (curva.length ? +curva[curva.length-1].u : null);
    h += `<div class="kpis"><div class="kpi"><b>${esc(r.n)}</b><span>Apuestas</span></div><div class="kpi"><b>${pct(r.acierto)}</b><span>Acierto</span></div>
      <div class="kpi"><b class="${clsN(r.roi)}">${r.roi==null?"–":(r.roi*100).toFixed(1)+"%"}</b><span>Rendimiento</span></div><div class="kpi"><b class="${clsN(uni)}">${fmtU(uni)}</b><span>Unidades</span></div></div>
      <div class="card"><div class="row"><b>Resultado acumulado</b><span class="meta">unidades de apuesta</span></div><div id="ch-hist"></div>
      <div class="meta">${r.n<200?`Con ${esc(r.n)} apuestas todavía domina la suerte: el rendimiento es confiable a partir de ~200.`:"Muestra suficiente para evaluar."} 1 unidad = lo que apostaste en ese pick.</div></div>
      ${["por_tipo","por_mercado"].filter(f=>Object.keys(r[f]||{}).length).map(f=>tabla(`<div class="card"><table><tr><th>${f==="por_tipo"?"Tipo":"Mercado"}</th><th>N</th><th>Rendimiento</th></tr>
      ${Object.entries(r[f]).sort((a,b)=>b[1].n-a[1].n).map(([k,v])=>{ const q=roiDe(v); return `<tr><td>${esc(k)}</td><td>${esc(v.n)}</td><td class="${clsN(q)}">${q==null?"–":(q*100).toFixed(1)+"%"}</td></tr>` }).join("")}</table></div>`)).join("")}`;
  }
  const pend = (H?.picks||[]).filter(p=>p.estado==="pendiente" && p.tipo==="valor");
  h += `<h2>Pendientes (${pend.length})</h2>` + (pend.length? `<div class="card">${tabla(`<table><tr><th>Pick</th><th>Cuota</th><th>Monto</th><th><span class="sr">Acción</span></th></tr>${pend.map(p=>{
      const k=key(p,"valor"), loc=hechos[k];
      const monto = loc?.monto;   // el monto ya no se publica: solo el local
      return `<tr><td><b>${esc(p.nombre)}</b><br><span class="meta">${esc(p.local)} vs ${esc(p.visita)} · ${hora(p.inicio)}</span></td>
      <td>${c2(loc?.cuota ?? p.cuota_tomada ?? p.cuota_minima)}${(loc||p.cuota_tomada)?"":'<br><span class="meta">mín.</span>'}</td><td>${monto==null?"–":usdn(monto)}</td>
      <td>${loc?.estado==="omitida"?'<span class="meta">omitida</span>':`<button class="btn small" data-omit="${esc(k)}">No aposté</button>`}</td></tr>`}).join("")}</table>`)}
      <div class="meta" style="margin-top:8px">Si no registras la cuota, el sistema asume la cuota mínima. Toca "No aposté" para excluirla de tu rendimiento.</div></div>` : `<div class="card empty">Nada pendiente.</div>`);
  const liq = (H?.picks||[]).filter(p=>["ganada","perdida","nula"].includes(p.estado) && p.tipo==="valor").slice(0,30);
  if(liq.length) h += `<h2>Últimas liquidadas</h2><div class="card">${tabla(`<table><tr><th>Pick</th><th>Cuota</th><th>Resultado</th></tr>${liq.map(p=>{
      const u = p.u!=null ? +p.u : null;
      return `<tr><td>${esc(p.nombre)}<br><span class="meta">${esc(p.local)} vs ${esc(p.visita)}</span></td><td>${c2(p.cuota_tomada)}</td><td class="${u>0?"pos":u<0?"neg":""}">${p.estado==="nula"?"Devuelta":u!=null?fmtU(u):"–"}</td></tr>`}).join("")}</table>`)}</div>`;

  // simulación real 30 días
  const S = D.sim;
  if(S && S.resumen){
    const R=S.resumen;
    // formato nuevo: u (unidades) y roi (fracción); formato viejo (dólares): se ignoran los $ y se muestra solo el ROI
    const fila=(n,r)=>{ if(!(r&&r.n)) return ""; const u = r.u!=null && isFinite(+r.u) ? +r.u : null, q = roiDe(r);
      return `<tr><td>${esc(n)}</td><td>${esc(r.n)}</td><td>${esc(r.ganadas)} (${pct(r.acierto)})</td><td>${pct(r.prob_media)}</td><td class="${clsN(u)}">${u==null?"–":fmtU(u)}</td><td class="${clsN(q)}">${q==null?"–":(q*100).toFixed(1)+"%"}</td></tr>` };
    h += `<h2>Prueba con datos reales: ${esc(S.periodo)}</h2><div class="card">
      <div class="meta">${esc(S.partidos)} partidos reales de las 5 grandes ligas. El sistema decidió cada día solo con información anterior, como si hubiera estado funcionando. El favorito del sistema acertó el 1X2 en <b>${pct(S.acierto_favorito_1x2)}</b> de los partidos.</div>
      ${tabla(`<table style="margin-top:8px"><tr><th>Nivel</th><th>N</th><th>Ganadas</th><th>Prob. esperada</th><th>Unidades</th><th>Rendimiento</th></tr>
      ${fila("Seguras",R.seguras)}${fila("Valor",R.valor)}${fila("Grandes",R.grandes)}</table>`)}
      <div class="note">Lo importante: <b>el sistema acierta lo que dice</b>. Si dice 80%, gana cerca del 80% de las veces. Ganar dinero depende de la cuota: con la cuota de Ecuabet escrita en la app, solo apuestas cuando paga lo suficiente.</div>
      <details><summary class="meta" style="cursor:pointer;padding:6px 0">Ver las ${(S.seguras||[]).length} seguras, una por una</summary>
      ${tabla(`<table><tr><th>Día</th><th>Pick</th><th>Prob.</th><th>Res.</th></tr>${(S.seguras||[]).map(x=>`<tr><td>${esc(ddmm(x.dia))}</td><td>${esc(x.pick)}<br><span class="meta">${esc(x.partido)} · ${esc(x.marcador)}</span></td><td>${pct(x.p)}</td><td>${x.resultado==="ganada"?'<span class="ok-ic" aria-label="Ganada">✓</span>':'<span class="no-ic" aria-label="Perdida">✗</span>'}</td></tr>`).join("")}</table>`)}</details>
      <details><summary class="meta" style="cursor:pointer;padding:6px 0">Ver las ${(S.grandes||[]).length} combinadas, pierna por pierna</summary>
      ${(S.grandes||[]).map(c=>`<div style="margin:10px 0"><div class="row"><b>${esc(ddmm(c.dia))} · objetivo $${esc(c.objetivo)} (cuota ${esc(c.cuota)})</b><span class="${c.resultado==="ganada"?"pos":"neg"}">${esc(c.aciertos)}/${(c.piernas||[]).length}</span></div>
        ${(c.piernas||[]).map(l=>`<div class="meta">${l.acierto?'<span class="ok-ic" aria-label="Acertada">✓</span>':'<span class="no-ic" aria-label="Fallada">✗</span>'} ${esc(l.pick)} — ${esc(l.partido)} (${pct(l.p)})</div>`).join("")}</div>`).join("")}</details>
    </div>`;
  }

  // backtest
  h += `<h2>Backtest: la estrategia en la temporada pasada</h2>`;
  const bt = D.bt && D.bt.resultado;
  if(!bt || !Object.keys(bt).length) h += `<div class="card empty">Aún no se ha corrido. Se calcula solo cada domingo (o desde Ajustes).</div>`;
  else{
    const NB={b365:["Casa blanda (Bet365)","--s1","Lo más parecido a Ecuabet"], max:["Mejor cuota del mercado","--s2","Optimista"]};
    const nf = (x,d)=>isFinite(+x)?(+x).toFixed(d):"–";
    h += `<div class="card"><div class="meta">1 unidad por apuesta, solo con información disponible antes de cada partido (el modelo se reentrena cada semana).</div>
      <div id="ch-bt"></div>
      ${tabla(`<table style="margin-top:6px"><tr><th></th>${Object.keys(bt).map(f=>`<th>${esc(NB[f]?.[0]||f)}</th>`).join("")}</tr>
      ${[["Apuestas",x=>esc(x.n)],["Acierto",x=>pct(x.acierto)],["ROI",x=>`<span class="${x.roi>=0?"pos":"neg"}">${nf(x.roi*100,1)}%</span>`],["Unidades",x=>usd(x.unidades).replace("$","")],
        ["CLV medio",x=>x.clv==null?"–":`<span class="${x.clv>=0?"pos":"neg"}">${nf(x.clv*100,1)}%</span>`],["Le gana al cierre",x=>pct(x.clv_positivo)],
        ["Racha perdedora máx.",x=>esc(x.max_racha_perdidas)],["Caída máxima",x=>nf(x.max_caida,1)+" u"]]
        .map(([n,f])=>`<tr><td>${n}</td>${Object.values(bt).map(x=>`<td>${f(x)}</td>`).join("")}</tr>`).join("")}</table>`)}
      <div class="note">El <b>CLV</b> mide si tomaste mejores cuotas que el cierre de Pinnacle. Un CLV positivo sostenido es la señal más confiable de que la ventaja es real, más que el ROI de pocas semanas.</div></div>`;
  }
  el.innerHTML = h;
  if(r&&r.n) lineChart($("#ch-hist"), [{name:"Unidades", color:"--s1", pts:curva}], {fmt:v=>(v<0?"−":"")+Math.abs(v).toFixed(Math.abs(v)<10?1:0)+"u", label:"Resultado acumulado en unidades de apuesta"});
  if(bt && Object.keys(bt).length) lineChart($("#ch-bt"), Object.entries(bt).map(([f,x])=>({name:f==="b365"?"Bet365":"Mejor cuota", color:f==="b365"?"--s1":"--s2", pts:x.curva||[]})), {fmt:v=>v.toFixed(0)+"u", label:"Unidades acumuladas en el backtest"});
  el.querySelectorAll("[data-omit]").forEach(b=>b.onclick=async()=>{
    const k=b.dataset.omit, [, uid, ...rest]=k.split("|"), clave=rest.join("|");
    b.disabled=true;
    const ok = await despachar("registrar.yml",{lote:JSON.stringify([{uid, clave, accion:"omitir", cuota:0, monto:0}])});
    if(!ok){ b.disabled=false; return }                       // despachar ya mostró el error
    hechos[k]={estado:"omitida"}; LS.set("hechos",hechos); vRend(); toast("Marcada como no apostada");
  });
}

// ------------------------------------------------------------ FUENTES
function vFuentes(){
  const el=$("#v-fuentes"), F=D.fuentes;
  if(!F){ el.innerHTML=`<div class="card empty">${EST.fuentes==="red"?"Sin conexión: no se pudieron cargar las fuentes.":"Aún no hay datos de fuentes."}</div>`; return }
  const orden=["mercado","modelo","forebet","apifootball"], fam=F.familias||{};
  let h = `<div class="note">El sistema mide el error de cada fuente en cada mercado y ajusta solo su peso: la que más acierta pesa más.</div>
    <h2>Peso actual de cada fuente</h2><div class="card"><div class="legend" style="flex-wrap:wrap">${orden.map(f=>`<span><span class="dot" style="background:var(${FUENTE[f][1]})"></span> ${esc(FUENTE[f][0])}</span>`).join("")}</div>
    ${Object.entries(F.pesos||{}).map(([fa,w])=>`<div style="margin-top:10px"><div class="row"><span style="font-size:13px">${esc(fam[fa]||fa)}</span></div>
      <div class="wbar" role="img" aria-label="${esc(orden.map(f=>FUENTE[f][0]+" "+pct(w[f])).join(", "))}">${orden.filter(f=>w[f]>0.005).map(f=>`<i style="width:${Math.min(100,w[f]*100)}%;background:var(${FUENTE[f][1]});color:${["forebet","apifootball"].includes(f)?"#0b0b0b":"#fff"}" title="${esc(FUENTE[f][0])} ${pct(w[f])}">${w[f]>=.12?pct(w[f]):""}</i>`).join("")}</div></div>`).join("")}</div>`;
  const cal=Array.isArray(F.calibracion)?F.calibracion:[];
  if(cal.length){
    const fams=[...new Set(cal.map(c=>c.familia))], fs=[...new Set(cal.map(c=>c.fuente))].sort((a,b)=>orden.indexOf(a)-orden.indexOf(b));
    h += `<h2>Error de cada fuente (Brier: más bajo = mejor)</h2><div class="card">${tabla(`<table><tr><th>Mercado</th>${fs.map(f=>`<th>${esc((FUENTE[f]||[f])[0])}</th>`).join("")}</tr>
      ${fams.map(fa=>{ const vals=cal.filter(c=>c.familia===fa), best=Math.min(...vals.map(v=>v.brier));
        return `<tr><td>${esc(fam[fa]||fa)}</td>${fs.map(f=>{const c=vals.find(v=>v.fuente===f); return `<td>${c?`<b style="${c.brier===best?"color:var(--good)":""}">${isFinite(+c.brier)?(+c.brier).toFixed(3):"–"}</b><br><span class="meta">n=${esc(c.n)}</span>`:"–"}</td>`}).join("")}</tr>`}).join("")}</table>`)}</div>`;
  } else h += `<div class="card empty">El error se empieza a medir cuando terminan los primeros partidos.</div>`;
  el.innerHTML=h;
}

// ------------------------------------------------------------ AJUSTES
function vAjustes(){
  const c=cfg();
  $("#v-ajustes").innerHTML = `
    <h2 style="margin-top:4px">Conexión con tu sistema</h2><div class="card">
    <div class="meta">Para registrar apuestas y correr el análisis desde aquí. Los datos se guardan solo en este navegador (almacenamiento local), sin cifrar.</div>
    <label class="field"><span>Usuario u organización de GitHub</span><input id="a-owner" value="${esc(ajustes.owner)}" autocomplete="off" autocapitalize="off"></label>
    <label class="field"><span>Repositorio</span><input id="a-repo" value="${esc(ajustes.repo)}" autocomplete="off" autocapitalize="off"></label>
    <label class="field"><span>Rama (ref) donde corren los workflows</span><input id="a-ref" value="${esc(ajustes.ref||"main")}" autocomplete="off" autocapitalize="off"></label>
    <div class="field"><label for="a-token"><span>Token de GitHub</span></label><div class="row" style="gap:8px">
      <input id="a-token" type="password" value="" placeholder="${ajustes.token?"Token guardado (déjalo vacío para conservarlo)":"github_pat_…"}" autocomplete="off" autocapitalize="off" spellcheck="false">
      <button type="button" class="btn small" id="a-ver" aria-pressed="false">Mostrar</button></div></div>
    <div class="note">Crea un token <b>fine-grained</b> (Personal access token) con acceso <b>solo a este repositorio</b>, permiso <b>únicamente Actions: Read and write</b> y una <b>caducidad corta</b> (por ejemplo 30 días). No uses un token clásico ni con más permisos.</div>
    <label class="field"><span>Banca para los cálculos de esta pantalla, en USD (vacío = $100.00)</span><input id="a-banca" type="text" inputmode="decimal" value="${esc(ajustes.banca??"")}" autocomplete="off"></label>
    <div class="row" style="gap:8px;flex-wrap:wrap;justify-content:flex-start"><button class="btn pri" id="a-guardar">Guardar</button>
    <button class="btn" id="a-correr">Analizar ahora</button><button class="btn" id="a-bt">Correr backtest</button>
    <button class="btn" id="a-borrar" ${ajustes.token?"":"disabled"}>Borrar token</button></div>
    <div class="meta" style="margin-top:8px">"Analizar ahora" tarda unos 3–5 minutos. Luego toca ↻.</div></div>
    <h2>Reglas activas</h2><div class="card">${tabla(`<table>
      <tr><td>Banca</td><td>$${(+c.banca).toFixed(2)}</td></tr><tr><td>Kelly</td><td>${esc(c.fraccion_kelly)}</td></tr>
      <tr><td>Máximo por pick</td><td>${pct(c.stake_max_pct,1)}</td></tr><tr><td>Valor mínimo</td><td>${pct(c.ventaja_minima)}</td></tr>
      <tr><td>Fuentes mínimas</td><td>${esc(c.min_fuentes??2)}</td></tr><tr><td>Desacuerdo máximo</td><td>±${((c.max_dispersion??.08)*100).toFixed(0)} pts</td></tr></table>`)}
      <div class="meta" style="margin-top:8px">Se cambian en <code>config.yaml</code>.</div></div>
    <h2>Instalar en el celular</h2><div class="card"><div class="meta">iPhone: Safari → Compartir → <b>Agregar a inicio</b>. Android: Chrome → ⋮ → <b>Instalar app</b>.</div></div>
    <div class="note">Ningún sistema garantiza ganancias. Apuesta solo dinero que puedas perder. Si apuestas para recuperar pérdidas, para.</div>`;
  $("#a-ver").onclick=e=>{ const i=$("#a-token"), ver=i.type==="password"; i.type=ver?"text":"password"; e.currentTarget.textContent=ver?"Ocultar":"Mostrar"; e.currentTarget.setAttribute("aria-pressed",ver) };
  $("#a-guardar").onclick=()=>{
    const owner=$("#a-owner").value.trim(), repo=$("#a-repo").value.trim(), ref=($("#a-ref").value.trim()||"main"), tk=$("#a-token").value.trim();
    const bRaw=$("#a-banca").value.trim().replace(",","."), b=bRaw===""?null:parseFloat(bRaw);
    if((owner&&!ownerOk(owner))||(repo&&!repoOk(repo))){ toast("Usuario (máx. 39) o repositorio (máx. 100) inválido: solo letras, números, punto, guion y guion bajo, y no solo puntos.", true); return }
    if(!RE_REF.test(ref)){ toast("Rama inválida.", true); return }
    if(bRaw!=="" && !(isFinite(b)&&b>0)){ toast("La banca debe ser un número mayor que 0.", true); return }
    ajustes={owner,repo,ref,token:tk||ajustes.token||"",banca:b}; LS.set("ajustes",ajustes); toast("Guardado"); renderTodo();
  };
  $("#a-borrar").onclick=()=>{ ajustes.token=""; LS.set("ajustes",ajustes); toast("Token borrado de este navegador"); vAjustes() };
  $("#a-correr").onclick=async()=>{ if(await despachar("diario.yml",{})) toast("Análisis en marcha. Vuelve en unos minutos.") };
  $("#a-bt").onclick=async()=>{ if(await despachar("backtest.yml",{})) toast("Backtest en marcha (~10 min).") };
}

// ------------------------------------------------------------- navegación
const TIT={hoy:"Hoy",partidos:"Partidos",rend:"Rendimiento",fuentes:"Fuentes",ajustes:"Ajustes"};
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll("nav button").forEach(x=>{ x.classList.toggle("on",x===b); if(x===b) x.setAttribute("aria-current","page"); else x.removeAttribute("aria-current") });
  Object.keys(TIT).forEach(v=>$("#v-"+v).classList.toggle("hide",v!==b.dataset.v));
  $("#titulo").textContent=TIT[b.dataset.v]; window.scrollTo(0,0);
  ({hoy:vHoy,partidos:vPartidos,rend:vRend,fuentes:vFuentes,ajustes:vAjustes})[b.dataset.v](); barra();
});
$("#recargar").onclick=()=>{ cargar(); toast("Actualizando…") };
try{ if("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(()=>{}) }catch(e){}
cargar();
