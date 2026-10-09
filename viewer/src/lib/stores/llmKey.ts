/**
 * Per-session LLM settings, job control tokens and the operator token -- held in tab memory ONLY.
 *
 * Decision (folio-insights-2026-10-05-1018-p10-p11-product-calls, q2-viewer-key-entry):
 * "Per-session key field, memory only." These are plain module-level Svelte stores. Nothing
 * here is ever written to localStorage, sessionStorage, IndexedDB, cookies or disk, so closing
 * or reloading the tab clears the key and every control token. `forgetKey()` clears the key
 * on demand. A "remember key" option would be a separate, explicit opt-in later.
 */
import { get, writable } from 'svelte/store';
import type { JobKind } from '$lib/api/jobs';

// ---------------------------------------------------------------------------
// Providers (mirror folio_insights.llm.providers.PROVIDERS)
// ---------------------------------------------------------------------------

export interface ProviderOption {
	id: string;
	label: string;
	/** False for providers that run on the server's own hardware without a per-user key. */
	requiresKey: boolean;
}

export const PROVIDERS: readonly ProviderOption[] = [
	{ id: 'anthropic', label: 'Anthropic', requiresKey: true },
	{ id: 'openai', label: 'OpenAI', requiresKey: true },
	{ id: 'google', label: 'Google Gemini', requiresKey: true },
	{ id: 'ollama', label: 'Ollama (local, server-hosted)', requiresKey: false },
];

export function providerById(id: string): ProviderOption | undefined {
	return PROVIDERS.find((p) => p.id === id);
}

// ---------------------------------------------------------------------------
// Session LLM settings
// ---------------------------------------------------------------------------

export interface LLMSession {
	provider: string;
	/** Optional model override; empty means the provider's default. */
	model: string;
	/** The user's API key. Empty when none is held. */
	apiKey: string;
	/** The provider the held key was entered for (a key is never sent to another provider). */
	keyProvider: string;
	/** Optional spend cap in USD (finite, > 0); null means no cap. */
	maxSpendUsd: number | null;
}

const EMPTY: LLMSession = {
	provider: PROVIDERS[0].id,
	model: '',
	apiKey: '',
	keyProvider: '',
	maxSpendUsd: null,
};

/** The tab's LLM settings. Memory only -- see the module comment. */
export const llmSession = writable<LLMSession>({ ...EMPTY });

/** Drop the key from memory (provider, model and cap stay). */
export function forgetKey(): void {
	llmSession.update((s) => ({ ...s, apiKey: '', keyProvider: '' }));
}

/**
 * The key held for `provider`, or '' when none should be sent: keyless providers never get a
 * key, and a key entered for one provider is never offered to another.
 */
export function heldKeyFor(session: LLMSession, provider: string): string {
	if (providerById(provider)?.requiresKey === false) return '';
	return session.keyProvider === provider ? session.apiKey.trim() : '';
}

/** True while a key is held in memory. */
export function hasKey(): boolean {
	return get(llmSession).apiKey.trim().length > 0;
}

/**
 * Parse the optional spend-cap field. Empty means "no cap". Anything else must be a finite
 * number greater than zero (the API rejects 0, negatives, NaN and Infinity with a 422).
 */
export function parseSpendCap(raw: string): { value: number | null; error: string | null } {
	const text = raw.trim();
	if (text === '') return { value: null, error: null };
	const value = Number(text);
	if (!Number.isFinite(value)) return { value: null, error: 'Enter a number, such as 5 or 12.50.' };
	if (value <= 0) return { value: null, error: 'The spend cap must be greater than 0.' };
	return { value, error: null };
}

// ---------------------------------------------------------------------------
// Job control tokens (one per job kind and corpus)
// ---------------------------------------------------------------------------

function tokenKey(kind: JobKind, corpusId: string): string {
	return `${kind}:${corpusId}`;
}

/** Control tokens returned by job submissions. Memory only -- see the module comment. */
export const controlTokens = writable<Record<string, string>>({});

export function setControlToken(kind: JobKind, corpusId: string, token: string): void {
	controlTokens.update((t) => ({ ...t, [tokenKey(kind, corpusId)]: token }));
}

export function getControlToken(kind: JobKind, corpusId: string): string | undefined {
	return get(controlTokens)[tokenKey(kind, corpusId)];
}

export function clearControlToken(kind: JobKind, corpusId: string): void {
	controlTokens.update((t) => {
		const next = { ...t };
		delete next[tokenKey(kind, corpusId)];
		return next;
	});
}

// ---------------------------------------------------------------------------
// Operator token (API authentication, drain plan U5)
// ---------------------------------------------------------------------------

/**
 * The operator bearer token the API requires on state-changing routes, minted by
 * `folio-insights api token-new`. Memory only -- see the module comment. Empty when none is held.
 * `$lib/api/client` sends it as `Authorization: Bearer <token>` on same-origin API calls.
 */
export const operatorToken = writable<string>('');

export function setOperatorToken(token: string): void {
	operatorToken.set(token.trim());
}

export function forgetOperatorToken(): void {
	operatorToken.set('');
}

/** The held operator token ('' when none). */
export function heldOperatorToken(): string {
	return get(operatorToken).trim();
}

/** Reset everything (tests). */
export function resetLLMSession(): void {
	llmSession.set({ ...EMPTY });
	controlTokens.set({});
	operatorToken.set('');
}
