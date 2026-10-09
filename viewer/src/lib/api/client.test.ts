/**
 * Operator authentication in the API client (drain plan U5): a held operator token goes out as
 * `Authorization: Bearer <token>` on same-origin API calls (including job calls), never to
 * another origin, and is never written to browser storage.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	apiFetch,
	createCorpusApi,
	deleteCorpusApi,
	downloadExport,
	fetchShardDerivation,
	fetchShardGraph,
	isSameOriginUrl,
	triggerExport,
	uploadFiles,
} from './client';
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

	it.each([
		['/\\elsewhere.example/api', 'backslash: browsers read "/\\host" as "//host"'],
		['/\\/elsewhere.example/api', 'backslash then slash'],
		['\\\\elsewhere.example/api', 'two backslashes'],
		['/\t/elsewhere.example/api', 'tab: stripped by URL parsing, leaving "//host"'],
		['/\n/elsewhere.example/api', 'newline'],
		['/\r/elsewhere.example/api', 'carriage return'],
		['/\u0000/elsewhere.example/api', 'NUL'],
		[' //elsewhere.example/api', 'leading space'],
		['api/v1/corpora', 'relative without a leading slash'],
		['', 'empty'],
		['javascript:alert(1)', 'another scheme'],
		['https://elsewhere.example/api', 'absolute URL'],
	])('never sends the token to %j (%s)', async (url) => {
		setOperatorToken(OP_TOKEN);
		await apiFetch(url, { method: 'POST' });
		expect(authOf(calls[0])).toBeNull();
	});

	it('sends the token to same-origin paths, absolute same-origin URLs included', async () => {
		vi.stubGlobal('location', new URL('http://127.0.0.1:8700/tasks'));
		setOperatorToken(OP_TOKEN);
		await apiFetch('/api/v1/corpora', { method: 'POST' });
		await apiFetch('/api/v1/tree?corpus=default');
		await apiFetch('http://127.0.0.1:8700/api/v1/corpora', { method: 'POST' });
		await apiFetch('http://127.0.0.1:8701/api/v1/corpora', { method: 'POST' });
		expect(calls.map(authOf)).toEqual([
			`Bearer ${OP_TOKEN}`,
			`Bearer ${OP_TOKEN}`,
			`Bearer ${OP_TOKEN}`,
			null,
		]);
	});

	it('isSameOriginUrl decides by the resolved origin', () => {
		const here = 'http://localhost:8700';
		expect(isSameOriginUrl('/api/v1/corpora', here)).toBe(true);
		expect(isSameOriginUrl('/api/../api/v1', here)).toBe(true);
		expect(isSameOriginUrl('//elsewhere.example/x', here)).toBe(false);
		expect(isSameOriginUrl('/\\elsewhere.example/x', here)).toBe(false);
		expect(isSameOriginUrl('http://localhost:8700/x', here)).toBe(true);
		expect(isSameOriginUrl('http://localhost.evil.example/x', here)).toBe(false);
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

describe('export downloads carry the operator token', () => {
	it('fetches a single format with the token and hands the file to the saver', async () => {
		setOperatorToken(OP_TOKEN);
		const saved: Array<{ name: string; size: number }> = [];
		const result = await downloadExport('synthetic', ['owl'], (blob, name) => {
			saved.push({ name, size: blob.size });
		});
		expect(result).toEqual({ success: true });
		expect(calls).toHaveLength(1);
		expect(calls[0].url).toBe('/api/v1/corpus/synthetic/export/owl');
		expect(calls[0].init.method ?? 'GET').toBe('GET');
		expect(authOf(calls[0])).toBe(`Bearer ${OP_TOKEN}`);
		expect(saved).toEqual([{ name: 'folio-insights-synthetic.owl', size: expect.any(Number) }]);
	});

	it('maps md to the markdown route', async () => {
		await downloadExport('synthetic', ['md'], () => {});
		expect(calls[0].url).toBe('/api/v1/corpus/synthetic/export/markdown');
	});

	it('posts several formats to the bundle route', async () => {
		setOperatorToken(OP_TOKEN);
		const names: string[] = [];
		await downloadExport('synthetic', ['owl', 'ttl'], (_blob, name) => void names.push(name));
		expect(calls[0].url).toBe('/api/v1/corpus/synthetic/export/bundle');
		expect(calls[0].init.method).toBe('POST');
		expect(JSON.parse(String(calls[0].init.body))).toEqual({ formats: ['owl', 'ttl'] });
		expect(authOf(calls[0])).toBe(`Bearer ${OP_TOKEN}`);
		expect(names).toEqual(['folio-insights-synthetic-export.zip']);
	});

	it('reports a refusal instead of saving it', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('{"detail":"Operator authentication required."}', { status: 401 }))
		);
		const saver = vi.fn();
		const result = await downloadExport('synthetic', ['ttl'], saver);
		expect(result).toEqual({ error: expect.stringMatching(/^401/) });
		expect(saver).not.toHaveBeenCalled();
	});
});

describe('shard graph reads (drain U10)', () => {
	const URN = 'urn:folio:shard/0123456789abcdef0123456789abcdef';

	it('encodes the corpus and the IRI as single path segments', async () => {
		await fetchShardGraph('kernel-corpus', URN, 2);
		await fetchShardDerivation('kernel-corpus', 'https://x.org/a b');
		await fetchShardGraph('c', URN);
		expect(calls.map((c) => c.url)).toEqual([
			'/api/v1/corpus/kernel-corpus/shards/urn%3Afolio%3Ashard%2F0123456789abcdef0123456789abcdef/graph?depth=2',
			'/api/v1/corpus/kernel-corpus/shards/https%3A%2F%2Fx.org%2Fa%20b/derivation',
			'/api/v1/corpus/c/shards/urn%3Afolio%3Ashard%2F0123456789abcdef0123456789abcdef/graph',
		]);
	});

	it('reports a refusal with its status and the API detail', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () =>
				new Response(JSON.stringify({ detail: "no corpus 'x'" }), {
					status: 404,
					headers: { 'Content-Type': 'application/json' },
				})
			)
		);
		expect(await fetchShardGraph('x', URN)).toEqual({ error: "no corpus 'x'", status: 404 });
	});

	it('reports a network failure as status 0', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('offline'))));
		const result = await fetchShardDerivation('x', URN);
		expect(result).toMatchObject({ status: 0 });
	});
});
