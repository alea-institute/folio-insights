import { get, writable } from 'svelte/store';

export type JobKind = 'processing' | 'discovery';
export type JobStatus = 'idle' | 'processing' | 'complete' | 'error' | 'needs_credentials' | 'budget_exhausted';

// Session secrets stay in JS memory; reloads and tab closure discard them.
export const llmKey = writable<string>('');
export const controlTokens = writable<Record<string, Partial<Record<JobKind, string>>>>({});

export function setLlmKey(key: string): void {
	llmKey.set(key.trim());
}

export function clearLlmKey(): void {
	llmKey.set('');
}

export function llmKeyHeaders(): Record<string, string> {
	const key = get(llmKey);
	return key ? { 'X-LLM-API-Key': key } : {};
}

export function setControlToken(corpusId: string, kind: JobKind, token: string): void {
	controlTokens.update((tokens) => ({
		...tokens,
		[corpusId]: { ...tokens[corpusId], [kind]: token },
	}));
}

export function getControlToken(corpusId: string, kind: JobKind): string | undefined {
	return get(controlTokens)[corpusId]?.[kind];
}
