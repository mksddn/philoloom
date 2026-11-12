/** Desktop and mobile browser smoke checks; captures CI screenshots. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdir } = require('node:fs/promises');
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8765';
const server = spawn('python3', ['-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', 'dist'], { stdio: 'ignore' });
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(base)).ok) return; } catch (_) {}
    await pause(200);
  }
  throw new Error('Static preview server did not start');
}
async function assertNoOverflow(page, label) {
  const sizes = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth,
  }));
  assert.ok(sizes.content <= sizes.viewport + 1, label + ': horizontal overflow ' + JSON.stringify(sizes));
}
(async () => {
  let browser;
  try {
    await waitForServer();
    await mkdir('screenshots', { recursive: true });
    browser = await chromium.launch({ headless: true });
    const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const home = await desktop.newPage();
    const errors = [];
    home.on('pageerror', error => errors.push(error.message));
    await home.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    assert.equal((await home.locator('.hero-cover h1').textContent()).replace(/\s+/g, ' ').trim(), 'Философия как искусство мышления');
    assert.equal(await home.locator('#theme-toggle').getAttribute('aria-pressed'), 'false');
    assert.equal(await home.locator('.section-nav a').count(), 4);
    assert.equal(await home.locator('.reference-section').count(), 4);
    assert.equal(await home.locator('.museum-shortcuts a').count(), 4);
    assert.equal(await home.locator('.editorial-topic').count(), 5);
    assert.ok(await home.locator('.editorial-spotlight').isVisible());

    await home.waitForFunction(() => [...document.querySelectorAll('.hero-artwork img, .editorial-topic img')]
      .every(image => image.complete), null, { timeout: 20000 });
    const artworkStatus = await home.locator('.hero-artwork img, .editorial-topic img')
      .evaluateAll(images => images.map(image => ({ url: image.src, loaded: image.naturalWidth > 0 })));
    assert.ok(artworkStatus.every(image => image.loaded),
      'All hero and editorial images must load: ' + JSON.stringify(artworkStatus));
    await assertNoOverflow(home, 'desktop home');
    await home.screenshot({ path: 'screenshots/01-home-desktop-dark.png', fullPage: true });
    await home.locator('#theme-toggle').click();
    assert.equal(await home.locator('html').getAttribute('data-theme'), 'light');
    await home.screenshot({ path: 'screenshots/02-home-desktop-light.png', fullPage: true });
    await home.reload({ waitUntil: 'domcontentloaded' });
    assert.equal(await home.locator('html').getAttribute('data-theme'), 'light');
    await home.locator('#search-open').click();
    assert.ok(await home.locator('#search-dialog').evaluate(element => element.open));
    await home.locator('#query').fill('онтология');
    await home.waitForFunction(() => document.querySelector('#search-status')?.textContent.startsWith('Найдено страниц'));
    assert.ok(await home.locator('#results a').count() > 0);
    await home.keyboard.press('Escape');
    await home.waitForFunction(() => !document.querySelector('#search-dialog').open);
    await home.locator('[data-resource-open="watch"]').click();
    assert.ok(await home.locator('#resource-dialog').evaluate(element => element.open));
    await home.locator('#resource-close').click();
    await home.locator('.section-nav a').first().click();
    await home.locator('.reference-section:not([hidden]) [data-view="list"]').click();
    assert.ok(await home.locator('.reference-section:not([hidden]) .entry-list').isVisible());
    await home.locator('.reference-section:not([hidden]) [data-view="gallery"]').click();
    await home.locator('.reference-section:not([hidden]) .cards .card').first().click();
    await home.locator('#panel-content h1').waitFor();
    assert.ok(await home.locator('#page-panel').evaluate(element => element.open));
    await home.locator('#panel-close').click();
    assert.deepEqual(errors, [], 'No uncaught JavaScript errors on desktop');
    await desktop.close();
    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1 });
    const small = await mobile.newPage();
    const mobileErrors = [];
    small.on('pageerror', error => mobileErrors.push(error.message));
    await small.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'dark');
    await assertNoOverflow(small, '390px home');
    await small.screenshot({ path: 'screenshots/03-home-mobile-dark.png', fullPage: true });
    await small.locator('#theme-toggle').click();
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'light');
    await small.screenshot({ path: 'screenshots/04-home-mobile-light.png', fullPage: true });
    await small.goto(base + '/89ecf3804396453cbc4256966e24aa27.html', { waitUntil: 'domcontentloaded' });
    assert.ok(await small.locator('article').isVisible());
    assert.ok(await small.locator('.page-breadcrumbs').isVisible());
    await assertNoOverflow(small, '390px article');
    await small.locator('[data-reader-toggle]').click();
    assert.equal(await small.locator('body').evaluate(el => el.classList.contains('reader-mode')), true);
    await small.screenshot({ path: 'screenshots/05-article-mobile-reader.png', fullPage: true });
    assert.deepEqual(mobileErrors, [], 'No uncaught JavaScript errors on mobile');
    await mobile.close();
    const narrow = await browser.newContext({ viewport: { width: 320, height: 640 }, isMobile: true });
    const narrowPage = await narrow.newPage();
    await narrowPage.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px home');
    await narrowPage.goto(base + '/89ecf3804396453cbc4256966e24aa27.html', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px article');
    await narrowPage.screenshot({ path: 'screenshots/06-article-narrow.png', fullPage: true });
    await narrow.close();
    console.log('Desktop 1440px, mobile 390px and narrow mobile 320px checks passed.');
  } finally {
    await browser?.close();
    server.kill('SIGTERM');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
