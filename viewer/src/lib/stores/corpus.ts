/**
 * Svelte stores for corpus management state.
 */
import { writable, get } from 'svelte/store';
import { fetchCorpora, createCorpusApi, deleteCorpusApi, type CorpusInfo } from '$lib/api/client';

/** List of all corpora. */
export const corpora = writable<CorpusInfo[]>([]);

/** Currently selected corpus. */
export const selectedCorpus = writable<CorpusInfo | null>(null);

/** Loading state for corpus operations. */
export const corpusLoading = writable<boolean>(false);

/** Error message from the last corpus operation (null = no error). */
export const corpusError = writable<string | null>(null);

/**
 * Load all corpora from the API.
 * Auto-selects the first corpus if none is currently selected.
 */
export async function loadCorpora(): Promise<void> {
	corpusLoading.set(true);
	const result = await fetchCorpora();
	if (!('error' in result)) {
		corpora.set(result);
		// Auto-select first if none selected
		const current = get(selectedCorpus);
		if (!current && result.length > 0) {
			selectedCorpus.set(result[0]);
		}
	}
	corpusLoading.set(false);
}

/**
 * Create a new corpus and select it.
 * Returns the created corpus, or null on failure (sets corpusError).
 */
export async function createCorpus(name: string): Promise<CorpusInfo | null> {
	corpusError.set(null);
	corpusLoading.set(true);
	const result = await createCorpusApi(name);
	if ('error' in result) {
		corpusError.set(result.error);
		corpusLoading.set(false);
		return null;
	}
	await loadCorpora();
	selectedCorpus.set(result);
	corpusLoading.set(false);
	return result;
}

/**
 * Delete a corpus. Clears selection if the deleted corpus was selected.
 */
export async function deleteCorpus(corpusId: string): Promise<boolean> {
	corpusError.set(null);
	const result = await deleteCorpusApi(corpusId);
	if (result && 'error' in result) {
		corpusError.set(result.error);
		return false;
	}
	const current = get(selectedCorpus);
	if (current?.id === corpusId) selectedCorpus.set(null);
	await loadCorpora();
	return true;
}

/**
 * Select a corpus.
 */
export function selectCorpus(corpus: CorpusInfo): void {
	selectedCorpus.set(corpus);
}

/**
 * Clear corpus error state.
 */
export function clearCorpusError(): void {
	corpusError.set(null);
}
