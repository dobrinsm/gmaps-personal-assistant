/**
 * export-contract smoke tests (Node, no browser needed).
 * Loads frontend/app.js in a minimal DOM stub and asserts the export builders
 * produce valid Google Maps URLs, well-formed KML, and RFC4180 CSV.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");

// ── Minimal DOM/browser stubs ────────────────────────────────────────
function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", value: "", disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    style: {}, scrollIntoView() {}, querySelectorAll() { return []; },
  };
}
const elements = {};
const sandbox = {
  window: { location: { origin: "http://localhost:3000" }, open() {}, addEventListener() {} },
  document: {
    getElementById(id) { if (!elements[id]) elements[id] = makeEl(id); return elements[id]; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    createElement(tag) { return makeEl(`created-${tag}`); },
    addEventListener() {},
    body: { appendChild() {}, removeChild() {} },
  },
  localStorage: {
    _s: {}, getItem(k) { return this._s[k] || null; },
    setItem(k, v) { this._s[k] = String(v); },
  },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert() {}, confirm() { return false; },
  console,
  Blob: class {}, URL: { createObjectURL() { return "blob:x"; }, revokeObjectURL() {} },
  setTimeout, clearTimeout,
  L: undefined, // Leaflet absent — map functions must no-op safely
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: "app.js" });

let passed = 0, failed = 0;
function check(name, cond) {
  if (cond) { passed++; }
  else { failed++; console.error(`FAIL: ${name}`); }
}

const NB = {
  destination: "Catania",
  shortlist: [
    { id: "p1", name: 'Osteria "da Vito"', rating: 4.7, combined_score: 8.4, intent_score: 9, taste_score: 8,
      scored_by: "llm", lat: 37.5043, lng: 15.0872, address: 'Via 1, "Catania"', maps_url: "https://maps.app/p1",
      types: ["restaurant"], price_level: "MODERATE", match_reason: 'Fresh "seafood"' },
    { id: "p2", name: "Cafe Lento", rating: 4.4, combined_score: 6.2, intent_score: 3, taste_score: 9,
      scored_by: "llm", lat: 37.5080, lng: 15.0900, address: "Via 2, Catania", maps_url: "",
      types: ["cafe"], price_level: "INEXPENSIVE", match_reason: "Cozy coffee" },
    { id: "p3", name: "No Coords Bar", rating: 4.0, combined_score: 5.0, intent_score: 5, taste_score: 5,
      scored_by: "heuristic", address: "Via 3, Catania", maps_url: "", types: ["bar"], match_reason: "x" },
  ],
};

// ── Google Maps directions URL ──────────────────────────────────────
const mapsUrl = vm.runInContext(`buildMapsDirUrl(${JSON.stringify(NB.shortlist)})`, sandbox);
check("maps URL is a directions URL", mapsUrl.startsWith("https://www.google.com/maps/dir/"));
check("maps URL uses coords for geocoded stops", mapsUrl.includes("37.5043,15.0872"));
check("maps URL caps at 10 stops", vm.runInContext(
  `buildMapsDirUrl(Array.from({length: 14}, (_, i) => ({name: 'Place ' + i, lat: i, lng: i}))).replace('https://www.google.com/maps/dir/','').split('/').length === 10`,
  sandbox
));

// ── KML ─────────────────────────────────────────────────────────────
const { kml, skipped } = vm.runInContext(`buildKML(${JSON.stringify(NB.shortlist)})`, sandbox);
check("KML skipped no-coord entries", skipped === 1);
check("KML is XML-declared", kml.startsWith('<?xml version="1.0"'));
check("KML has kml namespace", kml.includes('xmlns="http://www.opengis.net/kml/2.2"'));
check("KML includes geocoded placemarks", (kml.match(/<Placemark>/g) || []).length === 2);
check("KML coordinates are lng,lat order", kml.includes("<coordinates>15.0872,37.5043,0</coordinates>"));
check("KML wraps titles in CDATA", kml.includes("<![CDATA[(8) Osteria"));
check("KML includes dual scores in description", kml.includes("Intent: 9/10") && kml.includes("Taste: 8/10"));
// names with quotes survive CDATA (well-formedness: no raw < in names)
check("KML name quoting safe", kml.includes('Osteria "da Vito"'));

// ── CSV ─────────────────────────────────────────────────────────────
const csv = vm.runInContext(`buildCSV(${JSON.stringify(NB.shortlist)})`, sandbox);
const lines = csv.trim().split("\n");
check("CSV header present", lines[0].startsWith("Name,Score,IntentScore,TasteScore,ScoredBy"));
check("CSV row count = shortlist count", lines.length === 4);
check("CSV RFC4180 quotes embedded quotes", lines[1].includes('""da Vito""'));
check("CSV includes dual scores", lines[1].includes('"8.4","9","8","llm"'));
check("CSV marks heuristic rows", lines[3].includes('"heuristic"'));
check("CSV includes coords", lines[1].includes('"37.5043","15.0872"'));
check("CSV no-coords row has empty lat/lng", lines[3].includes(',"",""'));
check("CSV fallback maps link uses name", lines[3].includes("No%20Coords%20Bar"));

// ── mapsHrefFor fallbacks ───────────────────────────────────────────
check("mapsHref prefers maps_url", vm.runInContext(
  `mapsHrefFor({maps_url: 'https://maps.app/x', lat: 1, lng: 2})`, sandbox) === "https://maps.app/x");
check("mapsHref uses coords when no maps_url", vm.runInContext(
  `mapsHrefFor({lat: 1, lng: 2})`, sandbox).includes("query=1,2"));
check("mapsHref falls back to name without coords", vm.runInContext(
  `mapsHrefFor({name: 'Some Bar'})`, sandbox).includes("query=Some%20Bar"));

// ── scoreColor + placeKey ───────────────────────────────────────────
check("scoreColor high is green", vm.runInContext(`scoreColor(9)`, sandbox) === "#22c55e");
check("scoreColor low is gray", vm.runInContext(`scoreColor(1)`, sandbox) === "#71717a");
check("placeKey geo for coords", vm.runInContext(`placeKey({lat: 1, lng: 2})`, sandbox) === "geo:1,2");
check("placeKey name fallback", vm.runInContext(`placeKey({name: 'Foo'})`, sandbox) === "name:foo");

// ── map no-op safety without Leaflet ────────────────────────────────
vm.runInContext(`currentNotebook = ${JSON.stringify(NB)}; renderItineraryMap();`, sandbox);
check("renderItineraryMap no-ops without Leaflet (no crash)", true);

console.log(`\nExport smoke: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
