/** Verify browser-decoded portraits on the deployed production site. */
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const people = path.join(__dirname, '..', 'content', 'knowledge', 'Философия', 'Личности');
  const slugs = fs.readdirSync(people).filter(x => x.endsWith('.md')).map(x => x.slice(0, -3)).sort();
  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'chrome', args: ['--no-sandbox']});
  const ctx = await browser.newContext({viewport: {width: 1200, height: 900}});
  const results = [];
  let cursor = 0;
  async function inspect() {
    const page = await ctx.newPage();
    while (cursor < slugs.length) {
      const slug = slugs[cursor++];
      try {
        const response = await page.goto('https://mksddn.github.io/philoloom/people/' + slug + '/',
          {waitUntil: 'domcontentloaded', timeout: 25000});
        if (response?.status() !== 200) throw new Error('Page HTTP ' + (response?.status() ?? 'unavailable'));
        const portrait = page.locator('img.person-portrait-image').first();
        if (!await portrait.count()) throw new Error('Portrait IMG missing');
        await portrait.scrollIntoViewIfNeeded({timeout: 7000});
        const status = await portrait.evaluate(async img => {
          img.loading = 'eager';
          const state = await Promise.race([
            img.decode().then(() => 'decoded').catch(() => 'decode failed'),
            new Promise(resolve => setTimeout(() => resolve('timeout'), 13000))
          ]);
          return {src: img.currentSrc || img.src, naturalWidth: img.naturalWidth, state};
        });
        results.push({slug, ...status, error: status.naturalWidth ? null : 'Image not decoded'});
      } catch(error) {
        results.push({slug, error: String(error.message).split('\n')[0]});
      }
    }
    await page.close();
  }
  try {
    await Promise.all(Array.from({length: 5}, inspect));
    const failed = results.filter(r => r.error);
    const remote = results.filter(r => r.src?.startsWith('https://upload.wikimedia.org/'));
    console.log('LIVE PORTRAITS: ' + (results.length - failed.length) + '/' + results.length +
      ' decoded; remote Wikimedia: ' + remote.length);
    for (const r of failed) console.log('MISSING IMAGE: ' + JSON.stringify(r));
    for (const r of remote) console.log('REMOTE IMAGE: ' + JSON.stringify(r));
    console.log('LIVE PORTRAITS RESULT: ' + JSON.stringify({checked: results.length, failed: failed.length}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
