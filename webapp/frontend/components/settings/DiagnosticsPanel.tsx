"use client";

import { getDiagnostics } from "@/utils/api";
import type { DiagnosticCheck, DiagnosticStatus } from "@/utils/api";
import { useCallback, useEffect, useState } from "react";

const STATUS_DOT: Record<DiagnosticStatus, string> = {
	ok: "bg-emerald-500",
	warn: "bg-amber",
	error: "bg-red-500",
	info: "bg-slate-500",
};

const STATUS_LABEL: Record<DiagnosticStatus, string> = {
	ok: "OK",
	warn: "Needs attention",
	error: "Failed",
	info: "Not configured",
};

function CheckRow({ check }: { check: DiagnosticCheck }) {
	return (
		<div className="flex items-start gap-3 py-2.5" data-testid={`diagnostic-${check.id}`}>
			<span
				className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_DOT[check.status]}`}
				aria-hidden="true"
			/>
			<div className="min-w-0 flex-1">
				<div className="flex flex-wrap items-baseline gap-x-2">
					<span className="text-sm font-medium text-slate-200">{check.label}</span>
					<span className="text-xs text-slate-500">{STATUS_LABEL[check.status]}</span>
				</div>
				<p className="text-sm text-slate-400 mt-0.5">{check.message}</p>
			</div>
		</div>
	);
}

export function DiagnosticsPanel() {
	const [checks, setChecks] = useState<DiagnosticCheck[] | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [lastChecked, setLastChecked] = useState<Date | null>(null);

	const runChecks = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const result = await getDiagnostics();
			setChecks(result.checks);
			setLastChecked(new Date());
		} catch (e) {
			setError(e instanceof Error ? e.message : "Could not run diagnostics");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void runChecks();
	}, [runChecks]);

	return (
		<section
			className="rounded-xl glass-panel border border-slate-600/50 p-6"
			data-testid="diagnostics-panel"
		>
			<div className="flex items-center justify-between gap-4 mb-2">
				<h2 className="text-lg font-semibold text-amber">Diagnostics</h2>
				<button
					type="button"
					onClick={() => void runChecks()}
					disabled={loading}
					data-testid="diagnostics-recheck"
					className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 text-xs font-medium hover:bg-slate-600 disabled:opacity-50 border border-slate-600/50"
				>
					{loading ? "Checking..." : "Re-check"}
				</button>
			</div>
			<p className="text-sm text-slate-500 mb-2">
				One place to see what's actually working right now, instead of hunting through separate
				pages for the error.
			</p>

			{error && <p className="text-amber text-sm mt-2">{error}</p>}

			{checks && (
				<div className="mt-2 divide-y divide-slate-700/50">
					{checks.map((check) => (
						<CheckRow key={check.id} check={check} />
					))}
				</div>
			)}

			{!checks && loading && <p className="text-slate-500 text-sm mt-2">Running checks...</p>}

			{lastChecked && (
				<p className="text-xs text-slate-600 mt-3">
					Last checked {lastChecked.toLocaleTimeString()}
				</p>
			)}
		</section>
	);
}
