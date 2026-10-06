// Core Stack LULC — Leaflet frontend talking to the FastAPI backend.
// Week 18: everything happens inside a project (an area, a year, a base scheme, its classes and
// runs), owned by the signed-in user. The journey and why it's shaped this way: week18/app_design.md.
let PRESETS = {}, COLORS = {}, TREE = {}, STANDARDS = {}, INFER_OPTS = {};
let MERGES = [];                  // active merge rules, drawn onto the hierarchy tree (#1)
let mergeSel = new Set();         // leaf ids ticked in the tree, waiting to be merged (#1)
const AE_INFERENCE_ID = "ds_alphaearth_annual_v1";   // the Alpha Earth feature-source card
let ME = null;                    // the signed-in user
let PROJECT = null;               // the open project (null on the start screen)
let RUN_META = null;              // the run drawn on the map right now
let selected = null;              // the class the right panel acts on (none until you pick one)
let predLayer = L.layerGroup();   // vector cells (fallback render)
let rasterLayer = null;           // the 10 m classified tile overlay
let drawnLayer = L.featureGroup();
let lastGeometry = null;
let extentLayer = null;            // Model Zoo: the selected card's extent rectangle
let zooSelected = null;
let zooPickFor = null;             // set while the zoo is open to pick a model for a class
let aoiLayer = null;              // the project's area, always outlined so the user sees what runs
let newBbox = null;               // a box drawn for a new project, overriding the preset
let pickingArea = false;          // the start card is tucked away while a new area is drawn
let viewMode = "hierarchy";       // left panel: "hierarchy" tree or "ops" operations view (#13)
let TESSERA_SITES = {};           // bboxes where Tessera training is offered (#16)
let currentOpSeq = 0;             // the op-log head the server last reported
let dirty = false;                // the scheme changed since the run on the map

// attributionControl off: no credit box in the corner at all. Basemap is Esri World Imagery -- their
// terms do ask for attribution, so if this ever goes public, credit them in the page chrome instead.
const map = L.map("map", { center: [23.5, 80.0], zoom: 5, attributionControl: false });
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 19 }).addTo(map);
predLayer.addTo(map);
drawnLayer.addTo(map);

// draw tools: the rectangle sets a NEW project's area (an open project's area is fixed, Susmit's
// dataset lock), the polygon marks example geometry.
map.addControl(new L.Control.Draw({
  edit: false,
  draw: { polygon: true, marker: false, rectangle: true, polyline: false,
          circle: false, circlemarker: false },
}));
map.on(L.Draw.Event.CREATED, (e) => {
  if (e.layerType === "rectangle") {
    if (!pickingArea) {
      setStatus("A project's area is fixed. Start a new project for a different area.", "err");
      return;
    }
    const b = e.layer.getBounds();
    newBbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    endAreaPick();
    return;
  }
  drawnLayer.clearLayers();
  drawnLayer.addLayer(e.layer);
  lastGeometry = e.layer.toGeoJSON().geometry;
  setStatus("Polygon captured. Pick who it belongs to, then add it.");
});

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// the area outline: the open project's, or the one being chosen for a new project
function drawAoi() {
  const bb = currentBbox();
  if (aoiLayer) { map.removeLayer(aoiLayer); aoiLayer = null; }
  if (!bboxValid(bb)) return;
  const [w, s, e, n] = bb;
  aoiLayer = L.rectangle([[s, w], [n, e]],
    { color: "#ffd54f", weight: 2, fill: false, dashArray: "4,4" }).addTo(map);
  updateTesseraAvailability();       // the Tessera option depends on the area (#16)
}

// a small promise-based confirm modal, so we're not stuck with the ugly native confirm() (#11).
// Resolves true (OK) / false (Cancel/Esc/backdrop). Message is set via textContent, so it's safe
// with user text and keeps line breaks (CSS white-space: pre-line).
function uiConfirm(message, { okText = "OK", cancelText = "Cancel", danger = false } = {}) {
  return new Promise((resolve) => {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `<div class="modal-card"><p class="modal-msg"></p>
      <div class="modal-btns"><button class="modal-cancel"></button>
      <button class="modal-ok ${danger ? "danger" : "primary"}"></button></div></div>`;
    back.querySelector(".modal-msg").textContent = message;
    back.querySelector(".modal-cancel").textContent = cancelText;
    back.querySelector(".modal-ok").textContent = okText;
    const done = (v) => { back.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => {
      if (e.key === "Escape") done(false);
      if (e.key === "Enter") done(true);
    };
    back.querySelector(".modal-ok").onclick = () => done(true);
    back.querySelector(".modal-cancel").onclick = () => done(false);
    back.onclick = (e) => { if (e.target === back) done(false); };   // click outside = cancel
    document.addEventListener("keydown", onKey);
    document.body.appendChild(back);
    back.querySelector(".modal-ok").focus();
  });
}

// feedback: a floating toast over the map (visible from any panel) + the small status line.
// kind: "info" (auto-hides), "work" (stays up while something runs), "err" (red, lingers).
let _toastTimer = null;
function setStatus(text, kind = "info") {
  if ($("status")) $("status").textContent = text;
  const t = $("toast");
  t.textContent = text;
  t.className = "toast " + kind;            // also clears "hidden" -> visible
  clearTimeout(_toastTimer);
  if (kind !== "work") _toastTimer = setTimeout(() => t.classList.add("hidden"), kind === "err" ? 6000 : 3500);
}

let areaMode = "preset";          // new project: preset | coords | draw
function currentBbox() {
  if (PROJECT) return PROJECT.bbox;
  if (areaMode === "draw") return newBbox;
  if (areaMode === "coords") {
    // a square box of the given size around the point, the old lat/lon + size control in km
    const lat = parseFloat($("npLat").value), lon = parseFloat($("npLon").value);
    const half = (parseFloat($("npKm").value) || 0) / 2;
    const dLat = half / 111.32, dLon = half / (111.32 * Math.cos(lat * Math.PI / 180));
    return [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
  }
  return PRESETS[$("npPreset").value] || null;
}

// #6: ask the backend how long a train over the current area should take, from the benchmark
// profile (scripts/benchmark_training.py). Best-effort — returns null if there's no profile yet.
async function fetchEstimate(algo) {
  try {
    const [w, s, e, n] = currentBbox();
    const d = await getJSON(api(`/api/estimate?west=${w}&south=${s}&east=${e}&north=${n}&algo=${algo || "linearsvc"}`));
    return d.total_s;
  } catch { return null; }
}

// #6: a live elapsed-vs-expected timer on the "work" toast, so a long background run visibly ticks
// instead of sitting on a static "working…". Returns stop() to call the moment the run finishes.
function startWorkTimer(baseText, expectedS) {
  const t0 = Date.now();
  const tick = () => {
    const el = Math.round((Date.now() - t0) / 1000);
    const exp = expectedS ? ` / ~${Math.round(expectedS)}s expected` : "";
    setStatus(`${baseText} — ${el}s elapsed${exp}…`, "work");
  };
  tick();
  const id = setInterval(tick, 1000);
  return () => clearInterval(id);
}

// #3: equal-area size of the area, mirroring src/aoi.area_km2 so we can warn before the request goes
// out. The server re-checks against its own (admin-tunable) caps — this is just UX.
const AOI_TILE_CAP_KM2 = 40000, AOI_GEOTIFF_CAP_KM2 = 250;   // keep in step with config.py
function bboxAreaKm2(bb) {
  const [w, s, e, n] = bb;
  const mid = ((s + n) / 2) * Math.PI / 180;
  const widthM = Math.abs(e - w) * 111320 * Math.cos(mid);
  const heightM = Math.abs(n - s) * 111320;
  return (widthM * heightM) / 1e6;
}

// a finite, correctly-ordered, in-range box. Mirrors src/aoi.valid_bbox so client and server agree.
function bboxValid(bb) {
  if (!bb) return false;
  const [w, s, e, n] = bb;
  if (![w, s, e, n].every(Number.isFinite)) return false;
  if (w < -180 || e > 180 || s < -90 || n > 90) return false;
  return e > w && n > s;
}

// ---- where the backend lives ----
// Every call below writes a plain "/api/…" path; api() is the single place that turns one into a
// real URL. Default is RELATIVE to the page, so the app works unchanged at the domain root or under
// a reverse-proxy subpath (/corestack-lulc/). config.js can override it from the server's .env.
// "." not "": "/api/..." would point at the host root and miss a sub-path like /act4dws5/diy-lulc/
const API_BASE = (window.CORESTACK_CFG?.apiBase || ".").replace(/\/$/, "");
const api = (path) => API_BASE + path;

// Every API call carries the open project, so the server knows whose scheme to read or change. One
// wrapper around fetch instead of touching every call site. A 401 means the session ran out: back to
// the front page to sign in again.
const _fetch = window.fetch.bind(window);
window.fetch = async (url, opts = {}) => {
  const ours = typeof url === "string" && url.startsWith(API_BASE + "/api/");
  if (ours && PROJECT) opts = { ...opts, headers: { ...(opts.headers || {}), "X-Project-Id": PROJECT.id } };
  const r = await _fetch(url, opts);
  if (ours && r.status === 401 && !url.includes("/api/auth/")) location.href = "./";
  return r;
};

const getJSON = async (url) => (await fetch(url)).json();
const postJSON = async (url, body, method = "POST") => (await fetch(url,
  { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));

// tolerant JSON read: an uncaught server 500 returns a plain-text body, and r.json() throws on that,
// which would strand the "working…" toast forever. Never throw: fall back to a detail we can show.
async function readJson(r) {
  try { return await r.json(); }
  catch { return { detail: `server error (HTTP ${r.status})` }; }
}
const errText = (d, r) => (d && d.detail && (d.detail.message || d.detail)) || `HTTP ${r.status}`;

// Nothing classifies on its own (point 7). An edit leaves the map as it was and raises the banner,
// because running fires the DAG, which should happen because you asked for it.
function markStale(msg) {
  dirty = true;
  updateStale();
  setStatus(`${msg}. Run classification to see it on the map.`, "ok");
}
function updateStale() {
  const noRun = PROJECT && !PROJECT.current_run;
  $("stale").textContent = noRun ? "No run yet. Run classification to draw this project's map."
                                 : "Your scheme changed since the run on the map. Run classification to see it.";
  $("stale").classList.toggle("hidden", !(PROJECT && PROJECT.mine && (noRun || dirty)));
  $("run").classList.toggle("pulse", !!(PROJECT && (noRun || dirty)));
}

// Trigger the DAG through our backend and poll its run till it finishes. Same-origin, so no CORS, and
// the creds stay server-side. Returns the final status object (carries dag_run_id + state) on success.
async function triggerDagAndPoll(conf, { interval = 3000, onState } = {}) {
  const r = await postJSON(api("/api/dag/run"), { conf });
  const start = await readJson(r);
  if (!r.ok) throw new Error(start.detail || `trigger failed (HTTP ${r.status})`);
  const runId = start.dag_run_id;
  while (true) {
    await new Promise((res) => setTimeout(res, interval));
    const pr = await fetch(api(`/api/dag/status?run_id=${encodeURIComponent(runId)}`));
    const s = await readJson(pr);
    if (!pr.ok) throw new Error(s.detail || `poll failed (HTTP ${pr.status})`);
    if (onState) onState(s.state, runId);
    if (s.success) return s;
    if (s.state === "failed") throw new Error(`DAG run ${runId} failed`);
  }
}

// ---------------- tree ----------------
// the source->merge map, so a leaf can show which merge it's been relabelled into (#1)
function mergeOf(cls) { return MERGES.find((m) => (m.sources || []).includes(cls)); }

function renderTree() {
  const box = $("tree"); box.innerHTML = "";
  if (!TREE.root) return;
  const walk = (cls, depth) => {
    const n = TREE[cls];
    const color = n.color || "#666";
    const isLeaf = !(n.children || []).length;
    const tag = n.classifier ? '<span class="tag">model</span>' : n.rule ? '<span class="tag">rule</span>'
              : n.ee_rf ? '<span class="tag">IndiaSAT</span>' : "";
    const mr = isLeaf ? mergeOf(cls) : null;
    const mtag = mr ? `<span class="tag merge" style="color:${mr.color || "#8e44ad"}">→ ${esc(mr.name)}</span>` : "";
    // only leaves can be merge sources, so only leaves get the tick (and only on your own project)
    const chk = isLeaf && cls !== "root" && PROJECT && PROJECT.mine
      ? `<input type="checkbox" class="mchk" data-cls="${cls}"${mergeSel.has(cls) ? " checked" : ""}>` : "";
    const div = document.createElement("div");
    div.className = "node" + (cls === selected ? " sel" : "");
    div.style.paddingLeft = 6 + depth * 14 + "px";
    div.innerHTML = `${chk}<span class="swatch" style="background:${color}"></span>${esc(n.name)}${tag}${mtag}`;
    div.onclick = (e) => { if (!e.target.classList.contains("mchk")) select(cls); };
    const cb = div.querySelector(".mchk");
    if (cb) cb.onchange = () => { cb.checked ? mergeSel.add(cls) : mergeSel.delete(cls); };
    box.appendChild(div);
    (n.children || []).forEach((c) => walk(c, depth + 1));
  };
  walk("root", 0);
  renderMergeNodes(box);
}

// the merge targets, drawn as virtual nodes under the real tree: swatch + sources + an undo ✕ (#1)
function renderMergeNodes(box) {
  if (!MERGES.length) return;
  box.insertAdjacentHTML("beforeend", `<div class="merge-head">Merges</div>`);
  MERGES.forEach((m) => {
    const div = document.createElement("div");
    div.className = "node merge-node";
    div.style.paddingLeft = "6px";
    div.innerHTML = `<span class="swatch" style="background:${m.color || "#8e44ad"}"></span>${esc(m.name)}
      <span class="src">← ${(m.sources || []).map(esc).join(", ")}</span>
      ${PROJECT && PROJECT.mine ? `<button class="rm" data-t="${m.target}" title="undo merge">✕</button>` : ""}`;
    const rm = div.querySelector(".rm");
    if (rm) rm.onclick = () => removeMerge(m.target);
    box.appendChild(div);
  });
}

// the classes you've looked at, so the panel's Back can retrace them
let navStack = [];

function select(cls, { back = false } = {}) {
  if (!back && selected && selected !== cls) navStack.push(selected);
  selected = cls;
  $("selName").textContent = TREE[cls] ? TREE[cls].name : "nothing";
  renderTree();
  renderContext(cls);
  updateDataDist();
}

// Back retraces the classes you opened; with nowhere left to go it closes the panel. ✕ always closes.
function closePanel() {
  navStack = [];
  selected = null;
  $("selName").textContent = "nothing";
  renderTree();
  renderContext(null);
}
$("ctxBack").onclick = () => {
  const prev = navStack.pop();
  if (prev && TREE[prev]) select(prev, { back: true });
  else closePanel();
};
$("ctxClose").onclick = closePanel;

// what feeds a split's model: a child whose samples come from the user's examples (a residual
// "<x>_other" child made by Add draws on the base data instead, so it needs none)
function needsExamples(c) {
  const src = (TREE[c] || {}).source;
  return !src || src.type === "examples";
}
const trainable = (n) => n && (n.children || []).length && !n.rule && !n.ee_rf;

// Someone else's public project: the same panel, read only. It says what the class is and how it was
// made (which zoo model, a rule, an IndiaSAT model, or a split trained here), with the model card one
// click away. None of the editing blocks show.
function renderViewOnly(cls, n) {
  const ctx = $("context");
  ctx.classList.remove("hidden");
  document.body.classList.add("ctx-open");
  setTimeout(() => map.invalidateSize(), 0);
  ["ctxSplit", "ctxRuleSplit", "ctxImprove", "ctxExamples", "ctxMerge", "ctxAdd"]
    .forEach((id) => $(id).classList.add("hidden"));
  $("ctxBack").textContent = "← Close";
  navStack = [];
  $("ctxHead").textContent = n.name;
  const kids = n.children || [];
  const parent = TREE[n.parent];
  const names = (ids) => ids.map((c) => `${swatch(c)} ${esc(TREE[c]?.name || c)}`).join("<br>");
  let what, how = "";
  if (kids.length) {
    what = `Split into ${kids.map((c) => TREE[c]?.name || c).join(" / ")}.`;
    if (n.from_model) how = `Made with the zoo model <b>${esc(n.from_model.name)}</b>.
      <button class="ghost" id="viewCard">See its model card</button>`;
    else if (n.rule) how = "Made with a rule on spectral indices, so no training.";
    else if (n.ee_rf) how = "Made with an IndiaSAT model that runs inside Earth Engine.";
    else if (n.classifier) how = "Trained in this project on its owner's example polygons.";
  } else if (parent && n.parent !== "root") {
    what = `One of the classes the ${parent.name} split decides between.`;
  } else {
    what = `A class of the base map (${PROJECT.base_scheme === "worldcover" ? "WorldCover" : "IndiaSAT"}).`;
  }
  $("ctxWhat").textContent = what;
  const v = $("ctxView");
  v.innerHTML = (kids.length ? `<h3>Classes</h3><div class="hint">${names(kids)}</div>` : "")
    + (how ? `<h3>How it was made</h3><p class="hint">${how}</p>` : "")
    + `<p class="hint">You're viewing a public project. Copy it to your projects to change it.</p>`;
  v.classList.remove("hidden");
  if ($("viewCard")) $("viewCard").onclick = async () => { openZoo(); await showCardFull(n.from_model.card_id); };
}

// The right panel appears once a class is picked and offers only what makes sense for that class
// (points 9, 10). A leaf gets split (zoo model first, own data second); a node with a split gets
// trained or replaced; a leaf inside a split takes examples for its parent. Root isn't refined here:
// the base map is shared by every project.
function renderContext(cls) {
  const ctx = $("context");
  const n = TREE[cls];
  $("ctxView").classList.add("hidden");
  if (n && PROJECT && !PROJECT.mine && cls !== "root") return renderViewOnly(cls, n);
  if (!n || !PROJECT || !PROJECT.mine || cls === "root") {
    ctx.classList.add("hidden");
    document.body.classList.remove("ctx-open");
    setTimeout(() => map.invalidateSize(), 0);
    if (cls === "root" && PROJECT && PROJECT.mine) setStatus("The base map is shared by every project. Pick one of its classes to refine it.");
    return;
  }
  ctx.classList.remove("hidden");
  document.body.classList.add("ctx-open");
  navStack = navStack.filter((c) => TREE[c] && c !== "root" && c !== cls);
  const prev = navStack[navStack.length - 1];
  $("ctxBack").textContent = prev ? `← ${TREE[prev].name}` : "← Close";
  setTimeout(() => map.invalidateSize(), 0);
  const kids = n.children || [];
  const isLeaf = !kids.length;
  const parent = TREE[n.parent];
  const inSplit = isLeaf && parent && n.parent !== "root" && trainable(parent);
  $("ctxHead").textContent = n.name;
  document.querySelectorAll("#context .ctxcls").forEach((s) => (s.textContent = n.name));

  let what;
  if (n.rule) what = `Split by a rule into ${kids.join(" / ")}. Rules need no training.`;
  else if (n.ee_rf) what = `Split by an IndiaSAT model into ${kids.join(" / ")}. It trains inside Earth Engine.`;
  else if (kids.length && n.from_model) what = `Using "${n.from_model.name}" from the zoo. It's ready: ` +
      `run classification to see it. Give every class examples only if you want to train your own instead.`;
  else if (kids.length) what = n.classifier
      ? `A trained split into ${kids.join(" / ")}. Add more examples and train again to improve it.`
      : `Split into ${kids.join(" / ")} but not trained yet. Give every class some examples, then Train.`;
  else what = inSplit ? `One of the classes the ${parent.name} split decides between.`
                      : "Not split yet. Split it into finer classes, or pull a new class out of it.";
  $("ctxWhat").textContent = what;

  const show = (id, on) => $(id).classList.toggle("hidden", !on);
  show("ctxSplit", isLeaf);
  show("ctxRuleSplit", isLeaf);
  show("ctxImprove", kids.length > 0);
  show("ctxExamples", inSplit);
  // inside a split the job is feeding the parent's model, so examples lead; splitting further comes after
  $("ctxExamples").classList.toggle("lead", !!inSplit);
  show("ctxMerge", isLeaf);
  show("ctxAdd", !n.rule && !n.ee_rf);
  // a rule or IndiaSAT split has nothing to train; only replacing it makes sense
  ["dataDist", "exChild", "doRetrain", "metrics"].forEach((id) =>
    $(id).classList.toggle("hidden", !trainable(n)));
  document.querySelectorAll("#ctxImprove > label, #ctxImprove > .row, #ctxImprove > .hint, #ctxImprove > .btn-pair, #ctxImprove > details.opts:first-of-type")
    .forEach((el) => el.classList.toggle("hidden", !trainable(n)));

  if (kids.length) {
    $("exChild").innerHTML = kids.filter(needsExamples)
      .map((c) => `<option value="${c}">${esc(TREE[c].name)}</option>`).join("");
  }
  if (inSplit) $("exParent").textContent = parent.name;
  if (kids.length) $("exChild").onchange();          // the counter-example tick names the class it's about
  $("addHead").textContent = isLeaf ? `Pull a new class out of ${n.name}` : `Add another class to this split`;
  $("addHint").textContent = isLeaf
    ? `${n.name} becomes “${n.name} (rest)” plus the new class; you mark examples of the new one.`
    : `It joins ${kids.join(" / ")}; give it examples, then train again.`;
  updateTesseraAvailability();
}

// Tessera training is offered only when the area sits inside one of the prepared sites (#16)
function updateTesseraAvailability() {
  const row = $("embeddingRow");
  if (!row) return;
  const bb = currentBbox();
  const inSite = bb && Object.values(TESSERA_SITES).some((s) => bboxOverlap(s, bb));
  row.classList.toggle("hidden", !inSite);
  if (!inSite && $("embedding")) $("embedding").value = "ae";
  refreshModelFamilies();
}

// #1/#7: the algorithm dropdown is driven by the inference data — Alpha Earth offers the linear
// models (band math -> crisp tiles) plus Random Forest (point-grid render); Tessera-local adds more.
async function refreshModelFamilies() {
  const algo = $("algo"); if (!algo) return;
  const src = ($("embedding") && $("embedding").value === "tessera") ? "tessera" : "alphaearth";
  let fams;
  try { fams = (await getJSON(api(`/api/model-families?source=${src}`))).families; }
  catch { return; }
  const keep = algo.value;
  algo.innerHTML = "";
  fams.forEach((f) => {
    const o = new Option(f.label + (f.available ? "" : " (unavailable)"), f.id);
    if (!f.available) o.disabled = true;
    if (f.note) o.title = f.note;
    algo.add(o);
  });
  algo.value = [...algo.options].some((o) => o.value === keep && !o.disabled) ? keep : "linearsvc";
}

// ---------------- operations / schema view (#13) ----------------
function setLeftView(mode) {
  viewMode = mode;
  const ops = mode === "ops";
  $("tree").classList.toggle("hidden", ops);
  $("ops").classList.toggle("hidden", !ops);
  $("viewHier").classList.toggle("sel", !ops);
  $("viewOps").classList.toggle("sel", ops);
  if (ops) renderOps();
}

// the class an operation acts on, so clicking a step can open the right panel there
function opTargetNode(e) {
  const a = e.args || {};
  if (["split", "add", "rule_split"].includes(e.op)) return a.parent;
  if (["retrain", "apply", "apply_eerf", "upload"].includes(e.op)) return a.node;
  return null;
}

// a short human line for one op, from its args/result
function opSummary(e) {
  const a = e.args || {};
  const names = (cs) => (cs || []).map((c) => (typeof c === "string" ? c : c.name)).join(" / ");
  switch (e.op) {
    case "create":        return `${a.name} · ${a.year} · ${a.base_scheme}`;
    case "split":         return `${a.parent} → ${names(a.children)}${a.from ? " (from upload)" : ""}`;
    case "rule_split":    return `${a.parent} → ${names(a.classes)}`;
    case "add":           return `${a.name} under ${a.parent}`;
    case "upload":        return `${a.file || "file"} → ${Object.keys(a.classes || {}).join(" / ")}`;
    case "retrain":       return `${a.node}${a.years && a.years.length ? " · years " + a.years.join("/") : ""}`
                                 + `${a.balance && a.balance !== "balanced" ? " · " + a.balance : ""}`;
    case "merge":         return `${(a.sources || []).join(" + ")} → ${a.name || a.target}`;
    case "merge_remove":  return `undo ${a.target}`;
    case "apply":         return `${a.card_id}${a.node ? " → " + a.node : ""}`;
    case "apply_eerf":    return `${a.card_id} → ${a.node}`;
    case "base_select":   return `scheme → ${a.scheme}`;
    case "reset":         return `to ${a.scheme}`;
    default:              return "";
  }
}

async function renderOps() {
  const box = $("ops");
  let ops = [];
  try { ops = (await getJSON(api(`/api/oplog?since=0`))).ops || []; } catch { ops = []; }
  if (!ops.length) { box.innerHTML = `<p class="hint">No steps yet.</p>`; return; }
  box.innerHTML = "";
  ops.forEach((e, i) => {
    const node = opTargetNode(e);
    const div = document.createElement("div");
    div.className = "op-row" + (node && node === selected ? " sel" : "") + (node ? "" : " noclick");
    div.innerHTML = `<span class="op-seq">${i + 1}</span>
      <span class="op-verb v-${e.op}">${e.op.replace("_", " ")}</span>
      <span class="op-sum">${esc(opSummary(e))}</span>`;
    if (node) div.onclick = () => { if (TREE[node]) select(node); renderOps(); };
    box.appendChild(div);
  });
}

// live "data so far" for the split being trained: per-class counts + a balance guideline, shown
// right where the user adds data. Also decides whether Train is ready: every class that learns from
// examples needs at least one.
async function updateDataDist() {
  const box = $("dataDist");
  const node = TREE[selected];
  if (!box || !node || !(node.children || []).length) { if (box) box.innerHTML = ""; return; }
  const sibs = node.children.filter(needsExamples);
  let sum = {};
  try { sum = await getJSON(api("/api/examples/summary")); } catch { return; }
  const rows = sibs.map((c) => ({ c, n: (sum[c] || {}).positive || 0, neg: (sum[c] || {}).negative || 0 }));
  const missing = rows.filter((r) => r.n === 0).map((r) => TREE[r.c].name);
  $("doRetrain").disabled = missing.length > 0;
  $("doRetrain").textContent = node.from_model ? "Train your own" : node.classifier ? "Train again" : "Train";
  const max = Math.max(1, ...rows.map((r) => r.n));
  const bars = rows.map((r) =>
    `<div class="dd-row"><span class="sw" style="background:${COLORS[r.c] || "#888"}"></span>
      <span class="dd-name">${esc(TREE[r.c].name)}</span>
      <span class="dd-bar"><i style="width:${Math.round(100 * r.n / max)}%"></i></span>
      <span class="dd-n">${r.n}${r.neg ? ` <small>−${r.neg}</small>` : ""}</span></div>`).join("");
  let hint, col;
  // a zoo model already works, so missing examples are optional here, not a warning
  if (missing.length && node.from_model) { hint = "none needed: the zoo model is in use. Add examples to every class to train your own."; col = "#6f7468"; }
  else if (missing.length) { hint = `needs examples for ${missing.join(", ")} before it can train.`; col = "#b4791f"; }
  else {
    const counts = rows.map((r) => r.n);
    const ratio = Math.max(...counts) / Math.max(1, Math.min(...counts));
    if (ratio <= 3) { hint = `ready to train (balanced, ${ratio.toFixed(1)}:1).`; col = "#2f6b3f"; }
    else if (ratio <= 5) { hint = `ready (mild imbalance ${ratio.toFixed(1)}:1, class weighting handles it).`; col = "#b4791f"; }
    else { hint = `ready, but imbalanced (${ratio.toFixed(1)}:1); oversample under Model options.`; col = "#a23b2f"; }
  }
  box.innerHTML = `<div class="dd-title">Examples so far (polygons)</div>${bars}
    <div class="dd-hint" style="color:${col}">${hint}</div>`;
}

async function refreshTree(data) {
  data = data || await getJSON(api("/api/tree"));
  if (!data.tree) return;
  TREE = data.tree; COLORS = data.colors || COLORS;
  if (data.op_seq != null) currentOpSeq = data.op_seq;
  if (selected && !TREE[selected]) selected = null;
  await loadMerges();
  renderContext(selected);
  updateDataDist();
  if (viewMode === "ops") renderOps();
}

// the active merges feed the tree (source tags + virtual nodes). Drop ticks for leaves that no
// longer exist so a stale selection can't leak into the next merge.
async function loadMerges() {
  try { MERGES = (await getJSON(api("/api/merge"))).rules || []; } catch { MERGES = []; }
  for (const c of [...mergeSel]) if (!TREE[c] || (TREE[c].children || []).length) mergeSel.delete(c);
  renderTree();
}

// ---------------- init: who's here, then start screen or a project ----------------
async function init() {
  const me = await (await _fetch(api("/api/auth/me"))).json();
  ME = me.user;
  const pid = new URLSearchParams(location.search).get("project");
  // signed out: only a public project's link gets you in (view only); anything else goes to sign-in
  if (!ME && !pid) { location.href = "./"; return; }
  if (ME) {
    const who = `${esc(ME.name)} <a href="#" class="signOut">sign out</a>`;
    $("whoami").innerHTML = who;
    $("startWho").innerHTML = who;
    document.querySelectorAll(".signOut").forEach((a) => a.onclick = async (e) => {
      e.preventDefault();
      await postJSON(api("/api/auth/logout"), {});
      location.href = "./";
    });
  } else {
    $("whoami").innerHTML = `<a href="./">sign in</a>`;
    $("switchProject").classList.add("hidden");
  }
  PRESETS = (await getJSON(api("/api/presets"))).presets;
  const years = [];
  for (let y = 2024; y >= 2017; y--) years.push(y);
  for (const id of ["npYear", "projYear"]) $(id).innerHTML = years.map((y) => `<option>${y}</option>`).join("");
  $("npPreset").innerHTML = Object.keys(PRESETS).map((k) => `<option>${esc(k)}</option>`).join("");
  await refreshZooBadge();
  try { TESSERA_SITES = (await getJSON(api("/api/tessera-sites"))).sites || {}; } catch { /* best-effort */ }
  try { STANDARDS = await getJSON(api("/api/standards")); } catch { /* best-effort */ }
  try { INFER_OPTS = await getJSON(api("/api/inference-options")); } catch { /* best-effort */ }
  await loadRuleRegistry();
  if ($("embedding")) $("embedding").onchange = refreshModelFamilies;
  await refreshModelFamilies();
  if (pid) await openProject(pid);
  else showStart();
}

// ---------------- start screen: new project or open one (point 9) ----------------
async function showStart() {
  closeProject();
  $("start").classList.remove("hidden");
  document.body.classList.add("on-start");
  history.replaceState(null, "", location.pathname);
  updateNewArea();
  const row = (p, pub) => `<div class="prow" data-id="${p.id}">
      <div class="prow-name">${esc(p.name)}${p.is_public && !pub ? ' <span class="pill pub">public</span>' : ""}</div>
      <div class="prow-meta">${pub ? esc(p.owner_name) + " · " : ""}${p.year} · ${p.base_scheme} ·
        ${p.current_run ? `${p.current_run} run${p.current_run > 1 ? "s" : ""}` : "not run yet"} · ${ago(p.updated_at)}</div>
    </div>`;
  const mine = (await getJSON(api("/api/projects"))).projects || [];
  $("myProjects").innerHTML = mine.length ? mine.map((p) => row(p, false)).join("")
    : `<p class="hint">None yet. Start one on the left.</p>`;
  const pub = ((await getJSON(api("/api/projects/public"))).projects || []).filter((p) => !p.mine);
  $("pubProjects").innerHTML = pub.length ? pub.map((p) => row(p, true)).join("")
    : `<p class="hint">Nobody has made a project public yet.</p>`;
  document.querySelectorAll("#start .prow").forEach((el) => el.onclick = () => openProject(el.dataset.id));
}

// "3 days ago", falling back to a date past a week (Susmit's past-runs list does the same)
function ago(iso) {
  if (!iso) return "";
  // the DB hands back naive UTC ("…T10:00:00"), run.json an offset ("…+00:00"); only the first needs a Z
  const d = new Date(/(Z|[+-]\d\d:\d\d)$/.test(iso) ? iso : iso + "Z");
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  const days = Math.round(mins / 1440);
  return days < 7 ? `${days} day${days > 1 ? "s" : ""} ago` : d.toLocaleDateString();
}

function updateNewArea() {
  const bb = currentBbox();
  drawAoi();
  const ok = bboxValid(bb);
  if (ok) {
    map.fitBounds([[bb[1], bb[0]], [bb[3], bb[2]]], { maxZoom: 14 });
    const km2 = bboxAreaKm2(bb);
    const over = km2 > AOI_TILE_CAP_KM2;
    const what = { preset: "Preset", coords: "Box", draw: "Drawn box" }[areaMode];
    $("npArea").textContent = `${what} · ≈ ${km2.toLocaleString(undefined, { maximumFractionDigits: 1 })} km²`
      + (over ? ` — over the ${AOI_TILE_CAP_KM2.toLocaleString()} km² limit` : "");
    $("npArea").classList.toggle("warn", over);
    $("npCreate").disabled = over;
  } else {
    $("npArea").textContent = areaMode === "draw" ? "No box yet: pick Draw on map again to drag one."
                                                  : "Enter a valid latitude, longitude and size.";
    $("npArea").classList.remove("warn");
    $("npCreate").disabled = true;
  }
  $("npBaseHint").textContent = $("npBase").value === "worldcover"
    ? "Trees, shrubland, grassland, cropland, built-up, bare, water."
    : "Greenery, water, built-up, barren.";
}
function setAreaMode(mode) {
  areaMode = mode;
  document.querySelectorAll("#npAreaMode button").forEach((b) => b.classList.toggle("sel", b.dataset.mode === mode));
  $("npModePreset").classList.toggle("hidden", mode !== "preset");
  $("npModeCoords").classList.toggle("hidden", mode !== "coords");
  if (mode === "draw") startAreaPick();
  else updateNewArea();
}
document.querySelectorAll("#npAreaMode button").forEach((b) => b.onclick = () => setAreaMode(b.dataset.mode));
["npLat", "npLon", "npKm"].forEach((id) => $(id).oninput = updateNewArea);
$("npPreset").onchange = updateNewArea;
$("npBase").onchange = updateNewArea;
function startAreaPick() {
  pickingArea = true;
  $("start").classList.add("hidden");
  $("drawBar").classList.remove("hidden");
}
function endAreaPick() {
  pickingArea = false;
  $("drawBar").classList.add("hidden");
  $("start").classList.remove("hidden");
  if (!newBbox) setAreaMode("preset");     // cancelled without a box: back where we were
  else updateNewArea();
}
$("drawCancel").onclick = endAreaPick;

$("npCreate").onclick = async () => {
  const bb = currentBbox();
  if (!bboxValid(bb)) { setStatus("Pick or draw an area first.", "err"); return; }
  const name = $("npName").value.trim() || (areaMode === "preset" ? $("npPreset").value : "My area");
  setStatus("Creating the project…", "work");
  $("npCreate").disabled = true;
  try {
    const r = await postJSON(api("/api/projects"),
      { name, bbox: bb, year: Number($("npYear").value), base_scheme: $("npBase").value });
    const d = await readJson(r);
    if (!r.ok) { setStatus("Couldn't create it: " + errText(d, r), "err"); return; }
    newBbox = null; $("npName").value = ""; setAreaMode("preset");
    await openProject(d.id);
    setStatus(`Created “${d.name}”. Pick a class to refine, or run it as it is.`, "ok");
  } finally { $("npCreate").disabled = false; }
};

// ---------------- the open project ----------------
function closeProject() {
  navStack = [];
  PROJECT = null; RUN_META = null; TREE = {}; MERGES = []; selected = null; dirty = false;
  clearOverlay();
  drawnLayer.clearLayers(); lastGeometry = null;
  if (extentLayer) { map.removeLayer(extentLayer); extentLayer = null; }
  ["projHead", "runBox", "hierBox", "context"].forEach((id) => $(id).classList.add("hidden"));
  document.body.classList.remove("ctx-open");
  renderTree();
}

async function openProject(pid) {
  const r = await _fetch(api(`/api/projects/${pid}`));
  const d = await readJson(r);
  if (!r.ok) { setStatus("Can't open that project: " + errText(d, r), "err"); showStart(); return; }
  closeProject();                        // nothing of the last project may linger on the map
  PROJECT = d;
  $("start").classList.add("hidden");
  document.body.classList.remove("on-start");
  history.replaceState(null, "", `${location.pathname}?project=${pid}`);
  ["projHead", "runBox", "hierBox"].forEach((id) => $(id).classList.remove("hidden"));
  renderProjectHead();
  selected = null;
  await refreshTree(d);
  drawAoi();
  const [w, s, e, n] = PROJECT.bbox;
  map.fitBounds([[s, w], [n, e]]);
  renderRuns();
  dirty = false;
  if (PROJECT.current_run) await showRun(PROJECT.current_run, true);   // no re-run needed
  updateStale();
}

function renderProjectHead() {
  const p = PROJECT;
  const km2 = bboxAreaKm2(p.bbox).toLocaleString(undefined, { maximumFractionDigits: 0 });
  $("projName").textContent = p.name;
  $("projMeta").textContent = `${km2} km² · starts from ${p.base_scheme === "worldcover" ? "WorldCover" : "IndiaSAT"}`;
  $("projYear").value = String(p.year);
  $("projPublic").value = p.is_public ? "1" : "0";
  // someone else's public project: look, download, copy; nothing that writes
  const ro = !p.mine;
  $("readOnly").classList.toggle("hidden", !ro);
  ["projYear", "projPublic"].forEach((id) => ($(id).disabled = ro));
  ["run", "startFresh", "dlProject"].forEach((id) => $(id).classList.toggle("hidden", ro));
  $("eyeToggle").classList.toggle("hidden", false);
}

$("switchProject").onclick = showStart;
$("projYear").onchange = async () => {
  const r = await postJSON(api(`/api/projects/${PROJECT.id}`), { year: Number($("projYear").value) }, "PATCH");
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  PROJECT = { ...PROJECT, ...d };
  markStale(`Year set to ${PROJECT.year}`);
};
$("projPublic").onchange = async () => {
  const on = $("projPublic").value === "1";
  const r = await postJSON(api(`/api/projects/${PROJECT.id}`), { is_public: on }, "PATCH");
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  PROJECT = { ...PROJECT, ...d };
  setStatus(on ? "Public: anyone can view it and its runs, and signed-in users can copy it."
               : "Private again: only you can see it.", "ok");
};
$("copyProject").onclick = async () => {
  const r = await postJSON(api(`/api/projects/${PROJECT.id}/copy`), {});
  const d = await readJson(r);
  if (!r.ok) { setStatus("Couldn't copy: " + errText(d, r), "err"); return; }
  await openProject(d.id);
  setStatus(`Copied into your projects as “${d.name}”.`, "ok");
};

function renderRuns() {
  const runs = [...(PROJECT.runs || [])].reverse();
  $("runsList").innerHTML = runs.length ? runs.map((r) =>
    `<div class="run-item${RUN_META && RUN_META.run === r.run ? " sel" : ""}" data-n="${r.run}">
       <span>${esc(r.name)}</span><span class="rmeta">${r.year} · ${ago(r.created_at)}</span></div>`).join("")
    : `<p class="hint">No runs yet.</p>`;
  document.querySelectorAll(".run-item").forEach((el) => el.onclick = () => showRun(Number(el.dataset.n)));
  $("dlTif").disabled = !RUN_META;
}

// ---------------- runs: classify on purpose, keep every run ----------------
// Run starts the DAG when Airflow is wired (it exports the GEE asset in the background) and records the
// run straight away; without Airflow it just records it. Either way the map comes from the run we stored.
async function runClassify() {
  if (!PROJECT) return;
  $("run").disabled = true;
  // a run is 30-60 s of Earth Engine work with nothing to show; a ticking clock says it hasn't hung
  const t0 = Date.now();
  let phase = "Classifying in Earth Engine";
  const tick = () => setStatus(`${phase}… ${Math.round((Date.now() - t0) / 1000)} s (usually under a minute)`, "work");
  tick();
  const ticker = setInterval(tick, 1000);
  try {
    let dagRunId = null;
    if (window.CORESTACK_CFG?.airflow) {
      // Airflow exports the run as a GEE asset for the catalogue. That export sits in Earth Engine's
      // queue for 10-20 minutes, and the map doesn't need it (it draws from live tiles), so the run is
      // saved now and the export is watched in the background
      const conf = { region: PROJECT.bbox, year: String(PROJECT.year), base_scheme: PROJECT.base_scheme,
                     project_id: PROJECT.id, execution_type: "fullexec" };
      const r = await postJSON(api("/api/dag/run"), { conf });
      const start = await readJson(r);
      if (!r.ok) throw new Error(start.detail || `couldn't start the Airflow run (HTTP ${r.status})`);
      dagRunId = start.dag_run_id;
      phase = "Saving the run";
    }
    const r = await postJSON(api(`/api/projects/${PROJECT.id}/runs`), { dag_run_id: dagRunId });
    const d = await readJson(r);
    clearInterval(ticker);
    if (!r.ok) { setStatus("Run failed: " + errText(d, r), "err"); return; }
    PROJECT.current_run = d.run.run;
    PROJECT.runs = [...(PROJECT.runs || []), { run: d.run.run, name: d.run.name, created_at: d.run.created_at, year: d.run.year }];
    RUN_META = d.run;
    drawResult(d);
    dirty = false;
    updateStale();
    renderRuns();
    setStatus(`${d.run.name} saved.${countsLine(d.counts)}`, "ok");
    if (dagRunId) watchExport(dagRunId, d.run.name);
  } catch (err) { clearInterval(ticker); setStatus("Error: " + err, "err"); }
  finally { clearInterval(ticker); $("run").disabled = false; }
}
$("run").onclick = runClassify;

// the catalogue export of a run, followed quietly: only a failure interrupts, since the map is already
// saved. Gives up watching after an hour (the export itself carries on in Airflow either way)
async function watchExport(runId, runName) {
  const until = Date.now() + 60 * 60 * 1000;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 15000));
    let s;
    try { s = await getJSON(api(`/api/dag/status?run_id=${encodeURIComponent(runId)}`)); } catch { continue; }
    if (s.success) { console.log(`[dag] ${runId}: catalogue export done`); return; }
    if (s.state === "failed") {
      setStatus(`${runName}'s catalogue export failed in Airflow (${runId}). The map and the run are fine.`, "err");
      return;
    }
  }
}

// redraw a saved run from its frozen scheme (the server keeps one per run), no re-run needed
async function showRun(n, quiet = false) {
  setStatus(`Loading run ${n}…`, "work");
  const r = await fetch(api(`/api/projects/${PROJECT.id}/runs/${n}`));
  const d = await readJson(r);
  if (!r.ok) { setStatus("Couldn't load that run: " + errText(d, r), "err"); return; }
  RUN_META = d.run;
  drawResult(d);
  // a visitor can't edit, so their tree should match the map they're looking at: the run's own classes
  if (!PROJECT.mine && d.run_tree) { TREE = d.run_tree; COLORS = d.colors || COLORS; renderTree(); }
  // the latest run tells us whether the scheme moved on since
  if (n === PROJECT.current_run) dirty = d.run.op_seq !== currentOpSeq || d.run.year !== PROJECT.year;
  updateStale();
  renderRuns();
  setStatus(quiet ? `Showing ${d.run.name}, the latest run.${countsLine(d.counts)}` : `Showing ${d.run.name}.${countsLine(d.counts)}`, "ok");
}

function countsLine(counts) {
  if (!counts) return "";
  const tot = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([k, v]) => `${k} ${Math.round(100 * v / tot)}%`).join(", ");
  return top ? ` ${top}.` : "";
}

function clearOverlay() {
  predLayer.clearLayers();
  if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
  showLegend(null);
}

// the legend for whatever run is on the map: its own classes, colours and shares, biggest first
const legendCtl = L.control({ position: "bottomright" });
legendCtl.onAdd = () => { const d = L.DomUtil.create("div", "map-legend"); L.DomEvent.disableClickPropagation(d); return d; };
function showLegend(data) {
  const counts = data && data.counts;
  if (!counts || !Object.keys(counts).length) { legendCtl.remove(); return; }
  const colors = data.colors || COLORS;
  const tot = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<div class="lg-row"><span class="sw" style="background:${colors[k] || "#999"}"></span>
       <span class="lg-name">${esc((TREE[k] || {}).name || k.replace(/_/g, " "))}</span>
       <span class="lg-pct">${(100 * v / tot).toFixed(v / tot < 0.01 ? 1 : 0)}%</span></div>`).join("");
  legendCtl.addTo(map);
  legendCtl.getContainer().innerHTML = `<div class="lg-title">${esc((data.run && data.run.name) || "This run")}</div>${rows}`;
}

function drawResult(data) {
  clearOverlay();
  const [w, s, e, n] = (data.run && data.run.bbox) || PROJECT.bbox;
  if (data.render === "tiles") {
    rasterLayer = L.tileLayer(data.tile_url, { opacity: 0.7, bounds: [[s, w], [n, e]] }).addTo(map);
  } else if (data.render === "raster") {
    const [bw, bs, be, bn] = data.bounds;
    rasterLayer = L.imageOverlay(data.image_url, [[bs, bw], [bn, be]], { opacity: 0.7 }).addTo(map);
  } else if (data.cells) {
    const cw = data.cell_w / 2, ch = data.cell_h / 2;
    data.cells.forEach((c) => L.rectangle([[c.lat - ch, c.lon - cw], [c.lat + ch, c.lon + cw]],
      { stroke: false, fillOpacity: 0.55, fillColor: data.colors[c.pred] || "#999" }).addTo(predLayer));
  }
  overlayVisible = true;
  $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off");
  showLegend(data);
}

// ---------------- IndiaSAT EE-native RF models (#13 wk10) ----------------
// tree/crop (SAR) and farm/shrub (Alpha Earth, per-AEZ) both train + classify in Earth Engine. Their
// class names are fixed by the model, so the mapping step shows them without renaming.
async function useEeRfModel(cardId, targetNode) {
  const c = await getJSON(api(`/api/cards/${cardId}`));
  const parent = (targetNode && TREE[targetNode] && targetNode !== "root") ? targetNode
                 : (c.recommendation && c.recommendation.apply_after) || "greenery";
  const pname = (TREE[parent] || {}).name || parent;
  setStatus(`Applying "${c.name}" to ${pname}…`, "work");
  try {
    const r = await postJSON(api("/api/apply-eerf"), { card_id: cardId, parent });
    const d = await readJson(r);
    if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
    closeZoo();
    await refreshTree(d);
    select(parent);
    markStale(`Applied "${c.name}" to ${pname}`);
  } catch (err) { setStatus("Apply error: " + err, "err"); }
}

// ---------------- overlay eye-toggle (#21) ----------------
let overlayVisible = true;
function applyOverlayVisibility() {
  const layers = [rasterLayer, predLayer].filter(Boolean);
  layers.forEach((l) => (overlayVisible ? l.addTo(map) : map.removeLayer(l)));
  $("eyeToggle").textContent = overlayVisible ? "👁" : "🚫";
  $("eyeToggle").classList.toggle("off", !overlayVisible);
}
$("eyeToggle").onclick = () => { overlayVisible = !overlayVisible; applyOverlayVisibility(); };

// ---------------- downloads: the run's GeoTIFF, the whole project ----------------
// the session cookie rides along, and the server saves the GeoTIFF into the run folder
// the first time, so the second download is a file read, not an Earth Engine export
$("dlTif").onclick = async () => {
  if (!RUN_META) return;
  if (bboxAreaKm2(PROJECT.bbox) > AOI_GEOTIFF_CAP_KM2) {
    setStatus(`GeoTIFF download works up to ${AOI_GEOTIFF_CAP_KM2} km²; this project is ${Math.round(bboxAreaKm2(PROJECT.bbox))} km². The map and the project zip still work.`, "err");
    return;
  }
  setStatus("Preparing the GeoTIFF (first time takes a minute)…", "work");
  // fetched rather than followed, so the page knows when it's done (or why it failed) and says so
  const r = await fetch(api(`/api/projects/${PROJECT.id}/runs/${RUN_META.run}/geotiff`));
  if (!r.ok) {
    const d = (await readJson(r)).detail;
    setStatus(`GeoTIFF failed: ${typeof d === "string" ? d : JSON.stringify(d)}`, "err");
    return;
  }
  const name = (r.headers.get("content-disposition") || "").match(/filename="?([^";]+)/)?.[1]
    || `run_${RUN_META.run}.tif`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus(`Saved ${name}.`, "ok");
};
$("dlProject").onclick = () => { location.href = api(`/api/projects/${PROJECT.id}/download`); };

// STACD provenance (#4): STAC Item + DAG describing how the current output was produced.
$("exportStacd").onclick = async () => {
  setStatus("Building STACD provenance…", "work");
  try {
    const [w, s, e, n] = PROJECT.bbox;
    const doc = await getJSON(api(`/api/stacd?west=${w}&south=${s}&east=${e}&north=${n}&year=${PROJECT.year}&since=0`));
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "output.stacd.json";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("Downloaded STACD provenance (STAC Item + DAG + model locations).", "ok");
  } catch (err) { setStatus("STACD export failed: " + err, "err"); }
};

// ---------------- examples ----------------
async function addDrawn(node, role) {
  if (!lastGeometry) { setStatus("Draw a polygon on the map first (⬠, top left).", "err"); return; }
  try {
    const r = await postJSON(api("/api/examples"), { node, geometry: lastGeometry, role });
    const d = await readJson(r);
    if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
    setStatus(`Added to “${TREE[node].name}” (${d.total} now).`, "ok");
    drawnLayer.clearLayers(); lastGeometry = null;
    await updateDataDist();
  } catch (err) { setStatus("Add example failed: " + err, "err"); }
}
// examples by default; the tick marks counter-examples ("these are NOT <class>") and clears itself
// after each add, so nobody keeps feeding negatives by accident
const roleOf = (box) => { const r = $(box).checked ? "negative" : "positive"; $(box).checked = false; return r; };
$("addDrawn").onclick = () => addDrawn($("exChild").value, roleOf("role"));
$("addDrawnLeaf").onclick = () => addDrawn(selected, roleOf("roleLeaf"));
$("exChild").onchange = () => { $("roleCls").textContent = (TREE[$("exChild").value] || {}).name || "it"; };
$("gotoParent").onclick = () => { const p = TREE[selected] && TREE[selected].parent; if (p) select(p); };

// the standard-format upload: the file's classes become the selected class's children (a new split,
// or extra classes on an existing one) and every polygon lands on its class
async function uploadLabelled(input) {
  const f = input.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f); fd.append("node", selected);
  setStatus(`Reading ${f.name}…`, "work");
  try {
    const r = await fetch(api("/api/examples/labelled"), { method: "POST", body: fd });
    const d = await readJson(r);
    if (!r.ok) { setStatus("Upload rejected: " + errText(d, r), "err"); return; }
    await refreshTree(d);
    select(selected);
    const got = Object.entries(d.classes).map(([k, v]) => `${k} ${v}`).join(", ");
    // new data changes nothing on the map until it's trained, so the next step named here is Train
    setStatus(`${f.name}: ${got}${d.created.length ? ` (new: ${d.created.join(", ")})` : ""}. Train when ready.`, "ok");
  } catch (err) { setStatus("Upload failed: " + err, "err"); }
  finally { input.value = ""; }
}
// polygons of ONE class (GeoJSON or KML, no `class` needed): the old per-class upload, kept for
// files people already have
async function uploadForClass(input, node, role) {
  const f = input.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f); fd.append("node", node); fd.append("role", role);
  setStatus(`Uploading ${f.name} to “${TREE[node].name}”…`, "work");
  try {
    const r = await fetch(api("/api/examples/upload"), { method: "POST", body: fd });
    const d = await readJson(r);
    if (!r.ok) { setStatus("Upload rejected: " + errText(d, r), "err"); return; }
    setStatus(`${f.name}: “${TREE[node].name}” now has ${d.total} polygons.`, "ok");
    await updateDataDist();
  } catch (err) { setStatus("Upload failed: " + err, "err"); }
  finally { input.value = ""; }
}

// does this file carry a `class` on its polygons? then it's the standard format and fills every class;
// otherwise it's one class's polygons. KML never carries our property, so it's always the latter.
async function isLabelled(file) {
  if (/\.kml$/i.test(file.name)) return false;
  try {
    const fc = JSON.parse(await file.text());
    return (fc.features || []).some((f) => f.properties && f.properties.class);
  } catch { return false; }
}

$("uploadLabelled").onchange = () => uploadLabelled($("uploadLabelled"));
$("uploadMore").onchange = async () => {
  const f = $("uploadMore").files[0];
  if (!f) return;
  if (await isLabelled(f)) uploadLabelled($("uploadMore"));
  else uploadForClass($("uploadMore"), $("exChild").value, roleOf("role"));
};
$("uploadLeaf").onchange = () => uploadForClass($("uploadLeaf"), selected, roleOf("roleLeaf"));

// resume a saved project (the zip this app downloads, or an older project.json) as a new project
$("importProject").onchange = async () => {
  const input = $("importProject"), f = input.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  setStatus(`Importing ${f.name}…`, "work");
  try {
    const r = await fetch(api("/api/projects/import"), { method: "POST", body: fd });
    const d = await readJson(r);
    if (!r.ok) {
      const det = d.detail || {};
      setStatus("Can't import it: " + ((det.errors || []).join(" · ") || det.message || det), "err");
      return;
    }
    await openProject(d.id);
    const miss = (d.missing_classifiers || []).length
      ? ` ${d.missing_classifiers.length} split(s) need training again: ${d.missing_classifiers.join(", ")}.` : "";
    setStatus(`Imported “${d.name}”.${miss}`, miss ? "info" : "ok");
  } catch (err) { setStatus("Import failed: " + err, "err"); }
  finally { input.value = ""; }
};
$("fmtToggle").onclick = (e) => { e.preventDefault(); $("fmtHelp").classList.toggle("hidden"); };

// ---------------- operations ----------------
$("doSplit").onclick = async () => {
  const names = $("splitNames").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (names.length < 2) { setStatus("Give at least two class names, comma separated.", "err"); return; }
  const r = await postJSON(api("/api/split"), { parent: selected, children: names.map((name) => ({ name })) });
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  $("splitNames").value = "";
  await refreshTree(d);
  select(selected);
  setStatus(`Split “${TREE[selected].name}”. Now draw examples of each class, then Train.`, "ok");
};

// ---------------- rule-based split (#12) ----------------
let RULE_VARS = {};
async function loadRuleRegistry() {
  try { RULE_VARS = (await getJSON(api("/api/rules/registry"))).variables || {}; }
  catch { return; }
  const sel = $("ruleVar"); if (!sel) return;
  sel.innerHTML = "";
  Object.entries(RULE_VARS).forEach(([id, v]) => sel.add(new Option(v.label, id)));
  sel.onchange = showRuleVarDesc;
  showRuleVarDesc();
}
function showRuleVarDesc() {
  const v = RULE_VARS[$("ruleVar").value];
  if ($("ruleVarDesc")) $("ruleVarDesc").textContent = v ? v.describe : "";
}
function buildRule() {
  const trueCls = $("ruleTrue").value.trim(), falseCls = $("ruleFalse").value.trim();
  if (!trueCls || !falseCls) throw new Error("Name the class for both the true and the otherwise case.");
  const raw = $("ruleExpr").value.trim();
  const when = raw || `${$("ruleVar").value} ${$("ruleOp").value} ${$("ruleThresh").value}`;
  return { clauses: [{ when, class: trueCls }], default: falseCls };
}
$("doRuleSplit").onclick = async () => {
  let rule;
  try { rule = buildRule(); } catch (e) { setStatus(e.message, "err"); return; }
  const r = await postJSON(api("/api/split/rule"), { parent: selected, rule });
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  $("ruleTrue").value = ""; $("ruleFalse").value = ""; $("ruleExpr").value = "";
  await refreshTree(d);
  select(selected);
  markStale(`Rule split “${TREE[selected].name}” → ${d.classes.join(" / ")}`);
};

$("doAdd").onclick = async () => {
  const name = $("addName").value.trim();
  if (!name) { setStatus("Enter a class name.", "err"); return; }
  const r = await postJSON(api("/api/add"), { parent: selected, name });
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  $("addName").value = "";
  await refreshTree(d);
  select(selected);
  setStatus(`Added “${name}”. Draw examples of it, then Train.`, "ok");
};

$("doRetrain").onclick = async () => {
  const btn = $("doRetrain");
  const years = ($("trainYears").value.match(/\d{4}/g) || []).map(Number);
  const yearList = years.length ? years : [PROJECT.year];
  btn.disabled = true; btn.textContent = "Training… (sampling + fitting)";
  $("metrics").textContent = "";
  const embedding = ($("embedding") && !$("embeddingRow").classList.contains("hidden")) ? $("embedding").value : "ae";
  const est = await fetchEstimate($("algo").value);
  const node = selected;
  const stopTimer = startWorkTimer(`Training “${TREE[node].name}”`, est);
  const params = { node, balance: $("balance").value, years: yearList, algo: $("algo").value, embedding };
  try {
    const r = await postJSON(api("/api/retrain"), params);
    stopTimer();
    const d = await readJson(r);
    if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
    await refreshTree(d);
    select(node);
    $("metrics").textContent = formatReport(d.report, d.n_test);
    markStale(`Trained “${TREE[node].name}”`);
  } catch (err) { stopTimer(); setStatus("Error: " + err, "err"); }
  finally { btn.disabled = false; updateDataDist(); }
};

// ---------------- merge classes (#9) ----------------
$("doMerge").onclick = async () => {
  const sources = [...mergeSel];
  const name = $("mergeName").value.trim();
  if (sources.length < 2) { setStatus("Tick at least two classes in the tree to merge.", "err"); return; }
  if (!name) { setStatus("Name the merged class.", "err"); return; }
  const r = await postJSON(api("/api/merge"), { name, sources, color: $("mergeColor").value });
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return; }
  $("mergeName").value = "";
  mergeSel.clear();
  await refreshTree(d);
  markStale(`Merged ${sources.join(" + ")} → “${name}”`);
};

async function removeMerge(target) {
  const r = await fetch(api(`/api/merge/${target}`), { method: "DELETE" });
  const d = await readJson(r);
  if (!r.ok) { setStatus("Error removing merge.", "err"); return; }
  await refreshTree(d);
  markStale(`Removed merge “${target}”`);
}

// left-panel view toggle (#13): hierarchy tree vs the ordered operations that built the scheme
$("viewHier").onclick = () => setLeftView("hierarchy");
$("viewOps").onclick = () => setLeftView("ops");

// the manual reset: back to the project's base classes, examples cleared
$("startFresh").onclick = async () => {
  if (!await uiConfirm("Reset this project's scheme to its base classes?\n\nSplits, merges and the " +
                       "examples you marked are cleared. Earlier runs stay as they were.",
                       { okText: "Reset", danger: true })) return;
  setStatus("Resetting…", "work");
  const r = await postJSON(api("/api/session/reset"), {});
  const d = await readJson(r);
  if (!r.ok) { setStatus("Reset failed: " + errText(d, r), "err"); return; }
  selected = null;
  await refreshTree(d);
  markStale("Reset to the base classes");
};

// ---------------- use a zoo model for a class: pick, then map its classes (point 9) ----------------
$("splitFromZoo").onclick = () => openZoo(selected);
$("replaceFromZoo").onclick = () => openZoo(selected);

// Use a zoo model for a class, with the names typed on its card (see useButtonHTML). Left as they are,
// the model's own names are used, so the common case is one click; two rows given one name merge.
async function useModel(cardId, target) {
  const c = await getJSON(api(`/api/cards/${cardId}`));
  if (c.topology === "ee_rf") return useEeRfModel(cardId, target);
  const mapping = {};
  document.querySelectorAll("#useNames input").forEach((i) => { mapping[i.dataset.m] = i.value.trim() || i.dataset.m; });
  return applyModel(cardId, target, false, mapping);
}

// ---------------- model zoo (full-screen browser) ----------------
let zooTab = "model";        // which tab the grid shows
let zooCards = [];           // cached index rows
const isZooOpen = () => !$("zoo-overlay").classList.contains("hidden");

async function refreshZooBadge() {
  try {
    const s = await getJSON(api("/api/zoo/status"));
    const loc = (s.uncommitted || []).length;
    const txt = loc ? `· ${loc} unpublished` : "· all published";
    $("zooBadge").textContent = txt;
    $("zooHeadBadge").textContent = txt;
  } catch { /* zoo status is best-effort */ }
}

// `pickFor` = the class a model is being chosen for; the zoo then says so and every usable model
// card offers "Use for <class>", which leads to the mapping step
function openZoo(pickFor = null) {
  zooPickFor = pickFor && TREE[pickFor] ? pickFor : null;
  $("zooPick").classList.toggle("hidden", !zooPickFor);
  if (zooPickFor) {
    $("zooPick").innerHTML = `Choosing a model to split <b>${esc(TREE[zooPickFor].name)}</b>. ` +
      `Open a card, then “Use for ${esc(TREE[zooPickFor].name)}”.`;
    $("zooAoi").checked = true;           // the models that know this area come first to mind
  }
  $("zoo-overlay").classList.remove("hidden");
  loadZooFull();
}
function closeZoo() { $("zoo-overlay").classList.add("hidden"); zooPickFor = null; }

// the class a model would be used for: the one being picked for, else the selected class
function targetForUse() {
  if (zooPickFor) return zooPickFor;
  return (PROJECT && PROJECT.mine && selected && selected !== "root" && TREE[selected]) ? selected : null;
}

async function loadZooFull() {
  zooCards = (await getJSON(api("/api/catalogue"))).cards;
  // "only for current view": keep cards whose extent overlaps the AOI (#3). Polygon datasets
  // have real localized extents, so this actually discriminates; India-wide feature sources
  // overlap any India AOI and stay (as they should).
  if ($("zooAoi").checked) {
    const aoi = currentBbox();
    zooCards = zooCards.filter((c) => !c.extent_bbox || bboxOverlap(c.extent_bbox, aoi));
  }
  renderGrid();
  await refreshZooBadge();
}

function bboxOverlap(a, b) {
  return !(a[2] < b[0] || b[2] < a[0] || a[3] < b[1] || b[3] < a[1]);
}

let pubSel = new Set();          // cards ticked for selective publish (#25)

// picking a model to split a class: only models that split something can do that (no base maps, no
// merges), and the ones trained for this very class come first, marked (point 10)
const SPLITTERS = new Set(["per_node_split", "ee_rf", "rule_split", "flat_multiclass"]);
function forPick(rows) {
  if (!zooPickFor || zooTab !== "model") return rows;
  const home = (c) => c.node === zooPickFor || c.apply_after === zooPickFor;
  return rows.filter((c) => SPLITTERS.has(c.topology) && !/_prev\d+_/.test(c.id))
             .sort((a, b) => home(b) - home(a));
}

function renderGrid() {
  const grid = $("zoo-grid"); grid.innerHTML = "";
  const rows = forPick(zooCards.filter((c) => c.kind === zooTab));
  if (!rows.length) { grid.innerHTML = `<p class="hint">Nothing here yet.</p>`; return; }
  rows.forEach((c) => grid.appendChild(c.kind === "model" ? modelTile(c) : datasetTile(c)));
  updatePubSelBtn();
}

// a publish tick in a tile's corner (#25): stop it selecting the card, track it in pubSel
function pubCheckbox(id) {
  return `<input type="checkbox" class="pubchk" data-id="${id}"${pubSel.has(id) ? " checked" : ""} title="select for publish">`;
}
function wirePubCheckbox(div) {
  const cb = div.querySelector(".pubchk");
  if (!cb) return;
  cb.onclick = (e) => {
    e.stopPropagation();                       // don't open the card detail
    cb.checked ? pubSel.add(cb.dataset.id) : pubSel.delete(cb.dataset.id);
    updatePubSelBtn();
  };
}
function updatePubSelBtn() {
  const btn = $("zooPublishSel");
  if (!btn) return;
  btn.disabled = pubSel.size === 0;
  btn.textContent = pubSel.size ? `Publish selected (${pubSel.size})` : "Publish selected";
}

function swatch(cls) { return `<span class="sw" style="background:${COLORS[cls] || "#888"}"></span>`; }
function classChips(classes) {
  return (classes || []).map((c) => `<span class="chip">${swatch(c)}${c}</span>`).join("");
}

// tile chips that prefer the STANDARD class name when the uploader mapped it (#14); falls back to the
// user's own class when unmapped. `std_classes` (from the index row) aligns 1:1 with `classes`.
function tileClassChips(m) {
  const std = m.std_classes || [];
  if (!std.some((s) => s && s.std)) return classChips(m.classes);   // nothing mapped -> user classes
  return std.map((s) => s.std
    ? `<span class="chip std" title="uploader: ${s.class}">${swatch(s.class)}${s.std}</span>`
    : `<span class="chip">${swatch(s.class)}${s.class}</span>`).join("");
}

const isArchived = (id) => /_prev\d+_/.test(id || "");   // superseded snapshot cards (#9)

const THIN_TEST_PX = 100;   // below this, the rarest class's held-out score is a rough guide only

function thinNote(m) {
  const sup = Object.values(m.per_class || {}).map((c) => c && c.support).filter((v) => v != null);
  const low = sup.length ? Math.min(...sup) : null;
  return low != null && low < THIN_TEST_PX
    ? `<p class="hint thin">The rarest class had only ${low} held-out pixels, so read these scores as a rough guide.</p>` : "";
}

function modelTile(m) {
  const arch = isArchived(m.id) ? `<span class="pill arch">archived</span>` : "";
  const made = zooPickFor && m.node === zooPickFor ? `<span class="pill made">made for ${esc(TREE[zooPickFor].name)}</span>` : "";
  const pub = m.published ? `<span class="pill pub">published</span>` : `<span class="pill loc">local</span>`;
  // a perfect score on a few dozen test pixels isn't a perfect model; say how thin the test was
  const thin = m.min_test_px != null && m.min_test_px < THIN_TEST_PX ? ` <span class="thin" title="the rarest class had only ${m.min_test_px} held-out pixels">· thin test (${m.min_test_px} px)</span>` : "";
  const acc = m.accuracy != null ? `accuracy ${m.accuracy.toFixed(2)}${thin}` : "—";
  // cheap apply-after hint from the index row (full WorldCover hint shows in the detail pane)
  const after = (m.topology && m.topology !== "base_pooled" && m.node) ? ` · after ${m.node}` : "";
  const div = document.createElement("div");
  div.className = "zoo-card" + (m.id === zooSelected ? " sel" : "");
  div.innerHTML = `<div class="zc-top"><h4>${pubCheckbox(m.id)}${m.name || m.id}</h4>${made}${arch}${pub}</div>
    <div class="zc-classes">${tileClassChips(m)}</div>
    <div class="zc-acc">${acc} · ${m.topology || ""}${after}</div>`;
  div.onclick = () => showCardFull(m.id);
  wirePubCheckbox(div);
  return div;
}

function datasetTile(d) {
  const t = d.type === "inference" ? `<span class="pill infer">inference</span>`
                                   : `<span class="pill train">training</span>`;
  const div = document.createElement("div");
  div.className = "zoo-card" + (d.id === zooSelected ? " sel" : "");
  // how many models consume this dataset, straight off the index row (#15)
  const used = d.used_by_count ? ` · used in ${d.used_by_count} model${d.used_by_count > 1 ? "s" : ""}` : "";
  div.innerHTML = `<div class="zc-top"><h4>${pubCheckbox(d.id)}${d.name || d.id}</h4>${t}</div>
    <div class="zc-classes">${classChips(d.classes)}</div>
    <div class="zc-acc">${d.kind || "dataset"}${used}</div>`;
  div.onclick = () => showCardFull(d.id);
  wirePubCheckbox(div);
  return div;
}

// clickable dataset chips on a model card -> jump to that dataset's detail
function dsChips(ids) {
  const chips = (ids || []).map((id) =>
    `<span class="chip link" onclick="showCardFull('${id}')">${id}</span>`).join("");
  return `<div class="chips-row">${chips || "—"}</div>`;
}

async function showCardFull(id) {
  zooSelected = id;
  const c = await getJSON(api(`/api/cards/${id}`));
  $("zoo-detail").innerHTML = id.startsWith("mc_") ? modelDetail(c) : datasetDetail(c);
  renderGrid();   // refresh selection highlight
  // a polygon dataset: compute + fill the spread right away, so every polygon card shows it, not just
  // the ones that happened to have it precomputed (#6). recomputeSpread no-ops when there's no panel.
  if (!id.startsWith("mc_") && c.kind === "polygons") recomputeSpread(id, 0.25);
  // name the strong regions (districts / states) for models and polygon datasets (#7)
  if (id.startsWith("mc_") || c.kind === "polygons") fillCardRegions(id);
}

function modelDetail(c) {
  const m = c.metrics || {}, per = m.per_class || {}, a = c.about || {};
  const perRows = Object.entries(per).map(([k, v]) =>
    `<tr><td>${swatch(k)} ${k}</td><td>P ${v.precision}</td><td>R ${v.recall}</td><td>F ${v.f1}</td></tr>`).join("");
  const year = ((c.extent || {}).temporal || {}).year;
  const aboutRows = [["", a.description], ["Intended use", a.intended_use],
                    ["Limitations", a.limitations], ["Evidence", a.evidence],
                    ["Contributor", (c.zoo || {}).contributor]]
    .filter(([, v]) => v).map(([k, v]) => `<div class="prose">${k ? "<b>" + k + ":</b> " : ""}${v}</div>`).join("")
    || `<div class="prose">— not described yet —</div>`;
  return `
    <h3>${c.name}</h3>
    <div class="sub2">node <code>${c.node}</code> · ${c.topology}
      · ${c.zoo && c.zoo.published ? "published" : "local"}</div>
    ${zooPickFor ? `<div class="use-top">${useButtonHTML(c)}</div>` : ""}
    ${placementHTML(c)}
    <div class="blk"><span class="k">Produces</span><div class="chips-row">${produceChips(c.produces)}</div></div>
    ${m.accuracy != null ? `<div class="blk"><span class="k">Metrics — acc ${m.accuracy} (${m.eval || ""})</span>${thinNote(m)}
      <table>${perRows}</table></div>` : ""}
    ${balanceFeedback(c)}
    <div class="blk"><span class="k">Training data</span>${dsChips(c.training && c.training.datasets)}</div>
    <div class="blk"><span class="k">Inference features</span>${dsChips([(c.inference || {}).dataset].filter(Boolean))}</div>
    <div class="blk"><span class="k">Strong regions${year ? " · " + year : ""}</span>${extentLineForCard(c)}
      <div id="cardRegions" class="prose"></div>
      <button id="showExtent">Show on map</button></div>
    <div class="blk"><span class="k">About</span>${aboutRows}
      <button id="annotateToggle">Annotate / evidence / class mapping</button>
      ${annotateForm(c)}</div>
    <div class="blk"><span class="k">Artifact</span><code>${(c.artifact || {}).path || "—"}</code></div>
    ${zooPickFor ? "" : useButtonHTML(c)}
    <button id="pubBtn">${c.zoo && c.zoo.published ? "Re-publish" : "Publish to zoo"}</button>
    ${(c.zoo && c.zoo.published) ? "" : `<button id="delBtn" class="danger">Delete from zoo</button>`}`;
}

// what this card can do for the open project. Only offered when it makes sense (point 10): a split
// model or an IndiaSAT model can be used for a class; a base map is picked when a project starts.
function useButtonHTML(c) {
  if (c.topology === "merge_relabel") return `<div class="prose">A merge from someone's scheme. Merges are made in the tree, not applied.</div>`;
  if (c.topology === "base_pooled" || c.node === "root")
    return `<div class="prose">A base map. You choose the base when you start a project.</div>`;
  const t = targetForUse();
  if (!t) return `<div class="prose">To use it: open one of your projects, pick a class, then “Use a model from the zoo”.</div>`;
  const tn = esc(TREE[t].name);
  // the mapping, in place: what each model class will be called under the target, pre-filled with
  // the model's own name. Nothing to do unless you want your own names (sir's "class x is acacia").
  const eeRf = c.topology === "ee_rf";
  const rows = (c.produces || []).map((p) => `<div class="use-row">
      <span class="chip">${swatch(p.class)}${esc(p.class)}</span><span class="arrow">→</span>
      <input type="text" data-m="${esc(p.class)}" value="${esc(p.class)}" ${eeRf ? "disabled" : ""}></div>`).join("");
  const note = eeRf ? "Its class names are fixed. It trains inside Earth Engine and needs the IndiaSAT base."
                    : "Rename any to fit your scheme, or leave them. The same name twice merges those two.";
  return `<div class="use-box"><div class="k">Under ${tn} it becomes</div>
      <div id="useNames">${rows}</div><p class="hint">${note}</p>
      <button id="useForBtn" class="primary">Use for ${tn}</button></div>`;
}

// "where does this model slot in" hint (#2), auto-derived server-side from the card's node +
// any WorldCover mapping, with a cheap client-side check of whether it's relevant to the view.
function placementHTML(c) {
  const r = c.recommendation;
  if (!r) return "";
  if (!r.apply_after) {
    return `<div class="blk"><span class="k">Suggested placement</span>
      <div class="prose">${r.note || "Base map: the starting point."}</div></div>`;
  }
  const wc = r.worldcover ? ` <span class="prose">(WorldCover: ${r.worldcover.name})</span>` : "";
  const sp = c.extent && c.extent.spatial;
  const here = sp && sp.type === "bbox" ? bboxOverlap(sp.value, currentBbox()) : true;
  const aoiNote = here ? "" : ` <span class="prose">· outside current view</span>`;
  return `<div class="blk"><span class="k">Suggested placement</span>
    <div>Apply after <b>${r.apply_after_name || r.apply_after}</b>${wc}${aoiNote}</div></div>`;
}

// resolve a standard code to its display name via the loaded STANDARDS vocab (#14)
function stdName(kind, code) {
  const hit = ((STANDARDS[kind] || {}).classes || []).find((o) => String(o.code) === String(code));
  return hit ? hit.name : code;
}

// produced-class chips on the DETAIL pane: the uploader's own class, then what it maps to in a
// standard scheme by NAME (so it reads the same as the tile, which shows the standard name) (#14).
function produceChips(produces) {
  return (produces || []).map((p) => {
    const m = p.std_mapping || {};
    const std = Object.entries(m).map(([k, v]) => `${stdName(k, v)} (${k})`).join(", ");
    return `<span class="chip">${swatch(p.class)}${p.class}${std ? ` <span class="prose">→ ${std}</span>` : ""}</span>`;
  }).join("");
}

// class-balance feedback (#6): support ratio across classes + the balancing policy on the card
function balanceFeedback(c) {
  const per = (c.metrics || {}).per_class || {};
  const sup = Object.values(per).map((v) => v.support).filter((s) => s != null);
  const bal = (c.training || {}).balancing || {};
  const method = bal.method ? `policy: <code>${bal.method}</code>` : "";
  if (sup.length < 2) return method ? `<div class="blk"><span class="k">Balance</span>${method}</div>` : "";
  const ratio = Math.max(...sup) / Math.max(1, Math.min(...sup));
  const [label, col] = ratio <= 3 ? ["balanced", "#2f6b3f"]
                     : ratio <= 5 ? ["mild imbalance", "#b4791f"]
                     :              ["imbalanced — consider under/oversampling", "#a23b2f"];
  return `<div class="blk"><span class="k">Class balance</span>
    <div><b style="color:${col}">${ratio.toFixed(1)}:1</b> — ${label}</div>
    ${method ? `<div class="prose">${method}</div>` : ""}</div>`;
}

// a dropdown of a standard's classes (with a "none" option, since mapping is optional)
function stdSelect(kind, cls, current) {
  const opts = ((STANDARDS[kind] || {}).classes || []).map((o) =>
    `<option value="${o.code}" ${String(current) === String(o.code) ? "selected" : ""}>` +
    `${o.name}${kind === "worldcover" ? " (" + o.code + ")" : ""}</option>`).join("");
  const label = (STANDARDS[kind] || {}).label || kind;
  return `<select class="an-std" data-cls="${cls}" data-kind="${kind}">` +
    `<option value="">${label}: none</option>${opts}</select>`;
}

// the editor: describe the model, give evidence, map each class to a standard scheme (#8, #13-15)
function annotateForm(c) {
  const a = c.about || {}, contrib = (c.zoo || {}).contributor || localStorage.getItem("contributor") || "";
  // per class: pick a WorldCover and/or USDA class from dropdowns. All optional, any subset.
  const stdRows = (c.produces || []).map((p) => {
    const m = p.std_mapping || {};
    return `<div class="std-row"><span class="std-cls">${swatch(p.class)}${p.class}</span>
      ${stdSelect("worldcover", p.class, m.worldcover)}
      ${stdSelect("usda", p.class, m.usda)}</div>`;
  }).join("");
  return `<div id="annotateForm" class="hidden">
    <label>Description<textarea id="an_desc">${a.description || ""}</textarea></label>
    <label>Intended use<textarea id="an_use">${a.intended_use || ""}</textarea></label>
    <label>Limitations<textarea id="an_lim">${a.limitations || ""}</textarea></label>
    <label>Evidence (how annotated — drone, field photos, …)<textarea id="an_ev">${a.evidence || ""}</textarea></label>
    <label>Contributor<input id="an_contrib" type="text" value="${contrib}"></label>
    <span class="k" style="margin-top:8px">Map classes to a standard scheme (optional)</span>${stdRows}
    <button id="annotateSave" class="primary">Save annotation</button>
  </div>`;
}

async function saveAnnotation(id) {
  const v = (x) => ($(x) ? $(x).value.trim() : "");
  const std = {};
  document.querySelectorAll(".an-std").forEach((sel) => {
    if (!sel.value) return;                       // "none" -> skip; mapping stays optional
    const cls = sel.dataset.cls, kind = sel.dataset.kind;
    (std[cls] = std[cls] || {})[kind] = kind === "worldcover" ? Number(sel.value) : sel.value;
  });
  if (v("an_contrib")) localStorage.setItem("contributor", v("an_contrib"));   // remember for publish (#6)
  setStatus("Saving annotation…", "work");
  try {                                            // guard so a network throw can't strand the toast (#10)
    const r = await postJSON(api(`/api/cards/${id}/annotate`),
      { about: { description: v("an_desc"), intended_use: v("an_use"),
                 limitations: v("an_lim"), evidence: v("an_ev") },
        contributor: v("an_contrib"), std_mapping: std });
    if (!r.ok) { setStatus("Error saving annotation.", "err"); return; }
    setStatus("Saved annotation.", "ok");
    await loadZooFull();
    await showCardFull(id);
  } catch (err) { setStatus("Error saving annotation: " + err, "err"); }
}

// the spatial-diversity score as actionable feedback: is this dataset spread out, or clustered
// (which would skew a model)? Shannon entropy of the polygons over a grid, in [0,1]. The grid
// cell is user-adjustable (#1) — change it to see the spread at the scale you care about.
const SPREAD_CELLS = [0.1, 0.25, 0.5, 1.0];

// just the value line (diversity number + label + count), so initial render and live recompute
// share one renderer. d=diversity, occ=occupied cells, n=#polygons, cell=grid size in degrees.
function spreadValueHTML(d, occ, n, cell, coverage, missing) {
  if (missing) return `<div class="prose">its labelled polygons aren't on disk (archived by a “start fresh”). Reload or re-add them to measure spread.</div>`;
  if (d == null) return `<div class="prose">no spread (need ≥2 polygons)</div>`;
  const [label, col] = d >= 0.75 ? ["well spread", "#2f6b3f"]
                     : d >= 0.5  ? ["moderately spread", "#b4791f"]
                     :             ["clustered — risks skewing the model", "#a23b2f"];
  const cells = occ != null ? ` across ${occ} grid cells` : "";
  const tail = n != null ? `${n} polygons${cells} (${cell}° grid)` : "";
  // coverage judges the count against the size of the area you're about to classify (#4):
  // labelled area / AOI area. Tiny for crown polygons over a big box, which is the honest signal.
  const cov = coverage != null
    ? `<div class="prose">covers <b>${(coverage * 100).toFixed(coverage < 0.01 ? 2 : 1)}%</b> of the current AOI (labelled area ÷ area to classify)</div>`
    : "";
  return `<div><b style="color:${col}">${d.toFixed(2)}</b> — ${label}</div>
    ${tail ? `<div class="prose">${tail}</div>` : ""}${cov}`;
}

function spreadFeedback(c) {
  const q = c.quality || {};
  const d = q.spatial_diversity;
  const isPoly = c.kind === "polygons";
  if (d == null && !isPoly) return "";        // non-polygon cards with no precomputed spread: skip
  const opts = SPREAD_CELLS.map((cc) =>
    `<option value="${cc}" ${cc === 0.25 ? "selected" : ""}>${cc}°</option>`).join("");
  // a polygon card without a stored value gets the panel anyway — showCardFull fills it live (#6)
  const initial = d != null ? spreadValueHTML(d, q.occupied_cells, q.n_polygons, 0.25)
                            : `<div class="prose">computing…</div>`;
  return `<div class="blk"><span class="k">Spread (spatial diversity)</span>
    <label class="spread-grid">grid cell
      <select id="spreadCell">${opts}</select></label>
    <div id="spreadOut">${initial}</div>
    <div class="prose">Shannon entropy of where the polygons fall, normalized to [0,1] —
    flags data that's all from one area before it skews a model.</div></div>`;
}

// recompute the spread at a chosen grid cell for the open dataset card (#1)
async function recomputeSpread(id, cell) {
  const out = $("spreadOut");
  if (out) out.innerHTML = `<div class="prose">recomputing…</div>`;
  try {
    const b = currentBbox();   // judge coverage against the area we're about to classify (#4)
    const aoi = b ? `&w=${b[0]}&s=${b[1]}&e=${b[2]}&n=${b[3]}` : "";
    const q = await getJSON(api(`/api/cards/${id}/spread?cell=${cell}${aoi}`));
    if (out) out.innerHTML = spreadValueHTML(q.spatial_diversity, q.occupied_cells, q.n_polygons, q.cell, q.coverage, q.missing);
  } catch {
    if (out) out.innerHTML = `<div class="prose">couldn't recompute at this grid</div>`;
  }
}

// which models consume this dataset (#15) — provenance both ways. Clickable chips jump to the model.
function usedByHTML(c) {
  const used = c.used_by || [];
  const chips = used.length
    ? used.map((m) => `<span class="chip link" onclick="showCardFull('${m.id}')" title="${m.name || m.id}">${m.id}</span>`).join("")
    : `<span class="prose">not used by any model yet</span>`;
  return `<div class="blk"><span class="k">Used in models</span><div class="chips-row">${chips}</div></div>`;
}

function datasetDetail(c) {
  const q = c.quality || {}, p = c.provenance || {}, e = c.embedding || {};
  const cls = (c.classes || []).map((x) => `${x.class}${x.count != null ? " (" + x.count + ")" : ""}`).join(", ");
  return `
    <h3>${c.name}</h3>
    <div class="sub2"><span class="pill ${c.type === "inference" ? "infer" : "train"}">${c.type}</span>
      · ${c.kind}</div>
    <div class="blk prose">${c.description || ""}</div>
    <div class="blk"><span class="k">Classes</span><div class="chips-row">${classChips((c.classes || []).map((x) => x.class))}</div>
      <div class="prose">${cls}</div></div>
    ${usedByHTML(c)}
    <div class="blk"><span class="k">Definition</span><code>${JSON.stringify(c.definition)}</code></div>
    ${e.source ? `<div class="blk"><span class="k">Embedding</span>${e.source} ${e.dim}-d (${e.year || ""})</div>` : ""}
    ${spreadFeedback(c)}
    <div class="blk"><span class="k">Provenance</span><div class="prose">${p.annotator || "—"} · ${p.method || ""}
      ${p.license ? "· " + p.license : ""}</div></div>
    ${inferenceYearHTML(c)}
    ${sourceLinkHTML(c)}
    <div class="blk"><span class="k">Valid extent${((c.extent || {}).temporal || {}).year ? " · " + c.extent.temporal.year : ""}</span>${extentLineForCard(c)}
      <div id="cardRegions" class="prose"></div>
      <button id="showExtent">Show on map</button></div>`;
}

// name the districts / states a card's polygons fall in (#7), via the GAUL lookup, and drop them into
// the card's region line — so "strong regions" reads e.g. "Assam (Dibrugarh, Tinsukia)", not just a map.
async function fillCardRegions(id) {
  const out = $("cardRegions");
  if (!out) return;
  out.textContent = "naming districts / states…";
  try {
    const r = await getJSON(api(`/api/cards/${id}/regions`));
    if (!r.available) { out.textContent = ""; return; }
    const states = (r.states || []).join(", ");
    const districts = (r.districts || []).slice(0, 8).join(", ");
    const more = (r.districts || []).length > 8 ? ` +${r.districts.length - 8} more` : "";
    out.innerHTML = states
      ? `<b>${states}</b>${districts ? ` — ${districts}${more}` : ""}`
      : "";
  } catch { out.textContent = ""; }
}

// public source link, edited right here on the card (#3/#8b). The user attaches it once, on the
// dataset, instead of being prompted per-dataset at every publish. Blank clears it. Training
// datasets only — a feature source (Alpha Earth) has its own provenance.
function sourceLinkHTML(c) {
  if (c.type !== "training") return "";
  return `<div class="blk"><span class="k">Public source link</span>
    <input id="dsLink" type="text" placeholder="https://… (leave blank to keep this data private)"
      value="${c.source_url || ""}">
    <div class="prose">Where this data was fetched from. We only carry the link; the raw upload
      stays yours and is never pushed to the zoo.</div>
    <button id="dsLinkSave">Save link</button></div>`;
}

// the Alpha Earth inference year (#7) now lives on its feature-source card. Picking a year here
// sets what Run classification samples (Realistic mode); Detailed stays pinned to 2024.
function inferenceYearHTML(c) {
  if (c.id !== AE_INFERENCE_ID) return "";
  const cur = PROJECT ? PROJECT.year : 2024;
  const years = ((INFER_OPTS.realistic || {}).years) || [cur];
  const opts = years.map((y) => `<option value="${y}"${y === cur ? " selected" : ""}>${y}</option>`).join("");
  // temporal-validity + Tessera-year notes come from the backend (#3 / #6), best-effort
  const aeNote = (INFER_OPTS.realistic || {}).note || "";
  const teNote = (INFER_OPTS.detailed || {}).note || "";
  return `<div class="blk"><span class="k">Inference year</span>
    <select id="zooYear">${opts}</select>
    <div class="prose">Which year's Alpha Earth the map classifies. Same model, different temporal
      slice. Detailed mode is locked to 2024 (Tessera coverage).</div>
    ${aeNote ? `<div class="prose">${aeNote}</div>` : ""}
    ${teNote ? `<div class="prose">${teNote}</div>` : ""}</div>`;
}

// ---- extent: honest metadata, sane visualization ----
const INDIA_BBOX = [68.0, 6.5, 97.5, 37.5];
function isNational(bb) { return (bb[2] - bb[0]) > 8 || (bb[3] - bb[1]) > 8; }
// polygon-backed cards: the extent IS the polygons, not a country box — say so.
function extentLineForCard(c) {
  if (c.kind === "polygons") return `<span class="prose">its labelled polygons (see map)</span>`;
  // a model's strength is where its training data falls, not a country box (#7). Point at that.
  if (String(c.id || "").startsWith("mc_")) {
    const ds = (c.training && c.training.datasets) || [];
    if (ds.length) return `<span class="prose">strongest where its training data falls — see map ` +
      `(${ds.length} training set${ds.length > 1 ? "s" : ""})</span>`;
    return `<span class="prose">no localized training data — a general feature-source model</span>`;
  }
  return extentLine(c.extent);
}
function extentLine(extent) {
  const sp = extent && extent.spatial;
  if (!sp || sp.type !== "bbox") return `<span class="prose">no spatial extent</span>`;
  return isNational(sp.value) ? `<span class="prose">India-wide feature source</span>`
    : `<span class="prose">localized: [${sp.value.map((v) => v.toFixed(2)).join(", ")}]</span>`;
}

// "Show on map" for a card. The real extent of polygon-backed data IS the polygons, so draw a
// few prominent ones (everything here is India anyway — a country box says nothing). Feature
// sources (Alpha Earth / Tessera / pixel tables) have no polygons, so fall back to the bbox/label.
async function showOnMap(id) {
  if (id.startsWith("mc_")) { await showModelStrongRegion(id); return; }
  const geo = await getJSON(api(`/api/cards/${id}/geometry`));
  if (geo.drawable && (geo.features || []).length) { drawPolygons(geo); return; }
  const c = await getJSON(api(`/api/cards/${id}`));
  drawExtent(c.extent);
}

// a model's strong region is where its training data lives (#7): draw those polygons, gathered across
// its training datasets. Falls back to the extent for a model with no polygon training data.
async function showModelStrongRegion(id) {
  const c = await getJSON(api(`/api/cards/${id}`));
  const ds = (c.training && c.training.datasets) || [];
  const feats = [];
  for (const d of ds) {
    try {
      const g = await getJSON(api(`/api/cards/${d}/geometry`));
      if (g.drawable) feats.push(...(g.features || []));
    } catch { /* a dataset without drawable polygons just contributes nothing */ }
  }
  if (feats.length) { drawPolygons({ features: feats, shown: feats.length, total: feats.length }); return; }
  drawExtent(c.extent);
}

function drawPolygons(fc) {
  if (extentLayer) { map.removeLayer(extentLayer); extentLayer = null; }
  const grp = L.featureGroup();
  L.geoJSON(fc, { style: { color: "#4ea1ff", weight: 2,
    fillColor: "#4ea1ff", fillOpacity: 0.3 } }).addTo(grp);
  // the polygons can be spread across India and tiny when the view fits them all, so drop a
  // visible bubble at each one's centre — you can see where they are at any zoom.
  (fc.features || []).forEach((f) => {
    const center = L.geoJSON(f).getBounds().getCenter();
    L.circleMarker(center, { radius: 6, color: "#fff", weight: 2,
      fillColor: "#ff5252", fillOpacity: 0.95 }).addTo(grp);
  });
  grp.addTo(map);
  extentLayer = grp;
  // fit to them, but cap the zoom so a single small polygon doesn't slam to street level
  map.fitBounds(grp.getBounds(), { padding: [50, 50], maxZoom: 11 });
  const more = fc.total > fc.shown ? ` (+${fc.total - fc.shown} more)` : "";
  setStatus(`Showing ${fc.shown} of ${fc.total} polygons (red dots mark each)${more}.`, "ok");
}

// fallback when there are no polygons to draw: bbox for a localized extent, label for India-wide.
function drawExtent(extent) {
  if (extentLayer) { map.removeLayer(extentLayer); extentLayer = null; }
  const sp = extent && extent.spatial;
  if (!sp || sp.type !== "bbox") { setStatus("This card has no spatial extent.", "info"); return; }
  const [w, s, e, n] = sp.value;
  if (isNational(sp.value)) {
    map.fitBounds([[s, w], [n, e]]);
    setStatus("Feature source valid India-wide — no box drawn (it'd cover the whole country).", "info");
    return;
  }
  extentLayer = L.rectangle([[s, w], [n, e]],
    { color: "#4ea1ff", weight: 2, fill: false, dashArray: "5,5" }).addTo(map);
  map.fitBounds([[s, w], [n, e]]);
  setStatus("Drew this card's extent on the map.", "ok");
}

// who's publishing (#6): a GitHub handle or email. No popup — it's set on a card's detail pane
// (the Annotate form's Contributor field, which also remembers it here), and read silently here.
function contributor() {
  return localStorage.getItem("contributor") || "";
}

async function publishCard(id) {
  // no popups: the contributor (#6) comes from the card's Annotate field (remembered here), and
  // dataset links (#3) are set on each dataset card's detail pane — so publish is one quiet click.
  setStatus(`Publishing "${id}" to the zoo…`, "work");
  try {                                            // a push can fail on the network; don't strand the toast (#10)
    const r = await postJSON(api("/api/publish"), { card_ids: [id], contributor: contributor() });
    const d = await r.json();
    setStatus(d.pushed ? `Published "${id}" — pushed to the zoo.`
              : (d.committed ? `Committed "${id}" locally (${d.note}).` : d.note || "Nothing to publish."),
              r.ok ? "ok" : "err");
    await loadZooFull();
    await showCardFull(id);
  } catch (err) { setStatus(`Publish failed: ` + err, "err"); }
}

// ---- zoo overlay wiring ----
$("openZoo").onclick = () => openZoo(null);
$("closeZoo").onclick = closeZoo;
$("zooAoi").onchange = loadZooFull;
// publish just the ticked cards (#25) — the backend already takes a card_ids list
$("zooPublishSel").onclick = async () => {
  const ids = [...pubSel];
  if (!ids.length) return;
  setStatus(`Publishing ${ids.length} selected card(s)…`, "work");
  const r = await postJSON(api("/api/publish"), { card_ids: ids, contributor: contributor() });
  const d = await r.json();
  setStatus(d.committed || d.pushed ? `Published ${ids.length} card(s) (${d.note || "done"}).`
            : (d.note || "Nothing to publish."), r.ok ? "ok" : "err");
  pubSel.clear();
  await loadZooFull();
};
$("zooPublishAll").onclick = async () => {
  setStatus("Publishing all unpublished cards…", "work");
  const r = await postJSON(api("/api/publish"), { contributor: contributor() });
  const d = await r.json();
  setStatus(d.committed ? `Published the zoo (${d.note}).` : (d.note || "Nothing to publish."),
            r.ok ? "ok" : "err");
  await loadZooFull();
};
document.querySelectorAll(".ztab").forEach((t) => t.onclick = () => {
  document.querySelectorAll(".ztab").forEach((x) => x.classList.remove("sel"));
  t.classList.add("sel"); zooTab = t.dataset.tab; renderGrid();
});
// help drawer: a plain symptom -> fix table, slides over the map
const toggleHelp = (open) => $("help").classList.toggle("hidden", !open);
$("openHelp").onclick = () => toggleHelp(true);
$("closeHelp").onclick = () => toggleHelp(false);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (isZooOpen()) closeZoo(); else toggleHelp(false);
});
// "Show on map" lives in the injected detail HTML; delegate the click
$("zoo-detail").addEventListener("click", async (e) => {
  const id = e.target.id;
  if (id === "showExtent") { closeZoo(); await showOnMap(zooSelected); }
  else if (id === "annotateToggle") { $("annotateForm").classList.toggle("hidden"); }
  else if (id === "annotateSave") { await saveAnnotation(zooSelected); }
  else if (id === "useForBtn") { await useModel(zooSelected, targetForUse()); }   // names are on the card
  else if (id === "delBtn") { await deleteCardUI(zooSelected); }                 // #9 drop a card
  else if (id === "pubBtn") { await publishCard(zooSelected); }
  else if (id === "dsLinkSave") { await saveDatasetLink(zooSelected); }
});
// injected <select>s in the detail pane (spread grid #1, inference year #7) — delegate their change
$("zoo-detail").addEventListener("change", async (e) => {
  if (e.target.id === "spreadCell") await recomputeSpread(zooSelected, e.target.value);
  else if (e.target.id === "zooYear" && PROJECT && PROJECT.mine) {
    $("projYear").value = e.target.value;
    $("projYear").onchange();              // the project's year is the one place the run year lives
  }
});

// save a dataset's public source link straight from its card (#3). Empty clears it.
async function saveDatasetLink(id) {
  const url = ($("dsLink") ? $("dsLink").value : "").trim();
  setStatus("Saving source link…", "work");
  const r = await postJSON(api(`/api/cards/${id}/annotate`), { source_url: url });
  if (!r.ok) { setStatus("Error saving link.", "err"); return; }
  setStatus(url ? "Saved public source link." : "Cleared the source link.", "ok");
  await loadZooFull();
  await showCardFull(id);
}

// use a zoo model for a class, with the user's class names. If the model was trained for a different
// kind of class the server answers 409 and we ask before forcing it (#11). Nothing runs: the banner
// asks for a re-run (point 9).
async function applyModel(id, targetNode, force = false, mapping = null) {
  setStatus(`Applying "${id}"…`, "work");
  const r = await postJSON(api("/api/apply"), { card_id: id, target_node: targetNode, force, mapping });
  const d = await readJson(r);
  if (r.status === 409 && !force) {
    const msg = (d.detail && d.detail.message) || d.detail || "This model may not fit here.";
    if (await uiConfirm(msg + "\n\nUse it anyway?", { okText: "Use anyway", danger: true })) {
      return applyModel(id, targetNode, true, mapping);
    }
    setStatus("Left the scheme unchanged.", "info");
    return false;
  }
  if (!r.ok) { setStatus("Error: " + errText(d, r), "err"); return false; }
  closeZoo();
  await refreshTree(d);
  select(targetNode);
  markStale(`${TREE[targetNode].name} now splits into ${(d.classes || []).join(" / ")}`);
  return true;
}

// drop a card from the zoo (#9): a superseded/dummy model the user no longer wants
async function deleteCardUI(id) {
  if (!await uiConfirm(`Delete "${id}" from the zoo?\n\nThis removes the card (and any archived copy).`,
                       { okText: "Delete", danger: true })) return;
  setStatus(`Deleting "${id}"…`, "work");
  const r = await fetch(api(`/api/cards/${id}`), { method: "DELETE" });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + ((d.detail && d.detail.message) || d.detail || r.status), "err"); return; }
  zooSelected = null;
  $("zoo-detail").innerHTML = `<p class="hint">Deleted "${id}". Select a card to see its details.</p>`;
  await loadZooFull();
  setStatus(`Deleted "${id}".`, "ok");
}

// Two shapes land here: sklearn's report (inline retrain) and a model card's metrics (after a DAG
// retrain, where the card is all we can read back). Same numbers, different spelling of f1.
function formatReport(rep, nTest) {
  if (!rep) return "";
  const perClass = rep.per_class || rep;
  const lines = [`held-out: ${nTest ?? rep.n_test ?? "?"} px   acc ${(rep.accuracy ?? 0).toFixed(3)}`];
  for (const [k, v] of Object.entries(perClass)) {
    if (["accuracy", "macro avg", "weighted avg"].includes(k) || typeof v !== "object") continue;
    const f1 = v["f1-score"] ?? v.f1 ?? 0;
    lines.push(`${k.padEnd(14)} P${v.precision.toFixed(2)} R${v.recall.toFixed(2)} F${f1.toFixed(2)}`);
  }
  return lines.join("\n");
}

init();
