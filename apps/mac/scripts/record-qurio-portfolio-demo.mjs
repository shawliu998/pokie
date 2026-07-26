/* global console, document, process */

import { chromium } from '@playwright/test';
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const demoUrl = process.env.QURIO_DEMO_URL ?? 'http://127.0.0.1:5173/';
const repoRoot = resolve(import.meta.dirname, '../../..');
const outputDir = resolve(repoRoot, 'docs/portfolio');
const rawDir = resolve(outputDir, '.video-recording');
const outputPath = resolve(outputDir, 'qurio-90-second-mainline.webm');

mkdirSync(outputDir, { recursive: true });
rmSync(rawDir, { recursive: true, force: true });
mkdirSync(rawDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  colorScheme: 'dark',
  recordVideo: {
    dir: rawDir,
    size: { width: 1440, height: 900 },
  },
});
const page = await context.newPage();
const video = page.video();

async function caption(kicker, title, detail) {
  await page.evaluate(({ kicker, title, detail }) => {
    let element = document.querySelector('#qurio-demo-caption');
    if (!element) {
      element = document.createElement('aside');
      element.id = 'qurio-demo-caption';
      element.style.cssText = [
        'position:fixed',
        'right:28px',
        'bottom:24px',
        'z-index:2147483647',
        'width:410px',
        'padding:15px 17px 16px',
        'border:1px solid rgba(167,173,255,.42)',
        'border-radius:6px',
        'background:rgba(15,17,22,.94)',
        'box-shadow:0 16px 44px rgba(0,0,0,.32)',
        'font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
        'color:#f4f6fb',
        'pointer-events:none',
      ].join(';');
      document.body.appendChild(element);
    }
    element.innerHTML = `
      <div style="color:#9ba0ff;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase">${kicker}</div>
      <div style="margin-top:7px;font-size:19px;font-weight:650;line-height:1.25">${title}</div>
      <div style="margin-top:6px;color:#b6bdcc;font-size:13px;line-height:1.45">${detail}</div>
    `;
  }, { kicker, title, detail });
}

async function hold(milliseconds) {
  await page.waitForTimeout(milliseconds);
}

try {
  await page.goto(demoUrl, { waitUntil: 'domcontentloaded' });
  const guidedEntry = page.getByRole('button', { name: /Open guided demo/ });
  await guidedEntry.waitFor({ state: 'visible', timeout: 15_000 });
  await caption(
    'Qurio / Guided Demo',
    'One real-data, real-Provider research record',
    'A read-only retained Run. Opening it spends no Provider tokens and cannot mutate its evidence.',
  );
  await hold(6_000);

  await guidedEntry.click();
  await page.getByRole('heading', { name: 'Agent decision' }).waitFor({
    state: 'visible',
    timeout: 15_000,
  });
  await caption(
    'Autonomous research loop',
    'Observation → Why Qurio changed → Next action',
    'DeepSeek chose registered actions; the deterministic evaluator returned the evidence for the next decision.',
  );
  await hold(16_000);

  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await caption(
    'Inspectable evidence',
    'One candidate identity across every analysis view',
    'Equity, benchmark, drawdown, market context and retained trades all resolve to the selected RSI candidate.',
  );
  await hold(12_000);

  await page.getByRole('tab', { name: 'Drawdown', exact: true }).click();
  await caption(
    'Deterministic evaluator',
    'The model never calculates performance metrics',
    'One quantitative kernel owns returns, Sharpe, drawdown, trades and benchmark comparison.',
  );
  await hold(9_000);

  await page.getByRole('tab', { name: 'Market', exact: true }).click();
  await caption(
    'Retained context',
    'Signals stay attached to exact market observations',
    'The product preserves timestamps and the pinned BTCUSDT four-hour dataset rather than summarizing a chart in chat.',
  );
  await hold(8_000);

  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  await caption(
    'Exact evidence',
    'Every retained trade remains inspectable',
    'Entry, exit, holding bars and elapsed time come from the same authoritative backtest result.',
  );
  await hold(9_000);

  await page.getByRole('tab', { name: 'Decision', exact: true }).click();
  await caption(
    'Sealed validation',
    'Training selected RSI; the sealed holdout passed',
    'The holdout opened once after the final training choice. This proves the workflow—not future alpha.',
  );
  await hold(16_000);

  await page.getByRole('tab', { name: 'Experiments', exact: true }).click();
  await caption(
    'Qurio',
    'A complete Agent product loop, not a chat wrapper',
    'Real market data → bounded autonomy → comparative evidence → honest conclusion → structured Research Memory.',
  );
  await hold(12_000);
} finally {
  await context.close();
  await browser.close();
}

const rawPath = await video.path();
const ffmpegRoot = resolve(homedir(), 'Library/Caches/ms-playwright');
const ffmpegVersion = existsSync(ffmpegRoot)
  ? readdirSync(ffmpegRoot).find((name) => name.startsWith('ffmpeg-'))
  : undefined;
const ffmpegPath = ffmpegVersion
  ? resolve(ffmpegRoot, ffmpegVersion, 'ffmpeg-mac')
  : '';
if (ffmpegPath && existsSync(ffmpegPath)) {
  const result = spawnSync(
    ffmpegPath,
    ['-y', '-i', rawPath, '-t', '90', '-c', 'copy', outputPath],
    { encoding: 'utf8' },
  );
  if (result.status !== 0) {
    throw new Error(`Unable to trim the recorded video: ${result.stderr}`);
  }
} else {
  await video.saveAs(outputPath);
}
rmSync(rawDir, { recursive: true, force: true });
console.log(outputPath);
