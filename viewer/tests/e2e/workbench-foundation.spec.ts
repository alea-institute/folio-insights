import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const source = 'A party must give notice. 😀 Notice may be delayed. <img src=x onerror="window.fixtureExecuted=true">';

function audit(page: Page) {
	// axe's broad peer range can resolve a newer playwright-core than the pinned runner.
	// Its runtime bridge uses the shared Page API, not the newer optional methods.
	return new AxeBuilder({ page: page as unknown as ConstructorParameters<typeof AxeBuilder>[0]['page'] })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']);
}

test.beforeEach(async ({ page }) => {
	// The entire journey runs without a backend, ontology download or external font.
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		if (url.origin !== 'http://127.0.0.1:4173') return route.abort();
		if (url.pathname.startsWith('/api/')) {
			if (url.pathname.endsWith('/corpora')) {
				return route.fulfill({ json: [{ id: 'synthetic', name: 'Synthetic notice rules' }] });
			}
			if (url.pathname.endsWith('/review/stats')) {
				return route.fulfill({ json: { total: 3, approved: 1, by_confidence: { high: 1, medium: 1, low: 1 } } });
			}
			return route.fulfill({ status: 404, json: { error: 'Not a fixture endpoint' } });
		}
		return route.continue();
	});
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Review the source' })).toBeVisible();
});

test('source, card and chips expose branch, verdict, icons and keyboard actions', async ({ page }) => {
	const card = page.getByRole('article', { name: 'A party must give notice' });
	await expect(card).toContainText('Uncertain');
	await expect(card).toContainText('Review whether the exception applies.');
	await expect(card).toContainText('Deontic Specification');
	await expect(card).toContainText('Legal Process');
	await expect(card).toContainText('Correct');
	await expect(card).toContainText('Wrong');
	for (const icon of ['✓', '?', '×']) await expect(card).toContainText(icon);
	const chip = card.getByRole('button', { name: /Obligation/ });
	await chip.focus();
	await expect(chip).toBeFocused();
	expect(await chip.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe('solid');
	await page.keyboard.press('Space');
	await expect(chip).toHaveAttribute('aria-pressed', 'true');
	await page.keyboard.press('Tab');
	await expect(page.getByRole('button', { name: 'Confirm proposition' })).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(page.getByRole('status')).toHaveText('Proposition confirmed in fixture');
});

test('shared shell fits the viewport and passes WCAG 2.1 AA', async ({ page }, testInfo) => {
	await expect(page.getByRole('combobox', { name: 'Corpus selector' })).toHaveValue('synthetic');
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	for (const selector of ['.header', '.main-content', '.workbench-page']) {
		expect(await page.locator(selector).evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
	}
	const results = await audit(page).analyze();
	expect(results.violations).toEqual([]);
	await page.screenshot({ path: testInfo.outputPath('foundation.png'), fullPage: true });
	await page.getByRole('button', { name: 'Settings', exact: true }).click();
	await page.getByRole('dialog', { name: 'Settings' }).evaluate(async (el) => {
		await Promise.all(el.getAnimations().map((animation) => animation.finished));
	});
	expect((await audit(page).analyze()).violations).toEqual([]);
});

test('intervals preserve inert text, overlap and canonical Unicode offsets', async ({ page }) => {
	const annotated = page.locator('.annotated-text');
	expect(await annotated.textContent()).toBe(source);
	await expect(annotated.locator('img, script')).toHaveCount(0);
	await expect(annotated.locator('[data-annotation-ids="duty notice"]')).toHaveText('notice');
	await expect(annotated.locator('[data-annotation-ids="notice permission"]')).toHaveText('Notice ');
	await expect(annotated.locator('[data-annotation-ids="permission"]')).toHaveText('may be delayed. ');
	await expect(annotated.locator('[data-annotation-ids*="invalid"]')).toHaveCount(0);
	expect(await page.evaluate(() => 'fixtureExecuted' in window)).toBe(false);
});

test('reduced motion disables transitions and keeps source and actions visible', async ({ page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await expect(page.locator('.annotated-text')).toHaveText(source);
	await expect(page.getByRole('button', { name: 'Confirm proposition' })).toBeVisible();
	await page.getByRole('button', { name: 'Settings', exact: true }).click();
	await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible();
	expect(await page.locator('.nav-tab').first().evaluate((el) => getComputedStyle(el).transitionDuration)).toBe('0s');
	expect(await page.getByRole('dialog', { name: 'Settings' }).evaluate((el) => getComputedStyle(el).animationDuration)).toBe('0s');
});
