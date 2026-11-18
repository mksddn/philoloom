/** Audit actual published share metadata and JPEG download in headless Chrome.
 * Invocation: node tests/live_social_meta.cjs
 * Set STRICT_LIVE_OG=1 to fail on defects (use after deployment).
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = 'https://mksddn.github.io/philoloom/';

function allPages(root, prefix = '') {
  const result = [];
  for (const entry of fs.readdirSync(root, {withFileTypes: true})) {
    if (!entry.isDirectory() || ['media', 'og', 'ui', 'previews'].includes(entry.name)) continue;
    const dir = path.join(root, entry.name);
    if (fs.existsSync(path.join(dir, 'index.html'))) result.push(prefix + entry.name + '/');
    result.push(...allPages(dir, prefix + entry.name + '/'));
  }
  return result;
}

(async () => {
  const paths = ['', ...allPages(path.join(__dirname, '..', 'dist'))];
  const browser = await chromium.launch({
    headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'chrome',
    args: ['--no-sandbox']
  });
  const context = await browser.newContext();
  let index = 0;
  const results = [];
  async function worker() {
    const page = await context.newPage();
    while (index < paths.length) {
      const slug = paths[index++];
      const pageUrl = base + slug;
      try {
        const response = await page.goto(pageUrl, {waitUntil: 'domcontentloaded', timeout: 25000});
        if (!response || response.status() !== 200) throw new Error('Page HTTP ' + response?.status());
        const meta = await page.evaluate(() => {
          const get = key => document.querySelector('meta[property="' + key + '"]')?.content || '';
          const name = key => document.querySelector('meta[name="' + key + '"]')?.content || '';
          return {image: get('og:image'), secure: get('og:image:secure_url'),
            type: get('og:image:type'), width: get('og:image:width'), height: get('og:image:height'),
            alt: get('og:image:alt'), canonical: get('og:url'),
            twitter: name('twitter:image'), twitterAlt: name('twitter:image:alt'),
            card: name('twitter:card')};
        });
        if (!meta.image.startsWith(base + 'og/') || !meta.image.endsWith('.jpg'))
          throw new Error('Non-local or missing OG JPEG: ' + meta.image);
        if (meta.canonical !== pageUrl || meta.secure !== meta.image || meta.twitter !== meta.image ||
            meta.type !== 'image/jpeg' || meta.width !== '1200' || meta.height !== '630' ||
            meta.card !== 'summary_large_image' || !meta.alt || meta.twitterAlt !== meta.alt)
          throw new Error('Invalid OG/Twitter metadata: ' + JSON.stringify(meta));
        const imageResponse = await page.request.get(meta.image, {timeout: 20000});
        if (!imageResponse.ok() || !imageResponse.headers()['content-type']?.startsWith('image/jpeg'))
          throw new Error('Image response invalid: HTTP ' + imageResponse.status());
        const size = await page.evaluate(async src => {
          const image = new Image();
          image.src = src;
          await image.decode();
          return {width: image.naturalWidth, height: image.naturalHeight};
        }, meta.image);
        if (size.width !== 1200 || size.height !== 630)
          throw new Error('Image dimensions invalid: ' + JSON.stringify(size));
        results.push({slug, ok: true});
      } catch (error) { results.push({slug, error: String(error.message).split('\n')[0]}); }
    }
    await page.close();
  }
  try {
    await Promise.all(Array.from({length: 6}, worker));
    const failures = results.filter(r => r.error);
    console.log('LIVE OG AUDIT: ' + (results.length - failures.length) + '/' + results.length +
                ' valid, ' + failures.length + ' errors');
    for (const failure of failures) console.log('LIVE OG ISSUE: ' + JSON.stringify(failure));
    if (process.env.STRICT_LIVE_OG === '1' && failures.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
