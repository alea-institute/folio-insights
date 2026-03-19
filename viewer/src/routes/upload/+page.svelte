<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { selectedCorpus } from '$lib/stores/corpus';
	import {
		processingStatus,
		currentStage,
		progressPct,
		activityLog,
		totalUnits,
		processingError,
		sseState,
		startProcessingStream,
		closeStream,
		resetProcessing,
	} from '$lib/stores/processing';
	import {
		discoveryStatus,
		discoveryStage,
		discoveryProgress,
		discoveryLog,
		startDiscoveryStream,
		closeDiscoveryStream,
		resetDiscovery,
	} from '$lib/stores/discovery';
	import { uploadFiles, fetchCorpusFiles, triggerProcessing, triggerDiscovery } from '$lib/api/client';
	import type { CorpusFile } from '$lib/api/client';

	import CorpusSidebar from '$lib/components/CorpusSidebar.svelte';
	import UploadZone from '$lib/components/UploadZone.svelte';
	import FileListView from '$lib/components/FileList.svelte';
	import ProcessButton from '$lib/components/ProcessButton.svelte';
	import ProgressDisplay from '$lib/components/ProgressDisplay.svelte';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import DiscoverButton from '$lib/components/DiscoverButton.svelte';
	import DiscoveryProgress from '$lib/components/DiscoveryProgress.svelte';

	let files = $state<Array<{ filename: string; size_bytes: number; format: string; status: string }>>([]);
	let uploading = $state(false);
	let activityExpanded = $state(false);
	let navTimer: ReturnType<typeof setTimeout> | null = null;
	let discoveryNavTimer: ReturnType<typeof setTimeout> | null = null;

	// Load files when corpus changes
	$effect(() => {
		const corpus = $selectedCorpus;
		if (corpus) {
			resetProcessing();
			resetDiscovery();
			loadFiles(corpus.id);
		} else {
			files = [];
			resetProcessing();
			resetDiscovery();
		}
	});

	// Auto-navigate on completion
	$effect(() => {
		if ($processingStatus === 'complete' && $selectedCorpus) {
			const corpusId = $selectedCorpus.id;
			navTimer = setTimeout(() => {
				goto(`/?corpus=${corpusId}`);
			}, 1500);
		}
	});

	// Auto-navigate to tasks on discovery completion
	$effect(() => {
		if ($discoveryStatus === 'complete') {
			discoveryNavTimer = setTimeout(() => {
				goto('/tasks');
			}, 1500);
			return () => {
				if (discoveryNavTimer) clearTimeout(discoveryNavTimer);
			};
		}
	});

	// Auto-expand activity log on error
	$effect(() => {
		if ($processingStatus === 'error') {
			activityExpanded = true;
		}
	});

	// Status announcement text for screen readers
	let statusAnnouncement = $derived(
		$discoveryStatus === 'processing' && $discoveryStage
			? `Discovery stage: ${$discoveryStage}`
			: $discoveryStatus === 'complete'
				? 'Task discovery complete.'
				: $processingStatus === 'processing' && $currentStage
					? `Processing stage: ${$currentStage}`
					: $processingStatus === 'complete'
						? `Processing complete. ${$totalUnits} knowledge units extracted.`
						: $processingStatus === 'error'
							? `Processing failed. ${$processingError || 'Check the activity log for details.'}`
							: ''
	);

	// Derive discovery button status
	let discoverStatus = $derived<'ready' | 'disabled' | 'processing' | 'complete'>(
		$discoveryStatus === 'complete'
			? 'complete'
			: $discoveryStatus === 'processing'
				? 'processing'
				: $processingStatus === 'complete'
					? 'ready'
					: 'disabled'
	);

	async function loadFiles(corpusId: string) {
		const result = await fetchCorpusFiles(corpusId);
		if (!('error' in result)) {
			files = result.map((f: CorpusFile) => ({
				filename: f.filename,
				size_bytes: f.size_bytes,
				format: f.format,
				status: 'pending',
			}));
		}
	}

	async function handleFiles(fileList: FileList) {
		if (!$selectedCorpus) return;
		uploading = true;
		const result = await uploadFiles($selectedCorpus.id, fileList);
		if (!('error' in result)) {
			await loadFiles($selectedCorpus.id);
		}
		uploading = false;
	}

	async function handleProcess() {
		if (!$selectedCorpus) return;
		const result = await triggerProcessing($selectedCorpus.id);
		if (!('error' in result)) {
			startProcessingStream($selectedCorpus.id);
		}
	}

	async function handleDiscover() {
		if (!$selectedCorpus) return;
		const result = await triggerDiscovery($selectedCorpus.id);
		if (!('error' in result)) {
			startDiscoveryStream($selectedCorpus.id);
		}
	}

	function handleRemoveFile(filename: string) {
		files = files.filter((f) => f.filename !== filename);
	}

	onDestroy(() => {
		closeStream();
		closeDiscoveryStream();
		if (navTimer) clearTimeout(navTimer);
		if (discoveryNavTimer) clearTimeout(discoveryNavTimer);
	});
</script>

<div class="upload-layout">
	<CorpusSidebar />
	<div class="upload-main">
		{#if !$selectedCorpus}
			<div class="empty-state">
				<h2 class="empty-heading">No corpus selected</h2>
				<p class="empty-body">
					Create a new corpus or select an existing one from the sidebar.
				</p>
			</div>
		{:else if $processingStatus === 'complete'}
			<!-- Complete state: green progress, success message, discovery trigger -->
			<div class="upload-content">
				<ProgressDisplay
					progress={100}
					currentStage=""
					status="complete"
				/>
				<p class="success-text">
					Processing complete &mdash; {files.length} files processed, {$totalUnits} knowledge units extracted.
				</p>
				<DiscoverButton status={discoverStatus} onclick={handleDiscover} />
				{#if $discoveryStatus === 'processing' || $discoveryStatus === 'complete'}
					<DiscoveryProgress
						currentStage={$discoveryStage}
						progress={$discoveryProgress}
						status={$discoveryStatus}
					/>
					<ActivityLog entries={$discoveryLog} />
				{/if}
				{#if $discoveryStatus === 'complete'}
					<a href="/tasks" class="review-link" data-sveltekit-preload-data>Review Task Tree</a>
				{/if}
			</div>
		{:else if $processingStatus === 'processing'}
			<!-- Processing state: progress display replaces upload zone -->
			<div class="upload-content">
				<ProgressDisplay
					progress={$progressPct}
					currentStage={$currentStage}
					status="processing"
				/>
				<ActivityLog entries={$activityLog} expanded={activityExpanded} />
				{#if $sseState === 'reconnecting'}
					<p class="reconnecting-text">Connection lost. Reconnecting...</p>
				{/if}
				<ProcessButton onclick={handleProcess} disabled={true} status="processing" />
				<FileListView {files} />
			</div>
		{:else}
			<!-- Idle / Error state: upload zone, process button, file list -->
			<div class="upload-content">
				<UploadZone onfiles={handleFiles} disabled={uploading} />
				<ProcessButton
					onclick={handleProcess}
					disabled={files.length === 0 || uploading}
					status={$processingStatus}
				/>
				{#if $processingStatus === 'error' && $processingError}
					<p class="error-text">
						Processing failed. Check the activity log for details and retry.
					</p>
					<ActivityLog entries={$activityLog} expanded={true} />
				{/if}
				<FileListView {files} onremove={handleRemoveFile} />
			</div>
		{/if}

		<!-- Screen reader announcements -->
		<div aria-live="polite" class="sr-only">{statusAnnouncement}</div>
	</div>
</div>

<style>
	.upload-layout {
		display: flex;
		height: 100%;
	}

	.upload-main {
		flex: 1;
		padding: var(--md);
		overflow-y: auto;
	}

	.upload-content {
		display: flex;
		flex-direction: column;
		gap: var(--md);
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--sm);
	}

	.empty-heading {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.3px;
		color: var(--text);
	}

	.empty-body {
		font-size: 14px;
		color: var(--text-dim);
	}

	.success-text {
		font-size: 14px;
		color: var(--green);
		text-align: center;
		padding: var(--md) 0;
	}

	.error-text {
		font-size: 13px;
		color: var(--red);
	}

	.reconnecting-text {
		font-size: 11px;
		color: var(--orange);
	}

	.review-link {
		font-size: 14px;
		font-weight: 600;
		color: var(--accent);
		text-decoration: none;
		text-align: center;
		padding: var(--sm) 0;
	}

	.review-link:hover {
		text-decoration: underline;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
</style>
