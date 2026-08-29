/*
 * Rasterise the technology-stack marks the SIH deck's slide 3 shows.
 *
 *     node tools/sih-presentation/logos.js
 *
 * Writes brand-coloured PNGs into assets/logos/. This runs ONCE and its output
 * is what build_deck.py reads, so building the deck never needs node installed
 * — only regenerating the marks does.
 *
 * Marks come from simple-icons (CC0). Every entry here is a component the deck
 * actually claims to use; nothing decorative.
 */

const fs = require("fs");
const path = require("path");
const si = require("simple-icons");
const sharp = require("sharp");

const OUT = path.join(__dirname, "assets", "logos");

// slug -> label printed under the mark on the slide.
const MARKS = [
  ["python", "Python"],
  ["numpy", "NumPy"],
  ["numba", "Numba"],
  ["gdal", "GDAL"],
  ["fastapi", "FastAPI"],
  ["sqlite", "SQLite"],
  ["react", "React"],
  ["vite", "Vite"],
  ["leaflet", "Leaflet"],
  ["cesium", "Cesium"],
  ["googleearthengine", "Earth Engine"],
  ["pytest", "pytest"],
];

const SIZE = 256;

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const manifest = [];

  for (const [slug, label] of MARKS) {
    const key = "si" + slug.charAt(0).toUpperCase() + slug.slice(1);
    const icon = si[key];
    if (!icon) {
      console.error(`  ! no simple-icons mark for ${slug}`);
      continue;
    }
    // simple-icons ships monochrome black; paint it the brand colour.
    const svg = icon.svg.replace("<svg ", `<svg fill="#${icon.hex}" `);
    const file = path.join(OUT, `${slug}.png`);
    await sharp(Buffer.from(svg))
      .resize(SIZE, SIZE, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toFile(file);
    manifest.push({ slug, label, hex: icon.hex, title: icon.title });
    console.log(`  ${slug.padEnd(20)} #${icon.hex}  ${icon.title}`);
  }

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(`\nwrote ${manifest.length} marks to ${path.relative(process.cwd(), OUT)}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
