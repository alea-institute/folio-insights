/**
 * API client for the folio-insights Review Viewer backend.
 *
 * In dev mode the Vite proxy forwards /api to localhost:8700.
 * In production the SvelteKit build is served by FastAPI on the same origin.
 */

const API_BASE = import.meta.env.DEV ? 'http://localhost:8700' : '';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function request<T>(url: string, init?: RequestInit): Promise<T | { error: string }> {
	try {
		const res = await fetch(url, init);
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
	const res = await fetch(`${API_BASE}/api/v1/corpora/${corpusId}`, { method: 'DELETE' });
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
		const res = await fetch(`${API_BASE}/api/v1/corpus/${corpusId}/upload`, {
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

export async function triggerProcessing(
	corpusId: string
): Promise<{ job_id: string; status: string } | { error: string }> {
	return request<{ job_id: string; status: string }>(
		`${API_BASE}/api/v1/corpus/${corpusId}/process`,
		{
			method: 'POST',
		}
	);
}

export function getSSEUrl(corpusId: string): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/stream`;
}

// ---------------------------------------------------------------------------
// Task Discovery
// ---------------------------------------------------------------------------

export interface TaskTreeNode {
	id: string;
	path: string; // LTree dot-notation: "1.2.3"
	label: string;
	folio_iri: string;
	unit_count: number;
	review_status: string; // "unreviewed" | "partial" | "complete"
	is_task: boolean;
	has_contradictions: boolean;
	has_orphans: boolean;
	is_jurisdiction_sensitive: boolean;
	is_procedural: boolean;
	is_manual: boolean;
	sortOrder: number;
	depth: number;
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
	const res = await fetch(
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

export async function triggerDiscovery(
	corpusId: string
): Promise<{ job_id: string; status: string } | { error: string }> {
	return request(`${API_BASE}/api/v1/corpus/${corpusId}/discover`, {
		method: 'POST',
	});
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
): Promise<{ success: boolean; validation?: ExportValidationResult } | { error: string }> {
	// Trigger export via bundle endpoint which generates all files server-side
	return request(`${API_BASE}/api/v1/corpus/${corpusId}/export/bundle`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ formats }),
	});
}

export async function fetchExportValidation(
	corpusId: string,
): Promise<ExportValidationResult | { error: string }> {
	return request<ExportValidationResult>(
		`${API_BASE}/api/v1/corpus/${corpusId}/export/validation`
	);
}

export function getExportDownloadUrl(corpusId: string, format: string): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/export/${format}`;
}

export function getExportBundleUrl(corpusId: string, formats: string[]): string {
	return `${API_BASE}/api/v1/corpus/${corpusId}/export/bundle?formats=${formats.join(',')}`;
}
