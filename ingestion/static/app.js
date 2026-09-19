"use strict";

/* Presentation only. Every decision about what can be imported comes from
   the API; this file arranges it and speaks plainly about it. */

const $ = (id) => document.getElementById(id);

const state = {
  source: null,        // the chosen source description
  dataset: null,       // { dataset_id, name }
  details: null,       // variables and ranges for that dataset
  selection: null,     // what will be sent
};

const PANELS = ["step1", "step2", "step3", "step4",
                "progress-panel", "result-panel"];

/* Plain words for things the user should not have to learn. */
const SHAPE_WORDS = {
  grid: "Gridded data",
  profile: "Depth profiles",
  trajectory: "Track",
  trajectory_profile: "Track with depth profiles",
  point: "Point observations",
};

/* -- plumbing ------------------------------------------------------------ */

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || response.statusText);
  return body;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function showStep(id, stepNumber) {
  for (const panel of PANELS) $(panel).hidden = panel !== id;
  state.step = stepNumber;
  for (const item of $("steps").children) {
    const index = Number(item.dataset.step);
    item.classList.toggle("active", index === stepNumber);
    item.classList.toggle("done", stepNumber !== null && index < stepNumber);
    item.classList.toggle("reachable", canGoTo(index) && index !== stepNumber);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* A step is reachable once the choice it depends on has been made. Steps you
   have not got to yet are not, which is why they do not respond. */
function canGoTo(step) {
  if (step === 1) return true;
  if (step === 2) return Boolean(state.source);
  if (step === 3) return Boolean(state.details);
  if (step === 4) return Boolean(state.selection);
  return false;
}

function goToStep(step) {
  if (!canGoTo(step)) return;
  if (step === 1) { showStep("step1", 1); return; }
  if (step === 2) { showStep("step2", 2); return; }
  if (step === 3) { showStep("step3", 3); return; }
  if (step === 4) { toReview(); }
}

/* Friendly label for a variable: its description if it has one. */
function variableLabel(variable) {
  const name = variable.description && variable.description.trim()
    ? variable.description : variable.name;
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function prettyDate(value) {
  return String(value ?? "").replace("T", " ").replace("Z", "").slice(0, 16);
}

/* -- step 1: source ------------------------------------------------------ */

async function loadSources() {
  const { sources } = await api("/api/sources");
  const host = $("remote-sources");
  host.innerHTML = "";

  if (!sources.length) {
    host.innerHTML = `<p class="empty">No sources are configured.</p>`;
    return;
  }

  for (const source of sources) {
    const card = el("div", "card",
      `<span class="title">${esc(source.name)}</span>` +
      `<span class="sub">${esc(source.description)}</span>`);
    const browse = el("button", "primary", "Browse");
    browse.addEventListener("click", () => chooseSource(source));
    card.appendChild(browse);
    host.appendChild(card);
  }
}

async function chooseSource(source) {
  state.source = source;
  state.dataset = null;
  state.details = null;
  state.selection = null;
  $("step2-lead").textContent = `Datasets published by ${source.name}.`;
  showStep("step2", 2);
  $("search").value = "";
  await loadDatasets();
}

/* -- step 2: dataset ----------------------------------------------------- */

async function loadDatasets() {
  const host = $("datasets");
  host.innerHTML = "";
  $("step2-empty").hidden = true;

  let found = [];
  try {
    found = (await api(`/api/datasets?source_id=${
      encodeURIComponent(state.source.source_id)}`)).datasets;
  } catch (error) {
    $("step2-empty").hidden = false;
    $("step2-empty").textContent = error.message;
    return;
  }

  state.available = found;
  $("search-wrap").hidden = found.length < 6;
  renderDatasets();
}

function renderDatasets() {
  const term = $("search").value.trim().toLowerCase();
  const matching = (state.available || []).filter(
    (item) => !term || item.name.toLowerCase().includes(term));

  const host = $("datasets");
  host.innerHTML = "";

  if (!matching.length) {
    $("step2-empty").hidden = false;
    $("step2-empty").textContent = term
      ? "Nothing matches that search."
      : "This source has no datasets available.";
    return;
  }
  $("step2-empty").hidden = true;

  for (const item of matching) {
    const row = el("div", "row",
      `<span class="body"><span class="title">${esc(item.name)}</span>` +
      (item.description
        ? `<span class="sub">${esc(item.description)}</span>` : "") +
      `</span>`);
    const select = el("button", "", "Select");
    select.addEventListener("click", () => chooseDataset(item));
    row.appendChild(select);
    host.appendChild(row);
  }
}

/* -- step 3: variables and ranges --------------------------------------- */

async function chooseDataset(item) {
  state.dataset = item;
  state.selection = null;
  showStep("step3", 3);
  $("step3-lead").textContent = `Reading ${item.name}…`;
  $("variables").innerHTML = "";
  $("dataset-notes").hidden = true;
  for (const id of ["g-date", "g-depth", "g-area"]) $(id).hidden = true;

  let details;
  try {
    details = await api(`/api/dataset?source_id=${
      encodeURIComponent(state.source.source_id)}&dataset_id=${
      encodeURIComponent(item.dataset_id)}`);
  } catch (error) {
    $("step3-lead").textContent = "";
    $("dataset-notes").hidden = false;
    $("dataset-notes").textContent = error.message;
    return;
  }

  state.details = details;
  $("step3-lead").textContent = details.name;
  if (details.notes.length) {
    $("dataset-notes").hidden = false;
    $("dataset-notes").textContent = details.notes.join(" ");
  }

  state.variables = details.variables || [];
  $("variable-filter").value = "";
  renderVariables();
  clearComplaint("date-problem");

  // Clear first: the range wiring below depends on the fields being empty.
  ["date-start", "date-end", "area-west", "area-east",
   "area-south", "area-north"].forEach((id) => { $(id).value = ""; });

  const supports = state.source.supports;
  const byRole = Object.fromEntries(details.ranges.map((r) => [r.role, r]));
  showRange("date", "g-date", supports.time_subsetting, byRole.time);
  showRange("depth", "g-depth", supports.depth_subsetting, byRole.vertical);
  showArea(supports.spatial_subsetting, byRole.latitude, byRole.longitude);
}

/* An axis holding a single value has nothing to choose between, so asking
   for a range over it would be a control that cannot do anything. */
function hasChoice(range) {
  return Boolean(range) && (range.count === null || range.count === undefined
                            || range.count > 1);
}

function renderVariables() {
  const host = $("variables");
  const term = $("variable-filter").value.trim().toLowerCase();
  host.innerHTML = "";

  for (const variable of state.variables) {
    const described = Boolean(variable.description &&
                              variable.description.trim());
    const label = el("label", described ? "check" : "check compact");
    const units = variable.units ? `· ${esc(variable.units)}` : "";
    label.innerHTML =
      `<input type="checkbox" value="${esc(variable.name)}">` +
      `<span><span class="name">${esc(variableLabel(variable))}</span>` +
      `<span class="sub">${esc(variable.name)} ${units}</span></span>`;
    const haystack = `${variable.name} ${variable.description || ""} ` +
                     `${variable.units || ""}`.toLowerCase();
    label.hidden = Boolean(term) && !haystack.includes(term);
    label.querySelector("input").addEventListener("change", countVariables);
    host.appendChild(label);
  }

  // A filter only earns its place once the list is long enough to need one.
  $("variable-filter").hidden = state.variables.length < 8;
  countVariables();
}

function countVariables() {
  const boxes = [...$("variables").querySelectorAll("input")];
  const picked = boxes.filter((box) => box.checked).length;
  $("variable-count").textContent =
    `${picked} of ${boxes.length} selected`;
  if (picked) {
    $("variables-hint").textContent = "Choose at least one.";
    $("variables-hint").style.color = "";
  }
}

function setAllVariables(checked) {
  $("variables").querySelectorAll("input")
    .forEach((box) => { box.checked = checked; });
  countVariables();
}

function showRange(kind, panelId, supported, range) {
  const visible = Boolean(supported && hasChoice(range));
  $(panelId).hidden = !visible;
  if (!visible) return;
  const units = range.units && range.units !== "UTC" ? ` ${range.units}` : "";
  $(`${kind}-available`).textContent =
    `Available: ${prettyDate(range.minimum)} to ${prettyDate(range.maximum)}${units}`;

  if (kind === "date") bindDateRange(range);
  if (kind === "depth") bindDepthSliders(range);
}

/* Say what is wrong beside the control, without overwriting what it says
   about itself. */
function complain(id, panelId, message) {
  let note = $(id);
  if (!note) {
    note = el("p", "hint");
    note.id = id;
    $(panelId).appendChild(note);
  }
  note.textContent = message;
  note.style.color = "var(--bad)";
  note.hidden = false;
  $(panelId).scrollIntoView({ behavior: "smooth", block: "center" });
}

function clearComplaint(id) {
  const note = $(id);
  if (note) note.hidden = true;
}

/* Bound both pickers to the dataset's period, and to each other, so an
   impossible range cannot be built in the first place. */
function bindDateRange(range) {
  const first = String(range.minimum).slice(0, 10);
  const last = String(range.maximum).slice(0, 10);
  const start = $("date-start");
  const end = $("date-end");

  start.min = end.min = first;
  start.max = end.max = last;

  const tighten = () => {
    // The calendar greys out anything that would invert the range.
    end.min = start.value || first;
    start.max = end.value || last;
  };

  start.oninput = () => {
    if (end.value && start.value > end.value) end.value = start.value;
    tighten();
  };
  end.oninput = () => {
    if (start.value && end.value < start.value) start.value = end.value;
    tighten();
  };
  tighten();
}

/* A step a person would choose: 1, 2 or 5 times a power of ten. An awkward
   step leaves the slider unable to reach its own maximum. */
function niceStep(span) {
  if (!(span > 0)) return 1;
  const rough = span / 100;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const scaled = rough / magnitude;
  const factor = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return factor * magnitude;
}

/* Each end of the depth range has a slider and a box, kept in step. */
function bindDepthSliders(range) {
  const low = Number(range.minimum), high = Number(range.maximum);
  const step = niceStep(high - low);

  for (const end of ["min", "max"]) {
    const slider = $(`depth-${end}-slider`);
    const box = $(`depth-${end}`);
    slider.min = box.min = low;
    slider.max = box.max = high;
    box.step = step;
    // The slider moves freely and its value is rounded on release, because
    // stepping from an arbitrary start rarely lands on the true maximum.
    slider.step = "any";
    slider.value = box.value = end === "min" ? low : high;

    slider.oninput = () => {
      box.value = snapDepth(Number(slider.value), low, high, step);
      keepDepthOrdered(end);
    };
    slider.onchange = () => { slider.value = box.value; };
    box.oninput = () => { slider.value = box.value; keepDepthOrdered(end); };
  }
}

/* Round to the step, but let the two ends be exactly reachable. */
function snapDepth(value, low, high, step) {
  if (value <= low + step / 2) return low;
  if (value >= high - step / 2) return high;
  const rounded = low + Math.round((value - low) / step) * step;
  return Number(Math.min(Math.max(rounded, low), high).toFixed(3));
}

function keepDepthOrdered(moved) {
  const from = Number($("depth-min").value);
  const to = Number($("depth-max").value);
  if (from <= to) return;
  // Push the other end rather than letting the range invert.
  const other = moved === "min" ? "max" : "min";
  $(`depth-${other}`).value = moved === "min" ? from : to;
  $(`depth-${other}-slider`).value = $(`depth-${other}`).value;
}

function showArea(supported, latitude, longitude) {
  const visible = Boolean(supported &&
                          (hasChoice(latitude) || hasChoice(longitude)));
  $("g-area").hidden = !visible;
  if (!visible) return;
  const parts = [];
  if (longitude) parts.push(`${longitude.minimum} to ${longitude.maximum} east`);
  if (latitude) parts.push(`${latitude.minimum} to ${latitude.maximum} north`);
  $("area-available").textContent = `Available: ${parts.join(", ")}`;

  state.areaBounds = { latitude, longitude };
  const bound = (id, range, which) => {
    if (!range) return;
    $(id).min = range.minimum;
    $(id).max = range.maximum;
  };
  bound("area-west", longitude); bound("area-east", longitude);
  bound("area-south", latitude); bound("area-north", latitude);
}

/* -- building the request ------------------------------------------------ */

function textOf(id) {
  const raw = $(id).value.trim();
  return raw === "" ? null : raw;
}

function numberOf(id) {
  const raw = textOf(id);
  return raw === null ? null : Number(raw);
}

function buildSelection() {
  const variables = [...$("variables").querySelectorAll("input:checked")]
    .map((input) => input.value);

  const body = {
    source_id: state.source.source_id,
    dataset_id: state.dataset.dataset_id,
    variables,
  };
  if (textOf("date-start") && textOf("date-end"))
    body.time = { start: textOf("date-start"), end: textOf("date-end") };
  if (numberOf("depth-min") !== null && numberOf("depth-max") !== null)
    body.depth = { minimum: numberOf("depth-min"), maximum: numberOf("depth-max") };
  const area = ["area-west", "area-east", "area-south", "area-north"]
    .map(numberOf);
  if (area.every((value) => value !== null))
    body.area = { west: area[0], east: area[1], south: area[2], north: area[3] };
  return body;
}

/* How much data the selection covers, from the ranges the source reported.

   Gridded data multiplies its axes together. Row-based data does not: its
   position, depth and time all belong to the same list of measurements, so
   narrowing any of them filters the same rows rather than shrinking a
   separate axis. */
function estimateBytes(selection) {
  const details = state.details;
  if (!details) return null;
  const ranges = details.ranges || [];
  if (!ranges.length) return null;

  const chosen = selection.variables.length ||
                 (details.variables || []).length;
  if (!chosen) return null;

  const variableDims = new Set();
  for (const variable of details.variables || [])
    for (const dimension of variable.dimensions || []) variableDims.add(dimension);

  const axes = ranges.filter((range) => variableDims.has(range.name));
  let points;
  if (axes.length) {
    points = 1;                                   // gridded: axes multiply
    for (const range of axes)
      if (range.count) points *= fractionOf(range, selection) * range.count;
  } else {
    let rows = 0, kept = 1;                       // row-based: filters compound
    for (const range of ranges) {
      rows = Math.max(rows, range.count || 0);
      kept *= fractionOf(range, selection);
    }
    points = rows * kept;
  }
  return Math.round(points * chosen * 4);   // 4 bytes per value
}

function fractionOf(range, selection) {
  const span = (low, high, min, max) => {
    const extent = max - min;
    if (!(extent > 0)) return 1;
    const clipped = Math.min(high, max) - Math.max(low, min);
    return Math.max(0, Math.min(1, clipped / extent));
  };
  if (range.role === "time" && selection.time) {
    const toTime = (value) => Date.parse(String(value).replace(" ", "T"));
    const min = toTime(range.minimum), max = toTime(range.maximum);
    const low = toTime(selection.time.start), high = toTime(selection.time.end);
    if ([min, max, low, high].every(Number.isFinite))
      return span(low, high, min, max) || 1 / range.count;
  }
  if (range.role === "vertical" && selection.depth)
    return span(selection.depth.minimum, selection.depth.maximum,
                Number(range.minimum), Number(range.maximum)) || 1 / range.count;
  if (range.role === "latitude" && selection.area)
    return span(selection.area.south, selection.area.north,
                Number(range.minimum), Number(range.maximum)) || 1 / range.count;
  if (range.role === "longitude" && selection.area)
    return span(selection.area.west, selection.area.east,
                Number(range.minimum), Number(range.maximum)) || 1 / range.count;
  return 1;
}

function humanSize(bytes) {
  if (!bytes || bytes < 1024) return `${bytes || 0} bytes`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[index]}`;
}

/* -- step 4: review ------------------------------------------------------ */

function toReview() {
  const start = textOf("date-start"), end = textOf("date-end");
  if (start && end && start > end) {
    complain("date-problem", "g-date",
             "The start date must not be after the end date.");
    return;
  }
  clearComplaint("date-problem");

  const selection = buildSelection();
  if (!selection.variables.length) {
    $("variables-hint").textContent = "Choose at least one variable to continue.";
    $("variables-hint").style.color = "var(--bad)";
    return;
  }
  $("variables-hint").textContent = "Choose at least one.";
  $("variables-hint").style.color = "";
  state.selection = selection;

  const names = new Map((state.details.variables || [])
    .map((variable) => [variable.name, variableLabel(variable)]));

  const rows = [
    ["Source", state.source.name],
    ["Dataset", state.details.name],
    ["Variables", selection.variables.map((n) => names.get(n) || n).join(", ")],
  ];
  if (selection.time)
    rows.push(["Date range",
               `${selection.time.start} to ${selection.time.end}`]);
  if (selection.depth)
    rows.push(["Depth",
               `${selection.depth.minimum} to ${selection.depth.maximum} m`]);
  if (selection.area)
    rows.push(["Area",
               `${selection.area.west} to ${selection.area.east} east, ` +
               `${selection.area.south} to ${selection.area.north} north`]);

  $("summary").innerHTML = rows
    .map(([term, value]) =>
      `<dt>${esc(term)}</dt><dd>${esc(value)}</dd>`).join("");

  const bytes = estimateBytes(selection);
  $("estimate").hidden = bytes === null;
  if (bytes !== null)
    $("estimate").textContent = `Estimated size: about ${humanSize(bytes)}.`;

  showStep("step4", 4);
}

/* -- importing ----------------------------------------------------------- */

const STAGES = [
  ["Downloading", "Reading the data"],
  ["Preparing data", "Preparing the data"],
  ["Checking data", "Checking the data"],
  ["Sending to storage", "Saving"],
];

function renderStages(completedThrough, failedAt) {
  $("progress-list").innerHTML = STAGES.map(([label], index) => {
    let cssClass = "";
    if (failedAt === index) cssClass = "failed";
    else if (index < completedThrough) cssClass = "done";
    else if (index === completedThrough) cssClass = "active";
    const mark = cssClass === "done" ? "✓" : cssClass === "failed" ? "!" : "·";
    return `<li class="${cssClass}"><span class="mark">${mark}</span>${esc(label)}</li>`;
  }).join("");
  const filled = failedAt !== undefined
    ? (failedAt / STAGES.length) * 100
    : (completedThrough / STAGES.length) * 100;
  $("bar-fill").style.width = `${filled}%`;
}

async function runImport() {
  showStep("progress-panel", null);
  renderStages(0);
  $("do-import").disabled = true;

  let job;
  try {
    job = await api("/api/imports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.selection),
    });
    while (!job.done) {
      await new Promise((resolve) => setTimeout(resolve, 600));
      job = await api(`/api/imports/${job.import_id}`);
    }
  } catch (error) {
    renderStages(0, 0);
    showResult(null, error.message);
    return;
  } finally {
    $("do-import").disabled = false;
  }

  if (job.ok) {
    renderStages(STAGES.length);
    await new Promise((resolve) => setTimeout(resolve, 350));
    showResult(job);
  } else {
    renderStages(0, 2);
    showResult(job);
  }
}

function showResult(job, message) {
  showStep("result-panel", null);
  const host = $("result");

  if (!job || !job.ok) {
    const problems = (job && job.result && job.result.validation &&
                      job.result.validation.problems) || [];
    /* When the data itself was the problem, list what was wrong with it.
       The raw summary repeats those lines prefixed with internal check
       names, so it is shown only when there is nothing better to say. */
    const body = problems.length
      ? `<div>Problems found:</div><ul class="problems">${problems
          .map((problem) => `<li>${esc(problem.detail)}</li>`).join("")}</ul>`
      : `<div>${esc(message || (job && job.message) ||
                    "Something went wrong.")}</div>`;
    host.innerHTML =
      `<div class="banner bad"><span class="headline">Import failed</span>` +
      body + `</div>`;
    return;
  }

  const result = job.result;
  const names = new Map((state.details.variables || [])
    .map((variable) => [variable.name, variableLabel(variable)]));
  /* Dimensions are named by the source; say what they mean instead. */
  const roleOf = Object.fromEntries(
    Object.entries(result.coordinates || {}).map(([role, name]) => [name, role]));
  const DIMENSION_WORDS = { time: ["time step", "time steps"],
                            vertical: ["depth level", "depth levels"],
                            latitude: ["row", "rows"],
                            longitude: ["column", "columns"],
                            observation: ["measurement", "measurements"] };
  const size = Object.entries(result.sizes)
    .map(([name, count]) => {
      const words = DIMENSION_WORDS[roleOf[name]] || DIMENSION_WORDS[name];
      const word = words ? words[count === 1 ? 0 : 1] : name;
      return `${count} ${word}`;
    }).join(" × ");

  host.innerHTML =
    `<div class="banner ok"><span class="headline">Imported successfully</span></div>` +
    `<dl class="summary">` +
    `<dt>Source</dt><dd>${esc(result.source.source_name)}</dd>` +
    `<dt>Dataset</dt><dd>${esc(state.details.name)}</dd>` +
    `<dt>Variables</dt><dd>${esc(result.variables
        .map((name) => names.get(name) || name).join(", "))}</dd>` +
    `<dt>Data type</dt><dd>${esc(SHAPE_WORDS[result.geometry] || result.geometry)}</dd>` +
    `<dt>Size</dt><dd>${esc(size)}</dd>` +
    `<dt>Checks</dt><dd>All ${result.validation.checks_run.length} checks passed</dd>` +
    `</dl>`;
}

/* -- navigation ---------------------------------------------------------- */

function restart() {
  state.source = null;
  state.dataset = null;
  state.details = null;
  state.selection = null;
  showStep("step1", 1);
}

document.querySelectorAll("[data-back]").forEach((button) => {
  button.addEventListener("click", () =>
    goToStep(Number(button.dataset.back)));
});

for (const item of $("steps").children) {
  item.addEventListener("click", () => goToStep(Number(item.dataset.step)));
}

$("search").addEventListener("input", renderDatasets);
$("variable-filter").addEventListener("input", renderVariables);
$("select-all").addEventListener("click", () => setAllVariables(true));
$("select-none").addEventListener("click", () => setAllVariables(false));
$("area-full").addEventListener("click", () => {
  const { latitude, longitude } = state.areaBounds || {};
  if (longitude) {
    $("area-west").value = longitude.minimum;
    $("area-east").value = longitude.maximum;
  }
  if (latitude) {
    $("area-south").value = latitude.minimum;
    $("area-north").value = latitude.maximum;
  }
});
$("to-review").addEventListener("click", toReview);
$("do-import").addEventListener("click", runImport);
$("restart").addEventListener("click", restart);

showStep("step1", 1);
loadSources();
