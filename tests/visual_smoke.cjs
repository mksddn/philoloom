/** Desktop and mobile browser smoke checks; no screenshots required. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
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
    assert.equal(await home.locator('.featured-quote').count(), 1);
    assert.equal(await home.locator('.hero-cover-content .featured-quote').count(), 1);
    assert.equal(await home.locator('.home-source-strip .featured-quote').count(), 0);
    assert.equal(await home.locator('.resource-tiles .resource-tile').count(), 3);
    assert.equal(await home.locator('.footer-resources').count(), 0);
    assert.equal(await home.locator('.hero-summary').count(), 0);
    assert.ok((await home.locator('.featured-quote blockquote').textContent()).includes(
      'Человеку, исследующему истину, необходимо хоть один раз в жизни усомниться во всех вещах'));
    assert.equal((await home.locator('.featured-quote figcaption').textContent()).trim(), '— Рене Декарт');
    assert.ok(await home.locator('.hero-cover-content .featured-quote').evaluate(el => {
      const quote = el.getBoundingClientRect();
      const hero = document.querySelector('.hero-cover').getBoundingClientRect();
      return quote.top >= hero.top && quote.bottom <= hero.bottom;
    }), 'Quotation must fit within the Hero');
    assert.ok(await home.locator('.resource-tiles').evaluate(el => {
      const hero = document.querySelector('.hero-cover').getBoundingClientRect();
      const tiles = el.getBoundingClientRect();
      const tabs = document.querySelector('.section-nav').getBoundingClientRect();
      return tiles.top >= hero.bottom - 1 && tabs.top >= tiles.bottom - 1;
    }));
    assert.equal(await home.locator('.museum-head').count(), 1);
    assert.equal(await home.locator('.section-nav').count(), 1);
    assert.equal(await home.locator('.museum-shortcuts, .editorial-spotlight, .editorial-shelf, .hero-explore').count(), 0);
    assert.equal(await home.locator('.museum-frame, .museum-top-nav').count(), 0);
    assert.ok(await home.locator('html').evaluate(element => element.classList.contains('tabs-ready')));
    assert.ok(await home.locator('.reference-section:not([hidden]) .cards .card').count() > 20);

    await home.waitForFunction(() => {
      const artwork = document.querySelector('.hero-artwork img');
      return artwork.complete;
    }, null, { timeout: 20000 });
    assert.ok(await home.locator('.hero-artwork img').evaluate(image => image.naturalWidth > 0),
      'Full-bleed sculpture must load');
    const heroDimensions = await home.locator('.hero-cover').evaluate(element => ({
      left: element.getBoundingClientRect().left,
      width: element.getBoundingClientRect().width,
      viewport: document.documentElement.clientWidth,
    }));
    assert.ok(Math.abs(heroDimensions.left) <= 1 && Math.abs(heroDimensions.width - heroDimensions.viewport) <= 1,
      'Hero must span the entire viewport: ' + JSON.stringify(heroDimensions));
    await assertNoOverflow(home, 'desktop home');

    await home.locator('#theme-toggle').click();
    assert.equal(await home.locator('html').getAttribute('data-theme'), 'light');

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
    await home.locator('[data-resource-open="read"]').click();
    assert.ok(await home.locator('#resource-dialog').evaluate(element => element.open));
    assert.ok(await home.locator('#resource-read .resource-card').count() > 0);
    await home.locator('#resource-close').click();
    assert.equal(await home.locator('.resource-tile-blog').getAttribute('href'), 'https://flsf.maxdudin.ru/');
    await home.locator('.section-nav a').first().click();
    assert.equal(await home.locator('.reference-section:not([hidden])').count(), 1);
    await home.locator('.section-nav a').nth(1).click();
    assert.equal(await home.locator('.reference-section:not([hidden])').count(), 1);
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
    assert.equal(await small.locator('.section-nav').count(), 1);
    assert.equal(await small.locator('.resource-tiles .resource-tile').count(), 3);
    assert.ok(await small.locator('.hero-cover-content .featured-quote').isVisible());
    assert.equal(await small.locator('.home-source-strip .featured-quote').count(), 0);
    assert.ok(await small.locator('.hero-cover').evaluate(element =>
      Math.abs(element.getBoundingClientRect().width - document.documentElement.clientWidth) <= 1));

    await small.locator('#theme-toggle').click();
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'light');

    await small.goto(base + '/89ecf3804396453cbc4256966e24aa27.html', { waitUntil: 'domcontentloaded' });
    assert.ok(await small.locator('article').isVisible());
    assert.ok(await small.locator('.page-breadcrumbs').isVisible());
    await assertNoOverflow(small, '390px article');
    await small.locator('[data-reader-toggle]').click();
    assert.equal(await small.locator('body').evaluate(el => el.classList.contains('reader-mode')), true);

    assert.deepEqual(mobileErrors, [], 'No uncaught JavaScript errors on mobile');
    await mobile.close();
    const narrow = await browser.newContext({ viewport: { width: 320, height: 640 }, isMobile: true });
    const narrowPage = await narrow.newPage();
    await narrowPage.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px home');
    await narrowPage.goto(base + '/89ecf3804396453cbc4256966e24aa27.html', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px article');

    await narrow.close();
    console.log('Desktop 1440px, mobile 390px and narrow mobile 320px checks passed.');
  } finally {
    await browser?.close();
    server.kill('SIGTERM');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
