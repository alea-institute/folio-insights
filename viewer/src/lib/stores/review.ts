/**
 * Svelte stores for review workflow state.
 */
import { writable, get } from 'svelte/store';
import {
	fetchUnits,
	reviewUnit as apiReviewUnit,
	fetchStats,
	type KnowledgeUnitResponse,
	type ReviewStats,
} from '$lib/api/client';

/** Knowledge units for the currently selected concept. */
export const units = writable<KnowledgeUnitResponse[]>([]);

/** Currently focused / selected unit in the detail pane. */
export const selectedUnit = writable<KnowledgeUnitResponse | null>(null);

/** Aggregate review statistics. */
export const reviewStats = writable<ReviewStats | null>(null);

/** Inline editor open flag. */
export const editorOpen = writable<boolean>(false);

/** Loading state. */
export const loading = writable<boolean>(false);

/** Status announcement for aria-live region. */
export const announcement = writable<string>('');

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Load knowledge units for a concept and confidence filter, updating stores.
 */
export async function loadUnits(
	corpus: string,
	conceptIri?: string,
	confidence?: string
): Promise<void> {
	loading.set(true);
	const result = await fetchUnits(corpus, conceptIri, confidence);
	if ('error' in result) {
		units.set([]);
	} else {
		units.set(result);
		// Auto-select first unit
		if (result.length > 0) {
			selectedUnit.set(result[0]);
		} else {
			selectedUnit.set(null);
		}
	}
	loading.set(false);
}

/**
 * Submit a review decision and update the local store optimistically.
 */
export async function submitReview(
	unitId: string,
	status: string,
	corpus: string = 'default',
	editedText?: string,
	note?: string
): Promise<void> {
	// Optimistic update
	units.update((list) =>
		list.map((u) =>
			u.id === unitId
				? { ...u, review_status: status, edited_text: editedText ?? u.edited_text }
				: u
		)
	);

	const result = await apiReviewUnit(unitId, status, corpus, editedText, note);
	if ('error' in result) {
		// Revert on failure -- refetch
		await loadUnits(corpus);
	} else {
		// Update with server response
		units.update((list) => list.map((u) => (u.id === unitId ? result : u)));
		selectedUnit.update((su) => (su?.id === unitId ? result : su));
	}

	// Announce for screen readers
	announcement.set(`Unit ${status}`);

	// Refresh stats
	await refreshStats(corpus);
}

/**
 * Refresh review statistics from the API.
 */
export async function refreshStats(corpus: string = 'default'): Promise<void> {
	const result = await fetchStats(corpus);
	if (!('error' in result)) {
		reviewStats.set(result);
	}
}

/**
 * Navigate to the next or previous unit in the list.
 */
export function navigateUnit(direction: 'next' | 'prev'): void {
	const list = get(units);
	const current = get(selectedUnit);
	if (!current || list.length === 0) return;

	const idx = list.findIndex((u) => u.id === current.id);
	if (idx === -1) return;

	const newIdx = direction === 'next' ? Math.min(idx + 1, list.length - 1) : Math.max(idx - 1, 0);
	selectedUnit.set(list[newIdx]);
}
