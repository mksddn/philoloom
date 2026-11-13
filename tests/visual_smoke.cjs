/** Desktop and mobile browser smoke checks; no screenshots required. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const http = require('node:http');
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8765';
const server = spawn('python3', ['-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', 'dist'], { stdio: 'ignore' });
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitForServer() {
  // Node's bundled undici occasionally aborts on a server startup race.
  // A simple HTTP readiness probe avoids that unrelated test-runner crash.
  for (let i = 0; i < 60; i++) {
    const ready = await new Promise(resolve => {
      const req = http.get(base, response => {
        response.resume();
        resolve(response.statusCode === 200);
      });
      req.on('error', () => resolve(false));
      req.setTimeout(1000, () => { req.destroy(); resolve(false); });
    });
    if (ready) return;
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
async function assertPeopleLayout(page, expectedColumns, label) {
  await page.waitForFunction(columns => {
    const collection = document.querySelector('.entity-card--people')?.parentElement;
    return collection?.classList.contains('masonry-ready') &&
      getComputedStyle(collection).gridTemplateColumns.trim().split(/\s+/).length === columns;
  }, expectedColumns);
  // The breakpoints may change the width before the next animation frame
  // recomputes masonry positions. Allow two frames for its ResizeObserver.
  await page.evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const outcome = await page.locator('.entity-card--people').first().evaluate(card => {
    const collection = card.parentElement;
    const css = getComputedStyle(collection);
    const cards = [...collection.querySelectorAll(':scope > .entity-card')];
    const columns = css.gridTemplateColumns.trim().split(/\s+/).length;
    const columnGap = parseFloat(css.columnGap) || 0;
    const rowGap = parseFloat(css.rowGap) || 0;
    const width = cards[0].getBoundingClientRect().width;
    const origin = collection.getBoundingClientRect();
    const bottoms = Array(columns).fill(0);
    const violations = [];
    for (const entry of cards) {
      const expectedTop = Math.min(...bottoms);
      const column = bottoms.indexOf(expectedTop);
      const bounds = entry.getBoundingClientRect();
      const actualTop = bounds.top - origin.top;
      const actualLeft = bounds.left - origin.left;
      const expectedLeft = column * (width + columnGap);
      if (Math.abs(actualTop - expectedTop) > 2 || Math.abs(actualLeft - expectedLeft) > 2) {
        violations.push({ name: entry.querySelector('.entity-card-title')?.textContent,
          actualTop, actualLeft, expectedTop, expectedLeft });
      }
      for (const link of entry.querySelectorAll('.entity-card-connections .relation')) {
        const rect = link.getBoundingClientRect();
        if (rect.right > bounds.right + 1 || rect.left < bounds.left - 1) {
          violations.push({ name: 'Clipped relation', text: link.textContent, right: rect.right,
            cardRight: bounds.right });
        }
      }
      bottoms[column] += bounds.height + rowGap;
    }
    return { columns, enhanced: collection.classList.contains('masonry-ready'), violations };
  });
  assert.equal(outcome.columns, expectedColumns, label + ': incorrect number of columns');
  assert.ok(outcome.enhanced && outcome.violations.length === 0,
    label + ': masonry / connection link overflow ' + JSON.stringify(outcome.violations.slice(0, 5)));
  await assertNoOverflow(page, label);
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
    // A short tab must keep the footer flush with the bottom of a tall screen.
    await home.setViewportSize({ width: 1440, height: 1800 });
    await home.evaluate(() => window.scrollTo(0, 0));
    const footerPosition = await home.evaluate(() => ({
      bottom: document.querySelector('footer').getBoundingClientRect().bottom,
      viewport: window.innerHeight,
      pageHeight: document.documentElement.scrollHeight
    }));
    assert.ok(Math.abs(footerPosition.bottom - footerPosition.viewport) <= 2,
      'Footer should rest at bottom of tall viewport: ' + JSON.stringify(footerPosition));
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
    assert.equal(await home.locator('.history-timeline-period').count(), 8);
    const extraHistoryCards = home.locator('.history-related .entity-collection > .entity-card');
    if (await extraHistoryCards.count() === 1) {
      const dimensions = await extraHistoryCards.first().evaluate(card => ({
        cardWidth: card.getBoundingClientRect().width,
        sectionWidth: card.parentElement.getBoundingClientRect().width
      }));
      assert.ok(Math.abs(dimensions.cardWidth - dimensions.sectionWidth) <= 2,
        'Single cross-era card must occupy the full width: ' + JSON.stringify(dimensions));
    }
    await home.locator('.section-nav a').nth(2).click();
    assert.ok(await home.locator('.quote-catalog').isVisible());
    await home.locator('.section-nav a').nth(3).click();
    assert.ok(await home.locator('.entity-card--people').first().isVisible());
    const peopleColumns = await home.locator('.entity-card--people').first().evaluate(card =>
      getComputedStyle(card.parentElement).gridTemplateColumns.trim().split(/\s+/).length);
    assert.equal(peopleColumns, 5, 'Desktop personalities must display five cards per row');
    // Verify real shortest-column masonry rather than a grid with empty row gaps:
    // every card must sit immediately beneath the preceding card in its column.
    const waterfall = await home.locator('.entity-card--people').first().evaluate(first => {
      const collection = first.parentElement;
      const css = getComputedStyle(collection);
      const cards = [...collection.querySelectorAll(':scope > .entity-card')];
      const columns = css.gridTemplateColumns.trim().split(/\s+/).length;
      const width = cards[0].getBoundingClientRect().width;
      const xGap = parseFloat(css.columnGap);
      const yGap = parseFloat(css.rowGap);
      const bottoms = Array(columns).fill(0);
      const origin = collection.getBoundingClientRect();
      const violations = [];
      for (const card of cards) {
        const nextTop = Math.min(...bottoms);
        const column = bottoms.indexOf(nextTop);
        const bounds = card.getBoundingClientRect();
        const actualTop = bounds.top - origin.top;
        const actualLeft = bounds.left - origin.left;
        const desiredLeft = column * (width + xGap);
        if (Math.abs(actualTop - nextTop) > 2 || Math.abs(actualLeft - desiredLeft) > 2) {
          violations.push({ name: card.querySelector('.entity-card-title')?.textContent,
            expected: { top: nextTop, left: desiredLeft },
            actual: { top: actualTop, left: actualLeft } });
        }
        bottoms[column] += bounds.height + yGap;
      }
      return { enhanced: collection.classList.contains('masonry-ready'), violations };
    });
    assert.ok(waterfall.enhanced && waterfall.violations.length === 0,
      'Philosopher cards must fill the shortest available column: ' + JSON.stringify(waterfall));
    const relationLineHeight = await home.locator('.entity-card--people .relation').first().evaluate(link =>
      ({ fontSize: parseFloat(getComputedStyle(link).fontSize),
         lineHeight: parseFloat(getComputedStyle(link).lineHeight) }));
    assert.ok(Math.abs(relationLineHeight.lineHeight / relationLineHeight.fontSize - 1.3) < 0.01,
      'Entity relation links should use 1.3 line-height: ' + JSON.stringify(relationLineHeight));
    // Semantic HTML order is not enough: the visible chronology must also run
    // from left to right, then down to the next row (never down CSS columns).
    const peopleVisualOrder = await home.locator('.entity-card--people').evaluateAll(cards =>
      cards.map(card => {
        const rect = card.getBoundingClientRect();
        return { name: card.querySelector('.entity-card-title')?.textContent, top: rect.top, left: rect.left };
      })
    );
    assert.ok(peopleVisualOrder.length > 3, 'Expected multiple philosopher rows');
    for (let i = 1; i < peopleVisualOrder.length; i++) {
      const previous = peopleVisualOrder[i - 1];
      const current = peopleVisualOrder[i];
      assert.ok(current.top > previous.top + 0.25 ||
        (Math.abs(current.top - previous.top) <= 0.25 && current.left > previous.left + 2),
        'Philosopher cards must follow chronological row-major visual order: ' +
        JSON.stringify({ previous, current }));
    }
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
    const tablet = await browser.newContext({ viewport: { width: 820, height: 1180 }, colorScheme: 'dark' });
    const tabletPage = await tablet.newPage();
    await tabletPage.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    await tabletPage.locator('.section-nav a').nth(3).click();
    await assertPeopleLayout(tabletPage, 3, '820px tablet');
    for (const [width, columns] of [[700, 2], [701, 3], [1000, 3], [1001, 5]]) {
      await tabletPage.setViewportSize({ width, height: 1180 });
      await assertPeopleLayout(tabletPage, columns, width + 'px breakpoint');
    }
    await tablet.close();
    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1, colorScheme: 'dark' });
    const small = await mobile.newPage();
    const mobileErrors = [];
    small.on('pageerror', error => mobileErrors.push(error.message));
    await small.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    assert.equal(await small.locator('html').getAttribute('data-theme'), 'dark');
    assert.equal(await small.locator('.hero-brand-watermark').evaluate(el => getComputedStyle(el).opacity), '0.1');
    await assertNoOverflow(small, '390px home');
    await small.locator('.section-nav a').nth(1).click();
    await assertNoOverflow(small, '390px history');
    await small.locator('.section-nav a').nth(3).click();
    await assertNoOverflow(small, '390px people');
    await assertPeopleLayout(small, 2, '390px people');
    await small.locator('.section-nav a').last().click();
    await assertNoOverflow(small, '390px resources');
    await small.locator('.section-nav a').first().click();
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
    await narrowPage.locator('.section-nav a').nth(3).click();
    await assertPeopleLayout(narrowPage, 2, '320px people');
    await narrowPage.goto(base + '/topics/germenevtika/', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow(narrowPage, '320px article');

    await narrow.close();
    console.log('Desktop 1440px, tablet breakpoints 700–1001px, ultrawide 3840px (both themes), mobile 390px and narrow mobile 320px checks passed.');
  } finally {
    await browser?.close();
    server.kill('SIGTERM');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
