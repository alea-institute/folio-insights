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
 */
export async function createCorpus(name: string): Promise<CorpusInfo | null> {
	const result = await createCorpusApi(name);
	if ('error' in result) return null;
	await loadCorpora();
	selectedCorpus.set(result);
	return result;
}

/**
 * Delete a corpus. Clears selection if the deleted corpus was selected.
 */
export async function deleteCorpus(corpusId: string): Promise<boolean> {
	const result = await deleteCorpusApi(corpusId);
	if (result && 'error' in result) return false;
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
