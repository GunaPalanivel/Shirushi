/* Real browser acceptance; Playwright is a development tool, not an app dependency. */
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const directory = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const results = [];
  try {
    for (const viewport of [{width: 1440, height: 1000}, {width: 390, height: 844}, {width: 320, height: 720}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(pathToFileURL(path.join(directory, 'signalpost/index.html')).href);
      const rows = page.locator('[data-company]');
      assert.equal(await rows.count(), 100);
      await page.getByLabel('Search company number, name or activity').fill('Fixture 0 AS');
      assert.equal(await page.locator('[data-company]:visible').count(), 1);
      await page.getByLabel('Search company number, name or activity').fill('123450001');
      assert.equal(await page.locator('[data-company]:visible').count(), 1);
      await page.getByLabel('Search company number, name or activity').fill('');
      await page.getByLabel('Compare 123450000', {exact: true}).check();
      await page.getByLabel('Compare 123450001', {exact: true}).check();
      await page.getByRole('button', {name: 'Compare selected companies'}).click();
      assert.equal(await page.locator('#comparison section').count(), 2);
      const comparison = await page.locator('#comparison').innerText();
      assert.ok(comparison.includes('Registered employees'));
      assert.ok(comparison.includes('Unknown'));
      assert.ok(comparison.includes('0'));
      const firstLink = page.locator('#comparison section').first().getByRole('link', {name: '0', exact: true});
      await firstLink.click();
      const target = new URL(page.url()).hash.slice(1);
      assert.ok(target.startsWith('evidence-'));
      assert.equal(await page.locator('#' + target).count(), 1);
      await page.locator('#' + target + ' summary').click();
      assert.ok((await page.locator('#' + target).innerText()).includes('SHA-256'));
      assert.ok((await page.locator('#' + target).innerText()).includes('Retrieved:'));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(errors.length, 0);
      results.push({viewport, search: 'PASS', comparison: 'PASS', zero_and_unknown: 'PASS',
                    evidence_navigation: 'PASS', overflow: false, script_errors: errors});
      await page.screenshot({path: path.join(path.dirname(output), 'profile-' + viewport.width + '.png'), fullPage: true});
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(output, JSON.stringify({status: 'PASS', results, scope: '100 synthetic profiles in Chromium'}, null, 2));
  process.stdout.write(JSON.stringify({status: 'PASS', viewports: results.length}) + '\n');
}
main().catch(e => {process.stderr.write(e.stack + '\n'); process.exitCode = 1;});
