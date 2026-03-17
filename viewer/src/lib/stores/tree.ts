/**
 * Svelte stores for the FOLIO concept tree state.
 */
import { writable } from 'svelte/store';
import type { TreeNode } from '$lib/api/client';

/** Currently selected concept node in the tree. */
export const selectedConcept = writable<TreeNode | null>(null);

/** Full tree data loaded from the API. */
export const treeData = writable<TreeNode[]>([]);

/** Text filter applied to the tree. */
export const filterText = writable<string>('');

/** Active confidence band filter. */
export const confidenceFilter = writable<'all' | 'high' | 'medium' | 'low'>('all');

/** Tree or list view mode. */
export const viewMode = writable<'tree' | 'list'>('tree');
