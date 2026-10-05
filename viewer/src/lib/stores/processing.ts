/**
 * Svelte stores for processing pipeline state and SSE connection management.
 */
import { writable } from 'svelte/store';
import { clearControlToken } from '$lib/stores/llmKey';
import { mapJobStatus, pauseReasonOf, type JobUiStatus, type PauseReason } from '$lib/stores/jobStatus';
import { getSSEUrl } from '$lib/api/client';

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/** Overall processing status. */
export const processingStatus = writable<JobUiStatus>('idle');

/** Why the job is paused (set while the status is 'paused'). */
export const processingPause = writable<PauseReason | null>(null);

/** Current pipeline stage key (e.g. 'ingestion', 'structure_parser'). */
export const currentStage = writable<string>('');

/** Progress percentage 0-100. */
export const progressPct = writable<number>(0);

/** Timestamped activity log entries from the SSE stream. */
export const activityLog = writable<
	Array<{ timestamp: string; stage: string; message: string }>
>([]);

/** SSE connection state. */
export const sseState = writable<'connected' | 'reconnecting' | 'closed'>('closed');

/** Total knowledge units extracted (set on completion). */
export const totalUnits = writable<number>(0);

/** Processing error message (null when no error). */
export const processingError = writable<string | null>(null);

// ---------------------------------------------------------------------------
// EventSource lifecycle
// ---------------------------------------------------------------------------

let eventSource: EventSource | null = null;

/**
 * Open an SSE connection for the given corpus and start updating stores.
 * Closes any existing connection first.
 */
export function startProcessingStream(corpusId: string): void {
	closeStream();

	// Reset stores
	processingStatus.set('processing');
	currentStage.set('');
	progressPct.set(0);
	activityLog.set([]);
	sseState.set('connected');
	totalUnits.set(0);
	processingError.set(null);
	processingPause.set(null);

	eventSource = new EventSource(getSSEUrl(corpusId));

	eventSource.addEventListener('status', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		currentStage.set(data.stage);
		progressPct.set(data.progress);
	});

	eventSource.addEventListener('activity', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		activityLog.update((log) => [...log, data]);
	});

	eventSource.addEventListener('complete', (e: MessageEvent) => {
		const data = JSON.parse(e.data);
		totalUnits.set(data.total_units ?? 0);
		processingError.set(data.error ?? null);
		processingPause.set(pauseReasonOf(data.status));
		processingStatus.set(mapJobStatus(data.status));
		// A finished job can no longer be controlled; a paused one keeps its token.
		if (!pauseReasonOf(data.status)) clearControlToken('process', corpusId);
		sseState.set('closed');
		eventSource?.close();
		eventSource = null;
	});

	eventSource.onerror = () => {
		sseState.set('reconnecting');
	};
}

/**
 * Close the current SSE connection (if any).
 */
export function closeStream(): void {
	if (eventSource) {
		eventSource.close();
		eventSource = null;
	}
	sseState.set('closed');
}

/**
 * Close the SSE connection and reset all stores to defaults.
 */
export function resetProcessing(): void {
	closeStream();
	processingStatus.set('idle');
	currentStage.set('');
	progressPct.set(0);
	activityLog.set([]);
	totalUnits.set(0);
	processingError.set(null);
	processingPause.set(null);
}
