// Drive the local viewer to a flood station and screenshot it.
// Usage: node .claude/skills/run-viewer/shot.cjs [station_id] [out_prefix]
const { chromium } = require('playwright');
const sid = process.argv[2] || '12004';
const out = process.argv[3] || `viewer-${sid}`;
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const errs = [];
  p.on('console', (m) => m.type() === 'error' && errs.push(m.text()));
  await p.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  const t = p.getByTestId('layer-toggle-flood-stations');
  if (!(await t.isChecked())) await t.check();
  await p.getByTestId(`feature-${sid}`).click();
  await p.getByTestId('return-period-curve').waitFor({ timeout: 20000 });
  await p.waitForTimeout(1000);
  await p.screenshot({ path: `${out}.png` });
  await p.getByTestId('top-floods').scrollIntoViewIfNeeded();
  await p.waitForTimeout(500);
  await p.screenshot({ path: `${out}-floods.png` });
  console.log(`${out}.png ${out}-floods.png; console errors: ${errs.length}`, errs.slice(0, 3));
  await b.close();
})();
