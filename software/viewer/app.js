/* vivo-v5 viewer: vanilla JS + Canvas, no external dependencies. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const CHANNELS = ["EHZ", "ENE", "ENN", "ENZ"];
const COLORS = { EHZ: "#ffb454", ENE: "#64d2ff", ENN: "#7ee787", ENZ: "#ff7eb6" };
const UNITS = { EHZ: "m/s", ENE: "m/s²", ENN: "m/s²", ENZ: "m/s²" };
const MARKERS = {
  onset: "#ffd166",
  p: "#64d2ff",
  s: "#ff7eb6",
};

const state = {
  liveRows: [],
  liveChannels: new Set(CHANNELS),
  liveMinutes: 5,
  events: [],
  channels: [],
  selected: null,
  selectedStation: null,
  selectedTrace: null,
  detailChannels: new Set(CHANNELS),
};

/* ------------------------------------------------------------------ */
/* CSV and formatting                                                  */
/* ------------------------------------------------------------------ */
function parseCSV(text) {
  const src = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"') {
        if (src[i + 1] === '"') { field += '"'; i++; }
        else quoted = false;
      } else field += c;
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n") {
      row.push(field); field = "";
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
    } else if (c !== "\r") {
      field += c;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.some((v) => v !== "")) rows.push(row);
  }
  if (!rows.length) return [];
  const headers = rows.shift().map((h) => h.trim());
  return rows.map((r) => {
    const obj = {};
    headers.forEach((h, i) => { obj[h] = (r[i] ?? "").trim(); });
    return obj;
  });
}

async function fetchCSV(path) {
  const url = `${path}?t=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return parseCSV(await res.text());
}

function parseUtc(value) {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function fmtUtc(value, withMs = true) {
  const t = typeof value === "number" ? value : parseUtc(value);
  if (t === null || !Number.isFinite(t)) return value || "—";
  const iso = new Date(t).toISOString();
  const base = iso.replace("T", " ").replace("Z", "");
  return `${withMs ? base : base.slice(0, 19)} UTC`;
}

function fmtClock(value) {
  const t = typeof value === "number" ? value : parseUtc(value);
  if (t === null || !Number.isFinite(t)) return "—";
  return new Date(t).toISOString().slice(11, 19);
}

function num(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function prob(value) {
  const n = num(value);
  return n === null ? "—" : n.toFixed(3);
}

function fmtPhysical(value) {
  const n = num(value);
  if (n === null) return "—";
  if (n === 0) return "0";
  if (Math.abs(n) < 0.001 || Math.abs(n) >= 10000) return n.toExponential(2);
  return n.toPrecision(4);
}

function fmtAxis(value) {
  if (value === 0) return "0";
  if (Math.abs(value) < 0.001 || Math.abs(value) >= 10000) return value.toExponential(1);
  return value.toPrecision(3);
}

function fmtDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s < 60) return `${s.toFixed(0)} s`;
  if (s < 3600) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function splitStations(value) {
  return String(value || "").split("|").map((s) => s.trim()).filter(Boolean);
}

/* ------------------------------------------------------------------ */
/* Canvas drawing                                                      */
/* ------------------------------------------------------------------ */
function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function drawEmpty(canvas) {
  const { ctx, w, h } = prepareCanvas(canvas);
  ctx.fillStyle = "rgba(143, 162, 183, .06)";
  ctx.fillRect(0, 0, w, h);
}

function drawTraceCanvas(canvas, series, options = {}) {
  const { ctx, w, h } = prepareCanvas(canvas);
  const dataSeries = (series || []).filter((s) => s.points && s.points.length);
  if (!dataSeries.length) {
    drawEmpty(canvas);
    return;
  }

  let start = options.start ?? Infinity;
  let end = options.end ?? -Infinity;
  if (options.start === undefined || options.end === undefined) {
    for (const s of dataSeries) {
      for (const p of s.points) {
        if (p[0] === null) continue;
        if (p[0] < start) start = p[0];
        if (p[0] > end) end = p[0];
      }
    }
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    drawEmpty(canvas);
    return;
  }

  const margin = { left: 72, right: 16, top: 20, bottom: 30 };
  const gap = 12;
  const n = dataSeries.length;
  const plotW = Math.max(20, w - margin.left - margin.right);
  const plotH = Math.max(20, h - margin.top - margin.bottom);
  const panelH = Math.max(18, (plotH - gap * (n - 1)) / n);
  const xOf = (t) => margin.left + ((t - start) / (end - start)) * plotW;
  const timeSpan = (end - start) / 1000;

  // background + grid
  ctx.fillStyle = "rgba(11, 15, 20, .35)";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(143, 162, 183, .13)";
  ctx.lineWidth = 1;
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const x = margin.left + (i / ticks) * plotW;
    ctx.beginPath();
    ctx.moveTo(x, margin.top - 4);
    ctx.lineTo(x, h - margin.bottom + 4);
    ctx.stroke();
  }

  // time labels
  ctx.fillStyle = "rgba(143, 162, 183, .9)";
  ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let i = 0; i <= ticks; i++) {
    const t = start + (i / ticks) * (end - start);
    const x = margin.left + (i / ticks) * plotW;
    ctx.textAlign = i === 0 ? "left" : i === ticks ? "right" : "center";
    ctx.fillText(fmtClock(t), x, h - margin.bottom + 10);
  }

  const markers = (options.markers || []).filter((m) => m && Number.isFinite(m.t));
  dataSeries.forEach((s, index) => {
    const top = margin.top + index * (panelH + gap);
    const bottom = top + panelH;
    const center = top + panelH / 2;
    const half = Math.max(2, panelH / 2 - 7);
    let maxAbs = 0;
    for (const p of s.points) {
      if (p[1] === null || p[0] < start || p[0] > end) continue;
      maxAbs = Math.max(maxAbs, Math.abs(p[1]));
    }
    const limit = maxAbs > 0 ? maxAbs * 1.16 : 1e-9;
    const yOf = (v) => center - (v / limit) * half;

    // panel frame and zero line
    ctx.strokeStyle = "rgba(143, 162, 183, .18)";
    ctx.lineWidth = 1;
    ctx.strokeRect(margin.left, top, plotW, panelH);
    ctx.strokeStyle = "rgba(143, 162, 183, .28)";
    ctx.beginPath();
    ctx.moveTo(margin.left, center);
    ctx.lineTo(margin.left + plotW, center);
    ctx.stroke();

    // channel label
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillStyle = s.color || "#e8eef6";
    ctx.font = "600 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    ctx.fillText(s.label || "", 10, top + 4);
    ctx.fillStyle = "rgba(143, 162, 183, .9)";
    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    ctx.fillText(s.unit || "", 10, top + 21);
    ctx.fillText(fmtAxis(limit), 10, center - 6);
    ctx.fillText(fmtAxis(-limit), 10, center + 8);

    // trace
    ctx.strokeStyle = s.color || "#64d2ff";
    ctx.lineWidth = 1.15;
    ctx.beginPath();
    let drawing = false;
    for (const p of s.points) {
      const t = p[0];
      const v = p[1];
      if (t === null || v === null || t < start || t > end) {
        drawing = false;
        continue;
      }
      const x = xOf(t);
      const y = yOf(v);
      if (!drawing) { ctx.moveTo(x, y); drawing = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // markers across this panel
    for (const m of markers) {
      if (m.t < start || m.t > end) continue;
      const x = xOf(m.t);
      ctx.save();
      ctx.setLineDash(m.dash || [4, 4]);
      ctx.strokeStyle = m.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.restore();
    }
  });

  // marker labels at top
  if (markers.length) {
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.font = "600 10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    for (const m of markers) {
      if (m.t < start || m.t > end) continue;
      const x = Math.min(w - 48, Math.max(margin.left + 2, xOf(m.t) + 3));
      ctx.fillStyle = m.color;
      ctx.fillText(m.label, x, margin.top - 5);
    }
  }

  // title/time span
  ctx.fillStyle = "rgba(143, 162, 183, .9)";
  ctx.textAlign = "right";
  ctx.textBaseline = "top";
  ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  ctx.fillText(`${fmtClock(start)} – ${fmtClock(end)} UTC · ${timeSpan.toFixed(1)} s`, w - margin.right, 4);
}

/* ------------------------------------------------------------------ */
/* Live view                                                           */
/* ------------------------------------------------------------------ */
function renderLive() {
  const rows = state.liveRows;
  const empty = $("#liveEmpty");
  const badge = $("#liveBadge");
  const updated = $("#liveUpdated");
  if (!rows.length) {
    empty.hidden = false;
    empty.textContent = "Esperando el primer bloque del Shake…";
    badge.textContent = "VIVO —";
    badge.className = "badge";
    updated.textContent = "sin datos todavía";
    drawEmpty($("#liveCanvas"));
    $("#liveLegend").textContent = "";
    return;
  }
  const times = rows.map((r) => parseUtc(r.utc)).filter((t) => t !== null);
  const last = times.length ? Math.max(...times) : null;
  if (last === null) {
    empty.hidden = false;
    empty.textContent = "live.csv no tiene fechas válidas.";
    return;
  }
  const windowMs = state.liveMinutes * 60 * 1000;
  const start = last - windowMs;
  const selected = Array.from(state.liveChannels);
  const series = selected.map((channel) => {
    const points = rows
      .map((row) => [parseUtc(row.utc), num(row[channel])])
      .filter((p) => p[0] !== null && p[0] >= start);
    return { channel, label: channel, unit: UNITS[channel], color: COLORS[channel], points };
  });
  const hasData = series.some((s) => s.points.some((p) => p[1] !== null));
  empty.hidden = hasData;
  empty.textContent = "Sin muestras en la ventana seleccionada.";
  drawTraceCanvas($("#liveCanvas"), series, { start, end: last });

  const legend = $("#liveLegend");
  legend.textContent = "";
  for (const s of series) {
    const max = Math.max(0, ...s.points.map((p) => (p[1] === null ? 0 : Math.abs(p[1]))));
    const item = document.createElement("span");
    item.className = "item";
    const sw = document.createElement("span");
    sw.className = "swatch";
    sw.style.background = s.color;
    item.appendChild(sw);
    const label = document.createElement("span");
    label.textContent = `${s.label} `;
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = `${fmtPhysical(max)} ${s.unit}`;
    item.appendChild(label);
    item.appendChild(val);
    legend.appendChild(item);
  }

  const age = (Date.now() - last) / 1000;
  updated.textContent = `último dato ${fmtUtc(last)} · ${rows.length} filas`;
  badge.textContent = `VIVO · ${fmtClock(last)} UTC`;
  badge.className = "badge " + (age > 180 ? "bad" : age > 90 ? "warn" : "ok");
}

async function loadLive() {
  try {
    state.liveRows = await fetchCSV("data/live.csv");
    renderLive();
  } catch (err) {
    const badge = $("#liveBadge");
    badge.textContent = "VIVO · sin live.csv";
    badge.className = "badge bad";
    $("#liveUpdated").textContent = String(err.message || err);
  }
}

/* ------------------------------------------------------------------ */
/* Events                                                              */
/* ------------------------------------------------------------------ */
function eventStatusClass(status) {
  return `status ${String(status || "").replace(/[^A-Z_]/g, "")}`;
}

function renderEventTable() {
  const tbody = $("#eventRows");
  tbody.textContent = "";
  const filter = $("#statusFilter").value;
  const events = state.events
    .filter((e) => !filter || filter === "all" || e.status === filter)
    .slice()
    .sort((a, b) => String(b.utc_onset).localeCompare(String(a.utc_onset)));

  for (const event of events) {
    const tr = document.createElement("tr");
    tr.dataset.id = event.event_id;
    if (state.selected && state.selected.event_id === event.event_id) tr.classList.add("selected");

    const tdTime = document.createElement("td");
    tdTime.textContent = fmtUtc(event.utc_onset);
    tr.appendChild(tdTime);

    const tdStatus = document.createElement("td");
    const span = document.createElement("span");
    span.className = eventStatusClass(event.status);
    span.textContent = event.status || "—";
    tdStatus.appendChild(span);
    tr.appendChild(tdStatus);

    const tdP = document.createElement("td");
    tdP.textContent = prob(event.p_prob);
    tr.appendChild(tdP);

    const tdS = document.createElement("td");
    tdS.textContent = prob(event.s_prob);
    tr.appendChild(tdS);

    const tdAlert = document.createElement("td");
    tdAlert.textContent = event.alert === "1" ? "SÍ" : "—";
    tdAlert.className = event.alert === "1" ? "alert-yes" : "alert-no";
    tr.appendChild(tdAlert);

    tr.addEventListener("click", () => selectEvent(event.event_id));
    tbody.appendChild(tr);
  }
  $("#eventsEmpty").hidden = events.length > 0;

  const counts = {};
  for (const e of state.events) counts[e.status] = (counts[e.status] || 0) + 1;
  const pending = (counts.PROVISIONAL || 0) + (counts.PENDIENTE || 0);
  const alerts = state.events.filter((e) => e.alert === "1").length;
  $("#eventBadge").textContent = `${state.events.length} eventos · ${alerts} alertas`;
  $("#pendingBadge").textContent = `${pending} pendientes`;
  $("#pendingBadge").className = "badge " + (pending ? "warn" : "ok");
}

function summaryRow(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  dl.appendChild(dt);
  dl.appendChild(dd);
}

function renderEventSummary(event) {
  const dl = $("#eventSummary");
  dl.textContent = "";
  summaryRow(dl, "Evento", event.event_id);
  summaryRow(dl, "Estado", event.status);
  summaryRow(dl, "Onset", fmtUtc(event.utc_onset));
  summaryRow(dl, "Fin", fmtUtc(event.utc_end));
  summaryRow(dl, "Detectado", fmtUtc(event.utc_detect));
  summaryRow(dl, "Confirmar desde", fmtUtc(event.confirm_due_utc));
  summaryRow(dl, "Intentos", event.attempts);
  summaryRow(dl, "Confirmada por", event.confirmed_by);
  summaryRow(dl, "Veto", event.veto_reason);
  summaryRow(dl, "PhaseNet", event.phasenet_station && event.phasenet_input ? `${event.phasenet_station} · ${event.phasenet_input}` : "");
  summaryRow(dl, "P / S", `${prob(event.p_prob)} / ${prob(event.s_prob)}`);
  summaryRow(dl, "Pick P", fmtUtc(event.p_pick_utc));
  summaryRow(dl, "Pick S", fmtUtc(event.s_pick_utc));
  summaryRow(dl, "Alerta", event.alert === "1" ? "SÍ" : "no");
  summaryRow(dl, "Latencia", event.latency_s ? fmtDuration(Number(event.latency_s)) : "");
  summaryRow(dl, "Error", event.last_error);
}

function renderChannelTable(event, station) {
  const tbody = $("#channelRows");
  tbody.textContent = "";
  const rows = state.channels.filter((c) => c.event_id === event.event_id && c.station === station);
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = "Sin filas en canales.csv para esta estación.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const c of rows) {
    const tr = document.createElement("tr");
    for (const key of ["channel", "peak", "rms", "snr", "gap_pct"]) {
      const td = document.createElement("td");
      td.textContent = c[key] ?? "";
      if (key === "gap_pct" && c[key] !== "") td.textContent = `${c[key]}%`;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderStationButtons(event) {
  const box = $("#stationButtons");
  box.textContent = "";
  const stations = splitStations(event.trace_stations);
  if (!stations.length) stations.push(event.station || "RE626");
  for (const station of stations) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "station-btn" + (station === state.selectedStation ? " active" : "");
    btn.textContent = station;
    btn.addEventListener("click", () => selectStation(station));
    box.appendChild(btn);
  }
}

function updateDetailLinks(event, station) {
  const links = $("#detailLinks");
  links.textContent = "";
  if (!event || !station) return;
  const base = `data/trazas/${encodeURIComponent(event.event_id)}_${encodeURIComponent(station)}`;
  const csv = document.createElement("a");
  csv.href = `${base}.csv`;
  csv.textContent = "CSV procesado";
  const raw = document.createElement("a");
  raw.href = `${base}.csv.gz`;
  raw.textContent = "CSV crudo .gz";
  links.appendChild(csv);
  links.appendChild(raw);
}

function updateDetailHeader(event) {
  $("#detailTitle").textContent = fmtUtc(event.utc_onset);
  const meta = [
    event.status,
    event.confirmed_by ? `confirmada por ${event.confirmed_by}` : "",
    event.veto_reason ? `veto: ${event.veto_reason}` : "",
    event.event_id,
  ].filter(Boolean);
  $("#detailMeta").textContent = meta.join(" · ");
}

function buildTraceSeries(rows, selectedChannels) {
  const points = {};
  for (const channel of CHANNELS) points[channel] = [];
  let start = null;
  let end = null;
  for (const row of rows) {
    const t = parseUtc(row.utc);
    if (t === null) continue;
    if (start === null || t < start) start = t;
    if (end === null || t > end) end = t;
    for (const channel of CHANNELS) {
      if (!selectedChannels.has(channel)) continue;
      const key = `${channel}_m_s` in row ? `${channel}_m_s` : `${channel}_m_s2`;
      points[channel].push([t, num(row[key])]);
    }
  }
  const series = CHANNELS
    .filter((ch) => selectedChannels.has(ch))
    .map((channel) => ({
      channel,
      label: channel,
      unit: UNITS[channel],
      color: COLORS[channel],
      points: points[channel],
    }))
    .filter((s) => s.points.some((p) => p[1] !== null));
  return { series, start, end };
}

function drawEventTrace() {
  const event = state.selected;
  if (!event || !state.selectedTrace) return;
  const { series, start, end } = buildTraceSeries(state.selectedTrace, state.detailChannels);
  const empty = $("#eventEmpty");
  if (!series.length) {
    empty.hidden = false;
    empty.textContent = "No hay canales seleccionados con datos.";
    drawEmpty($("#eventCanvas"));
    $("#eventLegend").textContent = "";
    return;
  }
  empty.hidden = true;

  const markers = [];
  const onset = parseUtc(event.utc_onset);
  if (onset !== null) markers.push({ t: onset, label: "onset", color: MARKERS.onset });
  if (state.selectedStation && state.selectedStation === event.phasenet_station) {
    const p = parseUtc(event.p_pick_utc);
    const s = parseUtc(event.s_pick_utc);
    if (p !== null) markers.push({ t: p, label: "P", color: MARKERS.p });
    if (s !== null) markers.push({ t: s, label: "S", color: MARKERS.s });
  }
  drawTraceCanvas($("#eventCanvas"), series, { start, end, markers });

  const legend = $("#eventLegend");
  legend.textContent = "";
  for (const s of series) {
    const max = Math.max(0, ...s.points.map((p) => (p[1] === null ? 0 : Math.abs(p[1]))));
    const item = document.createElement("span");
    item.className = "item";
    const sw = document.createElement("span");
    sw.className = "swatch";
    sw.style.background = s.color;
    item.appendChild(sw);
    const label = document.createElement("span");
    label.textContent = `${s.label} `;
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = `pico ${fmtPhysical(max)} ${s.unit}`;
    item.appendChild(label);
    item.appendChild(val);
    legend.appendChild(item);
  }
}

async function selectStation(station) {
  if (!state.selected) return;
  state.selectedStation = station;
  renderStationButtons(state.selected);
  updateDetailLinks(state.selected, station);
  const url = `data/trazas/${encodeURIComponent(state.selected.event_id)}_${encodeURIComponent(station)}.csv`;
  const empty = $("#eventEmpty");
  empty.hidden = false;
  empty.textContent = "Cargando traza…";
  try {
    state.selectedTrace = await fetchCSV(url);
    empty.hidden = true;
    renderChannelTable(state.selected, station);
    drawEventTrace();
  } catch (err) {
    state.selectedTrace = null;
    drawEmpty($("#eventCanvas"));
    $("#eventLegend").textContent = "";
    empty.hidden = false;
    empty.textContent = `No se pudo cargar la traza de ${station}: ${err.message || err}`;
  }
}

function selectEvent(id) {
  const event = state.events.find((e) => e.event_id === id);
  if (!event) return;
  state.selected = event;
  const stations = splitStations(event.trace_stations);
  const preferred = stations.includes(event.phasenet_station)
    ? event.phasenet_station
    : stations.includes("RE626") ? "RE626" : stations[0] || event.station || "RE626";
  state.selectedStation = preferred;
  state.selectedTrace = null;
  state.detailChannels = new Set(CHANNELS);
  for (const cb of $$("[data-detail-ch]")) cb.checked = true;
  $("#detailToolbar").hidden = false;
  updateDetailHeader(event);
  renderEventSummary(event);
  renderStationButtons(event);
  updateDetailLinks(event, preferred);
  renderChannelTable(event, preferred);
  selectStation(preferred);
  renderEventTable();
}

async function loadEvents() {
  try {
    const [events, channels] = await Promise.all([
      fetchCSV("data/eventos.csv"),
      fetchCSV("data/canales.csv").catch(() => []),
    ]);
    state.events = events;
    state.channels = channels;
    if (state.selected) {
      const current = state.events.find((e) => e.event_id === state.selected.event_id);
      if (current) {
        state.selected = current;
        updateDetailHeader(current);
        renderEventSummary(current);
      }
    }
    renderEventTable();
  } catch (err) {
    $("#eventsEmpty").hidden = false;
    $("#eventsEmpty").textContent = `No se pudo leer eventos.csv: ${err.message || err}`;
  }
}

async function loadHealth() {
  try {
    const rows = await fetchCSV("data/health.csv");
    if (!rows.length) return;
    const h = rows[rows.length - 1];
    const parts = [];
    if (h.pending !== undefined) parts.push(`${h.pending} pendientes`);
    if (h.disk_free_gb) parts.push(`${h.disk_free_gb} GB libres`);
    if (h.last_fdsn_ok_utc) parts.push(`FDSN ${fmtClock(h.last_fdsn_ok_utc)}`);
    $("#footerHealth").textContent = parts.join(" · ") || "—";
  } catch (_) {
    // health.csv is optional for the viewer
  }
}

/* ------------------------------------------------------------------ */
/* Wiring                                                              */
/* ------------------------------------------------------------------ */
function switchTab(name) {
  for (const tab of $$(".tab")) tab.classList.toggle("active", tab.dataset.tab === name);
  for (const view of $$(".view")) view.classList.toggle("active", view.id === `view-${name}`);
  if (name === "events") loadEvents();
  else loadLive();
  setTimeout(redrawAll, 30);
}

function redrawAll() {
  renderLive();
  drawEventTrace();
}

function wire() {
  for (const tab of $$(".tab")) {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  }
  $("#liveWindow").addEventListener("change", (ev) => {
    state.liveMinutes = Number(ev.target.value) || 5;
    renderLive();
  });
  for (const cb of $$("[data-live-ch]")) {
    cb.addEventListener("change", () => {
      if (cb.checked) state.liveChannels.add(cb.dataset.liveCh);
      else state.liveChannels.delete(cb.dataset.liveCh);
      renderLive();
    });
  }
  for (const cb of $$("[data-detail-ch]")) {
    cb.addEventListener("change", () => {
      if (cb.checked) state.detailChannels.add(cb.dataset.detailCh);
      else state.detailChannels.delete(cb.dataset.detailCh);
      drawEventTrace();
    });
  }
  $("#statusFilter").addEventListener("change", renderEventTable);
  $("#refreshEvents").addEventListener("click", loadEvents);
  window.addEventListener("resize", () => {
    clearTimeout(window.__vivoResize);
    window.__vivoResize = setTimeout(redrawAll, 120);
  });
  setInterval(() => {
    $("#clock").textContent = `UTC ${new Date().toISOString().slice(11, 19)}`;
  }, 1000);
  $("#clock").textContent = `UTC ${new Date().toISOString().slice(11, 19)}`;
  setInterval(loadLive, 5000);
  setInterval(loadEvents, 10000);
  setInterval(loadHealth, 15000);
}

(async function init() {
  wire();
  await Promise.allSettled([loadLive(), loadEvents(), loadHealth()]);
})();
