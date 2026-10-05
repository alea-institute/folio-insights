/**
 * LLM job API: submit, cancel, re-supply a key, resume (Phase 10 durable queue).
 *
 * Bring your own key. The user's LLM API key travels ONLY in the `X-LLM-API-Key`
 * request header, and only on the calls that need it: submit, resume and key
 * re-supply. It never goes in a URL, a query string, a request body or a log.
 *
 * Job control. Submitting returns a one-time `control_token`. Cancel, resume and
 * re-supply send it back in `X-Job-Control-Token`. The caller keeps it in memory
 * (see `$lib/stores/llmKey`); it is never persisted.
 *
 * All URLs are relative: the Vite proxy (dev) or FastAPI (prod) serves /api.
 */

export const LLM_KEY_HEADER = 'X-LLM-API-Key';
export const CONTROL_TOKEN_HEADER = 'X-Job-Control-Token';

/** Which pipeline a job runs: extraction ("process") or task discovery ("discover"). */
export type JobKind = 'process' | 'discover';

/** Per-job LLM choices. `apiKey` goes in a header; the rest goes in the JSON body. */
export interface JobLLMOptions {
	provider?: string;
	model?: string;
	apiKey?: string;
	maxSpendUsd?: number | null;
}

export interface SubmitJobResponse {
	job_id: string;
	queue_job_id?: string;
	status: string;
	duplicate?: boolean;
	/** Returned once, on creation. Needed to cancel, resume or re-key the job. */
	control_token?: string | null;
}

/** A job snapshot as the control routes return it (ProcessingJob.model_dump). */
export interface JobSnapshot {
	id: string;
	corpus_id: string;
	status: string;
	current_stage?: string;
	progress_pct?: number;
	error?: string | null;
	[key: string]: unknown;
}

/**
 * A failed job call: HTTP status (0 for a network failure) and a user-facing message.
 * `ok: false` is the discriminator -- a successful JobSnapshot has its own `error` field
 * (e.g. "resumed: waiting for an API key"), so the presence of `error` proves nothing.
 */
export interface JobError {
	ok: false;
	error: string;
	status: number;
}

export function isJobError(value: unknown): value is JobError {
	return typeof value === 'object' && value !== null && (value as { ok?: unknown }).ok === false;
}

// ---------------------------------------------------------------------------
// URLs (never carry the key or the control token)
// ---------------------------------------------------------------------------

function corpusPath(corpusId: string): string {
	return `/api/v1/corpus/${encodeURIComponent(corpusId)}`;
}

export function submitUrl(kind: JobKind, corpusId: string, force = false): string {
	if (kind === 'discover') return `${corpusPath(corpusId)}/discover`;
	return `${corpusPath(corpusId)}/process${force ? '?force=true' : ''}`;
}

export function controlUrl(
	kind: JobKind,
	corpusId: string,
	action: 'cancel' | 'credentials' | 'resume'
): string {
	const jobBase = kind === 'discover' ? '/discover/job' : '/job';
	return `${corpusPath(corpusId)}${jobBase}/${action}`;
}

// ---------------------------------------------------------------------------
// Error messages (never echo the key)
// ---------------------------------------------------------------------------

/** Replace every occurrence of each secret in `text` with a placeholder. */
export function redact(text: string, secrets: Array<string | undefined | null>): string {
	let out = text;
	for (const secret of secrets) {
		if (secret && secret.length >= 4) out = out.split(secret).join('[redacted]');
	}
	return out;
}

/** Pull a readable message out of a FastAPI error body (`detail` string or 422 list). */
function detailText(body: string): string {
	try {
		const parsed = JSON.parse(body) as { detail?: unknown };
		const detail = parsed?.detail;
		if (typeof detail === 'string') return detail;
		if (Array.isArray(detail)) {
			return detail
				.map((d) => {
					const item = d as { loc?: unknown[]; msg?: string };
					const field = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : '';
					return field ? `${field}: ${item.msg ?? 'invalid'}` : (item.msg ?? 'invalid');
				})
				.join('; ');
		}
	} catch {
		// Not JSON; fall through to the raw text.
	}
	return body.slice(0, 300);
}

/** A plain-language message for a failed job call. */
export function describeJobError(status: number, detail: string): string {
	const suffix = detail ? ` (${detail})` : '';
	switch (status) {
		case 0:
			return `Could not reach the server.${suffix}`;
		case 401:
			return `The request was not authorized. Check the API key and try again.${suffix}`;
		case 403:
			return `The server refused this request.${suffix}`;
		case 404:
			return `Not found.${suffix}`;
		case 409:
			return `This conflicts with the job's current state.${suffix}`;
		case 413:
			return `The request is too large for the server.${suffix}`;
		case 422:
			return `Some values were not accepted.${suffix}`;
		default:
			return `Request failed with status ${status}.${suffix}`;
	}
}

async function jobRequest<T>(
	url: string,
	init: RequestInit,
	secrets: Array<string | undefined | null>
): Promise<T | JobError> {
	try {
		const res = await fetch(url, init);
		if (!res.ok) {
			const body = await res.text();
			const message = describeJobError(res.status, detailText(body));
			return { ok: false, error: redact(message, secrets), status: res.status };
		}
		return (await res.json()) as T;
	} catch (err) {
		return { ok: false, error: redact(describeJobError(0, String(err)), secrets), status: 0 };
	}
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

function llmBody(options: JobLLMOptions): Record<string, unknown> {
	const body: Record<string, unknown> = {};
	if (options.provider) body.llm_provider = options.provider;
	if (options.model && options.model.trim()) body.llm_model = options.model.trim();
	if (options.maxSpendUsd !== undefined && options.maxSpendUsd !== null) {
		body.max_spend_usd = options.maxSpendUsd;
	}
	return body;
}

/** Submit a job. The key (if any) goes in `X-LLM-API-Key`; nothing secret goes in the URL. */
export async function submitJob(
	kind: JobKind,
	corpusId: string,
	options: JobLLMOptions,
	force = false
): Promise<SubmitJobResponse | JobError> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	const apiKey = options.apiKey?.trim();
	if (apiKey) headers[LLM_KEY_HEADER] = apiKey;
	return jobRequest<SubmitJobResponse>(
		submitUrl(kind, corpusId, force),
		{ method: 'POST', headers, body: JSON.stringify(llmBody(options)) },
		[apiKey]
	);
}

/** Cancel the corpus's job of this kind (now if waiting, else at the next stage boundary). */
export async function cancelJob(
	kind: JobKind,
	corpusId: string,
	controlToken: string
): Promise<JobSnapshot | JobError> {
	return jobRequest<JobSnapshot>(
		controlUrl(kind, corpusId, 'cancel'),
		{ method: 'POST', headers: { [CONTROL_TOKEN_HEADER]: controlToken } },
		[controlToken]
	);
}

/** Give a `needs_credentials` job its key again. */
export async function resupplyJobKey(
	kind: JobKind,
	corpusId: string,
	controlToken: string,
	apiKey: string
): Promise<JobSnapshot | JobError> {
	const key = apiKey.trim();
	return jobRequest<JobSnapshot>(
		controlUrl(kind, corpusId, 'credentials'),
		{
			method: 'POST',
			headers: { [CONTROL_TOKEN_HEADER]: controlToken, [LLM_KEY_HEADER]: key },
		},
		[key, controlToken]
	);
}

/**
 * Resume a `budget_exhausted` job, optionally with a higher spend cap. The server dropped
 * the key at the cap, so pass `apiKey` to continue straight away; without it the job waits
 * as `needs_credentials`.
 */
export async function resumeJob(
	kind: JobKind,
	corpusId: string,
	controlToken: string,
	options: { apiKey?: string; maxSpendUsd?: number | null } = {}
): Promise<JobSnapshot | JobError> {
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		[CONTROL_TOKEN_HEADER]: controlToken,
	};
	const key = options.apiKey?.trim();
	if (key) headers[LLM_KEY_HEADER] = key;
	const body: Record<string, unknown> = {};
	if (options.maxSpendUsd !== undefined && options.maxSpendUsd !== null) {
		body.max_spend_usd = options.maxSpendUsd;
	}
	return jobRequest<JobSnapshot>(
		controlUrl(kind, corpusId, 'resume'),
		{ method: 'POST', headers, body: JSON.stringify(body) },
		[key, controlToken]
	);
}
