"use client";

import { API_BASE } from "@/utils/api";
import { useCallback, useEffect, useState } from "react";

const POLL_MS = 20000;

/**
 * Shows a full-width banner when the FastAPI backend (proxied at /api/health) is unreachable.
 */
export function BackendStatusBanner() {
	const [ok, setOk] = useState<boolean | null>(null);
	const [restarting, setRestarting] = useState(false);
	const [isTauri, setIsTauri] = useState(false);

	const check = useCallback(async () => {
		try {
			const res = await fetch(`${API_BASE}/health`, {
				cache: "no-store",
				method: "GET",
			});
			setOk(res.ok);
		} catch {
			setOk(false);
		}
	}, []);

	useEffect(() => {
		void check();
		const id = setInterval(() => void check(), POLL_MS);
		return () => clearInterval(id);
	}, [check]);

	// Tauri emits "backend-status" (ready / error: ...) — listen for a faster
	// signal than the HTTP poll, and detect whether we're running in the
	// desktop app at all (the Restart button only makes sense there).
	useEffect(() => {
		let unlisten: (() => void) | undefined;
		let cancelled = false;
		import("@tauri-apps/api/event")
			.then(async ({ listen }) => {
				if (cancelled) return;
				setIsTauri(true);
				unlisten = await listen<string>("backend-status", (event) => {
					setOk(event.payload === "ready");
				});
			})
			.catch(() => {
				// Not running inside Tauri (plain browser dev) — HTTP poll above covers it.
			});
		return () => {
			cancelled = true;
			unlisten?.();
		};
	}, []);

	const handleRestart = async () => {
		setRestarting(true);
		try {
			const { invoke } = await import("@tauri-apps/api/core");
			await invoke("start_backend");
		} catch {
			// Not running in Tauri, or the command failed — the poll above will
			// keep reflecting the real state either way.
		} finally {
			setRestarting(false);
		}
	};

	if (ok === null || ok === true) {
		return null;
	}

	return (
		<output
			aria-live="polite"
			className="flex w-full flex-wrap items-center justify-center gap-3 border-b border-amber-800/60 bg-amber-950/90 px-4 py-2 text-center text-sm text-amber-100"
		>
			<span>
				<strong className="font-semibold">Backend offline.</strong> Start the FastAPI server on port{" "}
				<strong>10740</strong> (e.g.{" "}
				<code className="rounded bg-slate-900/80 px-1">webapp/start.ps1</code> or{" "}
				<code className="rounded bg-slate-900/80 px-1">uvicorn</code>
				). Search, settings, and API-driven features will fail until the API is up.
			</span>
			{isTauri && (
				<button
					type="button"
					onClick={handleRestart}
					disabled={restarting}
					data-testid="restart-backend"
					className="rounded-lg border border-amber-700/60 bg-amber-900/60 px-3 py-1 text-xs font-medium text-amber-100 hover:bg-amber-900 disabled:opacity-50"
				>
					{restarting ? "Restarting…" : "Restart Backend"}
				</button>
			)}
		</output>
	);
}
