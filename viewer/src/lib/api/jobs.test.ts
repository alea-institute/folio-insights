/**
 * BYOK job calls: the key travels only in the X-LLM-API-Key header (never a URL or body),
 * the control token travels in X-Job-Control-Token on cancel / resume / re-supply, and
 * nothing is written to browser storage.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	CONTROL_TOKEN_HEADER,
	LLM_KEY_HEADER,
	cancelJob,
	describeJobError,
	isJobError,
	resumeJob,
	resupplyJobKey,
	submitJob,
} from './jobs';
import {
	clearControlToken,
	controlTokens,
	forgetKey,
	getControlToken,
	heldKeyFor,
	llmSession,
	parseSpendCap,
	resetLLMSession,
	setControlToken,
} from '$lib/stores/llmKey';

const FAKE_KEY = 'sk-test-FAKE-0123456789abcdef';
const TOKEN = 'ctl-FAKE-token-abcdef0123456789';

interface Call {
	url: string;
	init: RequestInit;
}

let calls: Call[];
let nextResponse: () => Response;

function headersOf(call: Call): Record<string, string> {
	return Object.fromEntries(new Headers(call.init.headers).entries());
}

function json(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' },
	});
}

/** A Storage double that records every write. */
function spyStorage() {
	const data = new Map<string, string>();
	return {
		setItem: vi.fn((k: string, v: string) => void data.set(k, v)),
		getItem: vi.fn((k: string) => data.get(k) ?? null),
		removeItem: vi.fn((k: string) => void data.delete(k)),
		clear: vi.fn(() => data.clear()),
		key: vi.fn(() => null),
		get length() {
			return data.size;
		},
	};
}

beforeEach(() => {
	calls = [];
	nextResponse = () => json(202, { job_id: 'j1', status: 'pending', control_token: TOKEN });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string, init: RequestInit = {}) => {
			calls.push({ url: String(url), init });
			return nextResponse();
		})
	);
	vi.stubGlobal('localStorage', spyStorage());
	vi.stubGlobal('sessionStorage', spyStorage());
	resetLLMSession();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('submitJob', () => {
	it('sends the key in the X-LLM-API-Key header and LLM choices in the body', async () => {
		const res = await submitJob('process', 'corp-1', {
			provider: 'anthropic',
			model: 'claude-test',
			apiKey: FAKE_KEY,
			maxSpendUsd: 2.5,
		});
		expect(isJobError(res)).toBe(false);
		expect(calls).toHaveLength(1);
		const [call] = calls;
		expect(call.url).toBe('/api/v1/corpus/corp-1/process');
		expect(call.init.method).toBe('POST');
		expect(headersOf(call)[LLM_KEY_HEADER.toLowerCase()]).toBe(FAKE_KEY);
		expect(headersOf(call)[CONTROL_TOKEN_HEADER.toLowerCase()]).toBeUndefined();
		expect(JSON.parse(String(call.init.body))).toEqual({
			llm_provider: 'anthropic',
			llm_model: 'claude-test',
			max_spend_usd: 2.5,
		});
	});

	it('never puts the key in the URL or the body', async () => {
		await submitJob('process', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY }, true);
		await submitJob('discover', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY });
		expect(calls.map((c) => c.url)).toEqual([
			'/api/v1/corpus/corp-1/process?force=true',
			'/api/v1/corpus/corp-1/discover',
		]);
		for (const call of calls) {
			expect(call.url).not.toContain(FAKE_KEY);
			expect(String(call.init.body)).not.toContain(FAKE_KEY);
		}
	});

	it('omits the header when no key is given (keyless provider)', async () => {
		await submitJob('process', 'corp-1', { provider: 'ollama' });
		expect(headersOf(calls[0])[LLM_KEY_HEADER.toLowerCase()]).toBeUndefined();
	});

	it('returns the control token for the caller to keep in memory', async () => {
		const res = await submitJob('process', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY });
		expect(isJobError(res)).toBe(false);
		if (!isJobError(res)) expect(res.control_token).toBe(TOKEN);
	});
});

describe('job control', () => {
	it('sends the control token (and no key) on cancel', async () => {
		nextResponse = () => json(200, { id: 'j1', corpus_id: 'corp-1', status: 'cancelled' });
		await cancelJob('process', 'corp-1', TOKEN);
		await cancelJob('discover', 'corp-1', TOKEN);
		expect(calls.map((c) => c.url)).toEqual([
			'/api/v1/corpus/corp-1/job/cancel',
			'/api/v1/corpus/corp-1/discover/job/cancel',
		]);
		for (const call of calls) {
			expect(headersOf(call)[CONTROL_TOKEN_HEADER.toLowerCase()]).toBe(TOKEN);
			expect(headersOf(call)[LLM_KEY_HEADER.toLowerCase()]).toBeUndefined();
			expect(call.url).not.toContain(TOKEN);
		}
	});

	it('sends the control token, the key and the new cap on resume', async () => {
		nextResponse = () => json(200, { id: 'j1', corpus_id: 'corp-1', status: 'pending' });
		await resumeJob('process', 'corp-1', TOKEN, { apiKey: FAKE_KEY, maxSpendUsd: 10 });
		const [call] = calls;
		expect(call.url).toBe('/api/v1/corpus/corp-1/job/resume');
		expect(headersOf(call)[CONTROL_TOKEN_HEADER.toLowerCase()]).toBe(TOKEN);
		expect(headersOf(call)[LLM_KEY_HEADER.toLowerCase()]).toBe(FAKE_KEY);
		expect(JSON.parse(String(call.init.body))).toEqual({ max_spend_usd: 10 });
		expect(call.url).not.toContain(FAKE_KEY);
	});

	it('treats a successful snapshot that carries an error note as success', async () => {
		nextResponse = () =>
			json(200, {
				id: 'j1',
				corpus_id: 'corp-1',
				status: 'needs_credentials',
				error: 'resumed: waiting for an API key',
			});
		const res = await resumeJob('process', 'corp-1', TOKEN, {});
		expect(isJobError(res)).toBe(false);
		if (!isJobError(res)) expect(res.status).toBe('needs_credentials');
	});

	it('resumes without a key header when none is given', async () => {
		nextResponse = () => json(200, { id: 'j1', corpus_id: 'corp-1', status: 'needs_credentials' });
		await resumeJob('discover', 'corp-1', TOKEN, {});
		const [call] = calls;
		expect(call.url).toBe('/api/v1/corpus/corp-1/discover/job/resume');
		expect(headersOf(call)[CONTROL_TOKEN_HEADER.toLowerCase()]).toBe(TOKEN);
		expect(headersOf(call)[LLM_KEY_HEADER.toLowerCase()]).toBeUndefined();
	});

	it('sends the control token and the key on re-supply', async () => {
		nextResponse = () => json(200, { id: 'j1', corpus_id: 'corp-1', status: 'pending' });
		await resupplyJobKey('process', 'corp-1', TOKEN, FAKE_KEY);
		const [call] = calls;
		expect(call.url).toBe('/api/v1/corpus/corp-1/job/credentials');
		expect(headersOf(call)[CONTROL_TOKEN_HEADER.toLowerCase()]).toBe(TOKEN);
		expect(headersOf(call)[LLM_KEY_HEADER.toLowerCase()]).toBe(FAKE_KEY);
		expect(call.url).not.toContain(FAKE_KEY);
		expect(call.init.body).toBeUndefined();
	});
});

describe('errors', () => {
	it.each([
		[401, 'not authorized'],
		[403, 'refused'],
		[409, 'conflicts'],
		[413, 'too large'],
		[422, 'not accepted'],
	])('maps HTTP %i to a plain message', async (status, phrase) => {
		nextResponse = () => json(status, { detail: 'server detail' });
		const res = await submitJob('process', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY });
		expect(isJobError(res)).toBe(true);
		if (isJobError(res)) {
			expect(res.status).toBe(status);
			expect(res.error.toLowerCase()).toContain(phrase);
			expect(res.error).toContain('server detail');
		}
	});

	it('flattens a FastAPI 422 validation list', async () => {
		nextResponse = () =>
			json(422, { detail: [{ loc: ['body', 'max_spend_usd'], msg: 'Input should be greater than 0' }] });
		const res = await submitJob('process', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY });
		expect(isJobError(res) && res.error).toContain('max_spend_usd: Input should be greater than 0');
	});

	it('never echoes the key, even if the server does', async () => {
		nextResponse = () => json(403, { detail: `bad key ${FAKE_KEY}` });
		const res = await submitJob('process', 'corp-1', { provider: 'openai', apiKey: FAKE_KEY });
		expect(isJobError(res)).toBe(true);
		if (isJobError(res)) {
			expect(res.error).not.toContain(FAKE_KEY);
			expect(res.error).toContain('[redacted]');
		}
	});

	it('never echoes the key from a network failure', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => {
				throw new TypeError(`failed ${FAKE_KEY}`);
			})
		);
		const res = await resupplyJobKey('process', 'corp-1', TOKEN, FAKE_KEY);
		expect(isJobError(res) && res.status).toBe(0);
		expect(isJobError(res) && res.error).not.toContain(FAKE_KEY);
	});

	it('describes an unknown status', () => {
		expect(describeJobError(500, '')).toBe('Request failed with status 500.');
	});
});

describe('memory-only session store', () => {
	it('holds the key and tokens in memory and writes nothing to browser storage', async () => {
		llmSession.set({ provider: 'openai', model: '', apiKey: FAKE_KEY, keyProvider: 'openai', maxSpendUsd: 3 });
		const res = await submitJob('process', 'corp-1', { ...get(llmSession) });
		if (!isJobError(res) && res.control_token) setControlToken('process', 'corp-1', res.control_token);
		expect(getControlToken('process', 'corp-1')).toBe(TOKEN);
		await cancelJob('process', 'corp-1', TOKEN);
		clearControlToken('process', 'corp-1');

		for (const storage of [localStorage, sessionStorage] as unknown as Array<
			ReturnType<typeof spyStorage>
		>) {
			expect(storage.setItem).not.toHaveBeenCalled();
			expect(storage.length).toBe(0);
		}
		expect(get(controlTokens)).toEqual({});
	});

	it('forgetKey clears the key but keeps the other choices', () => {
		llmSession.set({ provider: 'google', model: 'm', apiKey: FAKE_KEY, keyProvider: 'google', maxSpendUsd: 4 });
		forgetKey();
		expect(get(llmSession)).toEqual({
			provider: 'google',
			model: 'm',
			apiKey: '',
			keyProvider: '',
			maxSpendUsd: 4,
		});
	});

	it('offers a held key only to the provider it was entered for, never to a keyless one', () => {
		const session = { provider: 'anthropic', model: '', apiKey: FAKE_KEY, keyProvider: 'anthropic', maxSpendUsd: null };
		expect(heldKeyFor(session, 'anthropic')).toBe(FAKE_KEY);
		expect(heldKeyFor(session, 'openai')).toBe('');
		expect(heldKeyFor(session, 'ollama')).toBe('');
		expect(heldKeyFor({ ...session, keyProvider: 'ollama' }, 'ollama')).toBe('');
	});

	it('no key-handling source touches persistent browser storage or the console', () => {
		// Loaded as raw text by Vite (no Node APIs, so svelte-check needs no @types/node).
		const sources = import.meta.glob(
			[
				'/src/lib/api/jobs.ts',
				'/src/lib/stores/{llmKey,jobStatus,processing,discovery}.ts',
				'/src/lib/components/{LLMJobDialog,JobPausedPanel}.svelte',
				'/src/routes/upload/+page.svelte',
			],
			{ query: '?raw', import: 'default', eager: true }
		) as Record<string, string>;
		expect(Object.keys(sources)).toHaveLength(8);
		for (const [file, raw] of Object.entries(sources)) {
			// Code only: the module comments explain the rule by naming these APIs.
			const text = raw
				.replace(/\/\*[\s\S]*?\*\//g, '')
				.replace(/<!--[\s\S]*?-->/g, '')
				.replace(/^\s*\/\/.*$/gm, '');
			expect(text, file).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie|console\./);
		}
	});
});

describe('parseSpendCap', () => {
	it.each([
		['', null, null],
		['  ', null, null],
		['5', 5, null],
		['12.50', 12.5, null],
	])('accepts %j', (raw, value, error) => {
		expect(parseSpendCap(raw)).toEqual({ value, error });
	});

	it.each(['0', '-1', 'abc', 'Infinity', 'NaN', '1e999'])('rejects %j', (raw) => {
		const res = parseSpendCap(raw);
		expect(res.value).toBeNull();
		expect(res.error).toBeTruthy();
	});
});
