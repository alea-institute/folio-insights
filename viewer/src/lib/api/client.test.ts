/**
 * Operator authentication in the API client (drain plan U5): a held operator token goes out as
 * `Authorization: Bearer <token>` on same-origin API calls (including job calls), never to
 * another origin, and is never written to browser storage.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { apiFetch, createCorpusApi, deleteCorpusApi, triggerExport, uploadFiles } from './client';
import { cancelJob, describeJobError, submitJob } from './jobs';
import {
	forgetOperatorToken,
	heldOperatorToken,
	operatorToken,
	resetLLMSession,
	setControlToken,
	setOperatorToken,
} from '$lib/stores/llmKey';

const OP_TOKEN = 'fio_op_FAKE-operator-token-0123456789abcdef';

interface Call {
	url: string;
	init: RequestInit;
}

let calls: Call[];

function authOf(call: Call): string | null {
	return new Headers(call.init.headers).get('Authorization');
}

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
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string, init: RequestInit = {}) => {
			calls.push({ url: String(url), init });
			return new Response(JSON.stringify({ id: 'c1', job_id: 'j1', status: 'pending' }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' },
			});
		})
	);
	vi.stubGlobal('localStorage', spyStorage());
	vi.stubGlobal('sessionStorage', spyStorage());
	resetLLMSession();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('operator token header', () => {
	it('sends no Authorization header while no token is held', async () => {
		await createCorpusApi('Synthetic');
		expect(calls).toHaveLength(1);
		expect(authOf(calls[0])).toBeNull();
	});

	it('sends Authorization: Bearer on every write once a token is held', async () => {
		setOperatorToken(`  ${OP_TOKEN}  `);
		await createCorpusApi('Synthetic');
		await deleteCorpusApi('synthetic');
		await uploadFiles('synthetic', [new File(['synthetic'], 'notes.txt')]);
		await triggerExport('synthetic', ['json']);
		expect(calls.map((c) => c.url)).toEqual([
			'/api/v1/corpora',
			'/api/v1/corpora/synthetic',
			'/api/v1/corpus/synthetic/upload',
			'/api/v1/corpus/synthetic/export/bundle',
		]);
		for (const call of calls) expect(authOf(call)).toBe(`Bearer ${OP_TOKEN}`);
		// Existing headers survive alongside it.
		expect(new Headers(calls[0].init.headers).get('Content-Type')).toBe('application/json');
	});

	it('sends it on job calls next to the control token and the LLM key', async () => {
		setOperatorToken(OP_TOKEN);
		setControlToken('process', 'synthetic', 'ctl-FAKE');
		await submitJob('process', 'synthetic', { provider: 'google', apiKey: 'sk-FAKE' });
		await cancelJob('process', 'synthetic', 'ctl-FAKE');
		for (const call of calls) expect(authOf(call)).toBe(`Bearer ${OP_TOKEN}`);
		expect(new Headers(calls[1].init.headers).get('X-Job-Control-Token')).toBe('ctl-FAKE');
	});

	it('stops sending it once forgotten', async () => {
		setOperatorToken(OP_TOKEN);
		forgetOperatorToken();
		expect(heldOperatorToken()).toBe('');
		await createCorpusApi('Synthetic');
		expect(authOf(calls[0])).toBeNull();
	});

	it('never sends the token to another origin', async () => {
		setOperatorToken(OP_TOKEN);
		await apiFetch('https://elsewhere.example/api/v1/corpora', { method: 'POST' });
		await apiFetch('//elsewhere.example/api/v1/corpora', { method: 'POST' });
		for (const call of calls) expect(authOf(call)).toBeNull();
	});

	it("leaves a caller's own Authorization header alone", async () => {
		setOperatorToken(OP_TOKEN);
		await apiFetch('/api/v1/corpora', { headers: { Authorization: 'Bearer other' } });
		expect(authOf(calls[0])).toBe('Bearer other');
	});

	it('keeps the token in memory only', async () => {
		setOperatorToken(OP_TOKEN);
		await createCorpusApi('Synthetic');
		expect(get(operatorToken)).toBe(OP_TOKEN);
		expect(localStorage.setItem).not.toHaveBeenCalled();
		expect(sessionStorage.setItem).not.toHaveBeenCalled();
	});

	it('explains a 401 in terms of the operator token', () => {
		expect(describeJobError(401, '')).toMatch(/operator token/);
	});
});
