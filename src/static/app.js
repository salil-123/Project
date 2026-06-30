// Core Stack LULC — Leaflet frontend talking to the FastAPI backend.
let PRESETS = {}, COLORS = {}, TREE = {}, STANDARDS = {}, INFER_OPTS = {};
let MERGES = [];                  // active merge rules, drawn onto the hierarchy tree (#1)
let mergeSel = new Set();         // leaf ids ticked in the tree, waiting to be merged (#1)
const AE_INFERENCE_ID = "ds_alphaearth_annual_v1";   // the Alpha Earth feature-source card
let inferYear = Number(localStorage.getItem("inferYear")) || 2024;   // year drives Run; set in zoo (#7)
let selected = "root";            // the class the example/operation panels act on
let predLayer = L.layerGroup();   // Detailed mode: vector cells
let rasterLayer = null;           // Realistic mode: 10 m classified PNG overlay
let drawnLayer = L.featureGroup();
let lastGeometry = null;
let extentLayer = null;            // Model Zoo: the selected card's extent rectangle
let zooSelected = null;

const map = L.map("map", { center: [19.133, 72.915], zoom: 14 });
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Esri", maxZoom: 19 }).addTo(map);
predLayer.addTo(map);
drawnLayer.addTo(map);

// draw tools (polygon + marker) for example markings
map.addControl(new L.Control.Draw({
  edit: { featureGroup: drawnLayer },
  draw: { polygon: true, marker: true, polyline: false, rectangle: false,
          circle: false, circlemarker: false },
}));
map.on(L.Draw.Event.CREATED, (e) => {
  drawnLayer.clearLayers();
  drawnLayer.addLayer(e.layer);
  lastGeometry = e.layer.toGeoJSON().geometry;
  setStatus("Polygon captured — pick a role and 'Add drawn polygon'.");
});

const $ = (id) => document.getElementById(id);

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
  const lat = parseFloat($("clat").value), lon = parseFloat($("clon").value);
  const h = parseFloat($("half").value);
  return [lon - h, lat - h, lon + h, lat + h];
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
  $("exClass").textContent = TREE[cls].name;
  renderTree();
  updateDataDist();
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

async function refreshTree(data) {
  data = data || await getJSON("/api/tree");
  TREE = data.tree; COLORS = data.colors;
  if (!TREE[selected]) selected = "root";
  await loadMerges();         // pulls the rules, then renders the tree (merges drawn on it)
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
  sel.onchange = () => $("custom").classList.toggle("hidden", sel.value !== "__custom__");
  await refreshTree();
  await refreshZooBadge();
  try { STANDARDS = await getJSON("/api/standards"); } catch { /* pick-list is best-effort */ }
  try { INFER_OPTS = await getJSON("/api/inference-options"); } catch { /* year picker is best-effort */ }
  // first thing on a fresh visit: pick the base classes to start from (sir's ask). Versioned key
  // so the chooser shows once even for users who saw the older onboarding.
  if (!localStorage.getItem("onboard_base")) await showBaseOnboard();
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
    if (!confirm(`Start from "${scheme}"? This sets your base classes and clears any existing ` +
                 `splits/merges.`)) return;
    setStatus(`Setting base to ${scheme}…`, "work");
    const r = await postJSON("/api/base/select", { scheme });
    const d = await r.json();
    if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
    await refreshTree(d);
  }
  endBaseOnboard();
  await runClassify();
}

function endBaseOnboard() {
  $("base-onboard").classList.add("hidden");
  localStorage.setItem("onboard_base", "1");   // chosen (or skipped) -> don't force it again
}
$("baseSkip").onclick = endBaseOnboard;

$("half").oninput = (e) => $("halfval").textContent = parseFloat(e.target.value).toFixed(3);
$("mode").onchange = () => {
  $("modehint").textContent = $("mode").value === "detailed"
    ? "Prior-aware AE soft-voted with Tessera, more rare-class detail. First run over a new area downloads tiles (slower). Year locks to 2024 (Tessera coverage)."
    : "Server-side 10 m classification served as Earth Engine map tiles — crisp at any zoom, calibrated to India's prior, no downloads.";
};

// ---------------- classify ----------------
async function runClassify() {
  const [w, s, e, n] = currentBbox();
  const mode = $("mode").value;
  const year = mode === "detailed" ? 2024 : inferYear;   // Tessera is 2024-only; AE year set in zoo (#7)
  setStatus(mode === "detailed" ? "Sampling AE + Tessera (may download tiles)…"
                                : "Classifying at 10 m…", "work");
  $("run").disabled = true;
  try {
    const data = await getJSON(
      `/api/classify?west=${w}&south=${s}&east=${e}&north=${n}&mode=${mode}&year=${year}`);
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
    setStatus("Done: " + JSON.stringify(data.counts));
  } catch (err) { setStatus("Error: " + err, "err"); }
  $("run").disabled = false;
}
$("run").onclick = runClassify;

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
  btn.disabled = true; btn.textContent = "Working… (sampling + training)";
  setStatus(`Retraining "${selected}" — sampling embeddings + training (can take a minute)…`, "work");
  $("metrics").textContent = "";
  try {
    const r = await postJSON("/api/retrain", { node: selected, balance: $("balance").value });
    const d = await r.json();
    if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); }
    else {
      await refreshTree(d);
      $("metrics").textContent = formatReport(d.report, d.n_test);
      setStatus(`Retrained "${selected}" — re-rendering the map…`, "ok");
      await refreshZooBadge();                          // the new model card just landed
      if (isZooOpen()) await loadZooFull();
      await runClassify();
    }
  } catch (err) { setStatus("Error: " + err, "err"); }
  btn.disabled = false; btn.textContent = "Retrain selected & apply";
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

// ---------------- save / load scheme (#4) ----------------
// the user's scheme is just the hierarchy + the op-log; download it as their portable save,
// load it back to continue. No accounts/sessions — the JSON file carries the state.
$("exportHier").onclick = async () => {
  try {
    const data = await getJSON("/api/hierarchy/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "hierarchy.json";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("Downloaded your hierarchy.", "ok");
  } catch (err) { setStatus("Export failed: " + err, "err"); }
};

$("importHier").onchange = async () => {
  const f = $("importHier").files[0];
  if (!f) return;
  setStatus(`Loading ${f.name}…`, "work");
  let body;
  try { body = JSON.parse(await f.text()); }
  catch { setStatus("That file isn't valid JSON.", "err"); $("importHier").value = ""; return; }
  if (!body.hierarchy) body = { hierarchy: body };        // accept a bare tree too
  const r = await postJSON("/api/hierarchy/import", body);
  const d = await r.json();
  $("importHier").value = "";
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  await refreshTree(d);
  await refreshZooBadge();
  const miss = (d.missing_classifiers || []).length
    ? ` — ${d.missing_classifiers.length} split(s) need retraining (${d.missing_classifiers.join(", ")})` : "";
  setStatus(`Loaded hierarchy${miss}. Re-classifying…`, "ok");
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

function renderGrid() {
  const grid = $("zoo-grid"); grid.innerHTML = "";
  const rows = zooCards.filter((c) => c.kind === zooTab);
  if (!rows.length) { grid.innerHTML = `<p class="hint">Nothing here yet.</p>`; return; }
  rows.forEach((c) => grid.appendChild(c.kind === "model" ? modelTile(c) : datasetTile(c)));
}

function swatch(cls) { return `<span class="sw" style="background:${COLORS[cls] || "#888"}"></span>`; }
function classChips(classes) {
  return (classes || []).map((c) => `<span class="chip">${swatch(c)}${c}</span>`).join("");
}

function modelTile(m) {
  const pub = m.published ? `<span class="pill pub">published</span>` : `<span class="pill loc">local</span>`;
  const acc = m.accuracy != null ? `accuracy ${m.accuracy.toFixed(2)}` : "—";
  // cheap apply-after hint from the index row (full WorldCover hint shows in the detail pane)
  const after = (m.topology && m.topology !== "base_pooled" && m.node) ? ` · after ${m.node}` : "";
  const div = document.createElement("div");
  div.className = "zoo-card" + (m.id === zooSelected ? " sel" : "");
  div.innerHTML = `<div class="zc-top"><h4>${m.name || m.id}</h4>${pub}</div>
    <div class="zc-classes">${classChips(m.classes)}</div>
    <div class="zc-acc">${acc} · ${m.topology || ""}${after}</div>`;
  div.onclick = () => showCardFull(m.id);
  return div;
}

function datasetTile(d) {
  const t = d.type === "inference" ? `<span class="pill infer">inference</span>`
                                   : `<span class="pill train">training</span>`;
  const div = document.createElement("div");
  div.className = "zoo-card" + (d.id === zooSelected ? " sel" : "");
  div.innerHTML = `<div class="zc-top"><h4>${d.name || d.id}</h4>${t}</div>
    <div class="zc-classes">${classChips(d.classes)}</div>
    <div class="zc-acc">${d.kind || "dataset"}</div>`;
  div.onclick = () => showCardFull(d.id);
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
    <button id="pubBtn">${c.zoo && c.zoo.published ? "Re-publish" : "Publish to zoo"}</button>`;
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

// produced-class chips, showing any standard-LULC mapping the user attached (#13-15)
function produceChips(produces) {
  return (produces || []).map((p) => {
    const m = p.std_mapping || {};
    const std = Object.entries(m).map(([k, v]) => `${k}:${v}`).join(", ");
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
  const r = await postJSON(`/api/cards/${id}/annotate`,
    { about: { description: v("an_desc"), intended_use: v("an_use"),
               limitations: v("an_lim"), evidence: v("an_ev") },
      contributor: v("an_contrib"), std_mapping: std });
  if (!r.ok) { setStatus("Error saving annotation.", "err"); return; }
  setStatus("Saved annotation.", "ok");
  await loadZooFull();
  await showCardFull(id);
}

// the spatial-diversity score as actionable feedback: is this dataset spread out, or clustered
// (which would skew a model)? Shannon entropy of the polygons over a grid, in [0,1]. The grid
// cell is user-adjustable (#1) — change it to see the spread at the scale you care about.
const SPREAD_CELLS = [0.1, 0.25, 0.5, 1.0];

// just the value line (diversity number + label + count), so initial render and live recompute
// share one renderer. d=diversity, occ=occupied cells, n=#polygons, cell=grid size in degrees.
function spreadValueHTML(d, occ, n, cell) {
  if (d == null) return `<div class="prose">no spread (need ≥2 polygons)</div>`;
  const [label, col] = d >= 0.75 ? ["well spread", "#3ddc84"]
                     : d >= 0.5  ? ["moderately spread", "#e0b341"]
                     :             ["clustered — risks skewing the model", "#ff7b72"];
  const cells = occ != null ? ` across ${occ} grid cells` : "";
  const tail = n != null ? `${n} polygons${cells} (${cell}° grid)` : "";
  return `<div><b style="color:${col}">${d.toFixed(2)}</b> — ${label}</div>
    ${tail ? `<div class="prose">${tail}</div>` : ""}`;
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
    const q = await getJSON(`/api/cards/${id}/spread?cell=${cell}`);
    if (out) out.innerHTML = spreadValueHTML(q.spatial_diversity, q.occupied_cells, q.n_polygons, q.cell);
  } catch {
    if (out) out.innerHTML = `<div class="prose">couldn't recompute at this grid</div>`;
  }
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
  return `<div class="blk"><span class="k">Inference year</span>
    <select id="zooYear">${opts}</select>
    <div class="prose">Which year's Alpha Earth the map classifies. Same model, different temporal
      slice. Detailed mode is locked to 2024 (Tessera coverage).</div></div>`;
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
  const r = await postJSON("/api/publish", { card_ids: [id], contributor: contributor() });
  const d = await r.json();
  setStatus(d.pushed ? `Published "${id}" — pushed to the zoo.`
            : (d.committed ? `Committed "${id}" locally (${d.note}).` : d.note || "Nothing to publish."),
            r.ok ? "ok" : "err");
  await loadZooFull();
  await showCardFull(id);
}

// ---- zoo overlay wiring ----
$("openZoo").onclick = openZoo;
$("closeZoo").onclick = closeZoo;
$("zooAoi").onchange = loadZooFull;
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
  else if (id === "pubBtn") { await publishCard(zooSelected); }
  else if (id === "dsLinkSave") { await saveDatasetLink(zooSelected); }
});
// injected <select>s in the detail pane (spread grid #1, inference year #7) — delegate their change
$("zoo-detail").addEventListener("change", async (e) => {
  if (e.target.id === "spreadCell") await recomputeSpread(zooSelected, e.target.value);
  else if (e.target.id === "zooYear") {
    inferYear = Number(e.target.value);
    localStorage.setItem("inferYear", inferYear);
    setStatus(`Inference year set to ${inferYear}. Run classification to apply.`, "ok");
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

// make a zoo model live on the map: register it on the tree, then re-classify the current area
async function applyModel(id) {
  setStatus(`Applying "${id}" to the map…`, "work");
  const r = await postJSON("/api/apply", { card_id: id });
  const d = await r.json();
  if (!r.ok) { setStatus("Error: " + (d.detail || r.status), "err"); return; }
  await refreshTree(d);
  closeZoo();
  setStatus(`Applied "${id}" — re-classifying…`, "ok");
  await runClassify();
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
