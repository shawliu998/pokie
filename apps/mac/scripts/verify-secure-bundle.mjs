import { randomBytes } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const appRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const distRoot = join(appRoot, 'dist');
const marker = 'GLINT_PRODUCTION_TOKEN_SENTINEL_';
const sentinel = `${marker}${randomBytes(48).toString('base64url')}`;

const build = spawnSync('pnpm', ['build'], {
  cwd: appRoot,
  env: { ...process.env, VITE_GLINT_ACCESS_TOKEN: sentinel },
  encoding: 'utf8',
});

if (build.stdout) process.stdout.write(build.stdout);
if (build.stderr) process.stderr.write(build.stderr);
if (build.status !== 0) process.exit(build.status ?? 1);

async function files(path) {
  const entries = await readdir(path, { withFileTypes: true });
  return (await Promise.all(entries.map((entry) => entry.isDirectory() ? files(join(path, entry.name)) : [join(path, entry.name)]))).flat();
}

for (const path of await files(distRoot)) {
  const content = await readFile(path);
  if (content.includes(Buffer.from(sentinel)) || content.includes(Buffer.from(marker))) {
    process.stderr.write(`Production bundle leaked the access-token sentinel in ${path.slice(appRoot.length + 1)}.\n`);
    process.exit(1);
  }
}

process.stdout.write('Secure bundle verification passed: the high-entropy access token sentinel is absent from dist.\n');
