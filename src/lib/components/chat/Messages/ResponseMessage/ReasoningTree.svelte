<script lang="ts">
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	import {
		SvelteFlow,
		Background,
		BackgroundVariant,
		useNodesInitialized,
		useSvelteFlow,
		MarkerType
	} from '@xyflow/svelte';
	import type { Node, Edge } from '@xyflow/svelte';
	import dagre from 'dagre';

	import '@xyflow/svelte/dist/style.css';
	import { writable } from 'svelte/store';

	import ReasoningNode from './ReasoningTree/ReasoningNode.svelte';
	import {
		getErrorSolutions,
		type ErrorSolutionResponse,
		type TrainingMethod,
		type TestTimeMethod,
		type CitationInfo
	} from '$lib/apis/analysis';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let nodes: any[] = [];
	export let edges: any[] = [];
	export let sections: { section_num: number; text: string }[] = [];
	export let overthinkingAnalysis: {
		score: number;
		first_correct_answer_section: number | null;
		all_answer_sections: number[];
		total_sections: number;
	} | null = null;
	export let detectedErrors: any[] = [];
	export let level = 0;
	export let chatId: string = '';
	export let messageId: string = '';
	export let model: string = '';
	// Analysis stage indicator: 'pending' | 'layer1' | 'layer2' | 'error_detection' | 'complete'
	export let analysisStage: string = 'complete';
	$: void level;

	const flowNodes = writable<Node[]>([]);
	const flowEdges = writable<Edge[]>([]);
	// Force a vertical layout so connections run top-to-bottom.
	const layoutDirection: 'vertical' = 'vertical';
	let graphError: string | null = null;
	let lastFitSignature = '';
	let nodesReady = false;

	// Store expanded paths and their children
	let expandedPaths = new Map<string, any[]>();
	let loadingPaths = new Set<string>();

	// Performance optimization: cache and debounce
	let buildGraphTimer: ReturnType<typeof setTimeout> | null = null;
	let lastBuildSignature = '';
	let cachedGraphData: { nodes: any[]; edges: any[] } | null = null;
	// Compute root signature lazily to avoid expensive string operations on every reactive update
	let rootGraphSignature = '';
	const computeRootSignature = (nodeList: any[], edgeList: any[]) => {
		if (!nodeList?.length && !edgeList?.length) return '';
		const nodeIds = nodeList
			.slice(0, 50)
			.map((n: any) => n?.id ?? '')
			.join('|');
		const edgeKeys = edgeList
			.slice(0, 50)
			.map((e: any) => `${e?.from ?? e?.source ?? ''}->${e?.to ?? e?.target ?? ''}`)
			.join('|');
		return `${nodeIds}::${edgeKeys}::${nodeList.length}::${edgeList.length}`;
	};

	const nodeTypes = { reasoning: ReasoningNode };
	const MAX_GRAPH_NODES = 200; // Increased from 120
	const MAX_GRAPH_EDGES = 500; // Increased from 260
	const HIGHLIGHT_EDGE_COLOR = '#f59e0b';
	let hoveredNodeId: string | null = null;
	let baseEdges: Edge[] = [];
	let hoverListener: ((event: CustomEvent<{ nodeId: string | null }>) => void) | null = null;
	let highlightListener: ((event: CustomEvent<any>) => void) | null = null;
	let highlightedNodeId: string | null = null;

	// Performance: Throttle hover updates and cache results
	let hoverThrottleTimer: ReturnType<typeof setTimeout> | null = null;
	let lastHoveredNodeId: string | null = null;
	let cachedPathEdgeIds: Set<string> = new Set();
	const HOVER_THROTTLE_MS = 80; // 80ms throttle for smooth but performant hover

	// Performance: Edge lookup map for O(1) access
	let edgeLookupMap = new Map<string, Edge>();

	// Performance: Cache paths to avoid recomputation
	let pathCache = new Map<string, Set<string>>();

	const ACTION_COLORS: Record<string, string> = {
		Step: '#475569',
		Decomposition: '#6366f1',
		Derivation: '#8b5cf6',
		'Knowledge Recall': '#10b981',
		Calculation: '#0ea5e9',
		'Tool Call': '#f97316',
		Assumption: '#f59e0b',
		Validation: '#22c55e',
		Backtrack: '#ef4444',
		// Layer1 node type colors
		problem_decomposition: '#6366f1',
		reasoning_step: '#8b5cf6',
		check: '#22c55e', // Layer1 check node
		intermediate_answer: '#10b981',
		final_answer: '#f59e0b',
		// Layer2 meta-decision node type colors
		decomposition: '#6366f1', // Purple - breaking down problems
		calculation: '#0ea5e9', // Sky blue - math/derivation
		knowledge_recall: '#10b981', // Emerald - retrieving facts
		tool_use: '#f97316', // Orange - external tools
		assumption: '#f59e0b', // Amber - making hypotheses
		validation: '#22c55e', // Green - verification
		backtrack: '#ef4444', // Red - error correction
		conclusion: '#8b5cf6', // Violet - results
		// Legacy support
		problem_analysis: '#6366f1',
		solution_path: '#8b5cf6',
		verification: '#22c55e'
	};

	// Display labels for node types (used for UI rendering)
	const NODE_TYPE_LABELS: Record<string, string> = {
		// Layer1 node types
		problem_decomposition: 'Problem Decomposition',
		reasoning_step: 'Reasoning',
		check: 'Verification',
		intermediate_answer: 'Intermediate Answer',
		final_answer: 'Final Answer',
		// Layer2 meta-decision node types
		decomposition: 'Decomposition',
		calculation: 'Calculation',
		knowledge_recall: 'Knowledge Recall',
		tool_use: 'Tool Use',
		assumption: 'Assumption',
		validation: 'Validation',
		backtrack: 'Backtrack',
		conclusion: 'Conclusion',
		// Legacy support
		problem_analysis: 'Problem Analysis',
		solution_path: 'Solution Path',
		verification: 'Verification'
	};

	const ISSUE_CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
		// Error types aligned with dataset evaluation (7 types)
		// Overthinking - Purple theme (process issue)
		Overthinking: { bg: '#f5f3ff', text: '#6b21a8', border: '#ddd6fe' },

		// Safety - Orange/Red theme (critical)
		Safety: { bg: '#fff7ed', text: '#c2410c', border: '#fed7aa' },

		// Knowledge Error - Indigo theme (correctness)
		'Knowledge Error': { bg: '#eef2ff', text: '#4338ca', border: '#c7d2fe' },

		// Logical Error - Rose theme (correctness)
		'Logical Error': { bg: '#fff1f2', text: '#e11d48', border: '#fecdd3' },

		// Formal Error (Calculation) - Cyan theme (correctness)
		'Formal Error': { bg: '#ecfeff', text: '#0ea5e9', border: '#bae6fd' },

		// Hallucination - Teal theme (faithfulness)
		Hallucination: { bg: '#f0fdfa', text: '#0f766e', border: '#99f6e4' },

		// Readability - Gray theme (quality)
		Readability: { bg: '#f3f4f6', text: '#374151', border: '#e5e7eb' },

		// Legacy compatibility mappings
		'Calculation Error': { bg: '#ecfeff', text: '#0ea5e9', border: '#bae6fd' },
		'Formal Manipulation Error': { bg: '#ecfeff', text: '#0ea5e9', border: '#bae6fd' },
		'Safety Issue': { bg: '#fff7ed', text: '#c2410c', border: '#fed7aa' },
		'Faithfulness Issue': { bg: '#f0fdfa', text: '#0f766e', border: '#99f6e4' },
		'Format Error': { bg: '#f3f4f6', text: '#374151', border: '#e5e7eb' },
		'Ineffective Reflection': { bg: '#fef3c7', text: '#b45309', border: '#fde68a' },
		Redundancy: { bg: '#f5f3ff', text: '#6b21a8', border: '#ddd6fe' },
		'Incoherent Content': { bg: '#fef2f2', text: '#b91c1c', border: '#fecaca' }
	};

	const normaliseIssues = (list: any[] = []) =>
		(Array.isArray(list) ? list : [])
			.map((i: any) => ({
				type: i?.type ?? i?.category ?? i?.label ?? '',
				description: i?.description ?? i?.detail ?? i?.reason ?? '',
				severity: i?.severity ?? i?.level ?? '',
				section_numbers: i?.section_numbers ?? i?.sectionNumbers ?? []
			}))
			.filter(
				(i) =>
					(i.type ?? '').toString().trim() !== '' || (i.description ?? '').toString().trim() !== ''
			);

	type IssueEntry = {
		id: string;
		nodeId: string;
		parentNodeId?: string | null;
		type: string;
		description: string;
		severity?: string;
		nodeTitle: string;
		step?: number;
		action?: string;
		isLayer2?: boolean;
		sectionNumbers?: number[]; // Section numbers where the error occurs
	};

	let issueList: IssueEntry[] = [];
	let filteredIssues: IssueEntry[] = [];
	let issueTypeSummary: { type: string; count: number }[] = [];
	let activeIssueType: string | null = null;
	let selectedIssue: IssueEntry | null = null; // Currently selected issue for solution panel
	let expandedIssue: IssueEntry | null = null; // Issue expanded for full detail view
	let inlineExpandedIssueId: string | null = null; // Issue ID expanded inline within the card

	// Dynamic solutions from knowledge base
	let solutionsCache: Map<string, ErrorSolutionResponse> = new Map();
	let currentSolutions: ErrorSolutionResponse | null = null;
	let loadingSolutions: boolean = false;
	let solutionsError: string | null = null;

	let activeMethodTab: 'test_time' | 'training' = 'test_time'; // Tab for method type selection

	// Citation popover state
	let activeCitationPopover: string | null = null; // unique ID for the currently open popover

	/**
	 * Get the URL for a citation (prefer DOI, fallback to URL/arXiv)
	 */
	function getCitationUrl(citation: CitationInfo): string {
		if (citation.doi) {
			return `https://doi.org/${citation.doi}`;
		}
		if (citation.url) {
			return citation.url;
		}
		if (citation.eprint && citation.archiveprefix?.toLowerCase() === 'arxiv') {
			return `https://arxiv.org/abs/${citation.eprint}`;
		}
		return '';
	}

	/**
	 * Format venue name for display (shorten long venue names)
	 */
	function formatVenue(citation: CitationInfo): string {
		const venue = citation.venue;
		if (!venue) {
			if (citation.archiveprefix?.toLowerCase() === 'arxiv') return 'arXiv';
			return '';
		}
		// Common venue abbreviations
		const abbrevs: Record<string, string> = {
			'Proceedings of the AAAI Conference on Artificial Intelligence': 'AAAI',
			'Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing': 'EMNLP 2025',
			'Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing': 'EMNLP 2024',
			'Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing': 'EMNLP 2023',
			'Findings of the Association for Computational Linguistics: EMNLP 2023': 'Findings of EMNLP 2023',
			'Findings of the Association for Computational Linguistics: NAACL 2025': 'Findings of NAACL 2025',
			'Findings of the Association for Computational Linguistics: ACL 2025': 'Findings of ACL 2025',
			'Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)': 'ACL 2025',
			'Proceedings of the 48th International ACM SIGIR Conference on Research and Development in Information Retrieval': 'SIGIR 2025',
			'Proceedings of the 31st ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.2': 'KDD 2025'
		};
		return abbrevs[venue] || venue;
	}

	/**
	 * Toggle the citation details popover
	 */
	function toggleCitationPopover(methodName: string, citationIndex: number) {
		const id = `${methodName}-${citationIndex}`;
		activeCitationPopover = activeCitationPopover === id ? null : id;
	}

	// Fallback static solutions (used when API is unavailable)
	const FALLBACK_SOLUTIONS: Record<string, string[]> = {
		Safety: [
			'Remove or rephrase harmful content',
			'Add appropriate content warnings',
			'Redirect to safer alternatives',
			'Apply content filtering guidelines'
		],
		'Knowledge Error': [
			'Verify facts against reliable sources',
			'Cross-reference with authoritative databases',
			'Correct factual inaccuracies',
			'Add citations for claims'
		],
		'Logical Error': [
			'Review the logical chain of reasoning',
			'Check for contradictions with earlier statements',
			'Ensure conclusions follow from premises',
			'Validate cause-effect relationships'
		],
		'Formal Error': [
			'Recalculate using correct formulas',
			'Verify arithmetic step by step',
			'Use calculator for complex computations',
			'Double-check units and conversions'
		],
		Hallucination: [
			'Verify all claims against known facts',
			'Remove fabricated information',
			'Request source citations',
			'Cross-reference with reliable data'
		],
		Readability: [
			'Restructure for clarity',
			'Break down complex sentences',
			'Add transitional phrases',
			'Improve organization and flow'
		],
		Overthinking: [
			'Identify where the answer was first found',
			'Remove redundant verification steps',
			'Streamline the reasoning process',
			'Focus on essential reasoning only'
		]
	};

	// Fetch solutions from API
	const fetchSolutions = async (errorType: string): Promise<void> => {
		if (solutionsCache.has(errorType)) {
			currentSolutions = solutionsCache.get(errorType) ?? null;
			return;
		}

		loadingSolutions = true;
		solutionsError = null;

		try {
			const token = localStorage.token ?? '';
			const solutions = await getErrorSolutions(token, errorType);
			solutionsCache.set(errorType, solutions);
			currentSolutions = solutions;
		} catch (err: any) {
			console.error('Failed to fetch solutions:', err);
			solutionsError = typeof err === 'string' ? err : 'Failed to load solutions';
			// Use fallback
			currentSolutions = {
				error_type: errorType,
				found: false,
				quick_fixes: FALLBACK_SOLUTIONS[errorType] ?? ['Review and correct the identified issue'],
				test_time_methods: [],
				test_time_methods_by_category: {},
				test_time_categories: [],
				training_methods: [],
				training_methods_by_category: {},
				categories: [],
				evaluation_metrics: []
			};
		} finally {
			loadingSolutions = false;
		}
	};

	// Watch for selected issue changes
	$: if (selectedIssue) {
		fetchSolutions(selectedIssue.type);
	} else {
		currentSolutions = null;
	}

	// Generate solution suggestions based on issue type (fallback)
	const getSolutionSuggestions = (issue: IssueEntry | null): string[] => {
		if (!issue) return [];

		// Use cached solutions if available
		if (currentSolutions?.quick_fixes?.length) {
			return currentSolutions.quick_fixes;
		}

		// Fallback to static solutions
		return (
			FALLBACK_SOLUTIONS[issue.type] ?? [
				'Review and correct the identified issue',
				'Verify the reasoning logic',
				'Cross-check with source material'
			]
		);
	};

	// Get all test-time methods (no training required)
	const getTestTimeMethods = (): TestTimeMethod[] => {
		return currentSolutions?.test_time_methods ?? [];
	};

	// Get all training methods
	const getTrainingMethods = (): TrainingMethod[] => {
		return currentSolutions?.training_methods ?? [];
	};

	const buildIssueKey = (issue: IssueEntry) => {
		const norm = (v: string | undefined | null) => `${v ?? ''}`.trim().toLowerCase();
		return [
			norm(issue.nodeId),
			norm(issue.type),
			norm(issue.description),
			norm(issue.severity)
		].join('|');
	};

	const getIssueStyle = (type: string) => {
		return ISSUE_CATEGORY_STYLES[type] ?? { bg: '#f8fafc', text: '#0f172a', border: '#e2e8f0' };
	};

	// Build a map from node_id to detected errors for quick lookup
	const buildDetectedErrorsMap = (errors: any[]): Map<string, any[]> => {
		const map = new Map<string, any[]>();
		if (!Array.isArray(errors)) return map;

		errors.forEach((error) => {
			const nodeId = error?.details?.node_id;
			if (nodeId) {
				const existing = map.get(nodeId) ?? [];
				existing.push({
					type: error?.type ?? 'Issue',
					description: error?.description ?? '',
					severity: error?.severity ?? 'medium',
					section_numbers: error?.section_numbers ?? [],
					details: error?.details ?? {}
				});
				map.set(nodeId, existing);
			}
		});

		return map;
	};

	// Reactive map of detected errors by node_id
	$: detectedErrorsMap = buildDetectedErrorsMap(detectedErrors);

	const normaliseActionType = (action: any) => {
		const raw = `${action ?? ''}`.trim();
		if (!raw) {
			return { label: $i18n.t('Step'), key: 'Step' };
		}

		// Check if we have a predefined label for this node type
		if (NODE_TYPE_LABELS[raw]) {
			return { label: $i18n.t(NODE_TYPE_LABELS[raw]), key: raw };
		}

		// Fallback to parsing the raw string
		const segments = raw
			.split('/')
			.map((s) => s.trim())
			.filter(Boolean);
		const label = segments.length > 0 ? segments.join(' / ') : raw;
		const key = segments.at(-1) ?? raw;
		return { label, key };
	};

	// Debug logging disabled for production
	const logGraph = (_msg: string, _data: Record<string, unknown> = {}) => {
		// Uncomment for debugging: console.info(`[ReasoningTree] ${_msg}`, _data);
	};

	// Store for layer2 data from nodes (used for expansion)
	let layer2DataMap = new Map<string, any>(); // Changed to store full layer2 data including issues

	// Track which graph is currently rendered (layer 1 or a layer 2 sub-tree)
	let activeGraphLevel: 'layer1' | 'layer2' = 'layer1';
	let visibleNodes: any[] = nodes ?? [];
	let visibleEdges: any[] = edges ?? [];
	let layer2Context: { parentNodeId: string | null; title: string; refinementReason?: string } = {
		parentNodeId: null,
		title: '',
		refinementReason: ''
	};

	const buildLayer2Graph = (nodeId: string, nodeData: any) => {
		const stored = layer2DataMap.get(nodeId) ?? {};
		const treeFromNode =
			nodeData?.layer2TreeNodes || nodeData?.layer2TreeEdges
				? { nodes: nodeData?.layer2TreeNodes ?? [], edges: nodeData?.layer2TreeEdges ?? [] }
				: null;
		const rawTree = treeFromNode ?? stored?.tree ?? { nodes: [], edges: [] };
		const steps = nodeData?.layer2Steps ?? stored?.steps ?? [];
		const refinementReason = nodeData?.refinementReason ?? stored?.refinementReason ?? '';

		let baseNodes = Array.isArray(rawTree?.nodes) ? rawTree.nodes : [];
		let baseEdges = Array.isArray(rawTree?.edges) ? rawTree.edges : [];

		// Fallback: if no structured tree nodes, build a linear chain from steps
		if (!baseNodes.length && Array.isArray(steps) && steps.length > 0) {
			baseNodes = steps.map((step: any, idx: number) => ({
				id: `${step?.id ?? `${nodeId}-step-${idx + 1}`}`,
				type: step?.action_type ?? step?.type ?? 'reasoning_step',
				label: step?.label ?? step?.summary ?? `Step ${idx + 1}`,
				description: step?.summary ?? step?.content_snippet ?? '',
				content: step?.content_snippet ?? step?.summary ?? '',
				action_type: step?.action_type ?? 'Step',
				content_snippet: step?.content_snippet ?? '',
				subsection_start: step?.subsection_start ?? null,
				subsection_end: step?.subsection_end ?? null,
				parentNodeId: nodeId,
				isLayer2Child: true,
				issues: normaliseIssues(step?.issues ?? []),
				has_layer2: false,
				canBeRefined: false,
				isClickable: false
			}));

			baseEdges =
				steps.length > 1
					? steps.slice(0, -1).map((_: any, idx: number) => ({
							from: `${steps[idx]?.id ?? `${nodeId}-step-${idx + 1}`}`,
							to: `${steps[idx + 1]?.id ?? `${nodeId}-step-${idx + 2}`}`,
							type: 'reasoning'
						}))
					: [];
		}

		const convertedNodes = baseNodes.map((step: any, idx: number) => {
			const normalizedIssues = normaliseIssues(step?.issues ?? []);
			const label = step?.label ?? step?.summary ?? step?.description ?? `Step ${idx + 1}`;
			return {
				...step,
				id: `${step?.id ?? `${nodeId}-tree-${idx + 1}`}`,
				type: step?.type ?? step?.action_type ?? 'reasoning_step',
				label,
				title: label,
				description: step?.description ?? step?.summary ?? '',
				content: step?.content ?? step?.summary ?? step?.description ?? '',
				detail: step?.detail ?? step?.description ?? step?.summary ?? '',
				action_type: step?.action_type ?? step?.type ?? 'Step',
				section_start: step?.section_start ?? step?.subsection_start ?? step?.start ?? null,
				section_end: step?.section_end ?? step?.subsection_end ?? step?.end ?? null,
				subsection_start: step?.subsection_start ?? null,
				subsection_end: step?.subsection_end ?? null,
				content_snippet: step?.content_snippet ?? step?.snippet ?? '',
				segment_text: step?.segment_text ?? step?.content_snippet ?? '',
				isLayer2Child: true,
				parentNodeId: nodeId,
				canBeRefined: false,
				hasLayer2: false,
				isClickable: normalizedIssues.length > 0,
				issues: normalizedIssues,
				layer2: null,
				layer2Steps: [],
				layer2TreeNodes: [],
				layer2TreeEdges: []
			};
		});

		let convertedEdges = (baseEdges ?? [])
			.map((edge: any, idx: number) => ({
				from: `${edge?.from ?? edge?.source ?? ''}`,
				to: `${edge?.to ?? edge?.target ?? ''}`,
				type: edge?.type ?? edge?.edge_type ?? 'reasoning',
				label: edge?.label ?? edge?.edge_label ?? '',
				id: `${edge?.from ?? edge?.source ?? 'from'}-${edge?.to ?? edge?.target ?? 'to'}-${idx}`
			}))
			.filter((edge) => edge.from && edge.to);

		if (!convertedEdges.length && convertedNodes.length > 1) {
			convertedEdges = convertedNodes.slice(0, -1).map((node, idx) => ({
				from: node.id,
				to: convertedNodes[idx + 1].id,
				type: 'reasoning'
			}));
		}

		return { nodes: convertedNodes, edges: convertedEdges, refinementReason };
	};

	const switchToLayer2View = (nodeId: string, nodeData: any) => {
		const graph = buildLayer2Graph(nodeId, nodeData);
		if (!graph.nodes || graph.nodes.length === 0) {
			return false;
		}

		activeGraphLevel = 'layer2';
		layer2Context = {
			parentNodeId: nodeId,
			title: nodeData?.title ?? nodeData?.label ?? $i18n.t('Node Detail'),
			refinementReason: graph.refinementReason ?? ''
		};
		visibleNodes = graph.nodes;
		visibleEdges = graph.edges;
		expandedPaths.clear();
		loadingPaths.clear();
		selectedNode = null;
		viewMode = 'tree';
		highlightedNodeId = null;
		setHoveredNode(null);
		lastBuildSignature = '';
		cachedGraphData = null;
		return true;
	};

	const resetToLayer1View = () => {
		activeGraphLevel = 'layer1';
		layer2Context = { parentNodeId: null, title: '', refinementReason: '' };
		visibleNodes = nodes ?? [];
		visibleEdges = edges ?? [];
		expandedPaths.clear();
		loadingPaths.clear();
		selectedNode = null;
		viewMode = 'tree';
		highlightedNodeId = null;
		setHoveredNode(null);
		lastBuildSignature = '';
		cachedGraphData = null;
		pathCache.clear();
	};

	// Handle node click - different behavior based on node type and refinability
	const handleNodeClick = async (nodeId: string, nodeData: any) => {
		if (!nodeId) return;

		const isLayer2Node = nodeId.includes('-step-') || nodeData?.isLayer2Child; // Layer 2 nodes have this pattern or explicit flag

		if (isLayer2Node) {
			// Layer 2 node: Show error detection for this specific step
			const parentNodeId = nodeData?.parentNodeId ?? nodeId.split('-step-')[0];
			const parentLayer2 = parentNodeId ? layer2DataMap.get(parentNodeId) : null;
			const issues =
				Array.isArray(nodeData?.issues) && nodeData.issues.length > 0
					? nodeData.issues
					: (parentLayer2?.issues ?? []);

			// Show detail view with issues for this specific step
			selectedNode = {
				nodeId,
				title: nodeData?.title ?? nodeData?.label ?? 'Step Detail',
				content: nodeData?.content ?? nodeData?.description ?? '',
				detail: nodeData?.detail ?? '',
				action: nodeData?.action ?? nodeData?.action_type ?? 'Step',
				step: nodeData?.step,
				issues: issues, // Show parent node's issues
				substeps: [],
				hasError: issues.length > 0,
				errorDescription: null,
				reasoningExcerpt: nodeData?.content_snippet ?? nodeData?.highlightText ?? '',
				segmentText: nodeData?.segment_text ?? nodeData?.content_snippet ?? '',
				isLayer2Node: true
			};
			viewMode = 'detail';
			return;
		}

		// Layer 1 node: Check if it can be refined
		const hasLayer2Steps = Boolean(nodeData?.layer2Steps && nodeData.layer2Steps.length > 0);
		const hasLayer2Tree = Boolean(nodeData?.layer2TreeNodes && nodeData.layer2TreeNodes.length > 0);
		const canBeRefined =
			nodeData?.canBeRefined ??
			nodeData?.can_be_refined ??
			(hasLayer2Steps || hasLayer2Tree || nodeData?.hasLayer2);
		const fallbackIssues = nodeData?.issues ?? nodeData?.layer2Issues ?? [];

		if (canBeRefined) {
			// Prefer rendering a full layer 2 graph
			const switched = switchToLayer2View(nodeId, nodeData);
			if (switched) {
				return;
			}

			// Fallback to inline expansion if graph data is unavailable
			if (!expandedPaths.has(nodeId)) {
				handleExpandNode(nodeId, nodeData?.layer2Steps, nodeData);
				return;
			}
		}

		// Cannot be refined OR fallback: Show error detection results
		const issues = fallbackIssues;
		selectedNode = {
			nodeId,
			title: nodeData?.title ?? nodeData?.label ?? 'Node Detail',
			content: nodeData?.content ?? nodeData?.description ?? '',
			detail: nodeData?.detail ?? '',
			action: nodeData?.action ?? 'Step',
			step: nodeData?.step,
			issues: issues,
			substeps: nodeData?.substeps ?? [],
			hasError: issues.length > 0 || nodeData?.hasError,
			errorDescription: nodeData?.errorDescription ?? null,
			reasoningExcerpt: nodeData?.reasoningExcerpt ?? nodeData?.highlightText ?? '',
			segmentText: nodeData?.segment_text ?? nodeData?.content_snippet ?? '',
			isLayer2Node: false
		};
		viewMode = 'detail';
	};

	const handleExpandNode = async (nodeId: string, layer2Steps?: any[], nodeData?: any) => {
		if (!nodeId || loadingPaths.has(nodeId) || expandedPaths.has(nodeId)) {
			return;
		}

		logGraph('handleExpandNode:start', { nodeId, hasLayer2Steps: !!layer2Steps });

		// If layer2Steps are provided directly (from node data), use them
		if (layer2Steps && layer2Steps.length > 0) {
			// Store the full layer2 data including issues for later access
			if (nodeData?.layer2Issues || nodeData?.issues) {
				layer2DataMap.set(nodeId, {
					steps: layer2Steps,
					issues: nodeData?.layer2Issues ?? nodeData?.issues ?? [],
					tree: {
						nodes: nodeData?.layer2TreeNodes ?? [],
						edges: nodeData?.layer2TreeEdges ?? []
					},
					refinementReason: nodeData?.refinementReason ?? ''
				});
			}

			// Convert layer2 steps to child nodes format for graph display
			const childNodes = layer2Steps.map((step: any, idx: number) => ({
				id: `${nodeId}-step-${idx + 1}`,
				type: step?.action_type ?? 'step',
				label: step?.label ?? step?.summary ?? `Step ${idx + 1}`,
				description: step?.summary ?? step?.content_snippet ?? '',
				content: step?.content_snippet ?? step?.summary ?? '',
				action_type: step?.action_type ?? 'Step',
				content_snippet: step?.content_snippet ?? '',
				subsection_start: step?.subsection_start ?? null,
				subsection_end: step?.subsection_end ?? null,
				parentNodeId: nodeId,
				// Layer 2 nodes show error detection on click, not further expansion
				layer2: null,
				has_layer2: false,
				canBeRefined: false,
				isLayer2Child: true
			}));

			// Store the expanded children
			expandedPaths.set(nodeId, childNodes);
			expandedPaths = expandedPaths; // Trigger reactivity

			logGraph('handleExpandNode:success using layer2 data', {
				nodeId,
				stepsCount: childNodes.length
			});

			// Rebuild the graph with the new children (debounced for better performance)
			if (buildGraphTimer) {
				clearTimeout(buildGraphTimer);
			}
			buildGraphTimer = setTimeout(() => {
				requestAnimationFrame(() => {
					buildGraph(visibleNodes, visibleEdges, layoutDirection);
					buildGraphTimer = null;
				});
			}, 100);
			return;
		}

		// Fallback: Check if we have stored layer2 data for this node
		const storedLayer2 = layer2DataMap.get(nodeId);
		if (storedLayer2 && Array.isArray(storedLayer2.steps) && storedLayer2.steps.length > 0) {
			handleExpandNode(nodeId, storedLayer2.steps);
			return;
		}

		// If no layer2 data available, show message
		alert('This node does not have detailed Layer 2 analysis data.');
	};

	// Build reverse adjacency map for path tracing (child -> parents)
	let reverseAdjacency = new Map<string, string[]>();

	// Find all paths from root nodes to a target node using BFS backwards
	const findPathsToNode = (targetNodeId: string): Set<string> => {
		if (!targetNodeId || !reverseAdjacency.size) return new Set<string>();

		// Check cache first
		const cached = pathCache.get(targetNodeId);
		if (cached) {
			return cached;
		}

		const pathEdgeIds = new Set<string>();

		// BFS backwards from target to find all ancestor edges
		const visited = new Set<string>();
		const queue: string[] = [targetNodeId];
		const maxDepth = 100; // Prevent infinite loops in malformed graphs
		let depth = 0;

		while (queue.length > 0 && depth < maxDepth) {
			const batchSize = queue.length;

			// Process current level in batch
			for (let i = 0; i < batchSize; i++) {
				const currentNode = queue.shift()!;
				if (visited.has(currentNode)) continue;
				visited.add(currentNode);

				const parents = reverseAdjacency.get(currentNode);
				if (!parents || parents.length === 0) continue;

				for (const parentId of parents) {
					// Use edge lookup map for O(1) access instead of find()
					const edgeKey = `${parentId}->${currentNode}`;
					const edge = edgeLookupMap.get(edgeKey);
					if (edge?.id) {
						pathEdgeIds.add(edge.id);
					}
					if (!visited.has(parentId)) {
						queue.push(parentId);
					}
				}
			}

			depth++;
		}

		// Cache the result
		pathCache.set(targetNodeId, pathEdgeIds);

		return pathEdgeIds;
	};

	// Optimized: Only update path edges; non-path edges reuse base references.
	const applyEdgeHighlights = (nodeId: string | null, pathEdgeIds?: Set<string>) => {
		if (!baseEdges.length) return [];

		// No highlight: return base edges directly (no cloning needed)
		if (!nodeId) {
			return baseEdges;
		}

		// Use cached pathEdgeIds if provided, otherwise compute
		const pathIds = pathEdgeIds ?? findPathsToNode(nodeId);

		// Modify only path edges; non-path edges stay as base references
		const highlightEdges = baseEdges.map((edge) => {
			if (!pathIds.has(edge.id)) {
				return edge;
			}

			const style = edge.style ?? {};
			const baseClass = edge.className ?? '';
			const className = baseClass.includes('flow-path-edge')
				? baseClass
				: `${baseClass} flow-path-edge`.trim();

			return {
				...edge,
				animated: true, // Enable built-in animation for flow effect
				className,
				style: {
					...style,
					stroke: HIGHLIGHT_EDGE_COLOR,
					strokeWidth: (style.strokeWidth ?? 6) + 2 // Make path edges thicker
				},
				markerEnd: edge.markerEnd
					? { ...edge.markerEnd, color: HIGHLIGHT_EDGE_COLOR }
					: edge.markerEnd
			};
		});

		return highlightEdges;
	};

	const setHoveredNode = (nodeId: string | null) => {
		// Skip if same node (avoid redundant updates)
		if (nodeId === lastHoveredNodeId) {
			return;
		}

		// Clear existing throttle timer
		if (hoverThrottleTimer) {
			clearTimeout(hoverThrottleTimer);
			hoverThrottleTimer = null;
		}

		// Immediate visual feedback by updating hoveredNodeId
		hoveredNodeId = nodeId;
		lastHoveredNodeId = nodeId;

		// Throttle the expensive path finding and edge updates
		hoverThrottleTimer = setTimeout(() => {
			// Use requestAnimationFrame to defer work to next frame
			requestAnimationFrame(() => {
				if (nodeId) {
					// Check if we already have cached path for this node
					if (cachedPathEdgeIds.size === 0 || hoveredNodeId === nodeId) {
						cachedPathEdgeIds = findPathsToNode(nodeId);
						flowEdges.set(applyEdgeHighlights(nodeId, cachedPathEdgeIds));
					}
				} else {
					// Clear cache when no node is hovered
					cachedPathEdgeIds.clear();
					flowEdges.set(applyEdgeHighlights(null));
				}

				hoverThrottleTimer = null;
			});
		}, HOVER_THROTTLE_MS);
	};

	const applyIssueHighlight = (nodeId: string | null) => {
		flowNodes.update((nodes) => {
			let changed = false;
			const nextNodes = nodes.map((node) => {
				const isTarget = Boolean(nodeId && node.id === nodeId);
				const current = Boolean(node?.data?.isIssueTarget);
				if (current === isTarget) {
					return node;
				}

				changed = true;
				return {
					...node,
					data: { ...(node.data ?? {}), isIssueTarget: isTarget }
				};
			});

			return changed ? nextNodes : nodes;
		});
	};

	const toggleIssueType = (type: string) => {
		activeIssueType = activeIssueType === type ? null : type;
	};

	const normaliseNode = (node: any, fallbackId: string) => {
		const nodeId = `${node?.id ?? fallbackId}`;
		const substeps = Array.isArray(node?.substeps)
			? node.substeps.map((step: any) => ({
					text: step?.text ?? '',
					is_error: Boolean(step?.is_error),
					note: step?.note ?? null
				}))
			: [];

		const evidence = Array.isArray(node?.evidence)
			? node.evidence.filter(Boolean).map((e: any) => `${e}`)
			: [];

		const layer2Data = node?.layer2 ?? null;
		const issues = normaliseIssues(node?.issues ?? []);
		const layer2Issues = normaliseIssues(layer2Data?.issues ?? []);

		// Merge detected errors from error detection result
		const detectedIssues = normaliseIssues(detectedErrorsMap.get(nodeId) ?? []);

		const combinedIssues = [...issues, ...layer2Issues, ...detectedIssues];
		const layer2Tree = layer2Data?.tree ?? null;
		const layer2TreeNodes = Array.isArray(layer2Tree?.nodes) ? layer2Tree.nodes : [];
		const layer2TreeEdges = Array.isArray(layer2Tree?.edges) ? layer2Tree.edges : [];
		const hasLayer2Tree = layer2TreeNodes.length > 0;
		const hasLayer2Steps = Array.isArray(layer2Data?.steps) && layer2Data.steps.length > 0;

		const reasoningExcerpt =
			node?.segment_text ?? // Use the actual extracted segment from backend
			node?.section_text ?? // Use section_text if available
			node?.reasoning_excerpt ?? // Fallback to old field for compatibility
			node?.reasoningSpan ??
			node?.source_excerpt ??
			node?.highlightText ??
			node?.description ??
			node?.detail ??
			node?.content ??
			'';

		const { label: actionLabel, key: actionKey } = normaliseActionType(
			node?.action_type ?? node?.actionType ?? node?.type
		);

		const nodeType = node?.type ?? '';
		const sectionStart = node?.section_start ?? node?.subsection_start ?? null;
		const sectionEnd = node?.section_end ?? node?.subsection_end ?? null;

		// Check if node has Layer 2 data (fine-grained steps)
		const hasLayer2 = Boolean(layer2Data && (hasLayer2Steps || hasLayer2Tree));

		// Check if node can be refined (from backend analysis)
		const canBeRefined = node?.can_be_refined ?? layer2Data?.can_be_refined ?? hasLayer2;

		// Node is clickable if it can be refined (to expand) or has issues (to show error detection)
		const hasIssues = combinedIssues.length > 0;
		const isClickable = canBeRefined || hasIssues || hasLayer2;

		return {
			id: nodeId,
			label: node?.label ?? node?.summary ?? $i18n.t('Step'),
			content: node?.content ?? node?.summary ?? node?.detail ?? '',
			detail: node?.detail ?? node?.content ?? '',
			segment_text: node?.segment_text ?? node?.section_text ?? node?.subsection_text ?? '',
			evidence,
			issues: combinedIssues,
			reasoning_excerpt: reasoningExcerpt,
			reasoningExcerpt: reasoningExcerpt,
			highlight_text: reasoningExcerpt,
			section_start: sectionStart,
			section_end: sectionEnd,
			hasError: Boolean(node?.hasError ?? node?.has_error),
			errorDescription: node?.errorDescription ?? null,
			action_type: actionLabel,
			action_key: actionKey,
			dependencies: Array.isArray(node?.dependencies)
				? node.dependencies.map((d: any) => `${d}`)
				: [],
			substeps,
			edgeType: node?.edgeType ?? 'normal',
			children: Array.isArray(node?.children) ? node.children : [],
			nodeType: nodeType,
			// New fields for click behavior
			canBeRefined: canBeRefined,
			hasLayer2: hasLayer2,
			isClickable: isClickable,
			layer2Steps: layer2Data?.steps ?? [],
			layer2TreeNodes,
			layer2TreeEdges,
			layer2Issues,
			layer2Subsections: layer2Data?.subsections ?? [],
			refinementReason: layer2Data?.refinement_reason ?? '',
			isExpanded: expandedPaths.has(nodeId),
			isLoading: loadingPaths.has(nodeId),
			// For Layer 2 child nodes
			isLayer2Child: node?.isLayer2Child ?? false,
			parentNodeId: node?.parentNodeId ?? null,
			content_snippet: node?.content_snippet ?? ''
		};
	};

	const buildGraph = (
		inputNodes: any[] = [],
		inputEdges: any[] = [],
		direction: 'vertical' | 'horizontal' = layoutDirection
	) => {
		// Performance: Check if we need to rebuild using a lightweight signature
		// Only sample a subset of nodes for the hash to avoid O(n) string operations
		const nodesSample =
			inputNodes.length > 20
				? [
						inputNodes[0],
						inputNodes[Math.floor(inputNodes.length / 2)],
						inputNodes[inputNodes.length - 1]
					]
				: inputNodes;
		const nodesHash = `${inputNodes.length}:${nodesSample.map((n) => n?.id ?? '').join(',')}`;
		const contextKey = `${activeGraphLevel}:${layer2Context.parentNodeId ?? 'root'}`;
		const buildSignature = `${contextKey}:${direction}:${nodesHash}:${inputEdges?.length ?? 0}:${expandedPaths.size}`;
		if (buildSignature === lastBuildSignature && cachedGraphData) {
			logGraph('buildGraph:cache-hit', { signature: buildSignature });
			return;
		}

		// Clear reverse adjacency for fresh build
		reverseAdjacency.clear();

		// Performance monitoring
		const startTime = performance.now();

		graphError = null;
		logGraph('buildGraph:start', {
			nodes: inputNodes?.length ?? 0,
			edges: inputEdges?.length ?? 0,
			direction,
			expandedPaths: expandedPaths.size,
			signature: buildSignature
		});

		try {
			if (
				(inputNodes?.length ?? 0) > MAX_GRAPH_NODES ||
				(inputEdges?.length ?? 0) > MAX_GRAPH_EDGES
			) {
				const nodeCount = inputNodes?.length ?? 0;
				const edgeCount = inputEdges?.length ?? 0;
				graphError = `${$i18n.t('Analysis graph is too large to render')}: ${nodeCount} ${$i18n.t('nodes')} (${$i18n.t('max')} ${MAX_GRAPH_NODES}), ${edgeCount} ${$i18n.t('edges')} (${$i18n.t('max')} ${MAX_GRAPH_EDGES})`;
				flowNodes.set([]);
				flowEdges.set([]);
				lastBuildSignature = '';
				cachedGraphData = null;
				return;
			}

			const nodesMap = new Map<string, any>();
			const derivedEdges: { from: string; to: string; type?: string }[] = [];

			const ingestHierarchical = (
				list: any[] = [],
				parentId: string | null = null,
				prefix = 'n'
			) => {
				list.forEach((item, idx) => {
					const id = `${item?.id ?? `${prefix}-${idx + 1}`}`;
					const normalised = normaliseNode(item, id);
					nodesMap.set(id, normalised);

					if (parentId) {
						derivedEdges.push({ from: parentId, to: id, type: item?.edgeType ?? 'normal' });
					}

					// If this node is expanded, inject its children from expandedPaths
					if (expandedPaths.has(id)) {
						const expandedChildren = expandedPaths.get(id) || [];
						if (expandedChildren.length > 0) {
							ingestHierarchical(expandedChildren, id, `${id}-exp`);
						}
					} else if (normalised.children.length > 0) {
						ingestHierarchical(normalised.children, id, `${id}-${idx + 1}`);
					}
				});
			};

			const hasNestedChildren = inputNodes.some(
				(node) => Array.isArray(node?.children) && node.children.length > 0
			);

			if (hasNestedChildren) {
				ingestHierarchical(inputNodes);
			} else {
				inputNodes.forEach((item, idx) => {
					const id = `${item?.id ?? idx + 1}`;
					const normalised = normaliseNode(item, id);
					nodesMap.set(id, normalised);
				});

				if (inputEdges?.length) {
					inputEdges.forEach((edge) => {
						const from = `${edge?.from ?? edge?.source ?? ''}`;
						const to = `${edge?.to ?? edge?.target ?? ''}`;
						if (nodesMap.has(from) && nodesMap.has(to)) {
							derivedEdges.push({ from, to, type: edge?.type ?? 'normal' });
						}
					});
				}

				// Always add dependency edges to avoid missing branches when the API omits edges.
				nodesMap.forEach((node) => {
					node.dependencies.forEach((dep: string) => {
						if (nodesMap.has(dep)) {
							derivedEdges.push({ from: dep, to: node.id, type: 'normal' });
						}
					});
				});
			}

			if (nodesMap.size > MAX_GRAPH_NODES || derivedEdges.length > MAX_GRAPH_EDGES) {
				graphError = $i18n.t('Analysis graph is too large to render');
				flowNodes.set([]);
				flowEdges.set([]);
				return;
			}
			if (nodesMap.size === 0) {
				flowNodes.set([]);
				flowEdges.set([]);
				return;
			}

			// Deduplicate edges and preserve order.
			const seenEdge = new Set<string>();
			const cleanedEdges = derivedEdges.filter((edge) => {
				const key = `${edge.from}->${edge.to}`;
				if (seenEdge.has(key)) return false;
				seenEdge.add(key);
				return true;
			});

			const adjacency = new Map<string, string[]>();
			const incoming = new Map<string, number>();
			const levelMap = new Map<number, string[]>();

			nodesMap.forEach((_, key) => {
				incoming.set(key, 0);
			});

			cleanedEdges.forEach(({ from, to }) => {
				const children = adjacency.get(from) ?? [];
				children.push(to);
				adjacency.set(from, children);
				if (incoming.has(to)) {
					incoming.set(to, (incoming.get(to) ?? 0) + 1);
				}

				// Build reverse adjacency for path tracing (child -> parents)
				const parents = reverseAdjacency.get(to) ?? [];
				parents.push(from);
				reverseAdjacency.set(to, parents);
			});

			let roots = Array.from(incoming.entries())
				.filter(([, count]) => count === 0)
				.map(([id]) => id);
			if (roots.length === 0 && nodesMap.size > 0) {
				roots = [Array.from(nodesMap.keys())[0]];
			}

			logGraph('buildGraph:structure', {
				nodes: nodesMap.size,
				edges: cleanedEdges.length,
				roots: roots.length
			});

			const edgeStyles: Record<
				string,
				{ stroke: string; dash?: string; animated?: boolean; label?: string }
			> = {
				// New simplified edge types (v3.0)
				reasoning: { stroke: '#94a3b8', label: '' }, // Normal forward flow - solid gray
				check: { stroke: '#22c55e', dash: '3 3', animated: true, label: 'check' }, // Verification - green dashed
				backtracking: { stroke: '#ef4444', dash: '6 3', animated: true, label: 'backtrack' }, // Path switch - red dashed

				// Legacy edge types (for backward compatibility)
				normal: { stroke: '#94a3b8' },
				branch: { stroke: '#3b82f6', dash: '2 2', label: 'branch' },
				produces: { stroke: '#8b5cf6', label: 'produces' },
				verify: { stroke: '#22c55e', dash: '3 3', animated: true, label: 'verify' },
				trigger: { stroke: '#f59e0b', animated: true, label: 'trigger' },
				backtrack_link: { stroke: '#ef4444', dash: '6 3', animated: true, label: 'backtrack' },
				merge: { stroke: '#06b6d4', label: 'merge' },
				backtrack: { stroke: '#ef4444', dash: '6 3', animated: true, label: 'backtrack' },
				validation: { stroke: '#22c55e', dash: '3 3', animated: true, label: 'check' }
			};

			// Compute depth and level counts for layout spacing.
			// Optimized: Use iterative BFS instead of recursion to avoid stack overflow
			// Use dagre for layout
			const g = new dagre.graphlib.Graph();
			// Slightly tighter layout to keep nodes closer together
			g.setGraph({ rankdir: direction === 'vertical' ? 'TB' : 'LR', nodesep: 20, ranksep: 36 });
			g.setDefaultEdgeLabel(() => ({}));

			nodesMap.forEach((_, id) => {
				g.setNode(id, { width: 280, height: 150 });
			});

			cleanedEdges.forEach(({ from, to }) => {
				g.setEdge(from, to);
			});

			dagre.layout(g);

			const nextNodes: Node[] = [];
			const nextEdges: Edge[] = [];

			// Convert Map keys to array to have an index
			const nodeIds = Array.from(nodesMap.keys());

			nodeIds.forEach((nodeId, idx) => {
				const node = nodesMap.get(nodeId);
				if (!node) return;

				const pos = g.node(nodeId);
				// If node is not in graph (should not happen), skip or default
				if (!pos) return;

				const x = pos.x - 140;
				const y = pos.y - 75;

				// Store layer2 data (including steps and issues) in map for later access
				if (node.hasLayer2 || node.layer2Issues?.length > 0) {
					layer2DataMap.set(nodeId, {
						steps: node.layer2Steps ?? [],
						issues: node.layer2Issues ?? [],
						subsections: node.layer2Subsections ?? [],
						refinementReason: node.refinementReason ?? '',
						tree: {
							nodes: node.layer2TreeNodes ?? [],
							edges: node.layer2TreeEdges ?? []
						}
					});
				}

				nextNodes.push({
					id: nodeId,
					type: 'reasoning',
					position: { x, y },
					data: {
						nodeId,
						step: idx + 1,
						title: node.label ?? $i18n.t('Step'),
						content: node.content ?? '',
						detail: node.detail ?? '',
						highlightText:
							node.reasoning_excerpt ??
							node.highlight_text ??
							node.detail ??
							node.content ??
							node.label ??
							'',
						segment_text: node.segment_text ?? '',
						section_start: node.section_start ?? null,
						section_end: node.section_end ?? null,
						issues: node.issues ?? [],
						evidence: node.evidence ?? [],
						substeps: node.substeps ?? [],
						hasError: Boolean(node.hasError),
						errorDescription: node.errorDescription,
						reasoningExcerpt: node.reasoning_excerpt ?? node.highlight_text ?? '',
						dependencies: node.dependencies ?? [],
						action: node.action_type ?? 'Step',
						actionColor:
							ACTION_COLORS[node.action_key] ?? ACTION_COLORS[node.action_type] ?? '#475569',
						layoutDirection: direction,
						// New fields for click-based interaction
						canBeRefined: node.canBeRefined ?? false,
						hasLayer2: node.hasLayer2 ?? false,
						isClickable: node.isClickable ?? false,
						layer2Steps: node.layer2Steps ?? [],
						layer2Issues: node.layer2Issues ?? [],
						isExpanded: node.isExpanded ?? false,
						isLoading: node.isLoading ?? false,
						// For Layer 2 child nodes
						isLayer2Child: node.isLayer2Child ?? false,
						parentNodeId: node.parentNodeId ?? null,
						content_snippet: node.content_snippet ?? '',
						// Click handler - removed button, now handled by node click
						onNodeClick: (data: any) => handleNodeClick(nodeId, data)
					}
				});
			});

			cleanedEdges.forEach((edge, idx) => {
				const style = edgeStyles[edge?.type ?? 'normal'] ?? edgeStyles.normal;
				nextEdges.push({
					id: `${edge.from}-${edge.to}-${idx}`,
					source: edge.from,
					target: edge.to,
					type: 'straight',
					animated: Boolean(style.animated),
					label: style.label,
					markerEnd: {
						type: MarkerType.ArrowClosed,
						color: style.stroke,
						width: 28,
						height: 22
					},
					style: {
						stroke: style.stroke,
						strokeWidth: 6, // Thicker edges for better visibility
						strokeDasharray: style.dash
					}
				});
			});

			flowNodes.set(nextNodes);
			// Store base edges and update flowEdges
			baseEdges = nextEdges;

			// Build edge lookup map for O(1) access in hover operations
			edgeLookupMap.clear();
			for (const edge of nextEdges) {
				const key = `${edge.source}->${edge.target}`;
				edgeLookupMap.set(key, edge);
			}

			// Reset hover state to ensure edges are in default state
			hoveredNodeId = null;
			lastHoveredNodeId = null;
			cachedPathEdgeIds.clear();
			pathCache.clear(); // Clear path cache when graph changes
			// Apply edge highlights (will use default state since hoveredNodeId is null)
			flowEdges.set(applyEdgeHighlights(null));

			// Update cache
			lastBuildSignature = buildSignature;
			cachedGraphData = { nodes: inputNodes, edges: inputEdges };

			// Performance monitoring
			const endTime = performance.now();
			const buildTime = endTime - startTime;
			logGraph('buildGraph:complete', {
				buildTime: `${buildTime.toFixed(2)}ms`,
				nodes: nextNodes.length,
				edges: nextEdges.length
			});

			// Performance warning disabled for production
		} catch (err) {
			console.error('Failed to build analysis graph', err);
			graphError = $i18n.t('Analysis graph failed to render');
			flowNodes.set([]);
			flowEdges.set([]);
			lastBuildSignature = '';
			cachedGraphData = null;
		}
	};

	// Keep visible graph in sync with incoming props when on Layer 1
	$: if (activeGraphLevel === 'layer1') {
		visibleNodes = nodes ?? [];
		visibleEdges = edges ?? [];
	}

	// Force rebuild when detectedErrors change (to merge errors into nodes)
	$: if (detectedErrors?.length > 0) {
		lastBuildSignature = ''; // Invalidate cache to force rebuild
		cachedGraphData = null;
	}

	// Reset to Layer 1 view when a new root graph arrives
	$: {
		const nextRootSignature = computeRootSignature(nodes ?? [], edges ?? []);
		if (nextRootSignature !== rootGraphSignature) {
			rootGraphSignature = nextRootSignature;
			if (activeGraphLevel === 'layer2') {
				resetToLayer1View();
			}
			layer2DataMap.clear();
			expandedPaths.clear();
			loadingPaths.clear();
			lastBuildSignature = '';
			cachedGraphData = null;
			pathCache.clear();
		}
	}

	// Debounced buildGraph to prevent excessive rebuilds
	// Use a ref to track the last scheduled build to avoid scheduling multiple times
	let lastScheduledBuildKey = '';

	$: {
		const currentNodes = visibleNodes ?? [];
		const currentEdges = visibleEdges ?? [];
		const currentDirection = layoutDirection;

		// Create a quick hash to check if we really need to schedule a rebuild
		const scheduleKey = `${currentNodes.length}:${currentEdges.length}:${currentDirection}`;
		if (scheduleKey === lastScheduledBuildKey && buildGraphTimer) {
			// Already scheduled for this configuration, skip
		} else {
			lastScheduledBuildKey = scheduleKey;

			if (buildGraphTimer) {
				clearTimeout(buildGraphTimer);
			}

			// Use 150ms debounce for better batching of rapid updates
			buildGraphTimer = setTimeout(() => {
				requestAnimationFrame(() => {
					buildGraph(currentNodes, currentEdges, currentDirection);
					buildGraphTimer = null;
				});
			}, 150);
		}
	}

	// Collect issues for the summary panel, deduplicated by node+type+description+severity
	// Use a stable cache key to avoid recomputing on every flowNodes update
	let issueListCache: IssueEntry[] = [];
	let issueListCacheKey = '';

	$: issueList = (() => {
		// Compute a lightweight cache key based on node count and detected errors
		const cacheKey = `${$flowNodes.length}:${(detectedErrors ?? []).length}:${overthinkingAnalysis?.score ?? 0}`;
		if (cacheKey === issueListCacheKey && issueListCache.length > 0) {
			return issueListCache;
		}
		issueListCacheKey = cacheKey;

		const unique = new Map<string, IssueEntry>();

		// Check if detectedErrors contains overthinking (from backend's unified format)
		const overthinkingFromBackend = (detectedErrors ?? []).find(
			(err: any) =>
				err?.type === 'Overthinking' || err?.type?.toLowerCase()?.includes('overthinking')
		);

		if (overthinkingFromBackend) {
			// Use overthinking from detectedErrors (unified format from backend)
			const overthinkingEntry: IssueEntry = {
				id: 'overthinking-analysis',
				nodeId: 'global',
				parentNodeId: null,
				type: 'Overthinking',
				description: overthinkingFromBackend.description ?? '',
				severity: overthinkingFromBackend.severity ?? 'medium',
				nodeTitle: 'Global Analysis',
				step: undefined,
				action: '',
				isLayer2: false,
				sectionNumbers: overthinkingFromBackend.section_numbers ?? []
			};
			unique.set('overthinking', overthinkingEntry);
		} else if (overthinkingAnalysis && overthinkingAnalysis.score > 0) {
			// Fallback: Add overthinking from legacy overthinkingAnalysis prop
			const overthinkingEntry: IssueEntry = {
				id: 'overthinking-analysis',
				nodeId: 'global',
				parentNodeId: null,
				type: 'Overthinking',
				description:
					overthinkingAnalysis.first_correct_answer_section !== null
						? `Correct answer found at section ${overthinkingAnalysis.first_correct_answer_section}/${overthinkingAnalysis.total_sections}, but reasoning continued. Score: ${(overthinkingAnalysis.score * 100).toFixed(0)}%`
						: `Overthinking score: ${(overthinkingAnalysis.score * 100).toFixed(0)}%`,
				severity:
					overthinkingAnalysis.score > 0.5
						? 'high'
						: overthinkingAnalysis.score > 0.3
							? 'medium'
							: 'low',
				nodeTitle: 'Global Analysis',
				step: undefined,
				action: '',
				isLayer2: false,
				sectionNumbers: overthinkingAnalysis.all_answer_sections ?? []
			};
			unique.set('overthinking', overthinkingEntry);
		}

		($flowNodes ?? []).forEach((node) => {
			const nodeIssues = Array.isArray(node?.data?.issues) ? node.data.issues : [];

			nodeIssues.forEach((issue: any, idx: number) => {
				// Skip Overthinking issues from nodes - they are already handled from detectedErrors above
				const issueType = `${issue?.type ?? ''}`.trim();
				if (issueType === 'Overthinking' || issueType.toLowerCase().includes('overthinking')) {
					return;
				}

				const entry: IssueEntry = {
					id: `${node.id}-issue-${idx}`,
					nodeId: node.id,
					parentNodeId: node.data?.parentNodeId ?? null,
					type: issueType || $i18n.t('Issue'),
					description: `${issue?.description ?? ''}`.trim(),
					severity: issue?.severity ?? issue?.level ?? '',
					nodeTitle: node.data?.title ?? $i18n.t('Step'),
					step: node.data?.step,
					action: node.data?.action ?? '',
					isLayer2: Boolean(node.data?.isLayer2Child),
					sectionNumbers: issue?.section_numbers ?? issue?.sectionNumbers ?? []
				};

				const key = buildIssueKey(entry);
				if (!unique.has(key)) {
					unique.set(key, entry);
				}
			});
		});

		issueListCache = Array.from(unique.values()).filter((entry) => entry.type || entry.description);
		return issueListCache;
	})();

	// Cache issueTypeSummary to avoid recomputing
	let issueTypeSummaryCache: { type: string; count: number }[] = [];
	let issueTypeSummaryCacheKey = '';

	$: issueTypeSummary = (() => {
		const cacheKey = `${issueList.length}:${issueList.map((i) => i.type).join(',')}`;
		if (cacheKey === issueTypeSummaryCacheKey) {
			return issueTypeSummaryCache;
		}
		issueTypeSummaryCacheKey = cacheKey;
		const counts = new Map<string, number>();
		issueList.forEach((issue) => {
			counts.set(issue.type, (counts.get(issue.type) ?? 0) + 1);
		});
		issueTypeSummaryCache = Array.from(counts.entries())
			.map(([type, count]) => ({ type, count }))
			.sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
		return issueTypeSummaryCache;
	})();

	$: filteredIssues = activeIssueType
		? issueList.filter((issue) => issue.type === activeIssueType)
		: issueList;

	$: if (!issueList.length) {
		activeIssueType = null;
	}

	$: if (highlightedNodeId && $flowNodes.length) {
		applyIssueHighlight(highlightedNodeId);
	}

	const { fitView, getNode } = useSvelteFlow();
	const nodesInitialized = useNodesInitialized();

	const fitFlow = async () => {
		await tick();
		if ($flowNodes.length > 0) {
			logGraph('fitFlow', { nodes: $flowNodes.length, edges: $flowEdges.length, layoutDirection });
			try {
				if (typeof fitView === 'function') {
					await fitView({ padding: 0.06, duration: 240 });
				} else {
					logGraph('fitFlow:fitView missing');
				}
			} catch (err) {
				console.error('[ReasoningTree] fitFlow error', err);
			}
		}
	};

	const focusNodeById = async (nodeId: string | null) => {
		if (!nodeId) return;

		const targetNode = getNode(nodeId);
		if (!targetNode) return;

		viewMode = 'tree';
		selectedNode = null;
		highlightedNodeId = nodeId;
		applyIssueHighlight(nodeId);
		setHoveredNode(nodeId);

		await tick();

		try {
			await fitView({
				nodes: [{ id: nodeId }],
				padding: 0.18,
				duration: 260,
				maxZoom: 1.2
			});
		} catch (err) {
			console.error('[ReasoningTree] focusNodeById error', err);
		}
	};

	const focusIssueOnNode = async (issue: IssueEntry) => {
		if (!issue) return;

		// For global issues like overthinking, we don't focus on a specific node
		if (issue.nodeId === 'global') {
			// Dispatch highlight event for the issue based on section numbers
			if (issue.sectionNumbers && issue.sectionNumbers.length > 0) {
				dispatch('highlight', {
					sentence: '',
					sectionNumbers: issue.sectionNumbers,
					sectionStart: null,
					sectionEnd: null,
					isError: true, // Mark as error for red styling
					highlightType: 'error'
				});
			}
			return;
		}

		// Prefer the specific node; fall back to its parent if the node is not rendered yet
		const targetId =
			getNode(issue.nodeId)?.id ??
			(issue.parentNodeId ? getNode(issue.parentNodeId)?.id : null) ??
			issue.nodeId;

		await focusNodeById(targetId);

		// Dispatch highlight event for errors based on section numbers
		if (issue.sectionNumbers && issue.sectionNumbers.length > 0) {
			dispatch('highlight', {
				sentence: '',
				sectionNumbers: issue.sectionNumbers,
				sectionStart: null,
				sectionEnd: null,
				isError: true // Mark as error highlight for red styling
			});
		}
	};

	const resetIssueFocus = () => {
		activeIssueType = null;
		highlightedNodeId = null;
		selectedIssue = null;
		applyIssueHighlight(null);
		setHoveredNode(null);
	};

	onMount(() => {
		// Load available models for report generation
		// Error handlers for debugging (silently catch errors in production)
		const onError = (_event: ErrorEvent) => {
			// Uncomment for debugging: console.error('[ReasoningTree] window error', _event.error ?? _event.message ?? _event);
		};
		const onRejection = (_event: PromiseRejectionEvent) => {
			// Uncomment for debugging: console.error('[ReasoningTree] unhandledrejection', _event.reason ?? _event);
		};
		window.addEventListener('error', onError);
		window.addEventListener('unhandledrejection', onRejection);

		const unsubscribe = nodesInitialized.subscribe((ready) => {
			nodesReady = ready;
			if (ready) {
				logGraph('nodesInitialized');
				fitFlow();
			}
		});

		hoverListener = ((event: CustomEvent<{ nodeId: string | null }>) => {
			setHoveredNode(event.detail?.nodeId ?? null);
		}) as any;
		window.addEventListener('reasoning-tree-hover', hoverListener as EventListener);

		highlightListener = ((event: CustomEvent<any>) => {
			dispatch('highlight', event.detail);
		}) as any;
		window.addEventListener('reasoning-tree-highlight', highlightListener as EventListener);

		return () => {
			// Cleanup
			unsubscribe();
			window.removeEventListener('error', onError);
			window.removeEventListener('unhandledrejection', onRejection);
			if (hoverListener) {
				window.removeEventListener('reasoning-tree-hover', hoverListener as EventListener);
				hoverListener = null;
			}
			if (highlightListener) {
				window.removeEventListener('reasoning-tree-highlight', highlightListener as EventListener);
				highlightListener = null;
			}

			// Clear timers to prevent memory leaks
			if (buildGraphTimer) {
				clearTimeout(buildGraphTimer);
				buildGraphTimer = null;
			}
			if (hoverThrottleTimer) {
				clearTimeout(hoverThrottleTimer);
				hoverThrottleTimer = null;
			}

			// Clear caches
			lastBuildSignature = '';
			cachedGraphData = null;
			expandedPaths.clear();
			loadingPaths.clear();
			edgeLookupMap.clear();
			cachedPathEdgeIds.clear();
			pathCache.clear();
		};
	});

	$: {
		const signature = `${layoutDirection}:${$flowNodes.length}:${$flowEdges.length}:${activeGraphLevel}`;
		if (nodesReady && signature !== lastFitSignature) {
			lastFitSignature = signature;
			fitFlow();
		}
	}

	// Reset edge styles when there is no hovered node.
	$: if (!$flowNodes.length) {
		setHoveredNode(null);
	}

	let selectedNode: {
		nodeId?: string;
		title?: string;
		content?: string;
		detail?: string;
		issues?: { type?: string; description?: string; severity?: string }[];
		highlightText?: string;
		action?: string;
		step?: number;
		substeps?: { text?: string; is_error?: boolean; note?: string | null }[];
		hasError?: boolean;
		errorDescription?: string | null;
		reasoningExcerpt?: string;
		segmentText?: string;
		isLayer2Node?: boolean;
	} | null = null;
	let viewMode: 'tree' | 'detail' = 'tree';

	const setSelectedNode = (detail: any) => {
		const payload =
			detail?.node?.data || // xyflow nodeclick event
			detail?.data || // other event shapes
			detail;

		if (!payload) return;

		const nodeId =
			detail?.nodeId ?? detail?.node?.id ?? detail?.node?.data?.nodeId ?? payload?.nodeId ?? null;

		// Use the new handleNodeClick for proper behavior based on node type
		if (nodeId && payload) {
			handleNodeClick(nodeId, payload);
		}

		if (nodeId) {
			setHoveredNode(nodeId);
		}
	};

	const clearSelectedNode = () => {
		selectedNode = null;
		viewMode = 'tree';
		setHoveredNode(null);
		dispatch('highlight', { sentence: '' });
	};
</script>

{#if graphError}
	<div
		class="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-4 text-sm text-amber-800 dark:text-amber-100"
	>
		{graphError}
	</div>
{:else if $flowNodes.length > 0}
	<div
		class="flex flex-col gap-2 overflow-hidden min-h-0"
		style="height: calc(100vh - 110px); max-height: calc(100vh - 120px); min-height: 520px;"
	>
		<div
			class="relative rounded-2xl border border-gray-200 dark:border-gray-800 bg-white/90 dark:bg-gray-900/90 shadow-[0_20px_60px_-35px_rgba(15,23,42,0.6)] overflow-hidden ring-1 ring-gray-100/60 dark:ring-white/5 flex-[2_1_0%] min-h-0"
		>
			<div
				class="absolute inset-0 opacity-[0.6] pointer-events-none"
				style="background-image: radial-gradient(circle at 1px 1px, rgba(148,163,184,0.25) 1px, transparent 0); background-size: 18px 18px;"
			></div>

			<div style:display={viewMode === 'tree' ? 'contents' : 'none'}>
				<div
					class="absolute left-3 top-3 flex flex-wrap gap-2 text-[11px] text-gray-600 dark:text-gray-300 z-10"
				>
					<div
						class="inline-flex items-center gap-1 bg-white/85 dark:bg-gray-900/85 border border-gray-200 dark:border-gray-800 rounded-full px-2.5 py-0.5 shadow-sm"
					>
						<span class="h-2 w-2 rounded-full bg-slate-500"></span>
						{$i18n.t('Reasoning')}
					</div>
					<div
						class="inline-flex items-center gap-1 bg-white/85 dark:bg-gray-900/85 border border-gray-200 dark:border-gray-800 rounded-full px-2.5 py-0.5 shadow-sm"
					>
						<span class="h-2 w-2 rounded-full bg-emerald-500"></span>
						{$i18n.t('Check')}
					</div>
					<div
						class="inline-flex items-center gap-1 bg-white/85 dark:bg-gray-900/85 border border-gray-200 dark:border-gray-800 rounded-full px-2.5 py-0.5 shadow-sm"
					>
						<span class="h-2 w-2 rounded-full bg-red-500"></span>
						{$i18n.t('Backtracking')}
					</div>
				</div>

				<div class="absolute right-3 top-3 flex gap-2 z-10 items-center">
					{#if activeGraphLevel === 'layer2'}
						<div
							class="px-2.5 py-1 text-[11px] rounded-full border border-amber-200 bg-amber-50 text-amber-800 dark:bg-amber-900/40 dark:border-amber-700 dark:text-amber-100 max-w-[220px] truncate"
							title={layer2Context.refinementReason
								? `${layer2Context.title} — ${layer2Context.refinementReason}`
								: layer2Context.title}
						>
							{$i18n.t('Layer 2')}: {layer2Context.title}
						</div>
						<button
							class="px-2.5 py-1 text-[11px] rounded-full border border-amber-200 dark:border-amber-700 bg-white/90 dark:bg-gray-900/90 hover:bg-amber-50 dark:hover:bg-amber-900/60 transition"
							on:click={() => resetToLayer1View()}
						>
							{$i18n.t('Back')}
						</button>
					{/if}
					<button
						class="px-2.5 py-1 text-[11px] rounded-full border border-gray-200 dark:border-gray-700 bg-white/90 dark:bg-gray-900/90 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
						aria-label="Fit view"
						on:click={() => fitFlow()}
					>
						{$i18n.t('Fit')}
					</button>
				</div>

				<div class="h-full w-full relative overflow-hidden">
					<SvelteFlow
						nodes={flowNodes}
						edges={flowEdges}
						{nodeTypes}
						fitView
						minZoom={0.25}
						maxZoom={1.6}
						panOnScroll
						panOnDrag
						nodesConnectable={false}
						nodesDraggable
						elementsSelectable={false}
						zoomOnDoubleClick={false}
						class={`bg-transparent ${hoveredNodeId ? 'edge-hover-active' : ''}`}
						on:highlight={(e) => dispatch('highlight', e.detail)}
						on:nodehover={(e) => setHoveredNode(e.detail?.nodeId ?? null)}
						on:select={(e) => setSelectedNode(e.detail)}
						on:nodeclick={(e) => setSelectedNode(e.detail)}
					>
						<Background variant={BackgroundVariant.Dots} gap={18} size={1} />
					</SvelteFlow>
				</div>
			</div>
			{#if selectedNode && viewMode === 'detail'}
				<div class="h-[500px] w-full relative overflow-auto">
					<div
						class="absolute inset-0 flex items-center justify-center p-4"
						on:click={() => clearSelectedNode()}
					>
						<div
							class="max-w-3xl w-full rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-xl p-5 space-y-4 max-h-[480px] overflow-auto"
							on:click|stopPropagation
						>
							<div class="flex items-start justify-between gap-3">
								<div class="space-y-2">
									<div
										class="flex items-center gap-2 text-[11px] uppercase text-gray-500 dark:text-gray-400"
									>
										<span
											class="px-2 py-0.5 rounded-full border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-semibold"
										>
											{selectedNode.action ?? $i18n.t('Step')}
										</span>
										{#if selectedNode.step}
											<span>{$i18n.t('Step')} {selectedNode.step}</span>
										{/if}
										{#if selectedNode.isLayer2Node}
											<span
												class="px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 dark:bg-purple-900/50 dark:text-purple-200 border border-purple-200 dark:border-purple-700"
											>
												{$i18n.t('Fine-grained step')}
											</span>
										{/if}
									</div>
									<div class="text-2xl font-semibold text-gray-900 dark:text-gray-100 leading-snug">
										{selectedNode.title}
									</div>
								</div>
								<button
									class="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 px-2 py-1 rounded border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-800"
									on:click={() => clearSelectedNode()}
								>
									← {$i18n.t('Back')}
								</button>
							</div>

							{#if selectedNode.content}
								<div class="space-y-1">
									<div class="text-[11px] uppercase text-gray-500 dark:text-gray-400">
										{$i18n.t('Summary')}
									</div>
									<div class="text-[13px] text-gray-800 dark:text-gray-100 leading-snug">
										{selectedNode.content}
									</div>
								</div>
							{/if}

							{#if selectedNode.substeps && selectedNode.substeps.length > 0}
								<div class="space-y-2">
									<div class="text-[11px] uppercase text-gray-500 dark:text-gray-400">
										{$i18n.t('Key actions')}
									</div>
									<ul class="space-y-1">
										{#each selectedNode.substeps as step, idx}
											<li class="text-sm text-gray-800 dark:text-gray-100 flex items-start gap-2">
												<span class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5"
													>{idx + 1}.</span
												>
												<span class={step?.is_error ? 'text-red-600 dark:text-red-300' : ''}>
													{step?.text}
													{#if step?.note}
														<span class="text-gray-500 dark:text-gray-300"> — {step.note}</span>
													{/if}
												</span>
											</li>
										{/each}
									</ul>
								</div>
							{/if}

							<!-- Error Detection Section -->
							<div class="space-y-2 border-t border-gray-100 dark:border-gray-800 pt-4">
								<div class="flex items-center gap-2">
									<div
										class="text-[11px] uppercase font-semibold {selectedNode.issues &&
										selectedNode.issues.length > 0
											? 'text-red-500 dark:text-red-300'
											: 'text-green-600 dark:text-green-400'}"
									>
										{$i18n.t('Error Detection Result')}
									</div>
									{#if selectedNode.issues && selectedNode.issues.length > 0}
										<span
											class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-700 dark:bg-red-900/50 dark:text-red-200 border border-red-200 dark:border-red-700"
										>
											{selectedNode.issues.length}
											{$i18n.t('issue(s)')}
										</span>
									{:else}
										<span
											class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 dark:bg-green-900/50 dark:text-green-200 border border-green-200 dark:border-green-700"
										>
											✓ {$i18n.t('No issues')}
										</span>
									{/if}
								</div>

								{#if selectedNode.issues && selectedNode.issues.length > 0}
									<ul class="space-y-2">
										{#each selectedNode.issues as issue}
											<li
												class="p-3 rounded-lg bg-red-50/50 dark:bg-red-900/20 border border-red-100 dark:border-red-800/50"
											>
												<div class="flex items-start gap-2">
													<span class="text-red-500 dark:text-red-400 text-sm">⚠</span>
													<div>
														<div class="font-semibold text-sm text-red-700 dark:text-red-300">
															{issue.type || $i18n.t('Issue')}
															{#if issue.severity}
																<span
																	class="ml-2 text-[10px] px-1.5 py-0.5 rounded {issue.severity ===
																	'high'
																		? 'bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200'
																		: issue.severity === 'medium'
																			? 'bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200'
																			: 'bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200'}"
																>
																	{issue.severity}
																</span>
															{/if}
														</div>
														{#if issue.description}
															<div class="text-sm text-gray-600 dark:text-gray-300 mt-1">
																{issue.description}
															</div>
														{/if}
													</div>
												</div>
											</li>
										{/each}
									</ul>
								{:else}
									<div
										class="p-3 rounded-lg bg-green-50/50 dark:bg-green-900/20 border border-green-100 dark:border-green-800/50 text-sm text-green-700 dark:text-green-300"
									>
										{$i18n.t('No issues were detected in this reasoning step.')}
									</div>
								{/if}
							</div>

							{#if selectedNode.errorDescription}
								<div
									class="text-sm text-red-600 dark:text-red-300 p-2 bg-red-50 dark:bg-red-900/30 rounded-lg"
								>
									{selectedNode.errorDescription}
								</div>
							{/if}

							{#if selectedNode.reasoningExcerpt || selectedNode.segmentText}
								<div class="space-y-1">
									<div class="text-[11px] uppercase text-gray-500 dark:text-gray-400">
										{$i18n.t('Reasoning excerpt')}
									</div>
									<div
										class="text-[13px] text-gray-800 dark:text-gray-100 leading-snug bg-gray-50 dark:bg-gray-800/70 rounded-lg p-3 border border-gray-200 dark:border-gray-700 max-h-32 overflow-auto"
									>
										{selectedNode.segmentText || selectedNode.reasoningExcerpt}
									</div>
								</div>
							{/if}

							<div
								class="text-[12px] text-gray-500 dark:text-gray-400 text-center pt-2 border-t border-gray-100 dark:border-gray-800"
							>
								{$i18n.t('Click empty space or press Back to return to the reasoning tree')}
							</div>
						</div>
					</div>
				</div>
			{/if}
		</div>

		{#if viewMode === 'tree'}
			<!-- Two-column layout for Issue Overview and Solution Suggestions -->
			<div class="flex gap-2 flex-[1_1_0%] min-h-0 overflow-hidden">
				<!-- Left Panel: Issue Overview (half width) -->
				<aside
					class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white/90 dark:bg-gray-900/90 shadow-[0_20px_60px_-35px_rgba(15,23,42,0.6)] ring-1 ring-gray-100/60 dark:ring-white/5 flex-1 min-h-0 overflow-hidden"
				>
					<div class="h-full flex flex-col overflow-hidden">
						<div
							class="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800"
						>
							<div>
								<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">
									{$i18n.t('Issue overview')}
								</div>
							</div>
							<div class="flex items-center gap-1">
								{#if issueList.length}
									<span
										class="px-1.5 py-0.5 rounded-full text-[9px] font-semibold bg-red-50 text-red-700 dark:bg-red-900/50 dark:text-red-200 border border-red-200 dark:border-red-700"
									>
										{issueList.length}
									</span>
								{/if}
								<button
									class="text-[10px] px-1.5 py-0.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed"
									on:click={() => resetIssueFocus()}
									disabled={!issueList.length && !highlightedNodeId}
								>
									{$i18n.t('Reset')}
								</button>
							</div>
						</div>

						<div class="p-2 space-y-2 overflow-auto flex-1">
							<!-- Loading State: Show spinner when analysis is still in progress -->
							{#if analysisStage !== 'complete' && issueTypeSummary.length === 0}
								<div class="flex flex-col items-center justify-center py-4 gap-2">
									<div class="relative">
										<div
											class="w-6 h-6 border-2 border-purple-200 dark:border-purple-800 rounded-full"
										></div>
										<div
											class="absolute inset-0 w-6 h-6 border-2 border-transparent border-t-purple-500 rounded-full animate-spin"
										></div>
									</div>
									<div class="text-[10px] text-gray-500 dark:text-gray-400 text-center">
										{#if analysisStage === 'layer1' || analysisStage === 'layer2'}
											{$i18n.t('Analyzing reasoning structure...')}
										{:else if analysisStage === 'error_detection'}
											{$i18n.t('Detecting errors...')}
										{:else}
											{$i18n.t('Starting analysis...')}
										{/if}
									</div>
								</div>
							{:else if issueTypeSummary.length > 0}
								<!-- Issue Type Summary -->
								<div class="flex flex-wrap gap-1">
									{#each issueTypeSummary as item}
										<button
											class={`group inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border transition`}
											style={`background:${getIssueStyle(item.type).bg}; color:${getIssueStyle(item.type).text}; border-color:${activeIssueType === item.type ? getIssueStyle(item.type).text : getIssueStyle(item.type).border};`}
											on:click={() => {
												activeIssueType = item.type;
											}}
											title={item.type}
										>
											<span class="line-clamp-1">{item.type}</span>
											<span
												class="px-1 py-0.5 rounded-full text-[9px] font-semibold bg-white/80 dark:bg-gray-900/70 border border-gray-200 dark:border-gray-700"
											>
												{item.count}
											</span>
										</button>
									{/each}
								</div>
							{:else}
								<div class="text-[10px] text-gray-500 dark:text-gray-400">
									{$i18n.t('No issues detected')}
								</div>
							{/if}

							{#if filteredIssues.length > 0}
								<div class="space-y-1.5">
									{#each filteredIssues as issue}
										<div
											class="w-full text-left p-1.5 rounded-lg border transition cursor-pointer {selectedIssue?.id ===
											issue.id
												? 'ring-2 ring-blue-500'
												: ''}"
											style={`background:${getIssueStyle(issue.type).bg}; color:${getIssueStyle(issue.type).text}; border-color:${highlightedNodeId === issue.nodeId || highlightedNodeId === issue.parentNodeId ? getIssueStyle(issue.type).text : getIssueStyle(issue.type).border};`}
											role="button"
											tabindex="0"
											on:click={() => {
												// Toggle inline expansion
												if (inlineExpandedIssueId === issue.id) {
													inlineExpandedIssueId = null;
												} else {
													inlineExpandedIssueId = issue.id;
												}
												selectedIssue = issue;
												// Focus on node and/or highlight sections for all issue types
												focusIssueOnNode(issue);
											}}
										>
											<div class="flex items-center justify-between gap-1">
												<button
													class="px-1.5 py-0.5 rounded-full text-[11px] font-semibold border"
													style={`background:${getIssueStyle(issue.type).bg}; color:${getIssueStyle(issue.type).text}; border-color:${getIssueStyle(issue.type).text};`}
													on:click|stopPropagation={() => {
														activeIssueType = issue.type;
													}}
													title={$i18n.t('Show all of this type')}
												>
													{issue.type}
												</button>
												<div class="flex items-center gap-1">
													{#if issue.severity}
														<span
															class="px-1.5 py-0.5 rounded-full text-[9px] font-semibold {issue.severity ===
															'high'
																? 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 border border-red-300'
																: issue.severity === 'medium'
																	? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300 border border-yellow-300'
																	: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300 border border-green-300'}"
														>
															{issue.severity}
														</span>
													{/if}
													<!-- Expand/Collapse indicator -->
													<div class="p-0.5">
														<svg
															class="w-3.5 h-3.5 transition-transform duration-200 {inlineExpandedIssueId ===
															issue.id
																? 'rotate-180'
																: ''}"
															fill="none"
															stroke="currentColor"
															viewBox="0 0 24 24"
														>
															<path
																stroke-linecap="round"
																stroke-linejoin="round"
																stroke-width="2"
																d="M19 9l-7 7-7-7"
															></path>
														</svg>
													</div>
												</div>
											</div>

											<!-- Collapsed view: show truncated description -->
											{#if inlineExpandedIssueId !== issue.id}
												<div class="text-xs mt-1 line-clamp-2 text-gray-800 dark:text-gray-100">
													{issue.description || issue.nodeTitle}
												</div>
											{:else}
												<!-- Expanded view: show full details -->
												<div class="mt-2 space-y-2 pt-2 border-t border-current/20">
													<!-- Node Title / Location -->
													{#if issue.nodeTitle}
														<div>
															<div class="text-[10px] uppercase font-semibold opacity-70 mb-0.5">
																{$i18n.t('Location')}
															</div>
															<div class="text-xs font-medium text-gray-800 dark:text-gray-100">
																{issue.nodeTitle}
															</div>
															{#if issue.sectionNumbers}
																<div class="text-[10px] opacity-70 mt-0.5">
																	Section: {issue.sectionNumbers}
																</div>
															{/if}
														</div>
													{/if}

													<!-- Full Description -->
													{#if issue.description}
														<div>
															<div class="text-[9px] uppercase font-semibold opacity-70 mb-0.5">
																{$i18n.t('Description')}
															</div>
															<div
																class="text-[11px] text-gray-800 dark:text-gray-100 whitespace-pre-wrap"
															>
																{issue.description}
															</div>
														</div>
													{/if}
												</div>
											{/if}
											<!-- Special progress bar for Overthinking type -->
											{#if issue.type === 'Overthinking' && overthinkingAnalysis && overthinkingAnalysis.first_correct_answer_section !== null && overthinkingAnalysis.total_sections > 0}
												<div class="mt-1.5 space-y-0.5">
													<div
														class="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden"
													>
														<div
															class="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-300"
															style="width: {(overthinkingAnalysis.first_correct_answer_section /
																overthinkingAnalysis.total_sections) *
																100}%"
														></div>
													</div>
													<div
														class="flex justify-between text-[9px] text-gray-500 dark:text-gray-400"
													>
														<span>{$i18n.t('Productive')}</span>
														<span>{$i18n.t('Overthinking')}</span>
													</div>
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{:else if issueList.length > 0}
								<div class="text-[10px] text-gray-500 dark:text-gray-400">
									{$i18n.t('Select a type to focus its issues')}
								</div>
							{/if}
						</div>
					</div>
				</aside>

				<!-- Right Panel: Solution Suggestions -->
				<aside
					class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white/90 dark:bg-gray-900/90 shadow-[0_20px_60px_-35px_rgba(15,23,42,0.6)] ring-1 ring-gray-100/60 dark:ring-white/5 flex-1 min-h-0 overflow-hidden"
				>
					<div class="h-full flex flex-col overflow-hidden">
						<div
							class="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800"
						>
							<div>
								<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">
									{$i18n.t('How to fix')}
								</div>
							</div>
							{#if selectedIssue}
								<span
									class="px-1.5 py-0.5 rounded-full text-[9px] font-semibold border"
									style={`background:${getIssueStyle(selectedIssue.type).bg}; color:${getIssueStyle(selectedIssue.type).text}; border-color:${getIssueStyle(selectedIssue.type).text};`}
								>
									{selectedIssue.type}
								</span>
							{/if}
						</div>

						<div class="p-2 space-y-2 overflow-auto flex-1">
							{#if loadingSolutions}
								<!-- Loading State -->
								<div class="flex items-center justify-center p-4">
									<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
									<span class="ml-2 text-[11px] text-gray-500"
										>{$i18n.t('Loading solutions...')}</span
									>
								</div>
							{:else if selectedIssue}
								<!-- Method Type Tabs -->
								<div
									class="flex items-center gap-1 mb-2 border-b border-gray-200 dark:border-gray-700"
								>
									<button
										class="px-2 py-1.5 text-[10px] font-semibold transition-colors border-b-2 {activeMethodTab ===
										'test_time'
											? 'text-emerald-600 dark:text-emerald-400 border-emerald-500'
											: 'text-gray-500 dark:text-gray-400 border-transparent hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeMethodTab = 'test_time')}
									>
										<span class="mr-1">⚡</span>
										{$i18n.t('Test-Time')}
										{#if currentSolutions?.test_time_methods?.length}
											<span
												class="ml-1 px-1 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 text-[8px]"
											>
												{currentSolutions.test_time_methods.length}
											</span>
										{/if}
									</button>
									<button
										class="px-2 py-1.5 text-[10px] font-semibold transition-colors border-b-2 {activeMethodTab ===
										'training'
											? 'text-purple-600 dark:text-purple-400 border-purple-500'
											: 'text-gray-500 dark:text-gray-400 border-transparent hover:text-gray-700 dark:hover:text-gray-300'}"
										on:click={() => (activeMethodTab = 'training')}
									>
										<span class="mr-1">🎓</span>
										{$i18n.t('Training')}
										{#if currentSolutions?.training_methods?.length}
											<span
												class="ml-1 px-1 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 text-[8px]"
											>
												{currentSolutions.training_methods.length}
											</span>
										{/if}
									</button>
								</div>

								<!-- Test-Time Methods Tab Content -->
								{#if activeMethodTab === 'test_time'}
									{#if currentSolutions?.test_time_methods?.length}
										<div class="space-y-1.5">
											<div class="flex items-center justify-between">
												<div
													class="text-[10px] uppercase font-semibold text-emerald-600 dark:text-emerald-400"
												>
													{$i18n.t('Test-Time Scaling Methods')}
												</div>
												<div class="text-[9px] text-gray-500 dark:text-gray-400">
													{$i18n.t('No training required')}
												</div>
											</div>

												<!-- Test-Time Method Cards -->
											<div class="space-y-1.5 max-h-64 overflow-auto">
												{#each getTestTimeMethods() as method}
													<div
														class="p-2 rounded-lg bg-emerald-50/50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800"
													>
														<div class="flex items-start justify-between gap-2">
															<div class="flex-1 min-w-0">
																<div class="flex items-center gap-1.5">
																	<span
																		class="text-xs font-semibold text-emerald-800 dark:text-emerald-200"
																	>
																		{method.name}
																	</span>
																</div>
																{#if method.full_name && method.full_name !== method.name}
																	<div class="text-[10px] text-emerald-600 dark:text-emerald-400">
																		{method.full_name}
																	</div>
																{/if}
																<div class="text-[11px] text-gray-600 dark:text-gray-400 mt-0.5">
																	{method.description}
																</div>
																{#if method.effect}
																	<div
																		class="text-[10px] text-green-600 dark:text-green-400 mt-0.5"
																	>
																		✓ {method.effect}
																	</div>
																{/if}
																{#if method.implementation}
																	<div class="text-[10px] text-cyan-600 dark:text-cyan-400 mt-0.5">
																		💡 {method.implementation}
																	</div>
																{/if}
																{#if method.citation_info && method.citation_info.length > 0}
																	<div class="mt-1 space-y-0.5">
																		{#each method.citation_info as citation, idx}
																			{@const popoverId = `tt-${method.name}-${idx}`}
																			<div class="relative inline-block">
																				<!-- Inline citation badge: [Author et al., Year] -->
																				<button
																					class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium
																						bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300
																						border border-blue-200 dark:border-blue-700
																						hover:bg-blue-100 dark:hover:bg-blue-800/40
																						transition-colors cursor-pointer"
																					on:click|stopPropagation={() => {
																						activeCitationPopover = activeCitationPopover === popoverId ? null : popoverId;
																					}}
																					title={citation.formatted_citation}
																				>
																					<span>📄</span>
																					<span>[{citation.inline_citation}]</span>
																				</button>

																				<!-- Citation detail popover -->
																				{#if activeCitationPopover === popoverId}
																					<div
																						class="absolute z-50 left-0 top-full mt-1 w-72 p-2.5 rounded-lg shadow-lg
																							bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600
																							text-left"
																					>
																						<!-- Close button -->
																						<button
																							class="absolute top-1 right-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-0.5"
																							aria-label="Close citation"
																							on:click|stopPropagation={() => { activeCitationPopover = null; }}
																						>
																							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
																							</svg>
																						</button>

																						<!-- Paper title -->
																						<div class="text-[11px] font-semibold text-gray-800 dark:text-gray-200 pr-4 leading-tight">
																							{citation.title}
																						</div>

																						<!-- Authors -->
																						{#if citation.authors && citation.authors.length > 0}
																							<div class="text-[10px] text-gray-600 dark:text-gray-400 mt-1 leading-snug">
																								{citation.authors.slice(0, 5).join(', ')}{citation.authors.length > 5 ? ', ...' : ''}
																							</div>
																						{/if}

																						<!-- Venue & Year -->
																						<div class="flex items-center gap-1.5 mt-1 flex-wrap">
																							{#if formatVenue(citation)}
																								<span class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
																									{formatVenue(citation)}
																								</span>
																							{/if}
																							{#if citation.year}
																								<span class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
																									{citation.year}
																								</span>
																							{/if}
																						</div>

																						<!-- Link to paper -->
																						{#if getCitationUrl(citation)}
																							<a
																								href={getCitationUrl(citation)}
																								target="_blank"
																								rel="noopener noreferrer"
																								class="inline-flex items-center gap-1 mt-1.5 px-1.5 py-0.5 rounded text-[9px] font-medium
																									bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400
																									hover:bg-blue-100 dark:hover:bg-blue-800/40 transition-colors"
																								on:click|stopPropagation
																							>
																								<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
																								</svg>
																								{citation.doi ? 'DOI' : citation.eprint ? 'arXiv' : 'Link'}
																							</a>
																						{/if}
																					</div>
																				{/if}
																			</div>
																		{/each}
																	</div>
																{:else if method.reference}
																	<div
																		class="text-[10px] text-blue-500 dark:text-blue-400 mt-0.5 truncate"
																	>
																		📄 {method.reference}
																	</div>
																{/if}
															</div>
														</div>
													</div>
												{/each}
											</div>
										</div>
									{:else}
										<div
											class="p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 text-center"
										>
											<div class="text-[10px] text-gray-500 dark:text-gray-400">
												{$i18n.t('No test-time methods available for this error type yet.')}
											</div>
										</div>
									{/if}

									<!-- Test-Time Tip -->
									<div
										class="mt-2 p-2 rounded-lg bg-emerald-50/50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800"
									>
										<div
											class="text-[10px] uppercase font-semibold text-emerald-600 dark:text-emerald-400 mb-1"
										>
											{$i18n.t('Tip')}
										</div>
										<div class="text-[10px] text-emerald-700 dark:text-emerald-300">
											{$i18n.t(
												'Test-time methods can be applied immediately at inference without additional training. Great for quick improvements!'
											)}
										</div>
									</div>
								{/if}

								<!-- Training Methods Tab Content -->
								{#if activeMethodTab === 'training'}
									{#if currentSolutions?.training_methods?.length}
										<div class="space-y-1.5">
											<div class="flex items-center justify-between">
												<div
													class="text-[10px] uppercase font-semibold text-purple-600 dark:text-purple-400"
												>
													{$i18n.t('Training Methods')}
												</div>
												<div class="text-[9px] text-gray-500 dark:text-gray-400">
													{$i18n.t('Requires training')}
												</div>
											</div>

											<!-- Training Method Cards -->
											<div class="space-y-1.5 max-h-64 overflow-auto">
												{#each getTrainingMethods() as method}
													<div
														class="p-2 rounded-lg bg-purple-50/50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800"
													>
														<div class="flex items-start justify-between gap-2">
															<div class="flex-1 min-w-0">
																<div class="flex items-center gap-1.5">
																	<span
																		class="text-xs font-semibold text-purple-800 dark:text-purple-200"
																	>
																		{method.name}
																	</span>
																</div>
																{#if method.full_name && method.full_name !== method.name}
																	<div class="text-[10px] text-purple-600 dark:text-purple-400">
																		{method.full_name}
																	</div>
																{/if}
																<div class="text-[11px] text-gray-600 dark:text-gray-400 mt-0.5">
																	{method.description}
																</div>
																{#if method.effect}
																	<div
																		class="text-[10px] text-green-600 dark:text-green-400 mt-0.5"
																	>
																		✓ {method.effect}
																	</div>
																{/if}
																{#if method.citation_info && method.citation_info.length > 0}
																	<div class="mt-1 space-y-0.5">
																		{#each method.citation_info as citation, idx}
																			{@const popoverId = `tr-${method.name}-${idx}`}
																			<div class="relative inline-block">
																				<!-- Inline citation badge: [Author et al., Year] -->
																				<button
																					class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium
																						bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300
																						border border-blue-200 dark:border-blue-700
																						hover:bg-blue-100 dark:hover:bg-blue-800/40
																						transition-colors cursor-pointer"
																					on:click|stopPropagation={() => {
																						activeCitationPopover = activeCitationPopover === popoverId ? null : popoverId;
																					}}
																					title={citation.formatted_citation}
																				>
																					<span>📄</span>
																					<span>[{citation.inline_citation}]</span>
																				</button>

																				<!-- Citation detail popover -->
																				{#if activeCitationPopover === popoverId}
																					<div
																						class="absolute z-50 left-0 top-full mt-1 w-72 p-2.5 rounded-lg shadow-lg
																							bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600
																							text-left"
																					>
																						<!-- Close button -->
																						<button
																							class="absolute top-1 right-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-0.5"
																							aria-label="Close citation"
																							on:click|stopPropagation={() => { activeCitationPopover = null; }}
																						>
																							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
																							</svg>
																						</button>

																						<!-- Paper title -->
																						<div class="text-[11px] font-semibold text-gray-800 dark:text-gray-200 pr-4 leading-tight">
																							{citation.title}
																						</div>

																						<!-- Authors -->
																						{#if citation.authors && citation.authors.length > 0}
																							<div class="text-[10px] text-gray-600 dark:text-gray-400 mt-1 leading-snug">
																								{citation.authors.slice(0, 5).join(', ')}{citation.authors.length > 5 ? ', ...' : ''}
																							</div>
																						{/if}

																						<!-- Venue & Year -->
																						<div class="flex items-center gap-1.5 mt-1 flex-wrap">
																							{#if formatVenue(citation)}
																								<span class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
																									{formatVenue(citation)}
																								</span>
																							{/if}
																							{#if citation.year}
																								<span class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
																									{citation.year}
																								</span>
																							{/if}
																						</div>

																						<!-- Link to paper -->
																						{#if getCitationUrl(citation)}
																							<a
																								href={getCitationUrl(citation)}
																								target="_blank"
																								rel="noopener noreferrer"
																								class="inline-flex items-center gap-1 mt-1.5 px-1.5 py-0.5 rounded text-[9px] font-medium
																									bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400
																									hover:bg-blue-100 dark:hover:bg-blue-800/40 transition-colors"
																								on:click|stopPropagation
																							>
																								<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
																								</svg>
																								{citation.doi ? 'DOI' : citation.eprint ? 'arXiv' : 'Link'}
																							</a>
																						{/if}
																					</div>
																				{/if}
																			</div>
																		{/each}
																	</div>
																{:else if method.reference}
																	<div
																		class="text-[10px] text-blue-500 dark:text-blue-400 mt-0.5 truncate"
																	>
																		📄 {method.reference}
																	</div>
																{/if}
															</div>
														</div>
													</div>
												{/each}
											</div>
										</div>
									{:else}
										<div
											class="p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 text-center"
										>
											<div class="text-[10px] text-gray-500 dark:text-gray-400">
												{$i18n.t('No training methods available for this error type yet.')}
											</div>
										</div>
									{/if}

									<!-- Training Tip -->
									<div
										class="mt-2 p-2 rounded-lg bg-purple-50/50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800"
									>
										<div
											class="text-[10px] uppercase font-semibold text-purple-600 dark:text-purple-400 mb-1"
										>
											{$i18n.t('Tip')}
										</div>
										<div class="text-[10px] text-purple-700 dark:text-purple-300">
											{$i18n.t(
												'Training methods require fine-tuning or RLHF. Choose based on your resources and expertise level.'
											)}
										</div>
									</div>
								{/if}

								<!-- Evaluation Metrics -->
								{#if currentSolutions?.evaluation_metrics?.length}
									<div
										class="mt-2 p-2 rounded-lg bg-indigo-50/50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800"
									>
										<div
											class="text-[10px] uppercase font-semibold text-indigo-600 dark:text-indigo-400 mb-1"
										>
											{$i18n.t('Evaluation metrics')}
										</div>
										<div class="flex flex-wrap gap-1">
											{#each currentSolutions.evaluation_metrics as metric}
												<span
													class="px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-800/50 text-[9px] text-indigo-700 dark:text-indigo-300"
												>
													{metric}
												</span>
											{/each}
										</div>
									</div>
								{/if}
							{:else}
								<!-- No Issue Selected / Analysis in progress -->
								{#if analysisStage !== 'complete' && issueList.length === 0}
									<!-- Analysis in progress -->
									<div class="h-full flex flex-col items-center justify-center text-center p-4">
										<div class="relative mb-3">
											<div
												class="w-10 h-10 border-2 border-purple-200 dark:border-purple-800 rounded-full"
											></div>
											<div
												class="absolute inset-0 w-10 h-10 border-2 border-transparent border-t-purple-500 rounded-full animate-spin"
											></div>
										</div>
										<div class="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
											{#if analysisStage === 'layer1' || analysisStage === 'layer2'}
												{$i18n.t('Analyzing...')}
											{:else if analysisStage === 'error_detection'}
												{$i18n.t('Detecting errors...')}
											{:else}
												{$i18n.t('Starting analysis...')}
											{/if}
										</div>
										<div class="text-[10px] text-gray-500 dark:text-gray-400">
											{$i18n.t('Solutions will appear here once issues are detected')}
										</div>
									</div>
								{:else}
									<!-- No issue selected (analysis complete) -->
									<div class="h-full flex flex-col items-center justify-center text-center p-4">
										<div
											class="w-12 h-12 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-3"
										>
											<svg
												class="w-6 h-6 text-gray-400"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
												></path>
											</svg>
										</div>
										<div class="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
											{$i18n.t('No issue selected')}
										</div>
										<div class="text-[10px] text-gray-500 dark:text-gray-400">
											{$i18n.t('Click on an issue from the left panel to view solution methods')}
										</div>
									</div>
								{/if}
							{/if}
						</div>
					</div>
				</aside>
			</div>
		{/if}

		<!-- Expanded Issue Detail Modal -->
		{#if expandedIssue}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
				on:click={() => (expandedIssue = null)}
			>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="relative max-w-lg w-full mx-4 max-h-[80vh] overflow-auto rounded-2xl bg-white dark:bg-gray-900 shadow-2xl border border-gray-200 dark:border-gray-700"
					on:click|stopPropagation
				>
					<!-- Modal Header -->
					<div
						class="sticky top-0 flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 rounded-t-2xl"
					>
						<div class="flex items-center gap-2">
							<span
								class="px-2 py-1 rounded-full text-[10px] font-bold border"
								style={`background:${getIssueStyle(expandedIssue.type).bg}; color:${getIssueStyle(expandedIssue.type).text}; border-color:${getIssueStyle(expandedIssue.type).text};`}
							>
								{expandedIssue.type}
							</span>
							<span
								class="px-2 py-1 rounded-full text-[10px] font-semibold {expandedIssue.severity ===
								'high'
									? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-400'
									: expandedIssue.severity === 'medium'
										? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-400'
										: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-400'}"
							>
								{expandedIssue.severity?.toUpperCase() || 'MEDIUM'}
							</span>
						</div>
						<button
							class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
							on:click={() => (expandedIssue = null)}
							aria-label="Close"
						>
							<svg
								class="w-5 h-5 text-gray-500"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M6 18L18 6M6 6l12 12"
								></path>
							</svg>
						</button>
					</div>

					<!-- Modal Body -->
					<div class="p-4 space-y-4">
						<!-- Node Title -->
						{#if expandedIssue.nodeTitle}
							<div>
								<div
									class="text-[10px] uppercase font-semibold text-gray-500 dark:text-gray-400 mb-1"
								>
									{$i18n.t('Location')}
								</div>
								<div class="text-sm font-medium text-gray-800 dark:text-gray-200">
									{expandedIssue.nodeTitle}
								</div>
								{#if expandedIssue.sectionNumbers}
									<div class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
										Section: {expandedIssue.sectionNumbers}
									</div>
								{/if}
							</div>
						{/if}

						<!-- Description -->
						{#if expandedIssue.description}
							<div>
								<div
									class="text-[10px] uppercase font-semibold text-gray-500 dark:text-gray-400 mb-1"
								>
									{$i18n.t('Description')}
								</div>
								<div class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
									{expandedIssue.description}
								</div>
							</div>
						{/if}
					</div>

					<!-- Modal Footer -->
					<div
						class="px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 rounded-b-2xl"
					>
						<div class="flex items-center justify-between">
							<button
								class="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-purple-500 hover:bg-purple-600 text-white transition-colors"
								on:click={() => {
									selectedIssue = expandedIssue;
									expandedIssue = null;
								}}
							>
								{$i18n.t('View training methods')}
							</button>
							<button
								class="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 transition-colors"
								on:click={() => (expandedIssue = null)}
							>
								{$i18n.t('Close')}
							</button>
						</div>
					</div>
				</div>
			</div>
		{/if}
	</div>
{:else}
	<div
		class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 text-sm text-gray-600 dark:text-gray-300"
	>
		{$i18n.t('No analysis available')}
	</div>
{/if}

<style>
	/* Flow path animation for edges when hovering on a node */
	:global(.flow-path-edge) {
		animation: flowPulse 1.5s ease-in-out infinite;
	}

	@keyframes flowPulse {
		0%,
		100% {
			filter: drop-shadow(0 0 3px rgba(245, 158, 11, 0.5));
		}
		50% {
			filter: drop-shadow(0 0 8px rgba(245, 158, 11, 0.9));
		}
	}

	/* Enhanced animated edge with flowing dot effect */
	:global(.svelte-flow .react-flow__edge.animated path) {
		stroke-dasharray: 8 4;
		animation: flowDash 0.6s linear infinite;
	}

	/* Dim non-path edges while hovering; keep path edges crisp */
	:global(.svelte-flow.edge-hover-active .react-flow__edge) {
		opacity: 0.25;
	}

	:global(.svelte-flow.edge-hover-active .react-flow__edge.flow-path-edge) {
		opacity: 1;
	}

	:global(.svelte-flow.edge-hover-active .react-flow__edge.flow-path-edge path) {
		stroke: #f59e0b;
		stroke-width: 8;
	}

	:global(.svelte-flow.edge-hover-active .react-flow__edge.animated:not(.flow-path-edge) path) {
		animation: none;
	}

	@keyframes flowDash {
		0% {
			stroke-dashoffset: 24;
		}
		100% {
			stroke-dashoffset: 0;
		}
	}

	/* Make edges more visible with subtle shadow */
	:global(.svelte-flow .react-flow__edge path) {
		filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
	}

	/* Smooth transition for edge opacity changes */
	:global(.svelte-flow .react-flow__edge) {
		transition: opacity 0.2s ease-out;
	}
</style>
