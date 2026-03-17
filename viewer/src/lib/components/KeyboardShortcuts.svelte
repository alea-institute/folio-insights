<script lang="ts">
	let visible = $state(false);

	const shortcuts = [
		{ key: 'A', action: 'Approve selected unit', scope: 'Detail pane' },
		{ key: 'R', action: 'Reject selected unit', scope: 'Detail pane' },
		{ key: 'E', action: 'Edit selected unit', scope: 'Detail pane' },
		{ key: 'S', action: 'Skip to next unit', scope: 'Detail pane' },
		{ key: 'Shift+A', action: 'Approve all high-confidence units', scope: 'Any' },
		{ key: 'J / ArrowDown', action: 'Next unit', scope: 'Detail pane' },
		{ key: 'K / ArrowUp', action: 'Previous unit', scope: 'Detail pane' },
		{ key: 'Enter', action: 'Expand/select tree node', scope: 'Tree pane' },
		{ key: 'Ctrl+F', action: 'Focus tree filter input', scope: 'Any' },
		{ key: 'Ctrl+Enter', action: 'Save inline edit', scope: 'Editor open' },
		{ key: 'Escape', action: 'Close editor / dismiss modal', scope: 'Any' },
		{ key: '?', action: 'Show keyboard shortcuts', scope: 'Any' },
		{ key: '1 / 2 / 3 / 4', action: 'Switch confidence filter', scope: 'Any' },
		{ key: 'Tab', action: 'Cycle focus between panes', scope: 'Any' },
	];

	export function toggle() {
		visible = !visible;
	}

	export function show() {
		visible = true;
	}

	export function hide() {
		visible = false;
	}

	function handleBackdropClick() {
		visible = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			visible = false;
		}
	}
</script>

{#if visible}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" role="presentation" onclick={handleBackdropClick} onkeydown={handleKeydown} tabindex="-1">
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-label="Keyboard shortcuts" onkeydown={handleKeydown} tabindex="-1">
			<h2 class="modal-title">Keyboard Shortcuts</h2>
			<div class="shortcut-list">
				{#each shortcuts as s}
					<div class="shortcut-row">
						<kbd class="shortcut-key">{s.key}</kbd>
						<span class="shortcut-action">{s.action}</span>
						<span class="shortcut-scope">{s.scope}</span>
					</div>
				{/each}
			</div>
			<button class="close-btn" onclick={() => (visible = false)} aria-label="Close">
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M18 6L6 18M6 6l12 12" />
				</svg>
			</button>
		</div>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		animation: fadeIn 200ms ease-out;
	}

	@keyframes fadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.modal {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: var(--lg);
		max-width: 520px;
		width: 90%;
		max-height: 80vh;
		overflow-y: auto;
		position: relative;
		animation: scaleIn 150ms ease-out;
	}

	@keyframes scaleIn {
		from { transform: scale(0.95); opacity: 0; }
		to { transform: scale(1); opacity: 1; }
	}

	.modal-title {
		font-size: 18px;
		font-weight: 600;
		margin-bottom: var(--md);
	}

	.shortcut-list {
		display: flex;
		flex-direction: column;
		gap: var(--xs);
	}

	.shortcut-row {
		display: flex;
		align-items: center;
		gap: var(--sm);
		padding: var(--xs) 0;
	}

	.shortcut-key {
		min-width: 100px;
		padding: 2px 6px;
		font-size: 12px;
		font-family: monospace;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--accent);
		text-align: center;
	}

	.shortcut-action {
		flex: 1;
		font-size: 13px;
	}

	.shortcut-scope {
		font-size: 11px;
		color: var(--text-dim);
	}

	.close-btn {
		position: absolute;
		top: var(--md);
		right: var(--md);
		color: var(--text-dim);
	}

	.close-btn:hover {
		color: var(--text);
	}
</style>
