import { expect, test } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

test.describe.configure({ timeout: 120_000 });

test('D1 Connector Directory fetches Kraken data into Catalog, Preview, and research setup', async ({ page }) => {
  test.skip(process.env.GLINT_E2E_API_MODE !== 'fixture', 'D1 connector proof uses the deterministic loopback fixture API.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('quant-sidebar').getByRole('button', { name: 'Data', exact: true }).click();

  await page.getByRole('tab', { name: 'Connections' }).click();
  const connections = page.getByRole('tabpanel', { name: 'Connections' });
  await expect(connections.getByRole('term').filter({ hasText: 'Kraken Spot public OHLC' })).toBeVisible();
  await expect(connections).toContainText('4h and 1D');
  await expect(connections).toContainText('BTCUSD, BTCUSDT, ETHUSD, ETHUSDT');
  await connections.getByRole('button', { name: 'Fetch data' }).click();

  const kraken = page.getByRole('tabpanel', { name: 'Kraken Spot public OHLC' });
  await expect(kraken.getByLabel('Kraken Spot symbol')).toHaveValue('BTCUSD');
  await expect(kraken.getByLabel('Kraken Spot interval')).toHaveValue('4h');
  await expect(kraken.getByLabel('Kraken Spot bar limit')).toHaveValue('548');
  const fetchRequest = page.waitForRequest((request) => request.url().endsWith('/v1/quant/connectors/kraken-spot-ohlc-v1/fetch') && request.method() === 'POST');
  await kraken.getByRole('button', { name: 'Fetch and validate' }).click();
  expect((await fetchRequest).postDataJSON()).toEqual({
    name: 'BTCUSD Kraken Spot 4 hour',
    symbol: 'BTCUSD',
    interval: '4h',
    limit: 548,
  });

  const catalog = page.getByRole('table', { name: 'Available research datasets' });
  const row = catalog.getByRole('row', { name: /BTCUSD Kraken Spot 4 hour/ });
  await expect(row).toContainText('Kraken Spot deterministic connector fixture');
  await expect(row).toContainText('548');
  await row.getByRole('button', { name: 'Preview' }).click();

  const preview = page.locator('.quant-dataset-preview');
  await expect(preview.getByRole('heading', { name: 'BTCUSD · 4h' }).first()).toBeVisible();
  await expect(preview.getByRole('img', { name: 'BTCUSD 4h price and volume chart' })).toBeVisible();
  await expect(preview).toContainText('240 of 548 stored bars shown');
  await preview.getByRole('button', { name: 'Use for research' }).click();

  await expect(page.getByRole('heading', { name: 'New research' })).toBeVisible();
  await expect(page.getByText('BTCUSD · 4h', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Research dataset')).toHaveValue('fixture-connector-kraken-btcusd-4h-548');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
