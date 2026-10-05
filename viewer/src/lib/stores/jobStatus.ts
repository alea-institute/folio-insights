/**
 * Shared mapping from the API's job statuses to the viewer's UI states.
 *
 * The SSE stream closes on a terminal status (completed, failed, cancelled) or a paused one
 * (needs_credentials, budget_exhausted). Paused jobs are resumable with the job's control
 * token; see $lib/api/jobs.ts.
 */

export type JobUiStatus = 'idle' | 'processing' | 'complete' | 'error' | 'paused' | 'cancelled';

export type PauseReason = 'needs_credentials' | 'budget_exhausted';

export function pauseReasonOf(status: string | undefined | null): PauseReason | null {
	return status === 'needs_credentials' || status === 'budget_exhausted' ? status : null;
}

export function mapJobStatus(status: string | undefined | null): JobUiStatus {
	switch (status) {
		case 'completed':
			return 'complete';
		case 'cancelled':
			return 'cancelled';
		case 'needs_credentials':
		case 'budget_exhausted':
			return 'paused';
		case 'pending':
		case 'processing':
		case 'queued':
		case 'running':
			return 'processing';
		default:
			return 'error';
	}
}

/** True once a job can no longer change (its control token is useless after this). */
export function isFinished(status: string | undefined | null): boolean {
	return status === 'completed' || status === 'failed' || status === 'cancelled';
}
