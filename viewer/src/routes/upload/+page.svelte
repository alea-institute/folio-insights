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
		discoveryError,
		startDiscoveryStream,
		closeDiscoveryStream,
		resetDiscovery,
	} from '$lib/stores/discovery';
	import { uploadFiles, fetchCorpusFiles, triggerProcessing, triggerDiscovery } from '$lib/api/client';
	import type { CorpusFile } from '$lib/api/client';
	import type { JobStatus } from '$lib/stores/llmKey';

	import CorpusSidebar from '$lib/components/CorpusSidebar.svelte';
	import UploadZone from '$lib/components/UploadZone.svelte';
	import FileListView from '$lib/components/FileList.svelte';
	import LlmKeyField from '$lib/components/LlmKeyField.svelte';
	import PausedJobControls from '$lib/components/PausedJobControls.svelte';
	import ProcessButton from '$lib/components/ProcessButton.svelte';
	import ProgressDisplay from '$lib/components/ProgressDisplay.svelte';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import DiscoverButton from '$lib/components/DiscoverButton.svelte';
	import DiscoveryProgress from '$lib/components/DiscoveryProgress.svelte';

	let files = $state<Array<{ filename: string; size_bytes: number; format: string; status: string }>>([]);
	let uploading = $state(false);
	let submittingProcess = $state(false);
	let submittingDiscovery = $state(false);
	let active = true;
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
			return () => {
				if (navTimer) clearTimeout(navTimer);
			};
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
	let statusAnnouncement = $derived.by(() => {
		if ($discoveryStatus === 'needs_credentials') return 'Discovery paused: an LLM API key is needed to continue.';
		if ($discoveryStatus === 'budget_exhausted') return 'Discovery paused: the spending budget has been exhausted.';
		if ($discoveryStatus === 'error') return `Discovery failed. ${$discoveryError || 'Check the activity log for details.'}`;
		if ($processingStatus === 'needs_credentials') return 'Processing paused: an LLM API key is needed to continue.';
		if ($processingStatus === 'budget_exhausted') return 'Processing paused: the spending budget has been exhausted.';
		return (
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
	});

	// Derive discovery button status
	let discoverStatus = $derived<JobStatus | 'ready' | 'disabled'>(
		$discoveryStatus === 'complete'
			? 'complete'
			: $discoveryStatus !== 'idle'
				? $discoveryStatus
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
		if (!$selectedCorpus || submittingProcess) return;
		const corpusId = $selectedCorpus.id;
		submittingProcess = true;
		processingError.set(null);
		const result = await triggerProcessing(corpusId);
		submittingProcess = false;
		if (!active || $selectedCorpus?.id !== corpusId) return;
		if ('error' in result) {
			processingError.set(result.error);
			processingStatus.set('error');
		} else {
			startProcessingStream(corpusId);
		}
	}

	async function handleDiscover() {
		if (!$selectedCorpus || submittingDiscovery) return;
		const corpusId = $selectedCorpus.id;
		if (navTimer) clearTimeout(navTimer);
		submittingDiscovery = true;
		discoveryError.set(null);
		const result = await triggerDiscovery(corpusId);
		submittingDiscovery = false;
		if (!active || $selectedCorpus?.id !== corpusId) return;
		if ('error' in result) {
			discoveryError.set(result.error);
			discoveryStatus.set('error');
		} else {
			startDiscoveryStream(corpusId);
		}
	}

	function handleRemoveFile(filename: string) {
		files = files.filter((f) => f.filename !== filename);
	}

	onDestroy(() => {
		active = false;
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
				<LlmKeyField />
				<DiscoverButton status={discoverStatus} disabled={submittingDiscovery} onclick={handleDiscover} />
				{#if $discoveryStatus === 'needs_credentials' || $discoveryStatus === 'budget_exhausted'}
					{#key $selectedCorpus.id}
						<PausedJobControls
							corpusId={$selectedCorpus.id}
							kind="discovery"
							status={$discoveryStatus}
							reason={$discoveryError}
							oncontinue={() => { if ($selectedCorpus) startDiscoveryStream($selectedCorpus.id); }}
						/>
					{/key}
				{/if}
				{#if $discoveryStatus === 'error'}
					<div aria-live="polite">
						{#if $discoveryError}<p class="error-text">{$discoveryError}</p>{/if}
					</div>
				{/if}
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
				<LlmKeyField />
				<ProcessButton
					onclick={handleProcess}
					disabled={files.length === 0 || uploading || submittingProcess}
					status={$processingStatus}
				/>
				{#if $processingStatus === 'needs_credentials' || $processingStatus === 'budget_exhausted'}
					{#key $selectedCorpus.id}
						<PausedJobControls
							corpusId={$selectedCorpus.id}
							kind="processing"
							status={$processingStatus}
							reason={$processingError}
							oncontinue={() => { if ($selectedCorpus) startProcessingStream($selectedCorpus.id); }}
						/>
					{/key}
				{/if}
				<div aria-live="polite">
					{#if $processingStatus === 'error' && $processingError}
						<p class="error-text">{$processingError}</p>
					{/if}
				</div>
				{#if $processingStatus === 'error' && $processingError}
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
		overflow-wrap: anywhere;
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
