/**
 * API client for the folio-insights Review Viewer backend.
 *
 * All /api requests use relative URLs. In dev mode, the Vite proxy forwards
 * them to the FastAPI backend (see viewer/vite.config.ts for the proxy target).
 * In production, FastAPI serves the SPA on the same origin.
 */

import { heldOperatorToken } from '$lib/stores/llmKey';

const API_BASE = '';

// ---------------------------------------------------------------------------
// Operator authentication
// ---------------------------------------------------------------------------

/** Control characters (C0, DEL) and backslashes: URL parsing strips or rewrites them. */
// eslint-disable-next-line no-control-regex
const UNSAFE_URL_CHARS = /[\u0000-\u001f\u007f\\]/;

/**
 * True when `url` resolves to `origin` (default: this page's origin).
 *
 * The URL is resolved the way `fetch` will resolve it (`new URL(url, origin)`) and the origins
 * are compared, so '//host', '/\\host' (browsers read a backslash as a slash) and other
 * spellings of another host are all refused. A URL holding a control character or a backslash
 * is refused outright: URL parsing silently strips tabs and newlines, so what was checked
 * would not be what is fetched.
 */
export function isSameOriginUrl(url: string, origin?: string): boolean {
	if (typeof url !== 'string' || url === '' || UNSAFE_URL_CHARS.test(url)) return false;
	const base = origin ?? globalThis.location?.origin;
	if (!base) {
		// No page origin (tests, SSR): only a plain absolute path can be same-origin.
		return url.startsWith('/') && !url.startsWith('//');
	}
	try {
		return new URL(url, base).origin === new URL(base).origin;
	} catch {
		return false;
	}
}

/**
 * `fetch` for this app's own API. When an operator token is held in tab memory
 * (`$lib/stores/llmKey`, `operatorToken`), it is sent as `Authorization: Bearer <token>`:
 * the API refuses state-changing requests without one (401). Only URLs that resolve to this
 * page's origin (`isSameOriginUrl`) ever get the header, so the token never leaves for another
 * host. A caller's own Authorization header is left alone.
 */
export function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
	const token = heldOperatorToken();
	if (!token || !isSameOriginUrl(url)) return fetch(url, init);
	const headers = new Headers(init.headers);
	if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
	return fetch(url, { ...init, headers });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function request<T>(url: string, init?: RequestInit): Promise<T | { error: string }> {
	try {
		const res = await apiFetch(url, init);
		if (!res.ok) {
			const body = await res.text();
			return { error: `${res.status}: ${body}` };
		}
		return (await res.json()) as T;
	} catch (err) {
		return { error: String(err) };
	}
}

function qs(params: Record<string, string | number | undefined | null>): string {
	const entries = Object.entries(params).filter(
		([, v]) => v !== undefined && v !== null && v !== ''
	);
	if (entries.length === 0) return '';
	return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
}

// ---------------------------------------------------------------------------
// Tree
// ---------------------------------------------------------------------------

export interface TreeNode {
	iri: string;
	label: string;
	branch: string;
	unit_count: number;
	children: TreeNode[];
}

export async function fetchTree(corpus: string): Promise<TreeNode[] | { error: string }> {
	return request<TreeNode[]>(`${API_BASE}/api/v1/tree${qs({ corpus })}`);
}

export async function fetchTreeFlat(
	corpus: string
): Promise<Array<{ iri: string; label: string; branch: string; unit_count: number }> | { error: string }> {
	return request(`${API_BASE}/api/v1/tree/flat${qs({ corpus })}`);
}

// ---------------------------------------------------------------------------
// Units
// ---------------------------------------------------------------------------

export interface FolioTag {
	iri: string;
	label: string;
	confidence: number;
	extraction_path: string;
	branch: string;
}

export interface KnowledgeUnitResponse {
	id: string;
	text: string;
	original_span: { start: number; end: number; source_file: string };
	unit_type: string;
	source_file: string;
	source_section: string[];
	folio_tags: FolioTag[];
	surprise_score: number;
	confidence: number;
	content_hash: string;
	review_status: string;
	edited_text: string | null;
	reviewer_note: string;
	reviewed_at: string | null;
}

export async function fetchUnits(
	corpus: string,
	conceptIri?: string,
	confidence?: string
): Promise<KnowledgeUnitResponse[] | { error: string }> {
	return request<KnowledgeUnitResponse[]>(
		`${API_BASE}/api/v1/units${qs({ corpus, concept_iri: conceptIri, confidence })}`
	);
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

export async function reviewUnit(
	unitId: string,
	status: string,
	corpus: string = 'default',
	editedText?: string,
	note?: string
): Promise<KnowledgeUnitResponse | { error: string }> {
	return request<KnowledgeUnitResponse>(
		`${API_BASE}/api/v1/units/${unitId}/review${qs({ corpus })}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ status, edited_text: editedText, note }),
		}
	);
}

export async function bulkApprove(
	corpus: string = 'default',
	unitIds?: string[],
	confidenceMin?: number
): Promise<{ approved_count: number; unit_ids: string[] } | { error: string }> {
	return request(`${API_BASE}/api/v1/units/bulk-approve${qs({ corpus })}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ unit_ids: unitIds, confidence_min: confidenceMin }),
	});
}

// ---------------------------------------------------------------------------
// Source
// ---------------------------------------------------------------------------

export interface SourceResponse {
	found: boolean;
	file_path: string;
	section_breadcrumb: string;
	text: string;
	message?: string;
	span_start_in_context?: number;
	span_end_in_context?: number;
}

export async function fetchSource(
	filePath: string,
	start: number,
	end: number
): Promise<SourceResponse | { error: string }> {
	return request<SourceResponse>(
		`${API_BASE}/api/v1/source${qs({ file: filePath, start, end })}`
	);
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export interface ReviewStats {
	total: number;
	approved: number;
	rejected: number;
	edited: number;
	unreviewed: number;
	by_confidence: { high: number; medium: number; low: number };
}

export async function fetchStats(corpus: string): Promise<ReviewStats | { error: string }> {
	return request<ReviewStats>(`${API_BASE}/api/v1/review/stats${qs({ corpus })}`);
}

// ---------------------------------------------------------------------------
// Corpus
// ---------------------------------------------------------------------------

export interface CorpusInfo {
	id: string;
	name: string;
	file_count: number;
	processing_status: string;
	last_processed: string | null;
	created_at: string;
}

export interface CorpusFile {
	filename: string;
	size_bytes: number;
	format: string;
}

export async function fetchCorpora(): Promise<CorpusInfo[] | { error: string }> {
	return request<CorpusInfo[]>(`${API_BASE}/api/v1/corpora`);
}

export async function createCorpusApi(name: string): Promise<CorpusInfo | { error: string }> {
	return request<CorpusInfo>(`${API_BASE}/api/v1/corpora`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name }),
	});
}

export async function deleteCorpusApi(corpusId: string): Promise<void | { error: string }> {
	const res = await apiFetch(`${API_BASE}/api/v1/corpora/${corpusId}`, { method: 'DELETE' });
	if (!res.ok) return { error: `${res.status}: ${await res.text()}` };
}

export async function fetchCorpusFiles(
	corpusId: string
): Promise<CorpusFile[] | { error: string }> {
	return request<CorpusFile[]>(`${API_BASE}/api/v1/corpora/${corpusId}/files`);
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

export async function uploadFiles(
	corpusId: string,
	files: FileList | File[]
): Promise<{ uploaded: Array<{ filename: string; size: number }>; count: number } | { error: string }> {
	const formData = new FormData();
	for (const file of files) {
		formData.append('files', file);
	}
	try {
		const res = await apiFetch(`${API_BASE}/api/v1/corpus/${corpusId}/upload`, {
			method: 'POST',
			body: formData,
		});
		if (!res.ok) return { error: `${res.status}: ${await res.text()}` };
		return await res.json();
	} catch (err) {
		return { error: String(err) };
	}
}

// ---------------------------------------------------------------------------
// Processing
// ---------------------------------------------------------------------------

// Submitting, cancelling and resuming LLM jobs lives in $lib/api/jobs.ts
// (the key travels only in a header there).

export function getSSEUrl(corpusId: string): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/stream`;
}

// ---------------------------------------------------------------------------
// Task Discovery
// ---------------------------------------------------------------------------

export interface TaskTreeNode {
	id: string;
	label: string;
	folio_iri: string;
	unit_count: number;
	review_status: string; // "unreviewed" | "partial" | "approved" | "rejected"
	is_task: boolean;
	has_contradictions: boolean;
	has_orphans: boolean;
	is_jurisdiction_sensitive: boolean;
	is_procedural: boolean;
	is_manual: boolean;
	depth: number;
	children: TaskTreeNode[];
}

export interface TaskDetailResponse {
	id: string;
	label: string;
	description: string;
	folio_iri: string;
	folio_label: string;
	parent_task_id: string | null;
	depth: number;
	is_procedural: boolean;
	canonical_order: number | null;
	unit_type_counts: Record<string, number>;
	confidence: number;
	review_status: string;
	has_contradictions: boolean;
	has_orphans: boolean;
	is_jurisdiction_sensitive: boolean;
	is_manual: boolean;
}

export interface TaskUnitGroup {
	type: string;
	units: KnowledgeUnitResponse[];
}

export interface ContradictionResponse {
	id: string;
	task_id: string;
	unit_id_a: string;
	unit_id_b: string;
	unit_text_a: string;
	unit_text_b: string;
	source_a: string;
	source_b: string;
	authority_a: number;
	authority_b: number;
	confidence_a: number;
	confidence_b: number;
	nli_score: number;
	contradiction_type: string;
	resolution: string | null;
	resolved_text: string | null;
	resolver_note: string;
}

export interface DiscoveryStatsResponse {
	total_tasks: number;
	total_subtasks: number;
	total_units_assigned: number;
	orphan_count: number;
	contradiction_count: number;
	contradictions_resolved: number;
	review_progress_pct: number;
	by_confidence: Record<string, number>;
	by_unit_type: Record<string, number>;
	source_coverage: Record<string, number>;
}

export async function fetchTaskTree(
	corpusId: string,
	mode?: string
): Promise<TaskTreeNode[] | { error: string }> {
	return request<TaskTreeNode[]>(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks/tree${qs({ mode })}`
	);
}

export async function fetchTaskDetail(
	corpusId: string,
	taskId: string
): Promise<TaskDetailResponse | { error: string }> {
	return request<TaskDetailResponse>(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks/${taskId}`
	);
}

export async function fetchTaskUnits(
	corpusId: string,
	taskId: string
): Promise<TaskUnitGroup[] | { error: string }> {
	return request<TaskUnitGroup[]>(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks/${taskId}/units`
	);
}

export async function reviewTask(
	corpusId: string,
	taskId: string,
	status: string,
	editedLabel?: string,
	note?: string
): Promise<TaskDetailResponse | { error: string }> {
	return request<TaskDetailResponse>(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks/${taskId}/review`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ status, edited_label: editedLabel, note }),
		}
	);
}

export async function bulkApproveTasks(
	corpusId: string,
	taskIds?: string[],
	confidenceMin?: number
): Promise<{ approved_count: number; task_ids: string[] } | { error: string }> {
	return request(`${API_BASE}/api/v1/corpus/${corpusId}/tasks/bulk-approve`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ task_ids: taskIds, confidence_min: confidenceMin }),
	});
}

export async function createTask(
	corpusId: string,
	label: string,
	folioIri?: string,
	parentTaskId?: string
): Promise<TaskDetailResponse | { error: string }> {
	return request<TaskDetailResponse>(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				label,
				folio_iri: folioIri,
				parent_task_id: parentTaskId,
			}),
		}
	);
}

export async function deleteTask(
	corpusId: string,
	taskId: string
): Promise<void | { error: string }> {
	const res = await apiFetch(
		`${API_BASE}/api/v1/corpus/${corpusId}/tasks/${taskId}`,
		{ method: 'DELETE' }
	);
	if (!res.ok) return { error: `${res.status}: ${await res.text()}` };
}

export async function submitHierarchyEdit(
	corpusId: string,
	editType: string,
	sourceTaskId?: string,
	targetTaskId?: string,
	detail?: string
): Promise<{ success: boolean } | { error: string }> {
	return request(`${API_BASE}/api/v1/corpus/${corpusId}/tasks/hierarchy-edit`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			edit_type: editType,
			source_task_id: sourceTaskId,
			target_task_id: targetTaskId,
			detail,
		}),
	});
}

export async function fetchContradictions(
	corpusId: string,
	status?: string
): Promise<ContradictionResponse[] | { error: string }> {
	return request<ContradictionResponse[]>(
		`${API_BASE}/api/v1/corpus/${corpusId}/contradictions${qs({ status })}`
	);
}

export async function resolveContradiction(
	corpusId: string,
	contradictionId: string,
	resolution: string,
	resolvedText?: string,
	note?: string
): Promise<ContradictionResponse | { error: string }> {
	return request<ContradictionResponse>(
		`${API_BASE}/api/v1/corpus/${corpusId}/contradictions/${contradictionId}/resolve`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				resolution,
				resolved_text: resolvedText,
				note,
			}),
		}
	);
}

export async function fetchDiscoveryStats(
	corpusId: string
): Promise<DiscoveryStatsResponse | { error: string }> {
	return request<DiscoveryStatsResponse>(
		`${API_BASE}/api/v1/corpus/${corpusId}/discovery/stats`
	);
}

export interface DiscoveryDiffEntry {
	type: 'added' | 'removed' | 'changed';
	id: string;
	description: string;
}

export async function fetchDiscoveryDiff(
	corpusId: string
): Promise<DiscoveryDiffEntry[] | { error: string }> {
	return request<DiscoveryDiffEntry[]>(
		`${API_BASE}/api/v1/corpus/${corpusId}/discovery/diff`
	);
}

export function getDiscoverySSEUrl(corpusId: string): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/discover/stream`;
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export interface ExportValidationCheck {
	name: string;
	status: 'PASS' | 'WARN' | 'FAIL';
	details: string;
}

export interface ExportValidationResult {
	conforms: boolean;
	checks: ExportValidationCheck[];
	markdown: string;
}

export async function triggerExport(
	corpusId: string,
	formats: string[],
): Promise<{ success: boolean } | { error: string }> {
	try {
		const res = await apiFetch(`${API_BASE}/api/v1/corpus/${corpusId}/export/bundle`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ formats }),
		});
		if (!res.ok) {
			const body = await res.text();
			return { error: `${res.status}: ${body}` };
		}
		// Bundle endpoint returns ZIP binary on success.
		// We don't parse it -- just confirm success. The actual download
		// happens via downloadExport, which carries the operator token.
		return { success: true };
	} catch (err) {
		return { error: String(err) };
	}
}

export async function fetchExportValidation(
	corpusId: string,
): Promise<ExportValidationResult | { error: string }> {
	return request<ExportValidationResult>(
		`${API_BASE}/api/v1/corpus/${corpusId}/export/validation`
	);
}

/** Export format (as the dialog names it) -> GET route segment. */
const EXPORT_ROUTE: Record<string, string> = { md: 'markdown', markdown: 'markdown' };

/** File extension of a single-format download. */
const EXPORT_EXTENSION: Record<string, string> = { markdown: 'md' };

/** Save `blob` as a browser download named `filename`. */
export function saveBlob(blob: Blob, filename: string): void {
	const href = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = href;
	link.download = filename;
	link.rel = 'noopener';
	document.body.appendChild(link);
	link.click();
	link.remove();
	// Revoke after the click has been dispatched, so the download keeps its source.
	setTimeout(() => URL.revokeObjectURL(href), 0);
}

/**
 * Download an export with the operator token. A plain link or `location.href` cannot carry
 * `Authorization`, and the OWL, Turtle, JSON-LD and validation exports require an operator
 * (they mint IRIs and write export files), so the file is fetched through `apiFetch` and then
 * saved. One format uses its GET route; several are zipped by the bundle route.
 */
export async function downloadExport(
	corpusId: string,
	formats: string[],
	save: (blob: Blob, filename: string) => void = saveBlob,
): Promise<{ success: true } | { error: string }> {
	if (formats.length === 0) return { error: 'No export format selected' };
	const corpus = encodeURIComponent(corpusId);
	let url: string;
	let init: RequestInit = {};
	let filename: string;
	if (formats.length === 1) {
		const route = EXPORT_ROUTE[formats[0]] ?? formats[0];
		url = `${API_BASE}/api/v1/corpus/${corpus}/export/${encodeURIComponent(route)}`;
		filename = `folio-insights-${corpusId}.${EXPORT_EXTENSION[route] ?? route}`;
	} else {
		url = `${API_BASE}/api/v1/corpus/${corpus}/export/bundle`;
		init = {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ formats }),
		};
		filename = `folio-insights-${corpusId}-export.zip`;
	}
	try {
		const res = await apiFetch(url, init);
		if (!res.ok) return { error: `${res.status}: ${await res.text()}` };
		save(await res.blob(), filename);
		return { success: true };
	} catch (err) {
		return { error: String(err) };
	}
}

/**
 * The GET URL of one export format. Only the markdown, json and html exports are open reads;
 * use `downloadExport` for the others, which need the operator token.
 */
export function getExportDownloadUrl(corpusId: string, format: string): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/export/${format}`;
}

// ---------------------------------------------------------------------------
// Shard dependency graph (drain U10, R12/R14)
// ---------------------------------------------------------------------------

/** One node of a shard dependency graph (`GET .../shards/{iri}/graph`). */
export interface ShardGraphNode {
	iri: string;
	/** Display path (`1`, `1.2.3`); null for an IRI that is not a shard of the corpus. */
	tractarian_path: string | null;
	/** One-line label, at most 140 characters (sense, else triple, else kernel Latin). */
	label: string;
	shard_type: string | null;
	epistemic_status: string | null;
	is_kernel: boolean;
	/** Kernel citation such as "VI 5.12.6"; null for a non-kernel node. */
	citation: string | null;
	citation_uri: string | null;
	/** False for a cited IRI the corpus does not hold (dangling, or an unseeded kernel maxim). */
	stored: boolean;
	/** Where the walk reached the node: the root, upstream (what it derives from) or downstream. */
	direction: 'root' | 'upstream' | 'downstream';
	/** Hops from the root. */
	distance: number;
}

/** `from` names `to` in its `field` list (so `from` depends on `to`). */
export interface ShardGraphEdge {
	from: string;
	to: string;
	field: string;
}

export interface ShardGraph {
	format: string;
	corpus: string;
	root: string;
	depth: number;
	node_cap: number;
	nodes: ShardGraphNode[];
	edges: ShardGraphEdge[];
	/** True when the depth bound or the node cap left nodes out. */
	truncated: boolean;
}

export interface KernelChain {
	kernel_iri: string;
	citation: string;
	citation_uri: string;
	depth: number;
	/** Root first, kernel shard last. */
	path: string[];
	edges: ShardGraphEdge[];
}

/** `GET .../shards/{iri}/derivation` (format `folio-insights/kernel-chain/v1`). */
export interface ShardDerivation {
	format: string;
	corpus: string;
	root: string;
	tractarian_path: string | null;
	max_depth: number;
	kernel_reached: boolean;
	derivedFromKernel: KernelChain[];
	nodes: Array<{
		iri: string;
		kernel: boolean;
		citation: string | null;
		citation_uri: string | null;
		tractarian_path: string | null;
	}>;
	missing: string[];
	truncated: boolean;
}

/** A refused graph read: the HTTP status (0 for a network failure) and the API's detail. */
export interface GraphError {
	error: string;
	status: number;
}

async function graphRequest<T>(url: string): Promise<T | GraphError> {
	try {
		const res = await apiFetch(url);
		if (!res.ok) {
			let detail = res.statusText || 'request failed';
			try {
				const body = await res.json();
				if (typeof body?.detail === 'string') detail = body.detail;
			} catch {
				// a non-JSON error body keeps the status text
			}
			return { error: detail, status: res.status };
		}
		return (await res.json()) as T;
	} catch (err) {
		return { error: String(err), status: 0 };
	}
}

function shardUrl(corpus: string, iri: string, view: 'graph' | 'derivation'): string {
	return (
		`${API_BASE}/api/v1/corpus/${encodeURIComponent(corpus)}` +
		`/shards/${encodeURIComponent(iri)}/${view}`
	);
}

/** The bounded dependency graph around `iri` (depth 0-8, server default 3). */
export async function fetchShardGraph(
	corpus: string,
	iri: string,
	depth?: number
): Promise<ShardGraph | GraphError> {
	return graphRequest<ShardGraph>(`${shardUrl(corpus, iri, 'graph')}${qs({ depth })}`);
}

/** Every kernel maxim `iri` derives from, with the shortest chain to each. */
export async function fetchShardDerivation(
	corpus: string,
	iri: string,
	maxDepth?: number
): Promise<ShardDerivation | GraphError> {
	return graphRequest<ShardDerivation>(
		`${shardUrl(corpus, iri, 'derivation')}${qs({ max_depth: maxDepth })}`
	);
}
