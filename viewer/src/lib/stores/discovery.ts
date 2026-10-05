/**
 * Svelte stores for task discovery pipeline state and SSE connection management.
 * Follows the same pattern as processing.ts.
 */
import { writable } from 'svelte/store';
import { clearControlToken } from '$lib/stores/llmKey';
import { mapJobStatus, pauseReasonOf, type JobUiStatus, type PauseReason } from '$lib/stores/jobStatus';
import { getDiscoverySSEUrl } from '$lib/api/client';

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/** Overall discovery status. */
export const discoveryStatus = writable<JobUiStatus>('idle');

/** Why the job is paused (set while the status is 'paused'). */
export const discoveryPause = writable<PauseReason | null>(null);

/** Current discovery stage key (e.g. 'heading_analysis', 'folio_mapping'). */
export const discoveryStage = writable<string>('');

/** Discovery progress percentage 0-100. */
export const discoveryProgress = writable<number>(0);

/** Timestamped activity log entries from the SSE stream. */
export const discoveryLog = writable<
	Array<{ timestamp: string; stage: string; message: string }>
>([]);

/** SSE connection state. */
export const discoverySseState = writable<'connected' | 'reconnecting' | 'closed'>('closed');

/** Total tasks discovered (set on completion). */
export const discoveryTotalTasks = writable<number>(0);

/** Discovery error message (null when no error). */
export const discoveryError = writable<string | null>(null);

// ---------------------------------------------------------------------------
// EventSource lifecycle
// ---------------------------------------------------------------------------

let eventSource: EventSource | null = null;

/**
 * Open an SSE connection for task discovery and start updating stores.
 * Closes any existing connection first.
 */
export function startDiscoveryStream(corpusId: string): void {
	closeDiscoveryStream();

	// Reset stores
	discoveryStatus.set('processing');
	discoveryStage.set('');
	discoveryProgress.set(0);
	discoveryLog.set([]);
	discoverySseState.set('connected');
	discoveryTotalTasks.set(0);
	discoveryError.set(null);
	discoveryPause.set(null);

	eventSource = new EventSource(getDiscoverySSEUrl(corpusId));

	eventSource.addEventListener('status', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		discoveryStage.set(data.stage);
		discoveryProgress.set(data.progress);
	});

	eventSource.addEventListener('activity', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		discoveryLog.update((log) => [...log, data]);
	});

	eventSource.addEventListener('complete', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		discoveryTotalTasks.set(data.total_tasks ?? 0);
		discoveryError.set(data.error ?? null);
		discoveryPause.set(pauseReasonOf(data.status));
		discoveryStatus.set(mapJobStatus(data.status));
		// A finished job can no longer be controlled; a paused one keeps its token.
		if (!pauseReasonOf(data.status)) clearControlToken('discover', corpusId);
		discoverySseState.set('closed');
		eventSource?.close();
		eventSource = null;
	});

	eventSource.onerror = () => {
		discoverySseState.set('reconnecting');
	};
}

/**
 * Close the current SSE connection (if any).
 */
export function closeDiscoveryStream(): void {
	if (eventSource) {
		eventSource.close();
		eventSource = null;
	}
	discoverySseState.set('closed');
}

/**
 * Close the SSE connection and reset all stores to defaults.
 */
export function resetDiscovery(): void {
	closeDiscoveryStream();
	discoveryStatus.set('idle');
	discoveryStage.set('');
	discoveryProgress.set(0);
	discoveryLog.set([]);
	discoveryTotalTasks.set(0);
	discoveryError.set(null);
	discoveryPause.set(null);
}
