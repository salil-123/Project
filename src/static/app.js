// Core Stack LULC — Leaflet frontend talking to the FastAPI backend.
let PRESETS = {}, COLORS = {}, TREE = {}, STANDARDS = {}, INFER_OPTS = {};
let MERGES = [];                  // active merge rules, drawn onto the hierarchy tree (#1)
let mergeSel = new Set();         // leaf ids ticked in the tree, waiting to be merged (#1)
const AE_INFERENCE_ID = "ds_alphaearth_annual_v1";   // the Alpha Earth feature-source card
let inferYear = Number(localStorage.getItem("inferYear")) || 2024;   // year drives Run; set in zoo (#7)
let selected = "root";            // the class the example/operation panels act on
let predLayer = L.layerGroup();   // vector cells (fallback render)
let rasterLayer = null;           // the 10 m classified tile overlay
let drawnLayer = L.featureGroup();
let lastGeometry = null;
let extentLayer = null;            // Model Zoo: the selected card's extent rectangle
let zooSelected = null;
let aoiLayer = null;              // the current AOI box, always drawn so the user sees what runs (#3)
let customBbox = null;           // a box drawn straight on the map overrides centre+half (#3)
let sessionStartSeq = null;      // op-log head when this session began — export scopes to it (#4)
let lastPreset = null;           // to detect a genuine area change and offer a reset (#5)
let viewMode = "hierarchy";      // left panel: "hierarchy" tree or "ops" operations view (#13)
let TESSERA_SITES = {};          // bboxes where Tessera training is offered (#16)

const map = L.map("map", { center: [28.540, 77.185], zoom: 14 });   // IIT Delhi + Sanjay Van strip
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Esri", maxZoom: 19 }).addTo(map);
predLayer.addTo(map);
drawnLayer.addTo(map);

// draw tools: rectangle sets the AOI (#3); polygon + marker mark example geometry
map.addControl(new L.Control.Draw({
  edit: { featureGroup: drawnLayer },
  draw: { polygon: true, marker: true, rectangle: true, polyline: false,
          circle: false, circlemarker: false },
}));
map.on(L.Draw.Event.CREATED, (e) => {
  if (e.layerType === "rectangle") {
    // a drawn box becomes the AOI (an arbitrary, possibly non-square rectangle)
    const b = e.layer.getBounds();
    customBbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    setPresetToCustom();
    drawAoi();
    maybeResetForNewArea().then((didReset) => { if (!didReset) runClassify(); });
    return;
  }
  drawnLayer.clearLayers();
  drawnLayer.addLayer(e.layer);
  lastGeometry = e.layer.toGeoJSON().geometry;
  setStatus("Polygon captured — pick a role and 'Add drawn polygon'.");
});

// click the map (in Custom mode) to drop the AOI centre; the slider then sizes the box (#3).
// This just repositions — the "new area, start fresh?" offer fires on the deliberate gestures
// (a different preset, or a freshly drawn box), not on every nudge, so it doesn't nag.
map.on("click", (e) => {
  if ($("preset").value !== "__custom__") return;
  customBbox = null;                       // back to a centre+half square
  $("clat").value = e.latlng.lat.toFixed(3);
  $("clon").value = e.latlng.lng.toFixed(3);
  drawAoi();
});

// the persistent AOI rectangle, redrawn whenever the area changes so it's always visible (#3)
function drawAoi() {
  const bb = currentBbox();
  if (!bb) return;
  const [w, s, e, n] = bb;
  if (aoiLayer) map.removeLayer(aoiLayer);
  aoiLayer = L.rectangle([[s, w], [n, e]],
    { color: "#ffd54f", weight: 2, fill: false, dashArray: "4,4" }).addTo(map);
  updateTesseraAvailability();       // the Tessera option depends on the AOI (#16)
  showAoiSize(bb);                    // report the area + warn if it's over a cap (#3)
}

// #3: keep the user honest about how big the box is, and disable Run past the hard tile cap.
function showAoiSize(bb) {
  const el = $("aoiSize");
  if (!el) return;
  const km2 = bboxAreaKm2(bb);
  const over = km2 > AOI_TILE_CAP_KM2;
  el.textContent = `Area ≈ ${km2.toLocaleString(undefined, { maximumFractionDigits: 0 })} km²`
    + (over ? ` — over the ${AOI_TILE_CAP_KM2.toLocaleString()} km² limit; draw a smaller box.`
       : km2 > AOI_GEOTIFF_CAP_KM2 ? ` (too large for GeoTIFF export; tiles still OK).` : "");
  el.classList.toggle("warn", over);
  if ($("run")) $("run").disabled = over;
}

function setPresetToCustom() {
  $("preset").value = "__custom__";
  $("custom").classList.remove("hidden");
}

const $ = (id) => document.getElementById(id);

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

function currentBbox() {
  const preset = $("preset").value;
  if (preset !== "__custom__") return PRESETS[preset];
  if (customBbox) return customBbox;                 // a box drawn on the map wins (#3)
  const lat = parseFloat($("clat").value), lon = parseFloat($("clon").value);
  const h = parseFloat($("half").value);
  return [lon - h, lat - h, lon + h, lat + h];
}

// #6: ask the backend how long a train over the current area should take, from the benchmark
// profile (scripts/benchmark_training.py). Best-effort — returns null if there's no profile yet,
// so the flow never blocks on it.
async function fetchEstimate(algo) {
  try {
    const [w, s, e, n] = currentBbox();
    const d = await getJSON(`/api/estimate?west=${w}&south=${s}&east=${e}&north=${n}&algo=${algo || "linearsvc"}`);
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

// #3: equal-area size of the AOI, mirroring src/aoi.area_km2 so we can warn/block before the
// request goes out. The server re-checks against its own (admin-tunable) caps — this is just UX.
const AOI_TILE_CAP_KM2 = 40000, AOI_GEOTIFF_CAP_KM2 = 600;
function bboxAreaKm2(bb) {
  const [w, s, e, n] = bb;
  const mid = ((s + n) / 2) * Math.PI / 180;
  const widthM = Math.abs(e - w) * 111320 * Math.cos(mid);
  const heightM = Math.abs(n - s) * 111320;
  return (widthM * heightM) / 1e6;
}

const getJSON = async (url) => (await fetch(url)).json();
const postJSON = async (url, body) => (await fetch(url,
  { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }));

// ---------------- tree ----------------
// the source->merge map, so a leaf can show which merge it's been relabelled into (#1)
function mergeOf(cls) { return MERGES.find((m) => (m.sources || []).includes(cls)); }

function renderTree() {
  const box = $("tree"); box.innerHTML = "";
  const walk = (cls, depth) => {
    const n = TREE[cls];
    const color = n.color || "#666";
    const isLeaf = !(n.children || []).length;
    const tag = n.classifier ? '<span class="tag">clf</span>' : "";
    // a leaf that's been merged shows a coloured "-> target" tag right on the tree
    const mr = isLeaf ? mergeOf(cls) : null;
    const mtag = mr ? `<span class="tag merge" style="color:${mr.color || "#8e44ad"}">→ ${mr.name}</span>` : "";
    // only leaves can be merge sources, so only leaves get the tick
    const chk = isLeaf
      ? `<input type="checkbox" class="mchk" data-cls="${cls}"${mergeSel.has(cls) ? " checked" : ""}>` : "";
    const div = document.createElement("div");
    div.className = "node" + (cls === selected ? " sel" : "");
    div.style.paddingLeft = 6 + depth * 14 + "px";
    div.innerHTML = `${chk}<span class="swatch" style="background:${color}"></span>${n.name}${tag}${mtag}`;
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
  box.insertAdjacentHTML("beforeend", `<div class="merge-head">Merges (cross-model)</div>`);
  MERGES.forEach((m) => {
    const div = document.createElement("div");
    div.className = "node merge-node";
    div.style.paddingLeft = "6px";
    div.innerHTML = `<span class="swatch" style="background:${m.color || "#8e44ad"}"></span>${m.name}
      <span class="src">← ${(m.sources || []).join(", ")}</span>
      <button class="rm" data-t="${m.target}" title="undo merge">✕</button>`;
    div.querySelector(".rm").onclick = () => removeMerge(m.target);
    box.appendChild(div);
  });
}

function select(cls) {
  selected = cls;
  $("selName").textContent = TREE[cls].name;
  renderTree();
  renderContext(cls);
  updateDataDist();
}

// the right panel is contextual (#8): it names the selected class, says what it is, and shows only
// the actions that make sense for it — de-emphasising the rest so the panel stays uncluttered (#10).
function renderContext(cls) {
  const n = TREE[cls];
  if (!n) return;
  const isLeaf = !(n.children || []).length;
  const hasClf = !!n.classifier;
  $("ctxHead").textContent = `Selected: ${n.name}`;
  // a one-line "what this is / what to do next", so the user always knows their next move (#6)
  let what;
  if (cls === "root") what = "The whole map. Split a base class, or pick one on the left to refine it.";
  else if (hasClf) what = `A trained split into ${(n.children || []).join(" / ")}. Mark more data and Retrain, or Merge/Split further.`;
  else if (isLeaf) what = "A leaf class. Mark example data, then Split or Add sub-classes and Retrain.";
  else what = `Has children (${(n.children || []).join(" / ")}) but no trained split yet — mark data for each, then Retrain.`;
  $("ctxWhat").textContent = what;

  // swap the "X" placeholders in the block hints for the real class name
  document.querySelectorAll("#context .ctxcls").forEach((s) => (s.textContent = n.name));

  // relevance: leaves emphasise Split/Add; a node with children emphasises Retrain; Merge is for
  // leaves. We dim (not hide) the less-relevant blocks so everything stays discoverable.
  // dim AND gate: a muted block also gets its inputs disabled, so a dimmed action can't fire on the
  // wrong selected class (#10 — muting alone left the buttons live).
  const dim = (id, off) => {
    $(id).classList.toggle("muted", off);
    $(id).querySelectorAll("button, input, select").forEach((el) => (el.disabled = off));
  };
  dim("ctxSplit", !isLeaf);                 // only a leaf splits into new children
  dim("ctxRuleSplit", !isLeaf);             // a rule split also acts on a leaf (#12)
  dim("ctxAdd", false);                     // add is always available
  dim("ctxMerge", cls === "root");          // root itself isn't a merge source
  dim("ctxRetrain", isLeaf && !hasClf);     // nothing to retrain until it has a split

  // flow-gate the balancing / multi-year fields (#12): they only make sense when the user is
  // training their own split (a node with children, not a bare leaf or the base pooled model).
  const ownTraining = !isLeaf && cls !== "root";
  $("retrainAdvanced").classList.toggle("hidden", !ownTraining);
  updateTesseraAvailability();
}

// Tessera training is offered only when the AOI sits inside one of the 4 prepared sites (#16)
function updateTesseraAvailability() {
  const row = $("embeddingRow");
  if (!row) return;
  const bb = currentBbox();
  const inSite = bb && Object.values(TESSERA_SITES).some((s) => bboxOverlap(s, bb));
  row.classList.toggle("hidden", !inSite);
  if (!inSite && $("embedding")) $("embedding").value = "ae";   // fall back off-site
  refreshModelFamilies();       // the valid model list depends on the chosen feature source (#1)
}

// #1/#7: the algorithm dropdown is driven by the inference data — Alpha Earth offers the linear
// models (band math -> crisp tiles) plus Random Forest (point-grid render); Tessera-local adds
// XGBoost and a planned object-detection family. The point-grid caveat rides each option's tooltip.
async function refreshModelFamilies() {
  const algo = $("algo"); if (!algo) return;
  const src = ($("embedding") && $("embedding").value === "tessera") ? "tessera" : "alphaearth";
  let fams;
  try { fams = (await getJSON(`/api/model-families?source=${src}`)).families; }
  catch { return; }
  const keep = algo.value;
  algo.innerHTML = "";
  fams.forEach((f) => {
    const label = f.label + (f.kind === "object" ? "" : "") + (f.available ? "" : " (unavailable)");
    const o = new Option(label, f.id);
    if (!f.available) o.disabled = true;
    if (f.note) o.title = f.note;
    algo.add(o);
  });
  algo.value = [...algo.options].some((o) => o.value === keep && !o.disabled) ? keep : "linearsvc";
}

// ---------------- operations / schema view (#13) ----------------
// the same scheme seen as the ordered steps that built it. Clicking a step selects its class so the
// right panel drives the action (retrain / split / merge) — both views feed one contextual panel.
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
  if (["split", "add"].includes(e.op)) return a.parent;
  if (["retrain", "apply"].includes(e.op)) return a.node;
  if (["base_select", "reset", "import_hierarchy"].includes(e.op)) return "root";
  return null;                       // merges target a virtual (non-tree) class — nothing to select
}

// a short human line for one op, from its args/result
function opSummary(e) {
  const a = e.args || {};
  const names = (cs) => (cs || []).map((c) => (typeof c === "string" ? c : c.name)).join(" / ");
  switch (e.op) {
    case "split":         return `${a.parent} → ${names(a.children)}`;
    case "add":           return `${a.name} under ${a.parent}`;
    case "retrain":       return `${a.node}${a.years && a.years.length ? " · years " + a.years.join("/") : ""}`
                                 + `${a.balance && a.balance !== "balanced" ? " · " + a.balance : ""}`;
    case "merge":         return `${(a.sources || []).join(" + ")} → ${a.name || a.target}`;
    case "merge_remove":  return `undo ${a.target}`;
    case "apply":         return `${a.card_id}${a.node ? " → " + a.node : ""}`;
    case "base_select":   return `scheme → ${a.scheme}`;
    case "reset":         return `to ${a.scheme}`;
    case "import_hierarchy": return `loaded scheme`;
    default:              return "";
  }
}

async function renderOps() {
  const box = $("ops");
  let ops = [];
  try { ops = (await getJSON(`/api/oplog?since=${sessionStartSeq || 0}`)).ops || []; } catch { ops = []; }
  if (!ops.length) {
    box.innerHTML = `<p class="hint">No steps yet this session. Split, add, merge, or retrain a class
      and the sequence that builds your scheme shows up here.</p>`;
    return;
  }
  box.innerHTML = "";
  ops.forEach((e, i) => {
    const node = opTargetNode(e);
    const div = document.createElement("div");
    div.className = "op-row" + (node && node === selected ? " sel" : "") + (node ? "" : " noclick");
    div.innerHTML = `<span class="op-seq">${i + 1}</span>
      <span class="op-verb v-${e.op}">${e.op}</span>
      <span class="op-sum">${opSummary(e)}</span>`;
    if (node) div.onclick = () => { if (TREE[node]) select(node); renderOps(); };
    box.appendChild(div);
  });
}

// live "data so far" for the split this class belongs to: per-class counts + a balance guideline,
// shown right where the user adds data so they can spot skew before retraining.
async function updateDataDist() {
  const box = $("dataDist");
  const node = TREE[selected];
  if (!box || !node) { if (box) box.innerHTML = ""; return; }
  // the sibling set = this node's children if it has them, else its parent's children
  const group = (node.children && node.children.length) ? selected : node.parent;
  const sibs = group ? (TREE[group].children || []) : [];
  if (sibs.length < 2) { box.innerHTML = ""; return; }   // nothing to compare against

  let sum = {};
  try { sum = await getJSON("/api/examples/summary"); } catch { return; }
  const rows = sibs.map((c) => ({ c, n: (sum[c] || {}).positive || 0 }));
  const counts = rows.map((r) => r.n);
  if (Math.max(...counts) === 0) { box.innerHTML = ""; return; }   // no added data yet, stay hidden
  const max = Math.max(...counts, 1);
  // highlight the class we're acting on right now, so switching tea<->non_tea visibly changes
  const bars = rows.map((r) =>
    `<div class="dd-row${r.c === selected ? " sel" : ""}"><span class="sw" style="background:${COLORS[r.c] || "#888"}"></span>
      <span class="dd-name">${r.c}</span>
      <span class="dd-bar"><i style="width:${Math.round(100 * r.n / max)}%"></i></span>
      <span class="dd-n">${r.n}</span></div>`).join("");

  // guideline
  const nonzero = counts.filter((n) => n > 0);
  let hint, col;
  if (nonzero.length < sibs.length) { hint = "some classes have no examples yet — add a few before retraining."; col = "#e0b341"; }
  else {
    const ratio = Math.max(...counts) / Math.min(...counts);
    if (ratio <= 3) { hint = `balanced (${ratio.toFixed(1)}:1).`; col = "#3ddc84"; }
    else if (ratio <= 5) { hint = `mild imbalance (${ratio.toFixed(1)}:1) — class weighting handles it.`; col = "#e0b341"; }
    else { hint = `imbalanced (${ratio.toFixed(1)}:1) — oversample the minority at retrain.`; col = "#ff7b72"; }
  }
  const splitName = (TREE[group] || {}).name || group;
  box.innerHTML = `<div class="dd-title">Data so far — ${splitName} split</div>${bars}
    <div class="dd-hint" style="color:${col}">${hint}</div>`;
}

let currentOpSeq = 0;         // the op-log head the server last reported (#4)

async function refreshTree(data) {
  data = data || await getJSON("/api/tree");
  TREE = data.tree; COLORS = data.colors;
  if (data.op_seq != null) currentOpSeq = data.op_seq;
  if (!TREE[selected]) selected = "root";
  await loadMerges();         // pulls the rules, then renders the tree (merges drawn on it)
  renderContext(selected);
  if (viewMode === "ops") renderOps();     // keep the operations view current after each action (#13)
}

// the active merges feed the tree (source tags + virtual nodes). Drop ticks for leaves that no
// longer exist so a stale selection can't leak into the next merge.
async function loadMerges() {
  try { MERGES = (await getJSON("/api/merge")).rules || []; } catch { MERGES = []; }
  for (const c of [...mergeSel]) if (!TREE[c] || (TREE[c].children || []).length) mergeSel.delete(c);
  renderTree();
}

// ---------------- init ----------------
async function init() {
  const r = await getJSON("/api/presets");
  PRESETS = r.presets;
  const sel = $("preset");
  Object.keys(PRESETS).forEach((k) => sel.add(new Option(k, k)));
  sel.add(new Option("Custom (lat/lon)", "__custom__"));
  lastPreset = sel.value;
  sel.onchange = onAreaSelect;
  await refreshTree();
  drawAoi();                                    // show the starting AOI box straight away (#3)
  // anchor the session to the current op-log head so export ships only this session's steps (#4).
  // Kept in localStorage so a page refresh doesn't reset the session mid-work.
  const stored = localStorage.getItem("sessionStartSeq");
  sessionStartSeq = stored != null ? Number(stored) : currentOpSeq;
  localStorage.setItem("sessionStartSeq", sessionStartSeq);
  await refreshZooBadge();
  try { TESSERA_SITES = (await getJSON("/api/tessera-sites")).sites || {}; } catch { /* Tessera opt is best-effort */ }
  try { STANDARDS = await getJSON("/api/standards"); } catch { /* pick-list is best-effort */ }
  try { INFER_OPTS = await getJSON("/api/inference-options"); } catch { /* year picker is best-effort */ }
  await loadRuleRegistry();          // the index vars for a rule split (#12)
  if ($("embedding")) $("embedding").onchange = refreshModelFamilies;   // data drives the model list (#1)
  await refreshModelFamilies();
  // every launch starts by choosing the base classes (the tool's "on arrival" step). The current
  // scheme is tagged; picking it just proceeds, so this isn't destructive unless you switch.
  updateTesseraAvailability();       // now that TESSERA_SITES is loaded, reflect the default AOI (#16)
  await showBaseOnboard();
}

// ---------------- first-run base-class chooser (#5) ----------------
// before doing anything, let the user choose which base scheme to build on. Picking a different
// scheme reseeds the tree (destructive, so we confirm); picking the current one just proceeds.
async function showBaseOnboard() {
  let b;
  try { b = await getJSON("/api/base"); } catch { return; }   // no base endpoint -> skip onboarding
  const box = $("baseOptions"); box.innerHTML = "";
  Object.entries(b.schemes).forEach(([k, v]) => {
    const div = document.createElement("div");
    div.className = "onboard-opt" + (k === b.active ? " active" : "");
    div.innerHTML = `<div class="oo-title">${v.label}${k === b.active ? ' <span class="tag">current</span>' : ""}</div>
      <div class="oo-cls">${(v.classes || []).join(", ")}</div>`;
    div.onclick = () => chooseBase(k, b.active);
    box.appendChild(div);
  });
  $("base-onboard").classList.remove("hidden");
}

async function chooseBase(scheme, active) {
  if (scheme !== active) {
    if (!await uiConfirm(`Start from "${scheme}"?\n\nThis sets your base classes and clears any ` +
                         `existing splits/merges.`, { okText: "Switch base", danger: true })) return;
    setStatus(`Setting base to ${scheme}…`, "work");
    const r = await postJSON("/api/base/select", { scheme });
    const d = await r.json();
    if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
    await refreshTree(d);
  }
  endBaseOnboard();
  await runClassify();
}

function endBaseOnboard() { $("base-onboard").classList.add("hidden"); }
$("baseSkip").onclick = endBaseOnboard;

$("half").oninput = (e) => {
  $("halfval").textContent = parseFloat(e.target.value).toFixed(3);
  customBbox = null;                 // the slider means "centre + half", so drop any drawn box
  drawAoi();                         // grow/shrink the AOI box live with the degree (#3)
};

// ---------------- area change → offer a fresh start (#5) ----------------
// picking a different preset (or moving to a new custom spot) is a new area, and a hierarchy built
// for the old place doesn't belong here. So we offer to reset to the base scheme — but only if the
// user actually built something, and only after they confirm (their splits/merges would be cleared).
async function onAreaSelect() {
  const sel = $("preset");
  $("custom").classList.toggle("hidden", sel.value !== "__custom__");
  if (sel.value !== "__custom__") customBbox = null;
  drawAoi();
  const changed = sel.value !== lastPreset;
  lastPreset = sel.value;
  const didReset = changed ? await maybeResetForNewArea() : false;
  if (!didReset) await runClassify();
}

// has the user grown the tree past the untouched base scheme? The base is root + its direct base
// leaves; so a trained classifier, an active merge, or any node nested below a base leaf (parent
// isn't root) all mean real work worth confirming before we wipe it.
function hasUserEdits() {
  if (MERGES.length) return true;
  return Object.values(TREE).some((n) => n.classifier ||
    (n.parent && n.parent !== "root"));
}

// confirm + reset the hierarchy for a new area. Returns true if it reset (so the caller doesn't
// double-classify). No-ops silently when the tree is still untouched base classes.
async function maybeResetForNewArea() {
  if (!hasUserEdits()) return false;
  const ok = await uiConfirm(
    "New area — start fresh?\n\nYour splits, merges, and marked example data will be cleared " +
    "(trained models stay in the Model Zoo). Download the hierarchy first if you want to keep the steps.",
    { okText: "Start fresh", danger: true });
  if (!ok) return false;
  return performReset();
}

// do the actual reset: reseed the base, empty the example canvas (#4), start a fresh session (#4)
async function performReset() {
  setStatus("Resetting to the base scheme…", "work");
  const r = await postJSON("/api/session/reset", {});
  const d = await r.json();
  if (!r.ok) { setStatus("Reset failed: " + (d.detail || r.status), "err"); return false; }
  await refreshTree(d);
  bumpSession();
  select("root");
  await refreshZooBadge();
  await runClassify();
  const cleared = (d.cleared_examples || []).length;
  setStatus(`Reset to base${cleared ? ` — cleared ${cleared} example set(s)` : ""}.`, "ok");
  return true;
}

// left-panel view toggle (#13): hierarchy tree vs the ordered operations that built the scheme
$("viewHier").onclick = () => setLeftView("hierarchy");
$("viewOps").onclick = () => setLeftView("ops");

// "use a model from the Zoo" to split the selected class (#13): open the zoo; the user picks a model
// and hits "Apply to selected class" on its card (which runs the #11 compatibility check).
$("splitFromZoo").onclick = () => {
  openZoo();
  setStatus(`Pick a model, then "Apply to selected class “${(TREE[selected] || {}).name || selected}”" on its card.`, "info");
};

// the manual "Start fresh" button: same reset, available on the current area without changing it
$("startFresh").onclick = async () => {
  const ok = await uiConfirm(
    "Reset to the base scheme?\n\nThis clears your splits, merges, and marked example data " +
    "(trained models stay in the Model Zoo).", { okText: "Start fresh", danger: true });
  if (ok) await performReset();
};

// move the session anchor to the current op-log head (new area / after import) so a later export
// carries only what happens from here on (#4).
function bumpSession() {
  sessionStartSeq = currentOpSeq;
  localStorage.setItem("sessionStartSeq", sessionStartSeq);
}

// ---------------- classify ----------------
async function runClassify() {
  const [w, s, e, n] = currentBbox();
  // one model now (#2): Alpha Earth served server-side as 10 m EE tiles, at the year set in the zoo.
  const year = inferYear;
  setStatus("Classifying at 10 m…", "work");
  $("run").disabled = true;
  drawAoi();
  try {
    const data = await getJSON(
      `/api/classify?west=${w}&south=${s}&east=${e}&north=${n}&mode=realistic&year=${year}`);
    if (data.detail) { setStatus(data.detail, "err"); $("run").disabled = false; return; }  // e.g. AOI too large (#3)
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    if (data.render === "tiles") {
      // Earth Engine map tiles: crisp at any zoom, EE serves them on demand (no download)
      rasterLayer = L.tileLayer(data.tile_url,
        { opacity: 0.7, bounds: [[s, w], [n, e]] }).addTo(map);
    } else if (data.render === "raster") {
      const [bw, bs, be, bn] = data.bounds;
      rasterLayer = L.imageOverlay(data.image_url, [[bs, bw], [bn, be]], { opacity: 0.7 }).addTo(map);
    } else {
      const cw = data.cell_w / 2, ch = data.cell_h / 2;
      data.cells.forEach((c) => {
        L.rectangle([[c.lat - ch, c.lon - cw], [c.lat + ch, c.lon + cw]],
          { stroke: false, fillOpacity: 0.55, fillColor: data.colors[c.pred] || "#999" })
          .addTo(predLayer);
      });
    }
    map.fitBounds([[s, w], [n, e]]);
    overlayVisible = true;                        // a fresh render is shown; reset the eye toggle (#21)
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    setStatus("Done: " + JSON.stringify(data.counts));
  } catch (err) { setStatus("Error: " + err, "err"); }
  $("run").disabled = false;
}
$("run").onclick = runClassify;

// ---------------- water on a fortnight (5, 7) ----------------
// separate from the annual LULC: raw Sentinel classified for one date, rendered as EE tiles.
async function runWater() {
  const [w, s, e, n] = currentBbox();
  const date = $("waterDate").value;
  if (!date) { setStatus("Pick a date for the water map.", "err"); return; }
  setStatus(`Mapping water for ${date}…`, "work");
  $("runWater").disabled = true;
  drawAoi();
  try {
    const d = await getJSON(`/api/water?west=${w}&south=${s}&east=${e}&north=${n}&date=${date}`);
    if (d.detail) { setStatus(d.detail, "err"); $("runWater").disabled = false; return; }
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    rasterLayer = L.tileLayer(d.tile_url, { opacity: 0.75, bounds: [[s, w], [n, e]] }).addTo(map);
    map.fitBounds([[s, w], [n, e]]);
    overlayVisible = true;
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    setStatus(`Water on ${date}: ${JSON.stringify(d.counts)}`);
  } catch (err) { setStatus("Water error: " + err, "err"); }
  $("runWater").disabled = false;
}
$("runWater").onclick = runWater;

// ---------------- water frequency over a year (#11 wk10) ----------------
// counts how many fortnights each pixel held water; served as a blue-ramp tile layer.
async function runWaterFreq() {
  const [w, s, e, n] = currentBbox();
  setStatus("Counting water fortnights over the year… (runs the model ~24×)", "work");
  $("runWaterFreq").disabled = true;
  drawAoi();
  try {
    const d = await getJSON(`/api/water-frequency?west=${w}&south=${s}&east=${e}&north=${n}&year=${inferYear}`);
    if (d.detail) { setStatus(d.detail, "err"); return; }
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    rasterLayer = L.tileLayer(d.tile_url, { opacity: 0.8, bounds: [[s, w], [n, e]] }).addTo(map);
    map.fitBounds([[s, w], [n, e]]);
    overlayVisible = true;
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    setStatus(`Water frequency ${d.stats.year}: 0–${d.stats.max} fortnights (mean ${d.stats.mean})`);
  } catch (err) { setStatus("Water-frequency error: " + err, "err"); }
  finally { $("runWaterFreq").disabled = false; }
}
$("runWaterFreq").onclick = runWaterFreq;

// ---------------- biomass overlay (AGBD regression) (#3 wk10) ----------------
// a continuous quantity, not classes, so it draws on the point grid with a green ramp: light ->
// dark green as AGBD climbs from the run's min to max. Renders like the tessera/detailed cells.
function biomassColor(v, lo, hi) {
  const t = hi > lo ? Math.max(0, Math.min(1, (v - lo) / (hi - lo))) : 0.5;
  // pale yellow-green (#e8f5c8) -> deep green (#1b5e20)
  const a = [232, 245, 200], b = [27, 94, 32];
  const ch = a.map((x, i) => Math.round(x + (b[i] - x) * t));
  return `rgb(${ch[0]},${ch[1]},${ch[2]})`;
}
async function runBiomass() {
  const [w, s, e, n] = currentBbox();
  setStatus("Mapping biomass (AGBD)…", "work");
  $("runBiomass").disabled = true;
  drawAoi();
  try {
    const d = await getJSON(`/api/biomass?west=${w}&south=${s}&east=${e}&north=${n}&year=${inferYear}`);
    if (d.detail) { setStatus(d.detail, "err"); $("runBiomass").disabled = false; return; }
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    const cw = d.cell_w / 2, ch = d.cell_h / 2, lo = d.ramp.min, hi = d.ramp.max;
    d.cells.forEach((c) => {
      if (c.val == null) return;                 // no embedding here -> leave transparent
      L.rectangle([[c.lat - ch, c.lon - cw], [c.lat + ch, c.lon + cw]],
        { stroke: false, fillOpacity: 0.6, fillColor: biomassColor(c.val, lo, hi) }).addTo(predLayer);
    });
    map.fitBounds([[s, w], [n, e]]);
    overlayVisible = true;
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    // legend: min .. max Mg/ha
    const ramp = $("biomassRamp");
    ramp.classList.remove("hidden");
    ramp.innerHTML = `<i style="background:${biomassColor(lo, lo, hi)}"></i>${lo.toFixed(0)}` +
      `<i style="background:${biomassColor(hi, lo, hi)}"></i>${hi.toFixed(0)} ${d.ramp.units}`;
    setStatus(`Biomass: ${lo.toFixed(0)}–${hi.toFixed(0)} ${d.ramp.units} (mean ${d.ramp.mean.toFixed(0)})`);
  } catch (err) { setStatus("Biomass error: " + err, "err"); }
  $("runBiomass").disabled = false;
}
$("runBiomass").onclick = runBiomass;

// ---------------- mining segmentation (vectorize a class) (#4 wk10) ----------------
// turn the mining pixels into discrete cleaned polygons drawn as outlines, with per-segment area.
let segmentGeojson = null;
let segmentClass = "mining";       // which class the last segmentation ran on (for the download name)
async function runSegment() {
  const [w, s, e, n] = currentBbox();
  // segment the class the user has selected (any leaf), not a hard-wired one (#10). Fall back to
  // mining when nothing useful is selected, since that's the canonical example.
  const cls = (TREE[selected] && !(TREE[selected].children || []).length && selected !== "root")
    ? selected : "mining";
  segmentClass = cls;
  setStatus(`Segmenting ${cls}…`, "work");
  $("runSegment").disabled = true;
  drawAoi();
  try {
    const d = await getJSON(`/api/segment?west=${w}&south=${s}&east=${e}&north=${n}&cls=${cls}&year=${inferYear}`);
    if (d.detail) { setStatus(d.detail, "err"); return; }
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    segmentGeojson = d.geojson;
    L.geoJSON(d.geojson, { style: { color: "#ff7b00", weight: 2, fillColor: "#ff7b00", fillOpacity: 0.35 },
      onEachFeature: (f, l) => l.bindTooltip(`${cls} · ${f.properties.area_ha} ha`) }).addTo(predLayer);
    if (d.summary.n_segments) map.fitBounds(L.geoJSON(d.geojson).getBounds());
    overlayVisible = true;
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    $("dlSegment").classList.toggle("hidden", !d.summary.n_segments);
    setStatus(`${cls}: ${d.summary.n_segments} segments, ${d.summary.total_area_ha} ha total`);
  } catch (err) { setStatus("Segment error: " + err, "err"); }
  finally { $("runSegment").disabled = false; }
}
$("runSegment").onclick = runSegment;
$("dlSegment").onclick = () => {
  if (!segmentGeojson) return;
  const blob = new Blob([JSON.stringify(segmentGeojson)], { type: "application/geo+json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `${segmentClass}_segments.geojson`; a.click();
  URL.revokeObjectURL(a.href);
};

// ---------------- IndiaSAT EE-native RF models (#13 wk10) ----------------
// tree/crop (SAR) and farm/shrub (Alpha Earth, per-AEZ) both train + classify in Earth Engine, so
// they come back as tile layers just like the base map. A small colour legend shows under the buttons.
function eeRfLegend(colors, counts) {
  return Object.keys(colors).map((c) =>
    `<span style="display:inline-flex;align-items:center;gap:3px;margin-right:8px">
       <i style="width:12px;height:12px;border-radius:2px;background:${colors[c]};display:inline-block"></i>
       ${c}${counts && counts[c] ? ` (${counts[c]})` : ""}</span>`).join("");
}
async function runEeRf(btnId, url, label) {
  const btn = $(btnId);
  const [w, s, e, n] = currentBbox();
  setStatus(`${label}…`, "work");
  btn.disabled = true;
  drawAoi();
  try {
    const d = await getJSON(`${url}&west=${w}&south=${s}&east=${e}&north=${n}`);
    if (d.detail) { setStatus(d.detail, "err"); return; }
    predLayer.clearLayers();
    if (rasterLayer) { map.removeLayer(rasterLayer); rasterLayer = null; }
    rasterLayer = L.tileLayer(d.tile_url, { opacity: 0.75, bounds: [[s, w], [n, e]] }).addTo(map);
    map.fitBounds([[s, w], [n, e]]);
    overlayVisible = true;
    if ($("eyeToggle")) { $("eyeToggle").textContent = "👁"; $("eyeToggle").classList.remove("off"); }
    $("eeRfLegend").innerHTML = eeRfLegend(d.colors, d.counts);
    setStatus(`${label}: ${JSON.stringify(d.counts)}`);
  } catch (err) { setStatus(`${label} error: ` + err, "err"); }
  finally { btn.disabled = false; }
}
$("runTreecrop").onclick = () => runEeRf("runTreecrop", "/api/treecrop?", "Tree vs crop (SAR)");
$("runFarmshrub").onclick = () => runEeRf("runFarmshrub", `/api/farmshrub?year=${inferYear}`, "Farm/shrub (AEZ)");

// ---------------- overlay eye-toggle (#21) ----------------
// hide/show the classification layer(s) without reclassifying, so the user can see the basemap under it
let overlayVisible = true;
function applyOverlayVisibility() {
  const layers = [rasterLayer, predLayer].filter(Boolean);
  layers.forEach((l) => (overlayVisible ? l.addTo(map) : map.removeLayer(l)));
  $("eyeToggle").textContent = overlayVisible ? "👁" : "🚫";
  $("eyeToggle").classList.toggle("off", !overlayVisible);
}
$("eyeToggle").onclick = () => { overlayVisible = !overlayVisible; applyOverlayVisibility(); };

// ---------------- download the classified output as GeoTIFF (#24) ----------------
$("dlTif").onclick = async () => {
  const [w, s, e, n] = currentBbox();
  setStatus("Preparing GeoTIFF (server-side export)…", "work");
  $("dlTif").disabled = true;                     // guard against double-firing concurrent exports (#10)
  try {
    const d = await getJSON(`/api/classify.tif?west=${w}&south=${s}&east=${e}&north=${n}&year=${inferYear}`);
    if (!d.url) { setStatus("GeoTIFF export failed: " + (d.detail || "no url"), "err"); return; }
    window.open(d.url, "_blank");                 // EE serves the .tif; the browser downloads it
    const legend = (d.classes || []).map((c, i) => `${i}=${c}`).join(", ");
    setStatus(`GeoTIFF ready — integer classes: ${legend}`, "ok");
  } catch (err) { setStatus("GeoTIFF export failed: " + err, "err"); }
  finally { $("dlTif").disabled = false; }
};

// ---------------- examples ----------------
$("addDrawn").onclick = async () => {
  if (!lastGeometry) { setStatus("Draw a polygon on the map first.", "err"); return; }
  const r = await postJSON("/api/examples",
    { node: selected, geometry: lastGeometry, role: $("role").value });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  const ds = d.dataset ? ` — dataset card ${d.dataset} updated` : "";
  setStatus(`Added ${d.role} example to "${selected}" (it now has ${d.total})${ds}.`, "ok");
  drawnLayer.clearLayers(); lastGeometry = null;
  await updateDataDist();
  await refreshZooBadge(); if (isZooOpen()) await loadZooFull();
};

$("upload").onchange = async () => {
  const f = $("upload").files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f); fd.append("node", selected); fd.append("role", $("role").value);
  setStatus(`Uploading ${f.name} → "${selected}"…`, "work");
  const r = await fetch("/api/examples/upload", { method: "POST", body: fd });
  const d = await r.json();
  const ds = d.dataset ? ` (dataset card ${d.dataset} updated)` : "";
  setStatus(r.ok ? `Uploaded ${f.name}: "${selected}" now has ${d.total} examples${ds}.`
                 : "Error: " + (d.detail || r.status), r.ok ? "ok" : "err");
  $("upload").value = "";
  if (r.ok) { await updateDataDist(); await refreshZooBadge(); if (isZooOpen()) await loadZooFull(); }
};

// ---------------- operations ----------------
$("doSplit").onclick = async () => {
  const names = $("splitNames").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (names.length < 2) { setStatus("Give at least two child names.", "err"); return; }
  const r = await postJSON("/api/split",
    { parent: selected, children: names.map((name) => ({ name })) });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  $("splitNames").value = "";
  await refreshTree(d);
  setStatus(`Split "${selected}". Now add examples to each child, then Retrain.`, "ok");
};

// ---------------- rule-based split (#12) ----------------
let RULE_VARS = {};
async function loadRuleRegistry() {
  try { RULE_VARS = (await getJSON("/api/rules/registry")).variables || {}; }
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
// compile the simple picker (or the advanced expression) into a rule the backend understands
function buildRule() {
  const trueCls = $("ruleTrue").value.trim(), falseCls = $("ruleFalse").value.trim();
  if (!trueCls || !falseCls) throw new Error("Name the class for both the true and the else case.");
  const raw = $("ruleExpr").value.trim();
  const when = raw || `${$("ruleVar").value} ${$("ruleOp").value} ${$("ruleThresh").value}`;
  return { clauses: [{ when, class: trueCls }], default: falseCls };
}
$("doRuleSplit").onclick = async () => {
  let rule;
  try { rule = buildRule(); } catch (e) { setStatus(e.message, "err"); return; }
  const r = await postJSON("/api/split/rule", { parent: selected, rule });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  $("ruleTrue").value = ""; $("ruleFalse").value = ""; $("ruleExpr").value = "";
  await refreshTree(d);
  await runClassify();                     // rule renders as tiles right away — show it
  setStatus(`Rule split "${selected}" → ${d.classes.join(" / ")}.`, "ok");
};

$("doAdd").onclick = async () => {
  const name = $("addName").value.trim();
  if (!name) { setStatus("Enter a class name.", "err"); return; }
  const r = await postJSON("/api/add", { parent: selected, name });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  $("addName").value = "";
  await refreshTree(d);
  setStatus(`Added "${name}" under "${selected}". Add examples, then Retrain.`, "ok");
};

$("doRetrain").onclick = async () => {
  const btn = $("doRetrain");
  // parse "2019, 2021, 2023" into a year list; blank -> null (single-year 2024). (#3)
  const years = ($("trainYears").value.match(/\d{4}/g) || []).map(Number);
  const yearNote = years.length ? ` across ${years.join("/")}` : "";
  btn.disabled = true; btn.textContent = "Working… (sampling + training)";
  $("metrics").textContent = "";
  const embedding = ($("embedding") && !$("embeddingRow").classList.contains("hidden"))
    ? $("embedding").value : "ae";                  // Tessera only when the row is enabled (site AOI)
  // #6: show the expected time (from the benchmark profile) and tick a live elapsed counter while it
  // trains, so the run has a real progress signal instead of a static "working…".
  const est = await fetchEstimate($("algo").value);
  const stopTimer = startWorkTimer(`Retraining "${selected}"${yearNote}`, est);
  try {
    const r = await postJSON("/api/retrain",
      { node: selected, balance: $("balance").value, years: years.length ? years : null,
        algo: $("algo").value, embedding });
    stopTimer();
    const d = await r.json();
    if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); }
    else {
      await refreshTree(d);
      $("metrics").textContent = formatReport(d.report, d.n_test);
      const teNote = embedding === "tessera" ? " (Tessera — scored + carded; not on the tile map)" : "";
      setStatus(`Retrained "${selected}"${teNote} — re-rendering the map…`, "ok");
      await refreshZooBadge();                          // the new model card just landed
      if (isZooOpen()) await loadZooFull();
      await runClassify();
    }
  } catch (err) { stopTimer(); setStatus("Error: " + err, "err"); }
  btn.disabled = false; btn.textContent = "Retrain & apply";
};

// ---------------- merge classes (#9) ----------------
// a merge relabels chosen leaves (possibly from different models) into one new class. The leaves
// are now ticked straight in the hierarchy tree (mergeSel); name + colour it, and it's applied as
// a relabel layer on the next classify. The result shows back on the tree (see renderTree).
$("doMerge").onclick = async () => {
  const sources = [...mergeSel];
  const name = $("mergeName").value.trim();
  if (sources.length < 2) { setStatus("Tick at least two leaf classes in the Hierarchy to merge.", "err"); return; }
  if (!name) { setStatus("Name the merged class.", "err"); return; }
  const r = await postJSON("/api/merge", { name, sources, color: $("mergeColor").value });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  $("mergeName").value = "";
  mergeSel.clear();
  await refreshTree(d);
  await refreshZooBadge();                       // the merge just minted a local model card
  if (isZooOpen()) await loadZooFull();
  setStatus(`Merged ${sources.join(" + ")} → "${name}". Re-classifying…`, "ok");
  await runClassify();
};

// undo a merge (the ✕ on its virtual node in the tree): the source leaves come back on their own.
async function removeMerge(target) {
  const r = await fetch(`/api/merge/${target}`, { method: "DELETE" });
  const d = await r.json();
  if (!r.ok) { setStatus("Error removing merge.", "err"); return; }
  await refreshTree(d);
  await refreshZooBadge();                       // its local card is gone now
  if (isZooOpen()) await loadZooFull();
  setStatus(`Removed merge "${target}". Re-classifying…`, "ok");
  await runClassify();
}

// ---------------- save / resume project (#4 / #18 / #23) ----------------
// A project is the class scheme + the *sequence* of steps that built it (not a running log, #18),
// wrapped with the area / year / base so a reload resumes the exact view — geolibre-style (#23).
// Datasets/models ride as links (ids + paths in classifier_refs), never copied into the file.
$("exportHier").onclick = async () => {
  setStatus("Preparing project download…", "work");     // busy feedback so a slow export isn't a dead button (#10)
  try {
    const data = await getJSON(`/api/hierarchy/export?since=${sessionStartSeq || 0}`);
    let base = "indiasat";
    try { base = (await getJSON("/api/base")).active || "indiasat"; } catch { /* best-effort */ }
    const project = {
      kind: "corestack-lulc-project", version: 1, created: new Date().toISOString(),
      aoi: currentBbox(), year: inferYear, base_scheme: base,
      hierarchy: data.hierarchy, sequence: data.op_log, classifier_refs: data.classifier_refs,
    };
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "project.json";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("Downloaded your project (scheme + sequence + area/year/base).", "ok");
  } catch (err) { setStatus("Export failed: " + err, "err"); }
};

// STACD provenance (#4): STAC Item + DAG describing how the current output was produced.
$("exportStacd").onclick = async () => {
  setStatus("Building STACD provenance…", "work");
  try {
    const [w, s, e, n] = currentBbox();
    const doc = await getJSON(
      `/api/stacd?west=${w}&south=${s}&east=${e}&north=${n}&year=${inferYear}&since=${sessionStartSeq || 0}`);
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "output.stacd.json";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("Downloaded STACD provenance (STAC Item + DAG + model locations).", "ok");
  } catch (err) { setStatus("STACD export failed: " + err, "err"); }
};

// Resume a saved project. Restores the area/year/base first, then validates + applies the scheme
// (a broken file is rejected before anything mutates). Accepts a project wrapper, an old hierarchy
// export, or a bare tree — so older saves still load.
$("importHier").onchange = async () => {
  const f = $("importHier").files[0];
  if (!f) return;
  setStatus(`Checking ${f.name}…`, "work");
  let file;
  try { file = JSON.parse(await f.text()); }
  catch { setStatus("That file isn't valid JSON.", "err"); $("importHier").value = ""; return; }

  // restore the view first (geolibre-style resume, #23): area, year, then base scheme if different
  if (Array.isArray(file.aoi) && file.aoi.length === 4) {
    customBbox = file.aoi.slice();
    setPresetToCustom();
    drawAoi();
  }
  if (file.year) { inferYear = Number(file.year); localStorage.setItem("inferYear", inferYear); }
  if (file.base_scheme) {
    try {
      const cur = (await getJSON("/api/base")).active;
      if (cur !== file.base_scheme) await postJSON("/api/base/select", { scheme: file.base_scheme });
    } catch { /* base switch is best-effort */ }
  }

  // the scheme envelope for the validate-then-apply importer (sequence -> op_log)
  const body = file.hierarchy
    ? { hierarchy: file.hierarchy, op_log: file.sequence || file.op_log || [] }
    : { hierarchy: file };
  const r = await postJSON("/api/hierarchy/import", body);
  const d = await r.json();
  $("importHier").value = "";
  if (!r.ok) {
    const det = d.detail || {};
    const errs = (det.errors || []).join(" · ") || det.message || det || r.status;
    setStatus("Can't load this project — " + errs, "err");
    return;
  }
  await refreshTree(d);
  bumpSession();                          // a resumed project starts a fresh session for export (#4)
  await refreshZooBadge();
  const miss = (d.missing_classifiers || []).length
    ? ` — ${d.missing_classifiers.length} split(s) need retraining (${d.missing_classifiers.join(", ")})` : "";
  setStatus(`Resumed project${miss}. Re-classifying…`, "ok");
  await runClassify();
};

// ---------------- model zoo (full-screen browser) ----------------
let zooTab = "model";        // which tab the grid shows
let zooCards = [];           // cached index rows
const isZooOpen = () => !$("zoo-overlay").classList.contains("hidden");

async function refreshZooBadge() {
  try {
    const s = await getJSON("/api/zoo/status");
    const loc = (s.uncommitted || []).length;
    const txt = loc ? `· ${loc} unpublished` : "· all published";
    $("zooBadge").textContent = txt;
    $("zooHeadBadge").textContent = txt;
  } catch { /* zoo status is best-effort */ }
}

function openZoo() {
  $("zoo-overlay").classList.remove("hidden");
  loadZooFull();
}
function closeZoo() { $("zoo-overlay").classList.add("hidden"); }

async function loadZooFull() {
  zooCards = (await getJSON("/api/catalogue")).cards;
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

function renderGrid() {
  const grid = $("zoo-grid"); grid.innerHTML = "";
  const rows = zooCards.filter((c) => c.kind === zooTab);
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

function modelTile(m) {
  const arch = isArchived(m.id) ? `<span class="pill arch">archived</span>` : "";
  const pub = m.published ? `<span class="pill pub">published</span>` : `<span class="pill loc">local</span>`;
  const acc = m.accuracy != null ? `accuracy ${m.accuracy.toFixed(2)}` : "—";
  // cheap apply-after hint from the index row (full WorldCover hint shows in the detail pane)
  const after = (m.topology && m.topology !== "base_pooled" && m.node) ? ` · after ${m.node}` : "";
  const div = document.createElement("div");
  div.className = "zoo-card" + (m.id === zooSelected ? " sel" : "");
  div.innerHTML = `<div class="zc-top"><h4>${pubCheckbox(m.id)}${m.name || m.id}</h4>${arch}${pub}</div>
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
  const c = await getJSON(`/api/cards/${id}`);
  $("zoo-detail").innerHTML = id.startsWith("mc_") ? modelDetail(c) : datasetDetail(c);
  renderGrid();   // refresh selection highlight
  // a polygon dataset: fill in coverage-vs-current-AOI right away, so it shows without touching
  // the grid select (#4). recomputeSpread no-ops when there's no spread panel.
  if (!id.startsWith("mc_") && (c.quality || {}).spatial_diversity != null) recomputeSpread(id, 0.25);
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
    ${placementHTML(c)}
    <div class="blk"><span class="k">Produces</span><div class="chips-row">${produceChips(c.produces)}</div></div>
    ${m.accuracy != null ? `<div class="blk"><span class="k">Metrics — acc ${m.accuracy} (${m.eval || ""})</span>
      <table>${perRows}</table></div>` : ""}
    ${balanceFeedback(c)}
    <div class="blk"><span class="k">Training data</span>${dsChips(c.training && c.training.datasets)}</div>
    <div class="blk"><span class="k">Inference features</span>${dsChips([(c.inference || {}).dataset].filter(Boolean))}</div>
    <div class="blk"><span class="k">Valid extent${year ? " · " + year : ""}</span>${extentLineForCard(c)}
      <button id="showExtent">Show on map</button></div>
    <div class="blk"><span class="k">About</span>${aboutRows}
      <button id="annotateToggle">Annotate / evidence / class mapping</button>
      ${annotateForm(c)}</div>
    <div class="blk"><span class="k">Artifact</span><code>${(c.artifact || {}).path || "—"}</code></div>
    ${c.topology === "merge_relabel"
      ? `<div class="prose">Already live as a relabel layer — undo it from the Hierarchy tree.</div>`
      : `<button id="applyBtn" class="primary">${
          c.base_scheme === "worldcover" ? "Use WorldCover base (7 classes)"
          : c.topology === "base_pooled" ? "Use IndiaSAT base (4 classes)"
          : "Use this model (apply to map)"}</button>`}
    ${(c.topology === "per_node_split" && c.node !== selected)
      ? `<button id="applyHereBtn">Apply to selected class “${(TREE[selected]||{}).name||selected}”</button>` : ""}
    <button id="pubBtn">${c.zoo && c.zoo.published ? "Re-publish" : "Publish to zoo"}</button>
    ${(c.zoo && c.zoo.published) ? "" : `<button id="delBtn" class="danger">Delete from zoo</button>`}`;
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
  const [label, col] = ratio <= 3 ? ["balanced", "#3ddc84"]
                     : ratio <= 5 ? ["mild imbalance", "#e0b341"]
                     :              ["imbalanced — consider under/oversampling", "#ff7b72"];
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
    const r = await postJSON(`/api/cards/${id}/annotate`,
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
  const [label, col] = d >= 0.75 ? ["well spread", "#3ddc84"]
                     : d >= 0.5  ? ["moderately spread", "#e0b341"]
                     :             ["clustered — risks skewing the model", "#ff7b72"];
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

function spreadFeedback(q) {
  const d = q.spatial_diversity;
  if (d == null) return "";
  const opts = SPREAD_CELLS.map((c) =>
    `<option value="${c}" ${c === 0.25 ? "selected" : ""}>${c}°</option>`).join("");
  return `<div class="blk"><span class="k">Spread (spatial diversity)</span>
    <label class="spread-grid">grid cell
      <select id="spreadCell">${opts}</select></label>
    <div id="spreadOut">${spreadValueHTML(d, q.occupied_cells, q.n_polygons, 0.25)}</div>
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
    const q = await getJSON(`/api/cards/${id}/spread?cell=${cell}${aoi}`);
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
    ${spreadFeedback(q)}
    <div class="blk"><span class="k">Provenance</span><div class="prose">${p.annotator || "—"} · ${p.method || ""}
      ${p.license ? "· " + p.license : ""}</div></div>
    ${inferenceYearHTML(c)}
    ${sourceLinkHTML(c)}
    <div class="blk"><span class="k">Valid extent${((c.extent || {}).temporal || {}).year ? " · " + c.extent.temporal.year : ""}</span>${extentLineForCard(c)}
      <button id="showExtent">Show on map</button></div>`;
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
  const years = ((INFER_OPTS.realistic || {}).years) || [inferYear];
  const opts = years.map((y) => `<option value="${y}"${y === inferYear ? " selected" : ""}>${y}</option>`).join("");
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
  const geo = await getJSON(`/api/cards/${id}/geometry`);
  if (geo.drawable && (geo.features || []).length) { drawPolygons(geo); return; }
  const c = await getJSON(`/api/cards/${id}`);
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
    const r = await postJSON("/api/publish", { card_ids: [id], contributor: contributor() });
    const d = await r.json();
    setStatus(d.pushed ? `Published "${id}" — pushed to the zoo.`
              : (d.committed ? `Committed "${id}" locally (${d.note}).` : d.note || "Nothing to publish."),
              r.ok ? "ok" : "err");
    await loadZooFull();
    await showCardFull(id);
  } catch (err) { setStatus(`Publish failed: ` + err, "err"); }
}

// ---- zoo overlay wiring ----
$("openZoo").onclick = openZoo;
$("closeZoo").onclick = closeZoo;
$("zooAoi").onchange = loadZooFull;
// publish just the ticked cards (#25) — the backend already takes a card_ids list
$("zooPublishSel").onclick = async () => {
  const ids = [...pubSel];
  if (!ids.length) return;
  setStatus(`Publishing ${ids.length} selected card(s)…`, "work");
  const r = await postJSON("/api/publish", { card_ids: ids, contributor: contributor() });
  const d = await r.json();
  setStatus(d.committed || d.pushed ? `Published ${ids.length} card(s) (${d.note || "done"}).`
            : (d.note || "Nothing to publish."), r.ok ? "ok" : "err");
  pubSel.clear();
  await loadZooFull();
};
$("zooPublishAll").onclick = async () => {
  setStatus("Publishing all unpublished cards…", "work");
  const r = await postJSON("/api/publish", { contributor: contributor() });
  const d = await r.json();
  setStatus(d.committed ? `Published the zoo (${d.note}).` : (d.note || "Nothing to publish."),
            r.ok ? "ok" : "err");
  await loadZooFull();
};
document.querySelectorAll(".ztab").forEach((t) => t.onclick = () => {
  document.querySelectorAll(".ztab").forEach((x) => x.classList.remove("sel"));
  t.classList.add("sel"); zooTab = t.dataset.tab; renderGrid();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isZooOpen()) closeZoo(); });
// "Show on map" lives in the injected detail HTML; delegate the click
$("zoo-detail").addEventListener("click", async (e) => {
  const id = e.target.id;
  if (id === "showExtent") { closeZoo(); await showOnMap(zooSelected); }
  else if (id === "annotateToggle") { $("annotateForm").classList.toggle("hidden"); }
  else if (id === "annotateSave") { await saveAnnotation(zooSelected); }
  else if (id === "applyBtn") { await applyModel(zooSelected); }
  else if (id === "applyHereBtn") { await applyModel(zooSelected, selected); }   // #11 target = selected class
  else if (id === "delBtn") { await deleteCardUI(zooSelected); }                 // #9 drop a card
  else if (id === "pubBtn") { await publishCard(zooSelected); }
  else if (id === "dsLinkSave") { await saveDatasetLink(zooSelected); }
});
// injected <select>s in the detail pane (spread grid #1, inference year #7) — delegate their change
$("zoo-detail").addEventListener("change", async (e) => {
  if (e.target.id === "spreadCell") await recomputeSpread(zooSelected, e.target.value);
  else if (e.target.id === "zooYear") {
    inferYear = Number(e.target.value);
    localStorage.setItem("inferYear", inferYear);
    setStatus(`Inference year set to ${inferYear} — re-running…`, "work");
    runClassify();                          // auto-refresh so the map matches the year (#10)
  }
});

// save a dataset's public source link straight from its card (#3). Empty clears it.
async function saveDatasetLink(id) {
  const url = ($("dsLink") ? $("dsLink").value : "").trim();
  setStatus("Saving source link…", "work");
  const r = await postJSON(`/api/cards/${id}/annotate`, { source_url: url });
  if (!r.ok) { setStatus("Error saving link.", "err"); return; }
  setStatus(url ? "Saved public source link." : "Cleared the source link.", "ok");
  await loadZooFull();
  await showCardFull(id);
}

// make a zoo model live on the map: register it on the tree, then re-classify the current area.
// `targetNode` applies it under the class the user selected (else the card's own node); if that's
// an incompatible base class the server answers 409 and we ask "proceed anyway?" before forcing (#11).
async function applyModel(id, targetNode = null, force = false) {
  setStatus(`Applying "${id}" to the map…`, "work");
  const r = await postJSON("/api/apply", { card_id: id, target_node: targetNode, force });
  const d = await r.json();
  if (r.status === 409 && !force) {
    // detail can be a string or the {message, needs_confirm} object we send from the guard
    const msg = (d.detail && d.detail.message) || d.detail || "This model may not fit here.";
    if (await uiConfirm(msg + "\n\nApply it anyway?", { okText: "Apply anyway", danger: true })) {
      return applyModel(id, targetNode, true);
    }
    setStatus("Left the map unchanged.", "info");
    return;
  }
  if (!r.ok) { setStatus("Error: " + ((d.detail && d.detail.message) || d.detail || r.status), "err"); return; }
  await refreshTree(d);
  closeZoo();
  setStatus(`Applied "${id}" — re-classifying…`, "ok");
  await runClassify();
}

// drop a card from the zoo (#9): a superseded/dummy model the user no longer wants
async function deleteCardUI(id) {
  if (!await uiConfirm(`Delete "${id}" from the zoo?\n\nThis removes the card (and any archived copy).`,
                       { okText: "Delete", danger: true })) return;
  setStatus(`Deleting "${id}"…`, "work");
  const r = await fetch(`/api/cards/${id}`, { method: "DELETE" });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + ((d.detail && d.detail.message) || d.detail || r.status), "err"); return; }
  zooSelected = null;
  $("zoo-detail").innerHTML = `<p class="hint">Deleted "${id}". Select a card to see its details.</p>`;
  await loadZooFull();
  setStatus(`Deleted "${id}".`, "ok");
}

function formatReport(rep, nTest) {
  if (!rep) return "";
  const lines = [`held-out: ${nTest} px   acc ${(rep.accuracy ?? 0).toFixed(3)}`];
  for (const [k, v] of Object.entries(rep)) {
    if (["accuracy", "macro avg", "weighted avg"].includes(k)) continue;
    lines.push(`${k.padEnd(14)} P${v.precision.toFixed(2)} R${v.recall.toFixed(2)} F${v["f1-score"].toFixed(2)}`);
  }
  return lines.join("\n");
}

init();
