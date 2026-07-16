import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const appRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const workspaceRoot = join(appRoot, '..', '..');
const productionOnly = process.argv.includes('--prod');

function addVersion(packages, name, version) {
  if (!name || !version || version.startsWith('link:') || version.startsWith('workspace:')) return;
  const normalized = version.replace(/\(.+\)$/, '');
  if (!/^\d/.test(normalized)) return;
  const versions = packages.get(name) ?? new Set();
  versions.add(normalized);
  packages.set(name, versions);
}

async function allLockedPackages() {
  const lock = await readFile(join(workspaceRoot, 'pnpm-lock.yaml'), 'utf8');
  const packageSection = lock.split('\npackages:\n', 2)[1]?.split('\nsnapshots:\n', 1)[0];
  if (!packageSection) throw new Error('pnpm-lock.yaml does not contain a packages section.');
  const packages = new Map();
  for (const line of packageSection.split('\n')) {
    const match = line.match(/^ {2}(?:'([^']+)'|([^:\s][^:]*)):\s*$/);
    const key = match?.[1] ?? match?.[2];
    if (!key) continue;
    const separator = key.lastIndexOf('@');
    if (separator <= 0) continue;
    addVersion(packages, key.slice(0, separator), key.slice(separator + 1));
  }
  return packages;
}

function productionPackages() {
  const graph = JSON.parse(execFileSync('pnpm', ['list', '--recursive', '--prod', '--depth', 'Infinity', '--json'], { cwd: workspaceRoot, encoding: 'utf8' }));
  const packages = new Map();
  const visit = (dependencies) => {
    for (const [name, node] of Object.entries(dependencies ?? {})) {
      addVersion(packages, name, node.version ?? '');
      visit(node.dependencies);
    }
  };
  for (const project of graph) visit(project.dependencies);
  return packages;
}

const packages = productionOnly ? productionPackages() : await allLockedPackages();
const payload = Object.fromEntries([...packages].sort(([left], [right]) => left.localeCompare(right)).map(([name, versions]) => [name, [...versions].sort()]));
const response = await fetch('https://registry.npmjs.org/-/npm/v1/security/advisories/bulk', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
  body: JSON.stringify(payload),
});
if (!response.ok) throw new Error(`Official npm bulk advisory endpoint returned ${response.status}: ${await response.text()}`);
const advisories = await response.json();
const findings = Object.entries(advisories).flatMap(([name, records]) => records.map((record) => ({ name, severity: record.severity, title: record.title, vulnerableVersions: record.vulnerable_versions })));
if (findings.length) {
  for (const finding of findings) process.stderr.write(`${finding.severity}: ${finding.name} ${finding.vulnerableVersions} — ${finding.title}\n`);
  process.stderr.write(`Official npm bulk audit found ${findings.length} advisory record(s) across ${packages.size} package name(s).\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`Official npm bulk audit passed: 0 advisories across ${packages.size} ${productionOnly ? 'production' : 'locked'} package name(s).\n`);
}
