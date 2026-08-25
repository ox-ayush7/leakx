from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
import json
import time
import random
import threading
import webbrowser
from datetime import datetime

from database import (
    create_database,
    add_reading,
    get_all_readings,
    get_latest_per_zone,
    ZONE_SLUGS,
)

app = FastAPI(title="LeakX API", version="5.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXPECTED_FLOW = 7.0
db_lock = threading.Lock()

# All simulated zones (in DB-column order). Each has its own valve and its
# own leak/normal cycle, offset so they don't all spike at the same time.
ZONE_NAMES = list(ZONE_SLUGS.keys())
DEFAULT_ZONE = ZONE_NAMES[0]

valves = {name: {"closed": False} for name in ZONE_NAMES}
zone_counters = {name: idx * 5 for idx, name in enumerate(ZONE_NAMES)}


def generate_zone_values(zone):
    """Returns (flow, pressure, status) for one zone for the current tick."""
    if valves[zone]["closed"]:
        return (
            round(random.uniform(0.3, 1.0), 1),
            round(random.uniform(48.0, 52.0), 1),
            "NORMAL",
        )

    zone_counters[zone] += 1
    phase = zone_counters[zone] % 15

    if 10 <= phase < 15:
        flow = round(random.uniform(12.5, 14.5), 1)
        pressure = round(random.uniform(26.0, 29.0), 1)
        status = "LEAK"
    else:
        flow = round(random.uniform(6.5, 8.5), 1)
        pressure = round(random.uniform(38.0, 42.0), 1)
        status = "NORMAL"

    return flow, pressure, status


def append_tick(timestamp, readings):
    """readings: dict of zone name -> (flow, pressure, status). One DB row per tick."""
    try:
        with db_lock:
            add_reading(timestamp, readings)
    except Exception as e:
        print("Database write error:", e)


def simulator_thread():
    while True:
        time.sleep(2)
        timestamp = datetime.now().strftime("%H:%M:%S")
        readings = {zone: generate_zone_values(zone) for zone in ZONE_NAMES}
        append_tick(timestamp, readings)


def read_sensor_data(zone=None):
    try:
        with db_lock:
            return get_all_readings(zone)
    except Exception:
        return []


def read_latest_per_zone():
    try:
        with db_lock:
            return get_latest_per_zone()
    except Exception:
        return []


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LeakX — Distribution Monitoring</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;900&family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'IBM Plex Sans',system-ui,sans-serif}
  :root{
    --bg:#141518;
    --panel:#1b1d21;
    --panel-alt:#212327;
    --border:#33353a;
    --border-strong:#4a4d53;
    --text:#dde0e3;
    --muted:#83878d;
    --copper:#c17d4a;
    --copper-dim:#8f6440;
    --green:#5f9668;
    --amber:#c99a4a;
    --red:#b8503a;
    --mono:'IBM Plex Mono',ui-monospace,monospace;
    --disp:'Big Shoulders Display',sans-serif;
  }
  body{
    background:
      linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px) 0 0/100% 28px,
      var(--bg);
    min-height:100vh;color:var(--text);padding:22px 26px 40px;
  }
  body.shake{animation:flicker .28s}
  @keyframes flicker{0%,100%{filter:none}45%{filter:brightness(1.5) contrast(1.1)}}

  /* ---- recurring instrument marker: a small square LED ---- */
  .led{display:inline-block;width:7px;height:7px;flex:0 0 auto}
  .led.led-green{background:var(--green)}
  .led.led-amber{background:var(--amber)}
  .led.led-red{background:var(--red);box-shadow:0 0 6px rgba(184,80,58,.7)}
  .led.led-off{background:var(--border-strong)}

  header.nameplate{
    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;
    background:var(--panel);border:1px solid var(--border);padding:14px 18px;margin-bottom:16px;
    position:relative;
  }
  header.nameplate::before,header.nameplate::after{
    content:"";position:absolute;top:6px;width:4px;height:4px;background:var(--border-strong);border-radius:50%;
  }
  header.nameplate::before{left:6px}
  header.nameplate::after{right:6px}
  .brand{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .brand-mark{font-family:var(--disp);font-weight:900;font-size:26px;letter-spacing:1px;text-transform:uppercase}
  .brand-mark .accent{color:var(--copper)}
  .brand-sub{font-size:11px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;font-weight:500}
  .controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}

  .tag-sim{padding:5px 10px;font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;
    background:var(--panel-alt);color:var(--amber);border:1px solid var(--border-strong)}

  .zsel,.ctrl-btn,.switch{
    font-family:'IBM Plex Sans',sans-serif;padding:7px 12px;font-size:11px;font-weight:600;letter-spacing:.6px;
    text-transform:uppercase;background:var(--panel-alt);color:var(--text);border:1px solid var(--border-strong);
    cursor:pointer;
  }
  .zsel{cursor:pointer}
  .ctrl-btn:hover{border-color:var(--copper)}
  .switch.open{color:var(--green);border-color:var(--green)}
  .switch.closed{color:var(--amber);border-color:var(--amber);background:rgba(201,154,74,.1)}

  .status-lamp{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:11px;font-weight:600;
    letter-spacing:1px;padding:6px 10px;border:1px solid var(--border-strong)}
  .status-lamp::before{content:"";width:7px;height:7px;flex:0 0 auto}
  .status-lamp.online::before{background:var(--green)}
  .status-lamp.offline::before{background:var(--red)}

  .clock{font-family:var(--mono);font-size:12px;color:var(--muted);letter-spacing:.5px}

  /* ---- instrument tiles ---- */
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;margin-bottom:16px;
    background:var(--border);border:1px solid var(--border)}
  .card{background:var(--panel);padding:16px 16px 14px;border-top:2px solid var(--copper-dim)}
  .label{font-family:var(--disp);font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;
    margin-bottom:10px;font-weight:700}
  .value{font-family:var(--mono);font-size:26px;font-weight:600;color:var(--text)}
  .unit{font-size:11px;color:var(--muted);margin-left:5px;font-weight:500}

  .grid2{display:grid;grid-template-columns:5fr 3fr;gap:1px;margin-bottom:16px;background:var(--border);border:1px solid var(--border)}
  @media(max-width:950px){.grid2{grid-template-columns:1fr}}
  .panel{background:var(--panel);padding:16px 18px 18px}
  .panel h2{font-family:var(--disp);font-size:14px;margin-bottom:14px;color:#c7cbd1;text-transform:uppercase;
    letter-spacing:.5px;font-weight:700;display:flex;align-items:center;gap:8px;padding-bottom:9px;
    border-bottom:1px solid var(--border)}
  .panel h2 .led{margin-right:1px}
  .panel h2 .zname{color:var(--copper)}
  canvas{width:100%;height:230px}

  .gauge-wrap{display:flex;gap:18px;align-items:flex-start;margin-bottom:6px}
  .gauge{position:relative;width:112px;height:112px;flex-shrink:0}
  .gauge svg{width:112px;height:112px}
  .gauge-bg{fill:none;stroke:var(--border-strong);stroke-width:9}
  .gauge-val{fill:none;stroke:var(--green);stroke-width:9;stroke-linecap:butt;stroke-dasharray:314;
    stroke-dashoffset:314;transform:rotate(-90deg);transform-origin:60px 60px;transition:stroke-dashoffset .8s,stroke .8s}
  .gauge-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
  .gauge-center b{font-family:var(--mono);font-size:21px;font-weight:600}
  .gauge-center small{font-size:9px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase}

  #zones{flex:1;min-width:0}
  .zrow{display:grid;grid-template-columns:1fr auto auto auto auto;gap:10px;padding:9px 6px;
    border-bottom:1px solid var(--border);font-size:12px;align-items:center;cursor:pointer;font-family:var(--mono)}
  .zrow:last-child{border-bottom:none}
  .zrow b{font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:12px}
  .zrow.active{background:var(--panel-alt);box-shadow:inset 2px 0 0 var(--copper)}
  .zone-ok,.zone-warn,.zone-crit{display:flex;align-items:center;gap:6px;font-weight:600}
  .zone-ok{color:var(--green)}.zone-warn{color:var(--amber)}.zone-crit{color:var(--red)}

  table{width:100%;border-collapse:collapse;font-size:12px;font-family:var(--mono)}
  th{text-align:left;color:var(--muted);padding:8px;border-bottom:1px solid var(--border-strong);font-size:10px;
    text-transform:uppercase;letter-spacing:1px;font-family:'IBM Plex Sans',sans-serif;font-weight:600}
  td{padding:8px;border-bottom:1px solid var(--border)}
  tr:hover td{background:var(--panel-alt)}
  .tag{padding:2px 8px;font-size:10px;font-weight:700;letter-spacing:.5px;border:1px solid var(--red);color:var(--red)}

  .steps{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin-bottom:16px;background:var(--border);border:1px solid var(--border)}
  @media(max-width:800px){.steps{grid-template-columns:1fr}}
  .step{background:var(--panel);padding:16px}
  .step .idx{font-family:var(--disp);font-size:13px;color:var(--copper);font-weight:700;letter-spacing:1px;margin-bottom:8px}
  .step b{display:block;font-size:13px;margin-bottom:6px;font-weight:600}
  .step p{font-size:12px;color:var(--muted);line-height:1.55}

  footer{text-align:center;color:var(--muted);font-size:10px;padding:12px 0 0;letter-spacing:1px;
    font-family:var(--mono);text-transform:uppercase}

  .toast{position:fixed;bottom:22px;left:22px;background:var(--panel);border:1px solid var(--border-strong);
    border-left:3px solid var(--copper);color:var(--text);padding:12px 18px;font-size:12px;font-family:var(--mono);
    z-index:1000;opacity:0;transform:translateY(8px);transition:.3s;pointer-events:none;max-width:360px}
  .toast.show{opacity:1;transform:translateY(0)}

  .overlay{position:fixed;inset:0;z-index:999;display:none;align-items:center;justify-content:center;
    flex-direction:column;text-align:center;background:#0b0c0e;overflow:hidden}
  .overlay.show{display:flex;animation:fadeIn .15s}
  @keyframes fadeIn{from{opacity:0}to{opacity:1}}
  .overlay::before,.overlay::after{
    content:"";position:absolute;left:0;right:0;height:22px;
    background:repeating-linear-gradient(135deg,var(--amber) 0 20px,#1a1a1a 20px 40px);
  }
  .overlay::before{top:0}
  .overlay::after{bottom:0}

  .hazard-tri{width:104px;height:90px;background:var(--amber);
    clip-path:polygon(50% 4%,4% 96%,96% 96%);
    display:flex;align-items:flex-end;justify-content:center;margin:0 auto 18px;position:relative}
  .hazard-tri::after{content:"!";font-family:var(--disp);font-weight:900;font-size:46px;color:#191300;padding-bottom:6px}

  .ov-title{font-family:var(--disp);font-size:46px;font-weight:900;letter-spacing:6px;color:#fff;
    animation:flash .6s steps(2) infinite;position:relative}
  @keyframes flash{50%{opacity:.45}}
  .ov-sub{font-family:var(--mono);font-size:12px;color:#e8c79a;margin:12px 0 24px;letter-spacing:1.5px;
    text-transform:uppercase;position:relative}
  .ov-sub .zname{color:#fff;font-weight:700}
  .ov-stats{display:flex;gap:1px;margin-bottom:28px;position:relative;flex-wrap:wrap;justify-content:center;
    background:rgba(255,255,255,.12)}
  .ov-stat{background:#151515;padding:10px 22px;font-weight:600;font-family:var(--mono);font-size:12px;color:#f2d9b8}
  .ov-stat b{display:block;font-size:16px;color:#fff;margin-top:2px}

  .btn-row{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;position:relative}
  .valve-btn{padding:13px 30px;border:1px solid var(--amber);background:var(--amber);color:#1a1200;font-weight:700;
    letter-spacing:1px;cursor:pointer;font-size:13px;text-transform:uppercase;font-family:'IBM Plex Sans',sans-serif}
  .valve-btn:hover{background:#dcae63}
  .ack{padding:13px 30px;border:1px solid #6b6b6b;background:transparent;color:#d8d8d8;font-weight:700;
    letter-spacing:1px;cursor:pointer;font-size:13px;text-transform:uppercase;font-family:'IBM Plex Sans',sans-serif}
  .ack:hover{border-color:#fff;color:#fff}
  @media(max-width:700px){.ov-title{font-size:30px;letter-spacing:3px}}
</style>
</head>
<body>

<header class="nameplate">
  <div class="brand">
    <span class="brand-mark">LEAK<span class="accent">X</span></span>
    <span class="brand-sub">Distribution Monitoring</span>
  </div>
  <div class="controls">
    <span class="tag-sim">Simulated Feed</span>
    <select class="zsel" id="zoneSelect" onchange="changeZone(this.value)">
      __ZONE_OPTIONS__
    </select>
    <button class="switch open" id="valveChip" onclick="toggleValve()">Valve — Open</button>
    <button class="ctrl-btn" onclick="window.open('/report?zone='+encodeURIComponent(currentZone))">Export CSV</button>
    <button class="ctrl-btn" id="sndBtn" onclick="enableSound()">Alarm Sound — Off</button>
    <span class="status-lamp offline" id="pill">Offline</span>
    <span class="clock" id="clock">--:--:--</span>
  </div>
</header>

<div class="cards">
  <div class="card"><div class="label">Flow Rate</div><div class="value"><span id="flow">--</span><span class="unit">L/min</span></div></div>
  <div class="card"><div class="label">Pressure</div><div class="value"><span id="pressure">--</span><span class="unit">PSI</span></div></div>
  <div class="card"><div class="label">Pipe Status</div><div class="value" id="status">--</div></div>
  <div class="card"><div class="label">Est. Water Loss</div><div class="value"><span id="loss">--</span><span class="unit">L</span></div></div>
  <div class="card"><div class="label">Alarm Count</div><div class="value"><span id="totalAlerts">--</span></div></div>
</div>

<div class="grid2">
  <div class="panel"><h2><span class="led led-amber"></span>Flow Telemetry — <span class="zname" id="chartZoneName"></span> — threshold 12 L/min</h2><canvas id="chart"></canvas></div>
  <div class="panel">
    <h2><span class="led led-amber"></span>Flow Gauge &amp; Zone Status</h2>
    <div class="gauge-wrap">
      <div class="gauge">
        <svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="50" class="gauge-bg"/><circle cx="60" cy="60" r="50" class="gauge-val" id="gaugeVal"/></svg>
        <div class="gauge-center"><b id="gaugeFlow">--</b><small>L/min</small></div>
      </div>
      <div id="zones" style="flex:1">Loading…</div>
    </div>
  </div>
</div>

<div class="steps">
  <div class="step"><div class="idx">01 — Sense</div><b>Sensor layer</b><p>Flow and pressure readings arrive every 2 seconds over the same REST endpoints that would accept real ESP32 hardware.</p></div>
  <div class="step"><div class="idx">02 — Detect</div><b>Threshold check</b><p>Flow above 12 L/min alongside a pressure drop below 30 PSI is classified as a leak, and water loss is estimated from the excess flow.</p></div>
  <div class="step"><div class="idx">03 — Respond</div><b>Alarm &amp; isolation</b><p>A full-screen alarm sounds, the valve can be shut from this screen, and a per-zone CSV report is available for maintenance records.</p></div>
</div>

<div class="panel" style="margin-bottom:16px"><h2><span class="led led-red"></span>Alarm Log</h2>
  <table>
    <thead><tr><th>Timestamp</th><th>Flow (L/min)</th><th>Pressure (PSI)</th><th>Est. Loss (L/min)</th><th>Severity</th></tr></thead>
    <tbody id="alertRows"></tbody>
  </table>
</div>

<footer>LeakX — FastAPI + SQLite — simulated pipeline, remote valve control, anomaly detection</footer>

<div class="toast" id="toast"></div>

<div class="overlay" id="overlay">
  <div class="hazard-tri" aria-hidden="true"></div>
  <div class="ov-title">LEAK DETECTED</div>
  <div class="ov-sub">Pipeline <span class="zname" id="ovZoneName">ZONE A</span> — critical pressure drop — immediate action required</div>
  <div class="ov-stats">
    <div class="ov-stat">Flow<b><span id="ovFlow">--</span> L/min</b></div>
    <div class="ov-stat">Pressure<b><span id="ovPressure">--</span> PSI</b></div>
    <div class="ov-stat">Loss<b><span id="ovLoss">--</span> L</b></div>
  </div>
  <div class="btn-row">
    <button class="valve-btn" onclick="shutValve()">Shut Valve — Isolate Leak</button>
    <button class="ack" onclick="ackAlert()">Acknowledge</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
async function j(p){ return (await fetch(p)).json(); }
setInterval(()=>{ $("clock").textContent = new Date().toLocaleTimeString(); },1000);

const ZONE_NAMES = __ZONE_NAMES_JSON__;
let currentZone = ZONE_NAMES[0];
let audioCtx=null, soundOn=false, osc=null, gain=null, sirenTimer=null;
let wasLeak=false, acknowledged=false;

function zq(path){
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}zone=${encodeURIComponent(currentZone)}`;
}

function changeZone(zone){
  currentZone = zone;
  $("zoneSelect").value = zone;
  wasLeak = false;
  acknowledged = false;
  $("overlay").classList.remove("show");
  stopSiren();
  $("chartZoneName").textContent = zone;
  refresh();
}

function showToast(msg){
  const t=$("toast");
  t.textContent=msg;
  t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"),3500);
}

function enableSound(){
  if(!audioCtx){ audioCtx = new (window.AudioContext||window.webkitAudioContext)(); }
  audioCtx.resume();
  soundOn = !soundOn;
  $("sndBtn").textContent = soundOn ? "Alarm Sound — On" : "Alarm Sound — Off";
  if(!soundOn) stopSiren();
}

function startSiren(){
  if(!audioCtx || !soundOn || sirenTimer) return;
  osc = audioCtx.createOscillator();
  gain = audioCtx.createGain();
  osc.type = "sawtooth";
  gain.gain.value = 0.06;
  osc.connect(gain); gain.connect(audioCtx.destination);
  osc.start();
  let up = true;
  sirenTimer = setInterval(()=>{
    const t = audioCtx.currentTime;
    osc.frequency.cancelScheduledValues(t);
    osc.frequency.linearRampToValueAtTime(up?950:600, t+0.5);
    up = !up;
  },500);
}

function stopSiren(){
  if(sirenTimer){ clearInterval(sirenTimer); sirenTimer=null; }
  if(osc){ try{ osc.stop(); }catch(e){} osc=null; }
}

function ackAlert(){
  acknowledged = true;
  $("overlay").classList.remove("show");
  stopSiren();
}

function updateValveChip(closed){
  const c=$("valveChip");
  c.className = "switch " + (closed?"closed":"open");
  c.textContent = closed?"Valve — Shut":"Valve — Open";
}

async function toggleValve(){
  const closed = $("valveChip").classList.contains("closed");
  const d = await (await fetch(zq(closed?"/valve/open":"/valve/close"),{method:"POST"})).json();
  updateValveChip(d.valve_closed);
  showToast(d.valve_closed?`Valve shut — flow isolated (${currentZone})`:`Valve reopened — monitoring resumed (${currentZone})`);
}

async function shutValve(){
  await fetch(zq("/valve/close"),{method:"POST"});
  updateValveChip(true);
  acknowledged = true;
  $("overlay").classList.remove("show");
  stopSiren();
  showToast(`Valve shut — leak isolated, system recovering (${currentZone})`);
}

function drawChart(readings){
  const c=$("chart"), ctx=c.getContext("2d");
  const W=c.width=c.clientWidth, H=c.height=c.clientHeight;
  ctx.clearRect(0,0,W,H);
  const data=readings.slice(-40).map(r=>parseFloat(r.flow));
  if(data.length<2) return;
  const maxV=Math.max(14,...data)+2;
  const x=i=>10+i*(W-20)/(data.length-1);
  const y=v=>H-10-(v/maxV)*(H-30);
  ctx.strokeStyle="#b8503a"; ctx.setLineDash([5,5]); ctx.beginPath();
  ctx.moveTo(10,y(12)); ctx.lineTo(W-10,y(12)); ctx.stroke(); ctx.setLineDash([]);
  ctx.strokeStyle="#c17d4a"; ctx.lineWidth=2; ctx.beginPath();
  data.forEach((v,i)=> i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v)));
  ctx.stroke();
  ctx.lineTo(x(data.length-1),H-10); ctx.lineTo(10,H-10); ctx.closePath();
  ctx.fillStyle="rgba(193,125,74,.14)"; ctx.fill();
}

function setGauge(flow){
  const val=Math.min(flow,16);
  $("gaugeVal").style.strokeDashoffset = 314*(1-val/16);
  $("gaugeVal").style.stroke = flow>12?"#b8503a":(flow>9?"#c99a4a":"#5f9668");
  $("gaugeFlow").textContent = flow;
}

async function refresh(){
  try{
    const latest=await j(zq("/latest"));
    const alerts=await j(zq("/alerts"));
    const loss=await j(zq("/water-loss"));
    const zones=await j("/zones");
    const all=await j(zq("/readings"));
    const v=await j(zq("/valve"));
    updateValveChip(v.valve_closed);
    $("pill").className="status-lamp online"; $("pill").textContent="System Online";
    $("flow").textContent=latest.flow ?? "--";
    $("pressure").textContent=latest.pressure ?? "--";
    $("loss").textContent=loss.estimated_water_loss_liters ?? "--";
    $("totalAlerts").textContent=alerts.total_alerts ?? "--";
    const st=$("status");
    st.textContent=latest.status ?? "--";
    st.style.color=(latest.status==="LEAK")?"#c1614a":"#5f9668";
    setGauge(latest.flow ?? 0);

    const leak = (latest.status==="LEAK");
    if(leak && !wasLeak){
      acknowledged=false;
      document.body.classList.add("shake");
      setTimeout(()=>document.body.classList.remove("shake"),600);
      showToast(`Alert dispatched to maintenance (simulated) — ${currentZone}`);
    }
    wasLeak = leak;
    if(leak && !acknowledged){
      $("ovZoneName").textContent=currentZone.toUpperCase();
      $("ovFlow").textContent=latest.flow;
      $("ovPressure").textContent=latest.pressure;
      $("ovLoss").textContent=loss.estimated_water_loss_liters;
      $("overlay").classList.add("show");
      startSiren();
    } else if(!leak){
      $("overlay").classList.remove("show");
      stopSiren();
    }

    $("zones").innerHTML=(zones.zones||[]).map(z=>{
      const cls=z.status==="CRITICAL"?"zone-crit":(z.status==="WARNING"?"zone-warn":"zone-ok");
      const led=z.status==="CRITICAL"?"led-red":(z.status==="WARNING"?"led-amber":"led-green");
      const active=z.zone===currentZone?"active":"";
      return `<div class="zrow ${active}" onclick="changeZone('${z.zone.replace(/'/g,"\\'")}')"><b>${z.zone}</b><span class="${cls}"><span class="led ${led}"></span>${z.status}</span><span>${z.flow} L/min</span><span>${z.pressure} PSI</span><span class="tag ${z.priority==="HIGH"?"high":""}">${z.priority}</span></div>`;
    }).join("")||"No data";
    $("alertRows").innerHTML=(alerts.alerts||[]).slice(-10).reverse().map(a=>
      `<tr><td>${a.timestamp}</td><td>${a.flow}</td><td>${a.pressure}</td><td>${a.estimated_loss_lpm}</td><td><span class="tag high">${a.severity}</span></td></tr>`
    ).join("")||`<tr><td colspan="5" style="color:#83878d">No leak events recorded</td></tr>`;
    drawChart(all.readings||[]);
  }catch(e){
    $("pill").className="status-lamp offline"; $("pill").textContent="Offline";
  }
}
$("chartZoneName").textContent = currentZone;
refresh();
setInterval(refresh,2000);
</script>
</body>
</html>
"""

DASHBOARD_HTML = DASHBOARD_HTML.replace(
    "__ZONE_OPTIONS__",
    "\n".join(
        f'<option value="{z}">{z}</option>' for z in ZONE_NAMES
    ),
).replace(
    "__ZONE_NAMES_JSON__",
    json.dumps(ZONE_NAMES),
)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.on_event("startup")
def startup():
    create_database()

    # Seed initial ticks so every zone has data before the first refresh.
    for _ in range(20):
        timestamp = datetime.now().strftime("%H:%M:%S")
        readings = {zone: generate_zone_values(zone) for zone in ZONE_NAMES}
        append_tick(timestamp, readings)

    threading.Thread(target=simulator_thread, daemon=True).start()
    threading.Timer(
        1.5,
        lambda: webbrowser.open("http://127.0.0.1:8000")
    ).start()


def _zone_or_default(zone):
    return zone if zone in valves else DEFAULT_ZONE


@app.get("/valve")
def valve_status(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    return {"zone": zone, "valve_closed": valves[zone]["closed"]}


@app.post("/valve/close")
def valve_close(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    valves[zone]["closed"] = True
    return {
        "zone": zone,
        "valve_closed": True,
        "message": f"Valve closed - flow isolated ({zone})",
    }


@app.post("/valve/open")
def valve_open(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    valves[zone]["closed"] = False
    return {
        "zone": zone,
        "valve_closed": False,
        "message": f"Valve reopened ({zone})",
    }


@app.get("/report")
def report(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    data = read_sensor_data(zone)

    lines = [
        "zone,timestamp,flow_lpm,pressure_psi,status,estimated_loss_lpm"
    ]

    for r in data:
        loss = (
            round(max(0, r["flow"] - EXPECTED_FLOW), 2)
            if r["status"] == "LEAK"
            else 0
        )

        lines.append(
            f"{zone},{r['timestamp']},{r['flow']},{r['pressure']},"
            f"{r['status']},{loss}"
        )

    safe_zone = "".join(
        c if c.isalnum() else "_" for c in zone
    ).strip("_")

    return Response(
        content="\n".join(lines),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename=LeakX_report_{safe_zone}.csv"
        },
    )


@app.get("/status")
def system_status():
    return {
        "system": "LeakX",
        "status": "online",
        "database": "SQLite",
        "version": "5.0",
    }


@app.get("/latest")
def latest_reading(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    data = read_sensor_data(zone)

    if not data:
        return {"message": "No sensor data available"}

    return data[-1]


@app.get("/readings")
def all_readings(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    data = read_sensor_data(zone)

    return {
        "count": len(data),
        "readings": data,
    }


@app.get("/alerts")
def alerts(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    data = read_sensor_data(zone)

    leak_readings = []

    for reading in data:
        if reading["status"] == "LEAK":
            excess_flow = max(
                0,
                reading["flow"] - EXPECTED_FLOW
            )

            leak_readings.append({
                "timestamp": reading["timestamp"],
                "flow": reading["flow"],
                "pressure": reading["pressure"],
                "estimated_loss_lpm": round(
                    excess_flow,
                    2
                ),
                "severity": "HIGH",
            })

    return {
        "total_alerts": len(leak_readings),
        "alerts": leak_readings,
    }


@app.get("/water-loss")
def water_loss(zone: str = Query(default=DEFAULT_ZONE)):
    zone = _zone_or_default(zone)
    data = read_sensor_data(zone)

    total_loss = 0
    leak_readings = 0

    for reading in data:
        if reading["status"] == "LEAK":
            excess_flow = max(
                0,
                reading["flow"] - EXPECTED_FLOW
            )

            
            loss_per_reading = excess_flow / 30

            total_loss += loss_per_reading
            leak_readings += 1

    return {
        "estimated_water_loss_liters": round(
            total_loss,
            2
        ),
        "leak_readings": leak_readings,
        "unit": "liters",
    }


def classify(flow, status):
    if status == "LEAK":
        return "CRITICAL", "HIGH"
    elif flow > EXPECTED_FLOW:
        return "WARNING", "MEDIUM"
    else:
        return "NORMAL", "LOW"


@app.get("/zones")
def zones():
    latest_rows = {row["zone"]: row for row in read_latest_per_zone()}
    result = []

    for name in ZONE_NAMES:
        row = latest_rows.get(name)
        if not row:
            continue
        zone_status, priority = classify(row["flow"], row["status"])
        result.append({
            "zone": name,
            "status": zone_status,
            "flow": row["flow"],
            "pressure": row["pressure"],
            "priority": priority,
        })

    return {"zones": result}


if __name__ == "__main__":
    import uvicorn

    print("LeakX V5 SQLite → http://127.0.0.1:8000")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )
