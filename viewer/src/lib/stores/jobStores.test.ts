/**
 * SSE end states: paused jobs (needs_credentials, budget_exhausted) keep their control token
 * and surface a pause reason; finished jobs drop the token.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { processingPause, processingStatus, resetProcessing, startProcessingStream } from './processing';
import { discoveryPause, discoveryStatus, resetDiscovery, startDiscoveryStream } from './discovery';
import { getControlToken, resetLLMSession, setControlToken } from './llmKey';
import { mapJobStatus } from './jobStatus';

class FakeEventSource {
	static last: FakeEventSource | null = null;
	listeners: Record<string, (e: MessageEvent) => void> = {};
	onerror: (() => void) | null = null;
	closed = false;
	constructor(public url: string) {
		FakeEventSource.last = this;
	}
	addEventListener(name: string, fn: (e: MessageEvent) => void) {
		this.listeners[name] = fn;
	}
	close() {
		this.closed = true;
	}
	emit(name: string, data: unknown) {
		this.listeners[name]?.({ data: JSON.stringify(data) } as MessageEvent);
	}
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeEventSource);
	resetLLMSession();
});

afterEach(() => {
	resetProcessing();
	resetDiscovery();
	vi.unstubAllGlobals();
});

describe('processing stream', () => {
	it.each(['needs_credentials', 'budget_exhausted'] as const)(
		'pauses on %s and keeps the control token',
		(status) => {
			setControlToken('process', 'c1', 'tok');
			startProcessingStream('c1');
			expect(FakeEventSource.last?.url).toBe('/api/v1/corpus/c1/stream');
			FakeEventSource.last?.emit('complete', { status, total_units: 0, error: null });
			expect(get(processingStatus)).toBe('paused');
			expect(get(processingPause)).toBe(status);
			expect(getControlToken('process', 'c1')).toBe('tok');
			expect(FakeEventSource.last?.closed).toBe(true);
		}
	);

	it.each([
		['completed', 'complete'],
		['failed', 'error'],
		['cancelled', 'cancelled'],
	] as const)('on %s drops the control token', (status, ui) => {
		setControlToken('process', 'c1', 'tok');
		startProcessingStream('c1');
		FakeEventSource.last?.emit('complete', { status, total_units: 3, error: null });
		expect(get(processingStatus)).toBe(ui);
		expect(get(processingPause)).toBeNull();
		expect(getControlToken('process', 'c1')).toBeUndefined();
	});
});

describe('discovery stream', () => {
	it('pauses on budget_exhausted and keeps the control token', () => {
		setControlToken('discover', 'c1', 'tok');
		startDiscoveryStream('c1');
		expect(FakeEventSource.last?.url).toBe('/api/v1/corpus/c1/discover/stream');
		FakeEventSource.last?.emit('complete', { status: 'budget_exhausted', total_tasks: 0, error: null });
		expect(get(discoveryStatus)).toBe('paused');
		expect(get(discoveryPause)).toBe('budget_exhausted');
		expect(getControlToken('discover', 'c1')).toBe('tok');
	});
});

describe('mapJobStatus', () => {
	it('maps API statuses to UI states', () => {
		expect(mapJobStatus('pending')).toBe('processing');
		expect(mapJobStatus('processing')).toBe('processing');
		expect(mapJobStatus('needs_credentials')).toBe('paused');
		expect(mapJobStatus('completed')).toBe('complete');
		expect(mapJobStatus('failed')).toBe('error');
	});
});
