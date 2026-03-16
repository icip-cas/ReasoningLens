import { WEBUI_API_BASE_URL } from '$lib/constants';

// Note: Reasoning analysis now uses streaming endpoint (/analysis/reasoning/stream)
// implemented directly in ResponseMessage.svelte for better control

// =============================================================================
// Model Analysis Report API
// =============================================================================

export interface AnalysisHistoryRecord {
	message_id: string;
	chat_id: string;
	analysis_model: string;
	reasoning_model: string;
	query_preview: string;
	node_count: number;
	section_count: number;
	error_count: number;
	overthinking_score: number;
	directory: string;
	has_error_detection: boolean;
	timestamp: string;
}

export interface AggregatedStats {
	total_analyses: number;
	total_errors: number;
	total_sections: number;
	total_nodes: number;
	error_type_counts: Record<string, number>;
	node_type_counts: Record<string, number>;
	avg_overthinking_score: number;
	high_overthinking_count: number;
	avg_sections: number;
	error_examples: Record<
		string,
		Array<{
			description: string;
			severity: string;
		}>
	>;
	reasoning_trees: Array<Record<string, unknown>>;
}

export interface ReportGenerationEvent {
	type: 'progress' | 'chunk' | 'complete' | 'error';
	stage?: string;
	message?: string;
	content?: string;
	report?: string;
	stats?: AggregatedStats;
	records_count?: number;
	reasoning_model?: string;
	analysis_model?: string;
}

export interface SavedReportSummary {
	report_id: string;
	reasoning_model: string;
	report_model: string;
	analysis_model: string;
	timestamp: string;
	records_count: number;
	content_preview: string;
	language: string;
}

export interface SavedReportFull {
	report_id: string;
	reasoning_model: string;
	report_model: string;
	analysis_model: string;
	timestamp: string;
	records_count: number;
	report_content: string;
	language: string;
}

/**
 * Get analysis history records
 */
export const getAnalysisHistory = async (
	token: string = '',
	options?: {
		reasoning_model?: string;
		analysis_model?: string;
		limit?: number;
	}
): Promise<{
	success: boolean;
	records: AnalysisHistoryRecord[];
	by_reasoning_model: Record<string, AnalysisHistoryRecord[]>;
	total: number;
}> => {
	const params = new URLSearchParams();
	if (options?.reasoning_model) params.append('reasoning_model', options.reasoning_model);
	if (options?.analysis_model) params.append('analysis_model', options.analysis_model);
	if (options?.limit) params.append('limit', options.limit.toString());

	const queryString = params.toString();
	const url = `${WEBUI_API_BASE_URL}/analysis/reasoning/history${queryString ? '?' + queryString : ''}`;

	const res = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getAnalysisHistory error:', err);
			throw err.detail ?? 'Failed to get analysis history';
		});

	return res;
};

/**
 * Get aggregated stats for a reasoning model
 */
export const getAggregatedStats = async (
	token: string = '',
	options?: {
		reasoning_model?: string;
		analysis_model?: string;
		limit?: number;
	}
): Promise<{
	success: boolean;
	stats: AggregatedStats | null;
	records_count: number;
	message?: string;
	reasoning_model?: string;
	analysis_model?: string;
}> => {
	const params = new URLSearchParams();
	if (options?.reasoning_model) params.append('reasoning_model', options.reasoning_model);
	if (options?.analysis_model) params.append('analysis_model', options.analysis_model);
	if (options?.limit) params.append('limit', options.limit.toString());

	const queryString = params.toString();
	const url = `${WEBUI_API_BASE_URL}/analysis/reasoning/report/stats${queryString ? '?' + queryString : ''}`;

	const res = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getAggregatedStats error:', err);
			throw err.detail ?? 'Failed to get aggregated stats';
		});

	return res;
};

/**
 * Generate analysis report with streaming support
 */
export const generateAnalysisReport = async (
	token: string = '',
	params: {
		reasoning_model: string;
		analysis_model?: string;
		report_model: string;
		directories?: string[];
		stream?: boolean;
		language?: 'zh' | 'en';
	},
	onEvent?: (event: ReportGenerationEvent) => void
): Promise<{
	report: string;
	stats: AggregatedStats;
	records_count: number;
}> => {
	const response = await fetch(`${WEBUI_API_BASE_URL}/analysis/reasoning/report/generate`, {
		method: 'POST',
		headers: {
			Accept: 'text/event-stream',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({
			reasoning_model: params.reasoning_model,
			analysis_model: params.analysis_model || null,
			report_model: params.report_model,
			directories: params.directories || null,
			stream: params.stream ?? true,
			language: params.language || 'zh'
		})
	});

	if (!response.ok) {
		const error = await response.json();
		throw error.detail ?? 'Failed to generate report';
	}

	const reader = response.body?.getReader();
	if (!reader) {
		throw new Error('Response body is not readable');
	}

	const decoder = new TextDecoder();
	let report = '';
	let stats: AggregatedStats | null = null;
	let records_count = 0;

	// Batch processing: yield to main thread less frequently
	let chunkCount = 0;
	const YIELD_INTERVAL = 10; // Yield every 10 chunks

	// Helper to yield control to the main thread
	const yieldToMain = () =>
		new Promise<void>((resolve) => {
			// Use setTimeout with 0 for better compatibility
			setTimeout(resolve, 0);
		});

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			const chunk = decoder.decode(value, { stream: true });
			const lines = chunk.split('\n');

			for (const line of lines) {
				if (line.startsWith('data: ')) {
					try {
						const data = JSON.parse(line.slice(6)) as ReportGenerationEvent;

						if (onEvent) {
							onEvent(data);
						}

						if (data.type === 'chunk' && data.content) {
							report += data.content;
							chunkCount++;
							// Yield to main thread periodically to prevent UI freeze
							if (chunkCount % YIELD_INTERVAL === 0) {
								await yieldToMain();
							}
						} else if (data.type === 'complete') {
							if (data.report) report = data.report;
							if (data.stats) stats = data.stats;
							if (data.records_count) records_count = data.records_count;
						} else if (data.type === 'error') {
							throw new Error(data.message || 'Report generation failed');
						}
					} catch (e) {
						if (e instanceof SyntaxError) {
							// Ignore JSON parse errors for incomplete chunks
							continue;
						}
						throw e;
					}
				}
			}
		}
	} finally {
		reader.releaseLock();
	}

	return {
		report,
		stats: stats || {
			total_analyses: 0,
			total_errors: 0,
			total_sections: 0,
			total_nodes: 0,
			error_type_counts: {},
			node_type_counts: {},
			avg_overthinking_score: 0,
			high_overthinking_count: 0,
			avg_sections: 0,
			error_examples: {},
			reasoning_trees: []
		},
		records_count
	};
};

// =============================================================================
// Error Solutions Knowledge Base API
// =============================================================================

export interface CitationInfo {
	paper_title: string;
	entry_type?: string;
	cite_key?: string;
	authors: string[];
	short_authors: string;
	year: string;
	title: string;
	venue: string;
	doi: string;
	url: string;
	pages: string;
	volume: string;
	number: string;
	publisher: string;
	eprint: string;
	archiveprefix: string;
	inline_citation: string;
	formatted_citation: string;
	raw_bibtex: string;
}

export interface TrainingMethod {
	category: string;
	name: string;
	full_name?: string;
	description: string;
	effect?: string;
	reference?: string | null;
	citation_info?: CitationInfo[];
	difficulty: 'beginner' | 'intermediate' | 'advanced';
}

export interface TestTimeMethod {
	category: string;
	name: string;
	full_name?: string;
	description: string;
	effect?: string;
	reference?: string | null;
	citation_info?: CitationInfo[];
	difficulty: 'beginner' | 'intermediate' | 'advanced';
	implementation?: string; // Implementation guidance for test-time methods
}

export interface ErrorSolutionResponse {
	error_type: string;
	found: boolean;
	display_name?: string;
	description?: string;
	severity_default?: string;
	quick_fixes: string[];
	// Test-time scaling methods (no training required)
	test_time_methods: TestTimeMethod[];
	test_time_methods_by_category: Record<string, TestTimeMethod[]>;
	test_time_categories: string[];
	// Training-required methods
	training_methods: TrainingMethod[];
	training_methods_by_category: Record<string, TrainingMethod[]>;
	categories: string[];
	evaluation_metrics: string[];
}

export interface ErrorTypeInfo {
	name: string;
	display_name: string;
	description: string;
	severity_default: string;
	quick_fixes_count: number;
	training_methods_count: number;
}

export interface DifficultyLevel {
	label: string;
	description?: string;
	color: string;
}

/**
 * Get list of all error types in the knowledge base
 */
export const getErrorTypes = async (
	token: string = ''
): Promise<{ success: boolean; error_types: ErrorTypeInfo[]; total: number }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/error-types`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getErrorTypes error:', err);
			throw err.detail ?? 'Failed to get error types';
		});

	return res;
};

/**
 * Get solutions for a specific error type
 */
export const getErrorSolutions = async (
	token: string = '',
	errorType: string,
	options?: {
		category?: string;
		difficulty?: string;
	}
): Promise<ErrorSolutionResponse> => {
	const params = new URLSearchParams();
	if (options?.category) params.append('category', options.category);
	if (options?.difficulty) params.append('difficulty', options.difficulty);

	const queryString = params.toString();
	const url = `${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/${encodeURIComponent(errorType)}${queryString ? '?' + queryString : ''}`;

	const res = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getErrorSolutions error:', err);
			throw err.detail ?? 'Failed to get error solutions';
		});

	return res;
};

/**
 * Get training methods for a specific error type
 */
export const getErrorTrainingMethods = async (
	token: string = '',
	errorType: string,
	options?: {
		category?: string;
		difficulty?: string;
	}
): Promise<{
	success: boolean;
	error_type: string;
	methods: TrainingMethod[];
	total: number;
	available_categories: string[];
	difficulty_levels: Record<string, DifficultyLevel>;
}> => {
	const params = new URLSearchParams();
	if (options?.category) params.append('category', options.category);
	if (options?.difficulty) params.append('difficulty', options.difficulty);

	const queryString = params.toString();
	const url = `${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/${encodeURIComponent(errorType)}/training-methods${queryString ? '?' + queryString : ''}`;

	const res = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getErrorTrainingMethods error:', err);
			throw err.detail ?? 'Failed to get training methods';
		});

	return res;
};

/**
 * Add a new training method to an error type
 */
export const addTrainingMethod = async (
	token: string = '',
	errorType: string,
	method: Partial<TrainingMethod> & { name: string; description: string }
): Promise<{ success: boolean; message: string }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/add-method`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({
			error_type: errorType,
			method: method
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('addTrainingMethod error:', err);
			throw err.detail ?? 'Failed to add training method';
		});

	return res;
};

/**
 * Add a new quick fix suggestion to an error type
 */
export const addQuickFix = async (
	token: string = '',
	errorType: string,
	quickFix: string
): Promise<{ success: boolean; message: string }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/add-quick-fix`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({
			error_type: errorType,
			quick_fix: quickFix
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('addQuickFix error:', err);
			throw err.detail ?? 'Failed to add quick fix';
		});

	return res;
};

/**
 * Reload the knowledge base from disk
 */
export const reloadKnowledgeBase = async (
	token: string = ''
): Promise<{ success: boolean; message: string; error_types: string[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analysis/reasoning/solutions/reload`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('reloadKnowledgeBase error:', err);
			throw err.detail ?? 'Failed to reload knowledge base';
		});

	return res;
};

// =============================================================================
// Saved Reports API
// =============================================================================

/**
 * List all saved reports
 */
export const listSavedReports = async (
	token: string = '',
	options?: {
		reasoning_model?: string;
		limit?: number;
	}
): Promise<{
	success: boolean;
	reports: SavedReportSummary[];
	total: number;
}> => {
	const params = new URLSearchParams();
	if (options?.reasoning_model) params.append('reasoning_model', options.reasoning_model);
	if (options?.limit) params.append('limit', options.limit.toString());

	const queryString = params.toString();
	const url = `${WEBUI_API_BASE_URL}/analysis/reasoning/report/list${queryString ? '?' + queryString : ''}`;

	const res = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('listSavedReports error:', err);
			throw err.detail ?? 'Failed to list saved reports';
		});

	return res;
};

/**
 * Get a specific saved report by ID
 */
export const getSavedReport = async (
	token: string = '',
	reportId: string
): Promise<{
	success: boolean;
	report: SavedReportFull;
}> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/analysis/reasoning/report/saved/${encodeURIComponent(reportId)}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				...(token && { authorization: `Bearer ${token}` })
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('getSavedReport error:', err);
			throw err.detail ?? 'Failed to get saved report';
		});

	return res;
};

/**
 * Delete a saved report by ID
 */
export const deleteSavedReport = async (
	token: string = '',
	reportId: string
): Promise<{
	success: boolean;
	message: string;
}> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/analysis/reasoning/report/saved/${encodeURIComponent(reportId)}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				...(token && { authorization: `Bearer ${token}` })
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error('deleteSavedReport error:', err);
			throw err.detail ?? 'Failed to delete saved report';
		});

	return res;
};
