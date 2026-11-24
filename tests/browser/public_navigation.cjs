/* Run against an isolated local LLT preview; no login submission or account writes. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const base = process.env.LLT_TEST_BASE_URL;
  assert.ok(base && ['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Use an isolated localhost preview');
  const out = process.env.LLT_TEST_ARTIFACT_DIR || '/tmp/llt-public-nav';
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {})});
  const reports = [];
  async function checkSignupContrast(page) {
    const signup = page.getByRole('link', {name:'Регистрация',exact:true});
    assert.equal(await signup.isVisible(),true);
    for (const hovered of [false,true]) {
      if (hovered) await signup.hover();
      await page.waitForTimeout(200); // Allow the existing colour transition to finish.
      const colours = await signup.evaluate(el=>({color:getComputedStyle(el).color, background:getComputedStyle(el).backgroundColor}));
      assert.equal(colours.color,'rgb(255, 255, 255)', 'Signup text must remain white over its coloured button');
      assert.notEqual(colours.color,colours.background);
    }
  }
  for (const javaScriptEnabled of [true, false]) {
    const context = await browser.newContext({viewport: {width:1440,height:1000}, javaScriptEnabled, reducedMotion:'reduce'});
    const page = await context.newPage();
    await page.goto(base);
    const menu = page.locator('.public-nav-toggle');
    const visibleLogin = page.getByRole('link', {name:'Вход',exact:true});
    assert.equal(await visibleLogin.count(),1, 'Desktop login is present without opening details');
    assert.equal(await visibleLogin.isVisible(),true);
    assert.equal(await menu.isVisible(),false);
    await checkSignupContrast(page);
    await page.screenshot({path:path.join(out,`desktop-js-${javaScriptEnabled}.png`)});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await menu.isVisible(),true);
    assert.equal(await visibleLogin.count(),0, 'Closed mobile menu does not leak duplicate desktop links');
    await menu.focus(); await page.keyboard.press('Enter');
    assert.equal(await visibleLogin.count(),1);
    await checkSignupContrast(page);
    await menu.focus();
    for (let i=0;i<4;i++) await page.keyboard.press('Tab');
    assert.equal(await visibleLogin.evaluate(el=>el===document.activeElement),true);
    await page.screenshot({path:path.join(out,`mobile-keyboard-js-${javaScriptEnabled}.png`)});
    await page.keyboard.press('Enter');
    await page.waitForURL('**/login');
    await page.goto(base);
    await menu.click();
    await page.setViewportSize({width:1440,height:1000});
    assert.equal(await visibleLogin.count(),1, 'Open mobile menu is hidden on desktop');
    assert.equal(await menu.isVisible(),false);
    await visibleLogin.focus();
    await page.keyboard.press('Enter');await page.waitForURL('**/login');
    await page.goto(base);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await visibleLogin.count(),0);
    await menu.focus(); await page.keyboard.press('Space');
    assert.equal(await visibleLogin.count(),1);
    await menu.press('Space');assert.equal(await visibleLogin.count(),0);
    await page.setViewportSize({width:1024,height:900});assert.equal(await visibleLogin.count(),1);
    await page.setViewportSize({width:1023,height:900});assert.equal(await visibleLogin.count(),0);
    reports.push({javaScriptEnabled, desktopLogin:true, mobileMenu:true, keyboardLogin:true, resizeRoundTrip:true, breakpoint1023_1024:true});
    await context.close();
  }
  await browser.close();fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(reports,null,2));
  console.log('PASS',JSON.stringify(reports));
})().catch(error=>{console.error(error);process.exit(1)});
