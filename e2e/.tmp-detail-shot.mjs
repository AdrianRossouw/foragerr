import { chromium } from 'playwright';
const SP = '/home/agent/.claude/jobs/b0353a00/tmp';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8793/series/5', { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
await page.screenshot({ path: `${SP}/detail-hero.png` });
// bulk selection: click first checkbox, shift-click a later one
const boxes = page.locator('tbody input[type="checkbox"]');
await boxes.nth(0).click();
await boxes.nth(5).click({ modifiers: ['Shift'] });
await page.waitForTimeout(400);
await page.screenshot({ path: `${SP}/detail-bulk.png` });
// collections tab
await page.getByRole('button', { name: /Collections/ }).click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${SP}/detail-collections.png` });
await browser.close();
