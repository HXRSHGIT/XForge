/* xforge UI.
 *
 * Two jobs: find a part and bring it into the project, and look at the board.
 * Keyboard first, because the people using this live in an editor.
 */

const $ = (id) => document.getElementById(id);

const state = {
  results: [],
  selected: -1,
  query: "",
  vendored: new Set(),
  seq: 0, // guards against a slow search overwriting a newer one
};

// ── status strip ────────────────────────────────────────────────────

function say(message, bad = false) {
  const el = $("f-msg");
  el.textContent = message || "";
  el.classList.toggle("bad", !!bad);
}

function lamp(kind, text) {
  $("lamp").className = "lamp " + kind;
  $("conn").textContent = text;
}

// ── search ──────────────────────────────────────────────────────────

const fmt = new Intl.NumberFormat("en-US");

function priceLabel(p) {
  if (p.price == null) return "";
  return "$" + (p.price < 1 ? p.price.toFixed(4) : p.price.toFixed(2));
}

function renderResults() {
  const list = $("results");
  list.innerHTML = "";

  if (!state.results.length) {
    const d = document.createElement("div");
    d.className = "placeholder";
    d.textContent = state.query
      ? `Nothing matched "${state.query}". Try the manufacturer part number, or a shorter fragment of it.`
      : "";
    list.appendChild(d);
    return;
  }

  state.results.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "row";
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(i === state.selected));
    row.dataset.index = String(i);

    const stockClass = p.stock > 0 ? "have" : "zero";
    row.innerHTML = `
      <div class="mpn"></div>
      <div class="stock ${stockClass}"></div>
      <div class="brand"></div>
      <div class="pkg"></div>
    `;
    row.querySelector(".mpn").textContent = p.mpn || p.lcsc;
    row.querySelector(".stock").textContent = p.stock > 0 ? fmt.format(p.stock) : "no stock";
    row.querySelector(".brand").textContent = p.brand || "";
    row.querySelector(".pkg").textContent = p.package || "";

    const flags = document.createElement("div");
    flags.className = "flags";
    const id = document.createElement("span");
    id.className = "lcsc";
    id.textContent = p.lcsc;
    flags.appendChild(id);
    if (p.basic) flags.appendChild(flag("basic", "Basic"));
    if (p.vendored || state.vendored.has(p.lcsc)) flags.appendChild(flag("vendored", "In project"));
    row.appendChild(flags);

    row.addEventListener("click", () => select(i));
    list.appendChild(row);
  });
}

function flag(cls, text) {
  const s = document.createElement("span");
  s.className = "flag " + cls;
  s.textContent = text;
  return s;
}

function select(i) {
  state.selected = i;
  renderResults();
  const row = document.querySelector(`.row[data-index="${i}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
  renderDetail();
}

async function search(q) {
  state.query = q;
  const mine = ++state.seq;
  if (!q.trim()) {
    state.results = [];
    state.selected = -1;
    $("tally").hidden = true;
    $("f-res").textContent = "0";
    renderResults();
    renderDetail();
    return;
  }
  lamp("busy", "searching");
  say("");
  try {
    const r = await fetch(`/api/parts/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();
    if (mine !== state.seq) return; // a newer search already answered
    if (!r.ok) throw new Error(data.error || "search failed");

    state.results = data.results || [];
    // Land on something buyable. Supplier relevance order is kept - the list
    // is not re-sorted - but a zero-stock assembly placeholder is not what
    // anyone opened the search for.
    const firstStocked = state.results.findIndex((p) => p.stock > 0);
    state.selected = state.results.length
      ? (firstStocked >= 0 ? firstStocked : 0)
      : -1;
    $("tally").hidden = false;
    $("tally-left").innerHTML = `<b>${fmt.format(data.total)}</b> matches`;
    $("tally-right").textContent = `showing ${state.results.length}`;
    $("f-res").textContent = String(state.results.length);
    renderResults();
    renderDetail();
    lamp("on", "online");
  } catch (err) {
    if (mine !== state.seq) return;
    lamp("bad", "offline");
    say(String(err.message || err), true);
    state.results = [];
    renderResults();
  }
}

// ── selected part ───────────────────────────────────────────────────

function renderDetail() {
  const box = $("detail");
  const p = state.results[state.selected];
  if (!p) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  const already = p.vendored || state.vendored.has(p.lcsc);
  const rows = [
    ["LCSC", p.lcsc],
    ["Package", p.package || "—"],
    ["Category", p.category || "—"],
    ["Stock", p.stock > 0 ? fmt.format(p.stock) : "0"],
    ["Unit price", priceLabel(p) || "—"],
    ["Min order", p.min_qty != null ? fmt.format(p.min_qty) : "—"],
    ["Type", p.basic ? "Basic" : "Extended"],
  ];
  if (p.price_breaks && p.price_breaks.length > 1) {
    const hundred = p.price_breaks.filter((b) => b.qty <= 100).pop();
    if (hundred) rows.push(["At qty 100", "$" + hundred.price.toFixed(4)]);
  }

  box.innerHTML = "";
  const head = document.createElement("header");
  const mpn = document.createElement("div");
  mpn.className = "mpn";
  mpn.textContent = p.mpn || p.lcsc;
  const brand = document.createElement("div");
  brand.className = "brand";
  brand.textContent = p.brand || "";
  head.append(mpn, brand);
  box.appendChild(head);

  const table = document.createElement("table");
  table.className = "spec";
  for (const [k, v] of rows) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = k;
    const td = document.createElement("td");
    td.textContent = v;
    tr.append(th, td);
    table.appendChild(tr);
  }
  box.appendChild(table);

  if (p.description) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = p.description;
    box.appendChild(note);
  }

  const act = document.createElement("div");
  act.className = "act";
  const btn = document.createElement("button");
  btn.className = "btn";
  if (already) {
    btn.textContent = "Already in project";
    btn.disabled = true;
  } else {
    btn.textContent = "Import into project";
    btn.addEventListener("click", () => importPart(p, btn));
  }
  act.appendChild(btn);
  box.appendChild(act);

  if (p.datasheet) {
    const ds = document.createElement("div");
    ds.className = "act";
    ds.style.borderTop = "0";
    ds.style.paddingTop = "0";
    const a = document.createElement("a");
    a.className = "btn ghost";
    a.style.display = "block";
    a.style.textAlign = "center";
    a.style.textDecoration = "none";
    a.href = p.datasheet;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "Open datasheet";
    ds.appendChild(a);
    box.appendChild(ds);
  }
}

async function importPart(p, btn) {
  btn.disabled = true;
  btn.textContent = "Importing";
  lamp("busy", "importing");
  try {
    const r = await fetch("/api/parts/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lcsc: p.lcsc }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "import failed");
    state.vendored.add(p.lcsc);
    const files = (data.imported.files || []).length;
    say(`Imported ${p.mpn || p.lcsc}: ${files} file${files === 1 ? "" : "s"}`);
    btn.textContent = "Already in project";
    await refreshStatus();
    renderResults();
  } catch (err) {
    say(String(err.message || err), true);
    btn.disabled = false;
    btn.textContent = "Import into project";
  } finally {
    lamp("on", "online");
  }
}

// ── board viewport ──────────────────────────────────────────────────
//
// The board arrives as polygons, not a mesh: an outline with cutouts, and one
// footprint outline per component with its placement and height. Extruding
// here keeps the payload small and keeps every solid tied to its reference
// designator, so a rule that flags R902 can light up R902.

let three = null;

const BOARD = 0x1d3b28;   // solder mask
const PART = 0x6f6a5e;    // package body
const TALL = 0x8a8275;    // anything standing proud of the board
const FLAG = 0xd9a441;    // flagged by a design rule

async function loadBoard() {
  const empty = $("view-empty");
  const canvas = $("canvas");

  let scene_data;
  try {
    const r = await fetch("/api/board");
    scene_data = await r.json();
    if (!r.ok) {
      $("empty-title").textContent = scene_data.error || "No board loaded";
      $("empty-body").textContent = scene_data.hint || "";
      return;
    }
  } catch (err) {
    $("empty-title").textContent = "Could not read the board";
    $("empty-body").textContent = String(err.message || err);
    return;
  }

  lamp("busy", "drawing");
  const T = await import("three");
  const { OrbitControls } = await import("three/addons/controls/OrbitControls.js");

  empty.classList.add("hidden");
  canvas.classList.remove("hidden");

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(36, 1, 0.1, 20000);
  const renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

  scene.add(new T.AmbientLight(0xffffff, 0.5));
  const key = new T.DirectionalLight(0xfff4e2, 2.0);
  key.position.set(0.6, 1.4, 0.9);
  scene.add(key);
  const fill = new T.DirectionalLight(0x9fb6cf, 0.55);
  fill.position.set(-1, 0.4, -0.8);
  scene.add(fill);

  const board = new T.Group();

  // Board: outer loops extruded, cutouts punched through as holes.
  const t = scene_data.thickness || 1.6;
  for (const loop of scene_data.outline) {
    const shape = new T.Shape(loop.map(([x, y]) => new T.Vector2(x, y)));
    for (const hole of scene_data.cutouts) {
      shape.holes.push(new T.Path(hole.map(([x, y]) => new T.Vector2(x, y))));
    }
    const geo = new T.ExtrudeGeometry(shape, { depth: t, bevelEnabled: false });
    const mesh = new T.Mesh(
      geo,
      new T.MeshStandardMaterial({ color: BOARD, roughness: 0.75, metalness: 0.05 })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.userData.kind = "board";
    board.add(mesh);
  }

  // Components, each one its own mesh so it can be picked and highlighted.
  const parts = [];
  for (const p of scene_data.parts) {
    if (!p.outline || p.outline.length < 3) continue;
    const shape = new T.Shape(p.outline.map(([x, y]) => new T.Vector2(x, y)));
    const h = Math.max(p.height, 0.2);
    const geo = new T.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false });
    const colour = p.flagged ? FLAG : h > 5 ? TALL : PART;
    const mesh = new T.Mesh(
      geo,
      new T.MeshStandardMaterial({
        color: colour,
        roughness: 0.6,
        emissive: p.flagged ? FLAG : 0x000000,
        emissiveIntensity: p.flagged ? 0.35 : 0,
      })
    );
    const bottom = p.side === "BOTTOM";
    mesh.rotation.x = -Math.PI / 2;
    mesh.rotation.z = (p.rot * Math.PI) / 180;
    mesh.position.set(p.x, bottom ? 0 : t, -p.y);
    if (bottom) mesh.scale.y = -1;
    mesh.userData = { ref: p.ref, part: p.part, height: p.height, flagged: p.flagged };
    parts.push(mesh);
    board.add(mesh);
  }
  scene.add(board);

  // Frame the whole board rather than guessing a distance: fit the larger
  // of its two dimensions to the camera's field of view, allowing for the
  // viewport aspect so a narrow window does not crop the board.
  const [w, d] = scene_data.size;
  const view = $("view");
  const aspect = (view.clientWidth || 1) / (view.clientHeight || 1);
  camera.aspect = aspect;
  const vFov = (camera.fov * Math.PI) / 180;
  const fitH = d / 2 / Math.tan(vFov / 2);
  const fitW = w / 2 / Math.tan(vFov / 2) / aspect;
  const dist = Math.max(fitH, fitW) * 1.35; // margin, and room for tall parts
  camera.position.set(dist * 0.45, dist * 0.72, dist * 0.78);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  three = { T, scene, camera, renderer, controls, parts, raycaster: new T.Raycaster() };
  resize();
  animate();
  lamp("on", "online");

  const flagged = scene_data.parts.filter((p) => p.flagged).length;
  showReadout(scene_data, flagged);
  canvas.addEventListener("pointermove", (e) => pick(e, scene_data));
}

function showReadout(d, flagged, hovered) {
  const el = $("readout");
  el.classList.remove("hidden");
  el.innerHTML = "";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = hovered ? hovered.ref : d.name;
  el.appendChild(title);

  const lines = hovered
    ? [
        ["part", hovered.part || "—"],
        ["height", hovered.height.toFixed(2) + " mm"],
        ["flagged", hovered.flagged ? "yes" : "no"],
      ]
    : [
        ["size", `${d.size[0].toFixed(1)} × ${d.size[1].toFixed(1)} mm`],
        ["thickness", d.thickness.toFixed(2) + " mm"],
        ["components", String(d.stats.placements)],
        ["flagged", String(flagged)],
        ["source", d.generator || "IDF"],
      ];
  for (const [k, v] of lines) {
    const row = document.createElement("div");
    row.innerHTML = `<span class="k"></span><span class="v"></span>`;
    row.querySelector(".k").textContent = k;
    row.querySelector(".v").textContent = v;
    el.appendChild(row);
  }
}

let lastHover = null;
function pick(event, data) {
  if (!three) return;
  const rect = three.renderer.domElement.getBoundingClientRect();
  const pointer = new three.T.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1
  );
  three.raycaster.setFromCamera(pointer, three.camera);
  const hit = three.raycaster.intersectObjects(three.parts, false)[0];
  const ref = hit ? hit.object.userData.ref : null;
  if (ref === lastHover) return;
  lastHover = ref;
  const flagged = data.parts.filter((p) => p.flagged).length;
  showReadout(data, flagged, hit ? hit.object.userData : null);
}

function resize() {
  if (!three) return;
  const v = $("view");
  three.renderer.setSize(v.clientWidth, v.clientHeight, false);
  three.camera.aspect = v.clientWidth / v.clientHeight || 1;
  three.camera.updateProjectionMatrix();
}

function animate() {
  if (!three) return;
  requestAnimationFrame(animate);
  three.controls.update();
  three.renderer.render(three.scene, three.camera);
}

// ── wiring ──────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("proj").textContent = (s.project || "").split(/[\\/]/).pop();
    $("f-proj").textContent = (s.project || "—").split(/[\\/]/).pop();
    $("f-vend").textContent = String(s.vendored || 0);
    (s.parts || []).forEach((p) => state.vendored.add(p));
    lamp("on", "online");
    return s;
  } catch {
    lamp("bad", "no server");
    return null;
  }
}

function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

const onType = debounce((v) => search(v), 220);

$("q").addEventListener("input", (e) => onType(e.target.value));

document.addEventListener("keydown", (e) => {
  const field = $("q");
  if (e.key === "/" && document.activeElement !== field) {
    e.preventDefault();
    field.focus();
    field.select();
    return;
  }
  if (e.key === "Escape" && document.activeElement === field) {
    field.value = "";
    search("");
    field.blur();
    return;
  }
  if (!state.results.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    select(Math.min(state.selected + 1, state.results.length - 1));
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    select(Math.max(state.selected - 1, 0));
  } else if (e.key === "Enter" && state.selected >= 0) {
    const btn = document.querySelector(".detail .btn:not(:disabled)");
    if (btn) btn.click();
  }
});

for (const [id, other] of [["tab-parts", "tab-board"], ["tab-board", "tab-parts"]]) {
  $(id).addEventListener("click", () => {
    $(id).setAttribute("aria-selected", "true");
    $(other).setAttribute("aria-selected", "false");
    const boardMode = id === "tab-board";
    document.querySelector(".rail").classList.toggle("hidden", boardMode);
    document.querySelector(".app").style.gridTemplateColumns = boardMode
      ? "0 1fr"
      : "var(--rail) 1fr";
    resize();
  });
}

addEventListener("resize", resize);

refreshStatus().then((s) => {
  if (s && s.model) loadBoard();
  // A query in the URL makes a search shareable between engineers, and is
  // how the interface is exercised in tests.
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) {
    $("q").value = initial;
    search(initial);
  }
  $("q").focus();
});
