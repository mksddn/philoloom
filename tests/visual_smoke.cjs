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
async function assertThemeArtwork(page, theme) {
  const result = await page.evaluate(async (expected) => {
    const art = document.querySelector('.hero-artwork');
    const background = getComputedStyle(art).backgroundImage;
    const imageUrl = background.match(/url\(["']?(.*?)["']?\)/)?.[1];
    if (!imageUrl) return { background, loaded: false };
    const image = new Image();
    image.src = imageUrl;
    await image.decode();
    return {
      background, loaded: image.naturalWidth === 1440 && image.naturalHeight === 810,
      heroBackground: getComputedStyle(document.querySelector('.hero-cover')).backgroundColor,
      headingColor: getComputedStyle(document.querySelector('.hero-cover h1')).color,
      quoteColor: getComputedStyle(document.querySelector('.hero-cover blockquote p')).color,
    };
  }, theme);
  assert.ok(result.background.includes('descartes-hero-' + theme + '.webp'),
    'Expected theme-specific Hero artwork: ' + JSON.stringify(result));
  assert.ok(result.loaded, 'Local theme-specific image must be available and decoded');
  return result;
}
(async () => {
  let browser;
  try {
    await waitForServer();
    // CI reuses the Google Chrome installed on its GitHub-hosted runner.
    // Without the env override, local development retains Playwright Chromium.
    const channel = process.env.PLAYWRIGHT_BROWSER_CHANNEL;
    browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
    const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
    const home = await desktop.newPage();
    const errors = [];
    home.on('pageerror', error => errors.push(error.message));
    await home.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    assert.equal((await home.locator('.hero-cover h1').textContent()).replace(/\s+/g, ' ').trim(), 'philoloom Атлас философской мысли');
    assert.equal(await home.locator('.hero-brand-watermark').count(), 1);
    assert.equal(await home.locator('.hero-brand-mark').count(), 0);
    // Both visual layers share an SVG: a sharp left half smoothly transitions
    // to the blurred right half without touching the Descartes portrait.
    const watermarkAsset = await home.locator('.hero-brand-watermark').evaluate(async element => {
      const style = getComputedStyle(element);
      const crisp = getComputedStyle(element, '::before');
      const blurred = getComputedStyle(element, '::after');
      const match = crisp.backgroundImage.match(/url\(["']?(.*?)["']?\)/);
      if (!match) return { ok: false };
      const response = await fetch(match[1]);
      return {
        ok: response.ok, type: response.headers.get('content-type'),
        opacity: style.opacity,
        blurred: blurred.filter.includes('blur(8px)'),
        transitionStartsLate: crisp.maskImage.includes('65%') && blurred.maskImage.includes('65%'),
        crispMask: crisp.maskImage !== 'none' || crisp.webkitMaskImage !== 'none',
        blurredMask: blurred.maskImage !== 'none' || blurred.webkitMaskImage !== 'none',
        sharedImage: crisp.backgroundImage === blurred.backgroundImage,
      };
    });
    assert.ok(watermarkAsset.ok && watermarkAsset.type?.includes('svg'), 'Vector tree background must load');
    assert.equal(watermarkAsset.opacity, '0.1', 'Hero logo opacity must be 0.1');
    assert.ok(watermarkAsset.blurred && watermarkAsset.transitionStartsLate && watermarkAsset.crispMask && watermarkAsset.blurredMask && watermarkAsset.sharedImage,
      'Sharp-to-blurred tree blend must use the same SVG on both layers');
    const visualBrand = await home.locator('.hero-cover').evaluate(async hero => {
      const tree = hero.querySelector('.hero-brand-watermark');
      const word = hero.querySelector('.hero-wordmark');
      const treeBounds = tree.getBoundingClientRect();
      const heroBounds = hero.getBoundingClientRect();
      const wordStyle = getComputedStyle(word);
      const mask = wordStyle.maskImage !== 'none' ? wordStyle.maskImage : wordStyle.webkitMaskImage;
      const response = mask?.includes('philoloom-wordmark.svg')
        ? await fetch(new URL('ui/philoloom-wordmark.svg', location.href))
        : null;
      return {
        treeWidth: treeBounds.width,
        heroHeight: heroBounds.height,
        wordWidth: word.getBoundingClientRect().width,
        maskLoaded: !!response?.ok,
        maskType: response?.headers.get('content-type'),
      };
    });
    assert.ok(visualBrand.treeWidth > visualBrand.heroHeight * 1.6,
      'Tree must be oversize for deliberate crop: ' + JSON.stringify(visualBrand));
    assert.ok(visualBrand.wordWidth >= 180 && visualBrand.maskLoaded && visualBrand.maskType?.includes('svg'),
      'Approved vector wordmark must load visibly: ' + JSON.stringify(visualBrand));
    assert.equal(await home.locator('#theme-toggle').count(), 0);
    assert.equal(await home.locator('.catalog-toolbar #search-open').count(), 1);
    assert.equal(await home.locator('.section-nav a').count(), 5);
    assert.equal(await home.locator('.reference-section').count(), 5);
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
    assert.equal(await home.locator('#more .resource-tiles .resource-tile').count(), 3);
    assert.ok(await home.locator('.resource-tiles').evaluate(el =>
      el.closest('#more') && el.compareDocumentPosition(document.querySelector('.section-nav')) & Node.DOCUMENT_POSITION_PRECEDING
    ));
    assert.equal(await home.locator('.museum-head').count(), 0);
    assert.equal(await home.locator('.section-nav').count(), 1);
    assert.equal(await home.locator('.museum-shortcuts, .editorial-spotlight, .editorial-shelf, .hero-explore').count(), 0);
    assert.equal(await home.locator('.museum-frame, .museum-top-nav').count(), 0);
    assert.ok(await home.locator('html').evaluate(element => element.classList.contains('tabs-ready')));
    assert.ok(await home.locator('.reference-section:not([hidden]) .entity-card').count() > 20);
    assert.ok(await home.locator('.reference-section:not([hidden]) .entity-card-connections .relation').count() > 0);

    const darkAppearance = await assertThemeArtwork(home, 'dark');
    assert.equal(await home.locator('.hero-artwork').getAttribute('aria-label'),
      'Художественный образ Рене Декарта');
    const heroDimensions = await home.locator('.hero-cover').evaluate(element => ({
      height: element.getBoundingClientRect().height,
      left: element.getBoundingClientRect().left,
      width: element.getBoundingClientRect().width,
      viewport: document.documentElement.clientWidth,
    }));
    assert.ok(Math.abs(heroDimensions.left) <= 1 && Math.abs(heroDimensions.width - heroDimensions.viewport) <= 1,
      'Hero must span the entire viewport: ' + JSON.stringify(heroDimensions));
    assert.ok(heroDimensions.height < 580, 'Desktop Hero must be compact: ' + heroDimensions.height);
    await assertNoOverflow(home, 'desktop home');

    await home.emulateMedia({ colorScheme: 'light' });
    await home.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    assert.equal(await home.locator('html').getAttribute('data-theme'), 'light');
    assert.equal(await home.locator('.hero-brand-watermark').evaluate(el => getComputedStyle(el).opacity), '0.1');
    const lightAppearance = await assertThemeArtwork(home, 'light');
    for (const token of ['heroBackground', 'headingColor', 'quoteColor']) {
      assert.notEqual(darkAppearance[token], lightAppearance[token],
        token + ' must change between dark and light theme');
    }

    await home.reload({ waitUntil: 'domcontentloaded' });
    assert.equal(await home.locator('html').getAttribute('data-theme'), 'light');
    assert.equal(await home.locator('#theme-toggle').count(), 0);
    await home.locator('#search-open').click();
    assert.ok(await home.locator('#search-dialog').evaluate(element => element.open));
    await home.locator('#query').fill('онтология');
    await home.waitForFunction(() => document.querySelector('#search-status')?.textContent.startsWith('Найдено страниц'));
    assert.ok(await home.locator('#results a').count() > 0);
    await home.keyboard.press('Escape');
    await home.waitForFunction(() => !document.querySelector('#search-dialog').open);
    await home.locator('.section-nav a').last().click();
    assert.ok(await home.locator('#more').isVisible());
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
    assert.equal(await home.locator('.view-controls').count(), 0);
    await home.locator('.section-nav a').nth(1).click();
    assert.ok(await home.locator('.history-timeline').isVisible());
    await home.locator('.section-nav a').nth(2).click();
    assert.ok(await home.locator('.quote-catalog').isVisible());
    await home.locator('.section-nav a').nth(3).click();
    assert.ok(await home.locator('.entity-card--people').first().isVisible());
    await home.locator('.section-nav a').first().click();
    await home.locator('.reference-section:not([hidden]) .entity-card-main').first().click();
    await home.locator('#panel-content .entity-header h1').waitFor();
    assert.ok(await home.locator('#panel-content article').isVisible());
    assert.equal(await home.locator('#panel-content .entity-kicker').count(), 1);
    assert.equal(await home.locator('#panel-content #search-open').count(), 0);
    assert.ok(await home.locator('#page-panel').evaluate(element => element.open));
    await home.locator('#panel-close').click();
    assert.deepEqual(errors, [], 'No uncaught JavaScript errors on desktop');
    await desktop.close();
    // A 4K desktop must not stretch the original 1440px artwork to 3840px.
    // Verify the capped, blended composition for both approved themes.
    const ultra = await browser.newContext({ viewport: { width: 3840, height: 2160 }, colorScheme: 'dark' });
    const ultraPage = await ultra.newPage();
    await ultraPage.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    for (const theme of ['dark', 'light']) {
      if (theme === 'light') {
        await ultraPage.emulateMedia({ colorScheme: 'light' });
        await ultraPage.waitForFunction(() => document.documentElement.dataset.theme === 'light');
      }
      const art = await ultraPage.locator('.hero-artwork').evaluate(element => {
        const css = getComputedStyle(element);
        return { backgroundImage: css.backgroundImage, backgroundSize: css.backgroundSize,
          backgroundPosition: css.backgroundPosition };
      });
      assert.ok(art.backgroundImage.includes('descartes-hero-' + theme + '.webp'),
        '4K background must retain approved artwork: ' + JSON.stringify(art));
      assert.ok(art.backgroundImage.includes('linear-gradient'),
        '4K portrait must blend into the hero surface: ' + JSON.stringify(art));
      assert.ok(art.backgroundSize.includes('1900px'),
        '4K source must not be stretched to viewport width: ' + JSON.stringify(art));
      assert.ok(/right|100%/.test(art.backgroundPosition),
        '4K portrait must remain right-aligned: ' + JSON.stringify(art));
    }
    await ultra.close();
    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1, colorScheme: 'dark' });
    const small = await mobile.newPage();
    const mobileErrors = [];
    small.on('pageerror', error => mobileErrors.push(error.message));
    await small.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'dark');
    assert.equal(await small.locator('.hero-brand-watermark').evaluate(el => getComputedStyle(el).opacity), '0.1');
    await assertNoOverflow(small, '390px home');
    assert.ok(await small.locator('.hero-cover').evaluate(el => el.getBoundingClientRect().height <= 620));
    assert.ok(await small.locator('.catalog-toolbar #search-open').isVisible());
    assert.equal(await small.locator('.section-nav').count(), 1);
    assert.equal(await small.locator('.resource-tiles .resource-tile').count(), 3);
    assert.ok(await small.locator('.hero-cover-content .featured-quote').isVisible());
    assert.equal(await small.locator('.home-source-strip .featured-quote').count(), 0);
    assert.ok(await small.locator('.hero-cover').evaluate(element =>
      Math.abs(element.getBoundingClientRect().width - document.documentElement.clientWidth) <= 1));

    await assertThemeArtwork(small, 'dark');
    await small.emulateMedia({ colorScheme: 'light' });
    await small.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'light');
    assert.equal(await small.locator('.hero-brand-watermark').evaluate(el => getComputedStyle(el).opacity), '0.1');
    await assertThemeArtwork(small, 'light');
    assert.ok(await small.locator('.hero-cover-content .featured-quote').evaluate(el =>
      el.getBoundingClientRect().bottom <= document.querySelector('.hero-cover').getBoundingClientRect().bottom),
      'Quotation must remain inside 390px Hero');

    await small.goto(base + '/people/rene-dekart/', { waitUntil: 'domcontentloaded' });
    assert.ok(await small.locator('.person-overview').isVisible());
    assert.ok(await small.locator('.person-context .relation').count() > 0);
    const portraitSrc = await small.locator('.person-portrait-image').getAttribute('src');
    assert.ok(portraitSrc?.startsWith('media/'), 'Portrait must be served from local optimized assets');
    await assertNoOverflow(small, '390px philosopher');
    await small.goto(base + '/index.html#quote-47d742c8761f4a0c86a27b43497759b0', { waitUntil: 'domcontentloaded' });
    await small.locator('#quote-47d742c8761f4a0c86a27b43497759b0').waitFor({state: 'visible'});
    assert.ok(await small.locator('.quote-catalog').isVisible(), 'Direct quote links must reveal the quotations tab');
    await assertNoOverflow(small, '390px inline quotation');
    await small.goto(base + '/topics/germenevtika/', { waitUntil: 'domcontentloaded' });
    assert.ok(await small.locator('article').isVisible());
    assert.ok(await small.locator('.page-breadcrumbs').isVisible());
    await assertNoOverflow(small, '390px article');
    assert.equal(await small.locator('[data-reader-toggle]').count(), 0);
    assert.equal(await small.locator('.detail-navigation #search-open').count(), 1);

    assert.deepEqual(mobileErrors, [], 'No uncaught JavaScript errors on mobile');
    await mobile.close();
    const narrow = await browser.newContext({ viewport: { width: 320, height: 640 }, isMobile: true, colorScheme: 'dark' });
    const narrowPage = await narrow.newPage();
    await narrowPage.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px home');
    assert.ok(await narrowPage.locator('.hero-cover').evaluate(el => el.getBoundingClientRect().height <= 650));
    assert.ok(await narrowPage.locator('.catalog-toolbar #search-open').isVisible());
    await assertThemeArtwork(narrowPage, 'dark');
    assert.ok(await narrowPage.locator('.hero-cover-content .featured-quote').evaluate(el =>
      el.getBoundingClientRect().bottom <= document.querySelector('.hero-cover').getBoundingClientRect().bottom),
      'Quotation must remain inside 320px Hero');
    await narrowPage.goto(base + '/topics/germenevtika/', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px article');

    await narrow.close();
    console.log('Desktop 1440px, ultrawide 3840px (both themes), mobile 390px and narrow mobile 320px checks passed.');
  } finally {
    await browser?.close();
    server.kill('SIGTERM');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
