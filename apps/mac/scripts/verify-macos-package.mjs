import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

if (process.platform !== 'darwin') {
  throw new Error('Qurio macOS package verification must run on macOS.');
}

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.resolve(scriptsDir, '..');
const bundleDir = path.join(macDir, 'src-tauri', 'target', 'release', 'bundle');
const appPath = path.join(bundleDir, 'macos', 'Qurio.app');
const dmgPath = path.join(bundleDir, 'dmg', 'Qurio_0.1.0_aarch64.dmg');
const runtimePath = path.join(appPath, 'Contents', 'Resources', 'qurio-runtime', 'qurio-runtime');
const info = JSON.parse(execFileSync('/usr/bin/plutil', ['-convert', 'json', '-o', '-', path.join(appPath, 'Contents', 'Info.plist')], { encoding: 'utf8' }));
const executablePath = path.join(appPath, 'Contents', 'MacOS', info.CFBundleExecutable);

for (const requiredPath of [dmgPath, executablePath, runtimePath]) {
  if (!statSync(requiredPath).size) {
    throw new Error(`Empty package artifact: ${requiredPath}`);
  }
}

execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], { stdio: 'inherit' });

if (info.CFBundleDisplayName !== 'Qurio' && info.CFBundleName !== 'Qurio') {
  throw new Error('Packaged application is not branded Qurio.');
}
if (info.CFBundleIdentifier !== 'com.glint.workbench') {
  throw new Error(`Unexpected bundle identifier: ${info.CFBundleIdentifier}`);
}

const digest = createHash('sha256').update(readFileSync(dmgPath)).digest('hex');
const checksumPath = path.join(path.dirname(dmgPath), 'SHA256SUMS.txt');
writeFileSync(checksumPath, `${digest}  ${path.basename(dmgPath)}\n`);

console.log(`Verified ${appPath}`);
console.log(`Verified ${runtimePath}`);
console.log(`Installer ${dmgPath}`);
console.log(`Checksum ${checksumPath}`);
