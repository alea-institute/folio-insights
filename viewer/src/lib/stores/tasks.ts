/**
 * Svelte stores for task hierarchy state.
 */
import { writable, get } from 'svelte/store';
import {
	fetchTaskTree,
	fetchTaskDetail,
	fetchTaskUnits,
	reviewTask as apiReviewTask,
	bulkApproveTasks,
	fetchContradictions,
	fetchDiscoveryStats,
	type TaskTreeNode,
	type TaskDetailResponse,
	type TaskUnitGroup,
	type ContradictionResponse,
	type DiscoveryStatsResponse,
} from '$lib/api/client';

// ---------------------------------------------------------------------------
// Tree state
// ---------------------------------------------------------------------------

/** Full task tree data loaded from the API. */
export const taskTreeData = writable<TaskTreeNode[]>([]);

/** Currently selected task node ID. */
export const selectedTaskId = writable<string | null>(null);

/** Tree display mode: tasks only or all FOLIO concepts. */
export const taskTreeMode = writable<'tasks_only' | 'all_concepts'>('tasks_only');

/** Search text for filtering the task tree. */
export const taskSearchText = writable<string>('');

// ---------------------------------------------------------------------------
// Detail state
// ---------------------------------------------------------------------------

/** Detail data for the currently selected task. */
export const taskDetail = writable<TaskDetailResponse | null>(null);

/** Knowledge units grouped by type for the selected task. */
export const taskUnits = writable<TaskUnitGroup[]>([]);

/** Currently selected knowledge unit ID within the detail pane. */
export const selectedUnitId = writable<string | null>(null);

/** Loading state for task detail/units. */
export const taskLoading = writable<boolean>(false);

// ---------------------------------------------------------------------------
// Filter state
// ---------------------------------------------------------------------------

/** Active unit type filters (empty = all types). */
export const unitTypeFilter = writable<string[]>([]);

/** Active confidence band filter. */
export const confidenceBandFilter = writable<string>('all');

/** Active review status filter. */
export const reviewStatusFilter = writable<string>('all');

/** Active flag filters (contradictions, orphans, jurisdiction). */
export const flagFilter = writable<string[]>([]);

// ---------------------------------------------------------------------------
// Contradictions
// ---------------------------------------------------------------------------

/** Contradictions for the current corpus. */
export const contradictions = writable<ContradictionResponse[]>([]);

/** Currently selected contradiction ID. */
export const selectedContradictionId = writable<string | null>(null);

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

/** Discovery statistics for the current corpus. */
export const discoveryStats = writable<DiscoveryStatsResponse | null>(null);

// ---------------------------------------------------------------------------
// Announcement (aria-live)
// ---------------------------------------------------------------------------

/** Status announcement for screen readers. */
export const taskAnnouncement = writable<string>('');

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Load the task tree for a corpus.
 */
export async function loadTaskTree(corpusId: string, mode?: string): Promise<void> {
	const result = await fetchTaskTree(corpusId, mode);
	if (!('error' in result)) {
		taskTreeData.set(result);
		// Auto-select first task node if none selected
		const currentId = get(selectedTaskId);
		if (!currentId && result.length > 0) {
			const firstTask = findFirstTask(result);
			if (firstTask) {
				selectedTaskId.set(firstTask.id);
			}
		}
	} else {
		taskTreeData.set([]);
	}
}

/**
 * Find the first task node (is_task: true) in a flat list of tree nodes.
 */
function findFirstTask(nodes: TaskTreeNode[]): TaskTreeNode | null {
	for (const node of nodes) {
		if (node.is_task) return node;
	}
	return null;
}

/**
 * Load detail for a specific task.
 */
export async function loadTaskDetail(corpusId: string, taskId: string): Promise<void> {
	taskLoading.set(true);
	const result = await fetchTaskDetail(corpusId, taskId);
	if (!('error' in result)) {
		taskDetail.set(result);
	} else {
		taskDetail.set(null);
	}
	taskLoading.set(false);
}

/**
 * Load knowledge units for a specific task.
 */
export async function loadTaskUnits(corpusId: string, taskId: string): Promise<void> {
	const result = await fetchTaskUnits(corpusId, taskId);
	if (!('error' in result)) {
		taskUnits.set(result);
		// Auto-select first unit
		if (result.length > 0 && result[0].units.length > 0) {
			selectedUnitId.set(result[0].units[0].id);
		} else {
			selectedUnitId.set(null);
		}
	} else {
		taskUnits.set([]);
		selectedUnitId.set(null);
	}
}

/**
 * Submit a task review decision.
 */
export async function submitTaskReview(
	corpusId: string,
	taskId: string,
	status: string,
	editedLabel?: string,
	note?: string
): Promise<void> {
	const result = await apiReviewTask(corpusId, taskId, status, editedLabel, note);
	if (!('error' in result)) {
		taskDetail.set(result);
		taskAnnouncement.set(`Task ${status}`);
		// Reload tree to reflect review status change
		const mode = get(taskTreeMode) === 'tasks_only' ? 'tasks_only' : undefined;
		await loadTaskTree(corpusId, mode);
	}
}

/**
 * Load contradictions for a corpus.
 */
export async function loadContradictions(corpusId: string): Promise<void> {
	const result = await fetchContradictions(corpusId);
	if (!('error' in result)) {
		contradictions.set(result);
	} else {
		contradictions.set([]);
	}
}

/**
 * Load discovery statistics for a corpus.
 */
export async function loadDiscoveryStats(corpusId: string): Promise<void> {
	const result = await fetchDiscoveryStats(corpusId);
	if (!('error' in result)) {
		discoveryStats.set(result);
	} else {
		discoveryStats.set(null);
	}
}
