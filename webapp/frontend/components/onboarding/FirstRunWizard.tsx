"use client";

import {
	createPlexPin,
	getDiagnostics,
	getLlmProviders,
	pollPlexPin,
	saveLlmProviderKey,
	testPlexConnection,
	updateSettings,
} from "@/utils/api";
import type { LlmProviderInfo } from "@/utils/api";
import { useCallback, useEffect, useRef, useState } from "react";

const ONBOARDED_KEY = "plex-onboarded";
const PIN_POLL_MS = 2000;
const PIN_TIMEOUT_MS = 5 * 60 * 1000;

type Step = "plex" | "llm" | "done";

function markOnboarded() {
	try {
		localStorage.setItem(ONBOARDED_KEY, "1");
	} catch {
		/* private mode / quota - the wizard will just show again next time */
	}
}

function alreadyOnboarded(): boolean {
	try {
		return localStorage.getItem(ONBOARDED_KEY) === "1";
	} catch {
		return false;
	}
}

export function FirstRunWizard() {
	const [visible, setVisible] = useState(false);
	const [checked, setChecked] = useState(false);
	const [step, setStep] = useState<Step>("plex");

	// --- Plex step state (mirrors Settings -> Plex) ---
	const [plexUrl, setPlexUrl] = useState("http://127.0.0.1:32400");
	const [plexToken, setPlexToken] = useState("");
	const [plexTesting, setPlexTesting] = useState(false);
	const [plexResult, setPlexResult] = useState<{ ok: boolean; text: string } | null>(null);
	const [pinFlow, setPinFlow] = useState<{
		status: "idle" | "waiting" | "error";
		message?: string;
	}>({
		status: "idle",
	});
	const pinPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const pinTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	// --- LLM step state ---
	const [llmProviders, setLlmProviders] = useState<LlmProviderInfo[]>([]);
	const [llmProvider, setLlmProvider] = useState("ollama");
	const [llmApiKey, setLlmApiKey] = useState("");
	const [llmSaving, setLlmSaving] = useState(false);
	const [llmMessage, setLlmMessage] = useState<string | null>(null);

	const stopPinPoll = useCallback(() => {
		if (pinPollRef.current != null) {
			clearInterval(pinPollRef.current);
			pinPollRef.current = null;
		}
		if (pinTimeoutRef.current != null) {
			clearTimeout(pinTimeoutRef.current);
			pinTimeoutRef.current = null;
		}
	}, []);

	useEffect(() => {
		if (alreadyOnboarded()) {
			setChecked(true);
			return;
		}
		let cancelled = false;
		(async () => {
			try {
				const diag = await getDiagnostics();
				const plexCheck = diag.checks.find((c) => c.id === "plex");
				if (!cancelled) {
					if (plexCheck && plexCheck.status !== "ok") {
						setVisible(true);
					} else {
						// Plex already works - an existing setup, not a fresh
						// install. Don't nag someone who's already up and running.
						markOnboarded();
					}
				}
			} catch {
				// Backend not reachable yet - don't block on it; the wizard
				// will show on next load once diagnostics actually respond.
			} finally {
				if (!cancelled) setChecked(true);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => () => stopPinPoll(), [stopPinPoll]);

	useEffect(() => {
		if (!visible) return;
		getLlmProviders()
			.then((d) => setLlmProviders(d.providers))
			.catch(() => setLlmProviders([]));
	}, [visible]);

	const handleTestPlex = async () => {
		setPlexTesting(true);
		setPlexResult(null);
		try {
			const result = await testPlexConnection({
				plex_url: plexUrl.trim() || undefined,
				plex_token: plexToken.trim() || undefined,
			});
			setPlexResult({ ok: result.success, text: result.message });
			if (result.success && plexToken.trim()) {
				await updateSettings({ plex_url: plexUrl.trim(), plex_token: plexToken.trim() });
			}
		} catch (e) {
			setPlexResult({ ok: false, text: e instanceof Error ? e.message : "Test failed" });
		} finally {
			setPlexTesting(false);
		}
	};

	const handleGetToken = async () => {
		stopPinPoll();
		setPlexResult(null);
		setPinFlow({ status: "waiting", message: "Requesting a code from plex.tv..." });
		try {
			const pin = await createPlexPin();
			if (!pin.success || !pin.data) {
				setPinFlow({ status: "error", message: pin.message });
				return;
			}
			const { pin_id, client_id, auth_url } = pin.data;
			window.open(auth_url, "_blank", "noopener,noreferrer");
			setPinFlow({
				status: "waiting",
				message: "Sign in and approve access in the tab that opened...",
			});

			pinPollRef.current = setInterval(async () => {
				try {
					const poll = await pollPlexPin(pin_id, client_id);
					if (poll.success && poll.data?.authorized) {
						stopPinPoll();
						setPinFlow({ status: "idle" });
						setPlexResult({ ok: true, text: "Token saved. Testing connection..." });
						await handleTestPlex();
					} else if (!poll.success) {
						stopPinPoll();
						setPinFlow({ status: "error", message: poll.message });
					}
				} catch (e) {
					stopPinPoll();
					setPinFlow({ status: "error", message: e instanceof Error ? e.message : "Poll failed" });
				}
			}, PIN_POLL_MS);

			pinTimeoutRef.current = setTimeout(() => {
				stopPinPoll();
				setPinFlow((prev) =>
					prev.status === "waiting" ? { status: "error", message: "Timed out. Try again." } : prev,
				);
			}, PIN_TIMEOUT_MS);
		} catch (e) {
			setPinFlow({
				status: "error",
				message: e instanceof Error ? e.message : "Could not start sign-in",
			});
		}
	};

	const handleSaveLlm = async () => {
		setLlmSaving(true);
		setLlmMessage(null);
		try {
			const info = llmProviders.find((p) => p.id === llmProvider);
			if (info?.kind === "cloud" && llmApiKey.trim()) {
				await saveLlmProviderKey(llmProvider, llmApiKey.trim());
			}
			await updateSettings({ llm_provider: llmProvider });
			setLlmMessage("Saved.");
			setStep("done");
		} catch (e) {
			setLlmMessage(e instanceof Error ? e.message : "Save failed");
		} finally {
			setLlmSaving(false);
		}
	};

	const handleFinish = () => {
		markOnboarded();
		setVisible(false);
	};

	const handleSkip = () => {
		markOnboarded();
		setVisible(false);
	};

	if (!checked || !visible) {
		return null;
	}

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
			role="dialog"
			aria-modal="true"
			aria-label="First-run setup"
			data-testid="first-run-wizard"
		>
			<div className="w-full max-w-lg rounded-2xl glass-panel-strong border border-slate-600/50 p-6">
				<div className="flex items-center justify-between mb-4">
					<h2 className="text-lg font-semibold text-amber">
						{step === "plex" && "Welcome - connect Plex"}
						{step === "llm" && "Optional: pick an AI provider"}
						{step === "done" && "You're set up"}
					</h2>
					<button
						type="button"
						onClick={handleSkip}
						data-testid="wizard-skip"
						className="text-xs text-slate-500 hover:text-slate-300"
					>
						Skip for now
					</button>
				</div>

				<div className="flex gap-1.5 mb-5">
					{(["plex", "llm", "done"] as Step[]).map((s) => (
						<div
							key={s}
							className={`h-1 flex-1 rounded-full ${
								s === step
									? "bg-amber"
									: step === "done" || (step === "llm" && s === "plex")
										? "bg-emerald-600"
										: "bg-slate-700"
							}`}
						/>
					))}
				</div>

				{step === "plex" && (
					<div className="space-y-3">
						<p className="text-sm text-slate-400">
							Plex MCP needs to reach your Plex Media Server. Sign in for a token, or paste one you
							already have.
						</p>
						<div>
							<label className="block text-xs text-slate-400 mb-1">Plex URL</label>
							<input
								type="url"
								value={plexUrl}
								onChange={(e) => setPlexUrl(e.target.value)}
								className="w-full px-3 py-2 rounded-lg glass-panel border border-slate-600/50 text-slate-200 text-sm"
							/>
						</div>
						<div>
							<label className="block text-xs text-slate-400 mb-1">
								Plex token (optional here)
							</label>
							<input
								type="password"
								value={plexToken}
								onChange={(e) => setPlexToken(e.target.value)}
								placeholder="Paste a token, or use Sign in with Plex below"
								className="w-full px-3 py-2 rounded-lg glass-panel border border-slate-600/50 text-slate-200 placeholder-slate-500 text-sm"
							/>
						</div>
						<div className="flex flex-wrap gap-2">
							<button
								type="button"
								onClick={() => void handleGetToken()}
								disabled={pinFlow.status === "waiting"}
								data-testid="wizard-plex-signin"
								className="px-4 py-2 rounded-lg bg-amber text-slate-900 text-sm font-medium hover:bg-amber/90 disabled:opacity-50"
							>
								{pinFlow.status === "waiting" ? "Waiting for approval..." : "Sign in with Plex"}
							</button>
							<button
								type="button"
								onClick={() => void handleTestPlex()}
								disabled={plexTesting}
								data-testid="wizard-plex-test"
								className="px-4 py-2 rounded-lg bg-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-600 disabled:opacity-50 border border-slate-600/50"
							>
								{plexTesting ? "Testing..." : "Test connection"}
							</button>
						</div>
						{plexResult && (
							<p className={plexResult.ok ? "text-emerald-400 text-sm" : "text-amber text-sm"}>
								{plexResult.text}
							</p>
						)}
						{pinFlow.status !== "idle" && (
							<p
								className={
									pinFlow.status === "error" ? "text-amber text-sm" : "text-slate-400 text-sm"
								}
							>
								{pinFlow.message}
							</p>
						)}
						<div className="flex justify-end pt-2">
							<button
								type="button"
								onClick={() => setStep("llm")}
								disabled={!plexResult?.ok}
								data-testid="wizard-plex-next"
								className="px-4 py-2 rounded-lg bg-amber text-slate-900 text-sm font-medium hover:bg-amber/90 disabled:opacity-40"
							>
								Next
							</button>
						</div>
					</div>
				)}

				{step === "llm" && (
					<div className="space-y-3">
						<p className="text-sm text-slate-400">
							Chat and recommendations need an LLM. Use a free local engine (Ollama) if you have one
							running, or a cloud provider if you don't have a capable GPU - both work.
						</p>
						<div>
							<label className="block text-xs text-slate-400 mb-1">Provider</label>
							<select
								value={llmProvider}
								onChange={(e) => {
									setLlmProvider(e.target.value);
									setLlmApiKey("");
								}}
								className="w-full px-3 py-2 rounded-lg glass-panel border border-slate-600/50 text-slate-200 text-sm"
							>
								<optgroup label="Local (needs a running engine)">
									<option value="ollama">Ollama</option>
									<option value="lmstudio">LM Studio</option>
									<option value="vllm">vLLM</option>
								</optgroup>
								<optgroup label="Cloud (no GPU required)">
									<option value="openai">OpenAI</option>
									<option value="anthropic">Anthropic</option>
									<option value="deepseek">DeepSeek</option>
									<option value="openrouter">OpenRouter</option>
								</optgroup>
							</select>
						</div>
						{llmProviders.find((p) => p.id === llmProvider)?.kind === "cloud" && (
							<div>
								<label className="block text-xs text-slate-400 mb-1">API key</label>
								<input
									type="password"
									value={llmApiKey}
									onChange={(e) => setLlmApiKey(e.target.value)}
									placeholder="Paste your API key"
									className="w-full px-3 py-2 rounded-lg glass-panel border border-slate-600/50 text-slate-200 placeholder-slate-500 text-sm"
								/>
							</div>
						)}
						{llmMessage && <p className="text-amber text-sm">{llmMessage}</p>}
						<div className="flex justify-between pt-2">
							<button
								type="button"
								onClick={() => setStep("plex")}
								className="px-4 py-2 rounded-lg bg-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-600 border border-slate-600/50"
							>
								Back
							</button>
							<div className="flex gap-2">
								<button
									type="button"
									onClick={() => setStep("done")}
									className="px-4 py-2 rounded-lg bg-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-600 border border-slate-600/50"
								>
									Skip this step
								</button>
								<button
									type="button"
									onClick={() => void handleSaveLlm()}
									disabled={llmSaving}
									data-testid="wizard-llm-save"
									className="px-4 py-2 rounded-lg bg-amber text-slate-900 text-sm font-medium hover:bg-amber/90 disabled:opacity-50"
								>
									{llmSaving ? "Saving..." : "Save & continue"}
								</button>
							</div>
						</div>
					</div>
				)}

				{step === "done" && (
					<div className="space-y-4">
						<p className="text-sm text-slate-400">
							You're ready to go. Visit <strong className="text-slate-300">Settings</strong> any
							time to change these, run <strong className="text-slate-300">Diagnostics</strong> if
							something looks off, or start browsing your library now.
						</p>
						<div className="flex justify-end">
							<button
								type="button"
								onClick={handleFinish}
								data-testid="wizard-finish"
								className="px-5 py-2.5 rounded-lg bg-amber text-slate-900 text-sm font-medium hover:bg-amber/90"
							>
								Go to Dashboard
							</button>
						</div>
					</div>
				)}
			</div>
		</div>
	);
}
