// Copy the project version from its single source into the package.json files.
//
//   node desktop/scripts/sync-version.mjs          write it
//   node desktop/scripts/sync-version.mjs --check  exit 1 if anything disagrees (CI)
//
// The single source is jalraksha/__init__.py (__version__). pyproject.toml reads
// it through setuptools' dynamic version and the FastAPI app reports it. The two
// package.json files cannot read Python, so they are kept equal here — and the
// desktop installer takes its version from desktop/package.json.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

export function projectVersion(root = repoRoot) {
  const init = fs.readFileSync(path.join(root, "jalraksha", "__init__.py"), "utf8");
  const match = init.match(/^__version__\s*=\s*["']([^"']+)["']/m);
  if (!match) throw new Error("jalraksha/__init__.py has no __version__ string");
  // electron-builder and npm need semver; PEP 440 pre-release spellings do not qualify.
  if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(match[1])) {
    throw new Error(`__version__ ${match[1]} is not semver (x.y.z or x.y.z-tag)`);
  }
  return match[1];
}

const TARGETS = ["frontend/package.json", "desktop/package.json"];

function main() {
  const check = process.argv.includes("--check");
  const version = projectVersion();
  let mismatched = 0;
  for (const rel of TARGETS) {
    const file = path.join(repoRoot, rel);
    const text = fs.readFileSync(file, "utf8");
    const pkg = JSON.parse(text);
    if (pkg.version === version) continue;
    if (check) {
      console.error(`${rel}: version ${pkg.version} != jalraksha.__version__ ${version}`);
      mismatched += 1;
    } else {
      // Replace only the version value, preserving the file's formatting.
      fs.writeFileSync(file, text.replace(/("version"\s*:\s*")[^"]*(")/, `$1${version}$2`));
      console.log(`${rel}: ${pkg.version} -> ${version}`);
    }
  }
  if (check && mismatched) process.exit(1);
  console.log(`version ${version}${check ? " consistent" : " synced"}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
