/** One-time import transport: Chromium fetches files using the same browser path as production. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const peopleDir = path.join(root, 'content/knowledge/Философия/Личности');
  const targetDir = path.join(root, 'content/previews/portraits');
  fs.mkdirSync(targetDir, {recursive: true});
  const slugs = [
    'fridrih-vilgelm-iozef-shelling','gerbert-markuze','iogann-gotlib-fihte',
    'ivan-kireevskii','karl-yaspers','maks-sheler','mishel-fuko',
    'pavel-florenskii','petr-chaadaev','seren-obe-kerkegor',
    'sergei-bulgakov','slavoi-zhizhek'
  ];
  const browser = await chromium.launch({channel: 'chrome', headless: true, args: ['--no-sandbox']});
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36',
    extraHTTPHeaders: {'Referer': 'https://mksddn.github.io/philoloom/'}
  });
  try {
    for (const slug of slugs) {
      if (fs.existsSync(path.join(targetDir, slug + '.jpg'))) continue;
      const markdown = fs.readFileSync(path.join(peopleDir, slug + '.md'), 'utf8');
      const imageURL = markdown.match(/!\[[^\]]*\]\((https?:\/\/[^)]+)\)/)?.[1];
      if (!imageURL?.startsWith('https://upload.wikimedia.org/wikipedia/commons/'))
        throw Error('Invalid Commons portrait for ' + slug + ': ' + imageURL);
      let bytes = null;
      for (let attempt = 0; attempt < 3 && !bytes; attempt++) {
        const page = await context.newPage();
        try {
          const response = await page.goto(imageURL, {waitUntil: 'load', timeout: 30000});
          if (response?.status() !== 200)
            throw Error('HTTP ' + (response?.status() || 'unknown'));
          if (!response.headers()['content-type']?.startsWith('image/'))
            throw Error('Unexpected content type: ' + response.headers()['content-type']);
          bytes = await response.body();
          if (bytes.length > 15000000) throw Error('Image exceeds size limit');
        } catch(error) {
          if (attempt === 2) throw Error(slug + ': ' + error.message);
          await page.waitForTimeout(1500 * (attempt + 1));
        } finally { await page.close(); }
      }
      fs.writeFileSync(path.join(targetDir, slug + '.download'), bytes);
      console.log('Browser downloaded ' + slug + ': ' + bytes.length + ' bytes');
      await new Promise(resolve => setTimeout(resolve, 900));
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
