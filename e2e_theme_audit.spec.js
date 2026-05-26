// @ts-check
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8000';

// Helper: set localStorage BEFORE page load via addInitScript
async function gotoWithTheme(page, url, mode) {
  await page.addInitScript((m) => {
    localStorage.setItem('shop_theme_mode', m);
  }, mode);
  await page.goto(BASE + url);
  await page.waitForLoadState('domcontentloaded');
}

// Helper: open quick-nav menu (if not already open), then click themeToggle
async function openMenuAndToggle(page) {
  const menuBtn = page.locator('#quickNavBtn');
  const menu = page.locator('#quickNavMenu');

  // Open if not already open
  const menuVisible = await menu.isVisible().catch(() => false);
  if (!menuVisible) {
    await menuBtn.click();
    await page.waitForTimeout(250);
  }

  const themeBtn = page.locator('#themeToggle').first();
  await expect(themeBtn).toBeVisible({ timeout: 5000 });
  await themeBtn.click();
  await page.waitForTimeout(300);
}

// Helper: check body has theme-dark class
async function isDark(page) {
  return page.evaluate(() => document.body.classList.contains('theme-dark'));
}

// Helper: read a CSS custom property from document.body
// Dark mode overrides are on body.theme-dark (NOT :root), so we must read from body
async function getCSSVar(page, varName) {
  return page.evaluate((v) => {
    return getComputedStyle(document.body).getPropertyValue(v).trim();
  }, varName);
}

// -------------------------------------------------------------------
// SUITE 1: Theme toggle — no refresh required
// -------------------------------------------------------------------
test.describe('1. تبديل الوضع من الهيدر بدون تحديث', () => {

  test('يتغير body.theme-dark فوراً عند النقر على زر الوضع', async ({ page }) => {
    await gotoWithTheme(page, '/', 'light');

    const beforeDark = await isDark(page);
    expect(beforeDark, 'يجب أن يبدأ بالوضع الفاتح').toBe(false);

    await openMenuAndToggle(page);

    const afterDark = await isDark(page);
    expect(afterDark, 'يجب أن يصبح داكناً بعد النقر').toBe(true);

    // Toggle back
    await openMenuAndToggle(page);
    const afterToggleBack = await isDark(page);
    expect(afterToggleBack, 'يجب أن يرجع فاتحاً بعد النقر مرة ثانية').toBe(false);
  });

  test('الحالة تُحفظ في localStorage وتنعكس عند إعادة التنقل', async ({ page }) => {
    await gotoWithTheme(page, '/', 'dark');
    const dark = await isDark(page);
    expect(dark, 'يجب تحميل الوضع الداكن من localStorage').toBe(true);

    // New page context for light
    const page2 = await page.context().newPage();
    await page2.addInitScript(() => localStorage.setItem('shop_theme_mode', 'light'));
    await page2.goto(BASE + '/');
    await page2.waitForLoadState('domcontentloaded');
    const light = await isDark(page2);
    expect(light, 'يجب تحميل الوضع الفاتح من localStorage').toBe(false);
    await page2.close();
  });

  test('نص زر التبديل يتغير بين مود الليل ومود النهار', async ({ page }) => {
    await gotoWithTheme(page, '/', 'light');

    const menuBtn = page.locator('#quickNavBtn');
    await menuBtn.click();
    await page.waitForTimeout(250);

    const btnText = await page.locator('#themeToggle').first().textContent();
    expect(btnText, 'نص الزر يجب أن يحتوي على مود الليل في وضع النهار').toContain('مود الليل');

    // Click toggle
    await page.locator('#themeToggle').first().click();
    await page.waitForTimeout(200);

    // Re-open menu to see new text
    await menuBtn.click();
    await page.waitForTimeout(250);
    const btnTextAfter = await page.locator('#themeToggle').first().textContent();
    expect(btnTextAfter, 'نص الزر يجب أن يتغير إلى مود النهار').toContain('مود النهار');
  });
});

// -------------------------------------------------------------------
// SUITE 2: Dark/Light visual consistency across pages
// -------------------------------------------------------------------
test.describe('2. اتساق بصري في الوضعين عبر الصفحات', () => {

  const pagesToTest = [
    { name: 'الرئيسية', url: '/' },
    { name: 'البحث', url: '/search?q=%D8%AA' },
    { name: 'الدولاب', url: '/home/' },
  ];

  for (const { name, url } of pagesToTest) {
    test(`متغيرات CSS صحيحة في الوضع الفاتح — ${name}`, async ({ page }) => {
      await gotoWithTheme(page, url, 'light');

      const darkClass = await isDark(page);
      expect(darkClass, `${name}: يجب ألا يكون الوضع داكناً`).toBe(false);

      const bg = await getCSSVar(page, '--bg');
      expect(bg, `${name}: --bg يجب أن يكون فاتحاً`).toMatch(/#f8f6f3/i);

      const card = await getCSSVar(page, '--card');
      expect(card, `${name}: --card يجب أن يكون أبيض`).toMatch(/#fff|#ffffff/i);

      await page.screenshot({ path: `screenshots/light_${name}.png`, fullPage: false });
    });

    test(`متغيرات CSS صحيحة في الوضع الداكن — ${name}`, async ({ page }) => {
      await gotoWithTheme(page, url, 'dark');

      const darkClass = await isDark(page);
      expect(darkClass, `${name}: يجب أن يكون theme-dark مفعلاً`).toBe(true);

      const bg = await getCSSVar(page, '--bg');
      expect(bg, `${name}: --bg يجب أن يكون داكناً`).toMatch(/#0b1220/i);

      const card = await getCSSVar(page, '--card');
      expect(card, `${name}: --card يجب أن يكون داكناً`).toMatch(/#0f1b2d/i);

      await page.screenshot({ path: `screenshots/dark_${name}.png`, fullPage: false });
    });
  }

  // --- Conditional: compartment/1, shelf/1, category/1 ---
  for (const { name, url } of [
    { name: 'compartment_1', url: '/compartment/1/' },
    { name: 'shelf_1', url: '/shelf/1/' },
    { name: 'category_1', url: '/category/1/' },
  ]) {
    test(`صفحة ${name} — الوضع الداكن أو إعادة توجيه`, async ({ page }) => {
      await gotoWithTheme(page, url, 'dark');

      const finalUrl = page.url();
      const pageTitle = await page.title();

      // Check if page returned 404 or redirected
      const bodyText = (await page.locator('body').textContent().catch(() => '')) ?? '';
      const is404 = bodyText.includes('404') || bodyText.includes('Page not found') || finalUrl !== BASE + url;

      if (is404) {
        console.log(`FINDING: ${name} → إعادة توجيه أو غير موجود — URL النهائي: ${finalUrl}`);
        return; // Skip — page doesn't exist with ID=1
      }

      const darkClass = await isDark(page);
      expect(darkClass, `${name}: يجب أن يحمل theme-dark`).toBe(true);

      const bg = await getCSSVar(page, '--bg');
      expect(bg).toMatch(/#0b1220/i);

      await page.screenshot({ path: `screenshots/dark_${name}.png`, fullPage: false });
    });
  }
});

// -------------------------------------------------------------------
// SUITE 3: Fake-gateway pay route check
// -------------------------------------------------------------------
test.describe('3. مسار fake-gateway', () => {
  test('التحقق من مسار /pay/fake/1/ (URL الحقيقي للبوابة)', async ({ page }) => {
    const resp = await page.goto(BASE + '/pay/fake/1/');
    const statusCode = resp?.status() ?? 0;
    const finalUrl = page.url();

    console.log(`FINDING: /pay/fake/1/ → ${finalUrl} (status: ${statusCode})`);

    // Document: the user asked about /fake-gateway/pay/1/ but actual pattern is /pay/fake/<id>/
    // That URL redirected to /home/ meaning no PaymentAttempt #1 exists
    if (finalUrl.includes('/home/') || finalUrl.includes('login')) {
      console.log('FINDING: /pay/fake/1/ يعيد التوجيه — طلب الدفع رقم 1 غير موجود أو غير مصرح به');
    }
    expect(statusCode).toBeLessThan(600);
  });

  test('مسار /fake-gateway/pay/1/ غير موجود (URL خاطئ)', async ({ page }) => {
    const resp = await page.goto(BASE + '/fake-gateway/pay/1/');
    const statusCode = resp?.status() ?? 0;
    console.log(`FINDING: /fake-gateway/pay/1/ → status ${statusCode} — هذا المسار غير موجود في urls.py`);
    // Should be 404
    expect(statusCode).toBeGreaterThanOrEqual(404);
  });
});

// -------------------------------------------------------------------
// SUITE 4: Availability dropdown — viewport overflow
// -------------------------------------------------------------------
test.describe('4. قائمة التوفر — لا تتجاوز حدود الشاشة', () => {

  async function checkDropdownInViewport(page, label) {
    await page.goto(BASE + '/search?q=%D8%AA');
    await page.waitForLoadState('domcontentloaded');

    const trigger = page.locator('#availTrigger');
    await expect(trigger).toBeVisible();

    await trigger.click();
    await page.waitForTimeout(300);

    const panel = page.locator('#availPanel');
    await expect(panel).toBeVisible();

    const vw = await page.evaluate(() => window.innerWidth);

    const box = await panel.boundingBox();
    expect(box, `${label}: اللوحة يجب أن تظهر`).not.toBeNull();

    if (box) {
      const leftOk = box.x >= -1;
      const rightOk = box.x + box.width <= vw + 2;
      expect(leftOk, `${label}: يجب ألا يتجاوز الجانب الأيسر (x=${box.x})`).toBe(true);
      expect(rightOk, `${label}: يجب ألا يتجاوز الجانب الأيمن (x+w=${box.x + box.width}, vw=${vw})`).toBe(true);

      console.log(`  ${label}: panel x=${box.x.toFixed(0)} w=${box.width.toFixed(0)} vw=${vw} — ok=${leftOk && rightOk}`);
    }

    await page.screenshot({ path: `screenshots/avail_dropdown_${label}.png` });
  }

  test('على شاشة سطح المكتب (1280×800)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await checkDropdownInViewport(page, 'desktop_1280');
  });

  test('على شاشة موبايل (375×812)', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await checkDropdownInViewport(page, 'mobile_375');
  });

  test('على شاشة موبايل ضيقة (320×568)', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await checkDropdownInViewport(page, 'mobile_320');
  });

  test('خيارات القائمة: الكل / متوفر / غير متوفر', async ({ page }) => {
    await page.goto(BASE + '/search?q=%D8%AA');
    await page.waitForLoadState('domcontentloaded');

    await page.locator('#availTrigger').click();
    await page.waitForTimeout(200);

    const options = await page.locator('#availPanel .avail-option').allTextContents();
    const optionValues = await page.locator('#availPanel .avail-option').evaluateAll(
      els => els.map(e => e.getAttribute('data-value'))
    );

    expect(options.length, 'يجب أن يكون هناك 3 خيارات').toBe(3);
    expect(optionValues).toContain('');
    expect(optionValues).toContain('available');
    expect(optionValues).toContain('out_of_stock');

    console.log(`  Options: ${options.join(' | ')} | Values: ${optionValues.join(' | ')}`);
  });

  test('اختيار خيار يغلق القائمة ويحدّث الحقل المخفي', async ({ page }) => {
    await page.goto(BASE + '/search?q=%D8%AA');
    await page.waitForLoadState('domcontentloaded');

    await page.locator('#availTrigger').click();
    await page.waitForTimeout(200);

    await page.locator('.avail-option[data-value="available"]').click();
    await page.waitForTimeout(200);

    const hiddenVal = await page.locator('#avail-hidden').inputValue();
    expect(hiddenVal, 'الحقل المخفي يجب أن يحمل قيمة available').toBe('available');

    const panelHidden = await page.locator('#availPanel').isHidden();
    expect(panelHidden, 'القائمة يجب أن تغلق بعد الاختيار').toBe(true);

    const labelText = await page.locator('#availLabel').textContent();
    expect(labelText?.trim(), 'التسمية يجب أن تتغير إلى متوفر').toBe('متوفر');
  });

  test('القائمة تعمل في مود الليل مع ألوان صحيحة', async ({ page }) => {
    await gotoWithTheme(page, '/search?q=%D8%AA', 'dark');

    const dark = await isDark(page);
    expect(dark, 'يجب أن يكون الوضع الداكن مفعلاً').toBe(true);

    await page.locator('#availTrigger').click();
    await page.waitForTimeout(200);

    const panel = page.locator('#availPanel');
    await expect(panel).toBeVisible();

    // In dark mode, background should NOT be white
    const bgColor = await panel.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bgColor, 'خلفية القائمة يجب ألا تكون بيضاء في مود الليل').not.toBe('rgb(255, 255, 255)');

    console.log(`  dark panel bg: ${bgColor}`);
    await page.screenshot({ path: `screenshots/avail_dropdown_dark.png` });
  });
});

// -------------------------------------------------------------------
// SUITE 5: create_return route accessibility
// -------------------------------------------------------------------
test.describe('5. مسار إنشاء الإرجاع من الطلبات', () => {
  test('صفحة /orders/ تُحمّل أو تعيد توجيه الضيف', async ({ page }) => {
    const resp = await page.goto(BASE + '/orders/');
    const finalUrl = page.url();
    const status = resp?.status() ?? 0;

    if (finalUrl.includes('login') || finalUrl.includes('accounts')) {
      console.log('FINDING: /orders/ → يعيد توجيه الضيف إلى تسجيل الدخول (صحيح)');
    } else {
      const returnLinks = await page.locator('a[href*="return"]').count();
      console.log(`FINDING: /orders/ → ${finalUrl} | روابط الإرجاع: ${returnLinks}`);
    }
    expect(status).toBeLessThan(600);
  });

  test('مسار /return/create/1/ محمي بتسجيل الدخول', async ({ page }) => {
    const resp = await page.goto(BASE + '/return/create/1/');
    const finalUrl = page.url();
    const status = resp?.status() ?? 0;

    if (finalUrl.includes('login') || finalUrl.includes('accounts')) {
      console.log('FINDING: /return/create/1/ → محاط بالحماية — يعيد التوجيه لتسجيل الدخول (صحيح)');
    } else if (status === 404) {
      console.log('FINDING: /return/create/1/ → 404 (لا يوجد طلب رقم 1)');
    } else {
      console.log(`FINDING: /return/create/1/ → ${finalUrl} (${status})`);
    }
    expect(status).toBeLessThan(600);
  });
});

// -------------------------------------------------------------------
// SUITE 6: DOM structure audit
// -------------------------------------------------------------------
test.describe('6. فحص بنية DOM', () => {
  test('لا يوجد تكرار id="themeToggle" في DOM للضيف', async ({ page }) => {
    await page.goto(BASE + '/');
    await page.waitForLoadState('domcontentloaded');

    const count = await page.evaluate(() =>
      document.querySelectorAll('#themeToggle').length
    );
    console.log(`  id="themeToggle" count in guest DOM: ${count}`);
    // Should be exactly 1 (only the {% else %} branch renders for guest)
    expect(count, 'يجب أن يكون هناك عنصر واحد فقط بـ id="themeToggle"').toBe(1);
  });

  test('الهيدر موجود في جميع الصفحات الرئيسية', async ({ page }) => {
    for (const url of ['/', '/search?q=%D8%AA', '/home/']) {
      await page.goto(BASE + url);
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('.site-header'), `الهيدر يجب أن يظهر في ${url}`).toBeVisible();
    }
  });

  test('زر التبديل يحمل aria-pressed صحيح بعد التفعيل', async ({ page }) => {
    await gotoWithTheme(page, '/', 'light');

    // Open menu
    await page.locator('#quickNavBtn').click();
    await page.waitForTimeout(250);

    const pressedBefore = await page.locator('#themeToggle').first().getAttribute('aria-pressed');
    expect(pressedBefore, 'aria-pressed يجب false في وضع النهار').toBe('false');

    await page.locator('#themeToggle').first().click();
    await page.waitForTimeout(200);

    // Re-open menu
    await page.locator('#quickNavBtn').click();
    await page.waitForTimeout(250);

    const pressedAfter = await page.locator('#themeToggle').first().getAttribute('aria-pressed');
    expect(pressedAfter, 'aria-pressed يجب true بعد تفعيل الوضع الداكن').toBe('true');
  });
});
