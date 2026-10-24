import axios from "axios";
import { create } from "zustand";
import { nanoid } from "nanoid";
import { commercialRequest } from "@/services/commercial-auth";

export type GenerationJob = {
    jobId?: string;
    taskKey: string;
    model: string;
    stage?: string;
    status?: string;
    startedAt?: number;
    updatedAt?: number;
    elapsedSeconds?: number;
    durations?: Record<string, number>;
    reusedImages?: number;
    canRecover?: boolean;
    error?: string;
    data?: Array<{ url: string }>;
};

export const useGenerationJobs = create<{ jobs: Record<string, GenerationJob>; update: (job: GenerationJob) => void; clear: () => void }>((set) => ({
    jobs: {},
    update: (job) => set((state) => ({ jobs: Object.fromEntries(Object.entries({ ...state.jobs, [job.taskKey]: { ...state.jobs[job.taskKey], ...job } }).slice(-20)) })),
    clear: () => set({ jobs: {} }),
}));

export class GenerationJobError extends Error {
    constructor(message: string, public taskKey: string, public recoverable = true) {
        super(message);
    }
}

export function isWorkbenchImageApi(url: string) {
    const parsed = new URL(url, location.href);
    return parsed.origin === location.origin && /^\/v1\/images\/(generations|edits)$/.test(parsed.pathname);
}

function updateJob(job: GenerationJob) {
    useGenerationJobs.getState().update(job);
    return job;
}

async function waitForJob(taskKey: string, signal?: AbortSignal, stopOnPending = false) {
    let consecutiveErrors = 0;
    while (true) {
        if (signal?.aborted) throw new GenerationJobError("已停止等待，原任务仍保留；可继续取图，不会重复生图", taskKey);
        let job: GenerationJob;
        try {
            job = updateJob(await commercialRequest<GenerationJob>(`/api/generation-jobs/by-key/${encodeURIComponent(taskKey)}`));
            consecutiveErrors = 0;
        } catch {
            if (++consecutiveErrors >= 5) throw new GenerationJobError("任务状态暂时无法读取，原任务已保留；请继续取图，不要重复生成", taskKey);
            await new Promise((resolve) => setTimeout(resolve, 1500));
            continue;
        }
        if (job.status === "failed") throw new GenerationJobError(job.error || "生成失败，本站积分已退回", taskKey, false);
        if (job.status === "succeeded" && job.data?.length) return { data: job.data };
        if (job.canRecover && stopOnPending) throw new GenerationJobError(job.error || "取图暂未完成，可继续重试原图下载", taskKey);
        // Await a deliberate recover action after automatic download retries are exhausted.
        await new Promise((resolve) => setTimeout(resolve, job.canRecover ? 2000 : 1000));
    }
}

export async function requestWorkbenchImage(url: string, body: unknown, headers: Record<string, string>, options?: { signal?: AbortSignal; onTask?: (key: string) => void }) {
    const taskKey = nanoid();
    const model = body instanceof FormData ? String(body.get("model") || "") : String((body as { model?: string }).model || "");
    updateJob({ taskKey, model, stage: "uploading_request", startedAt: Date.now() / 1000 });
    options?.onTask?.(taskKey);
    try {
        const response = await axios.post(url, body, { headers: { ...headers, Prefer: "respond-async", "X-Idempotency-Key": taskKey }, signal: options?.signal });
        if (!response.data?.jobId) return response.data;
        updateJob(response.data);
    } catch (error) {
        if (axios.isAxiosError(error) && error.response && error.response.status < 500) {
            updateJob({ taskKey, model, stage: "failed", status: "failed", error: "请求未被接受" });
            const detail = error.response.data?.detail;
            throw new GenerationJobError(typeof detail === "string" ? detail : detail?.message || "请求未被接受", taskKey, false);
        }
        // A lost POST response is resolved by its key; never submit another generation.
        updateJob({ taskKey, model, stage: "checking", error: "连接中断，正在查询原任务" });
    }
    return waitForJob(taskKey, options?.signal);
}

export async function recoverGenerationImage(taskKey: string, signal?: AbortSignal) {
    const job = updateJob(await commercialRequest<GenerationJob>(`/api/generation-jobs/by-key/${encodeURIComponent(taskKey)}`));
    if (job.canRecover && job.jobId) {
        updateJob(await commercialRequest<GenerationJob>(`/api/generation-jobs/${job.jobId}/recover`, { method: "POST" }));
    }
    return waitForJob(taskKey, signal, true);
}

export function generationErrorMetadata(error: unknown) {
    return error instanceof GenerationJobError ? { generationTaskKey: error.recoverable ? error.taskKey : undefined } : {};
}

export async function refreshGenerationJobs() {
    const result = await commercialRequest<{ items: GenerationJob[] }>("/api/generation-jobs");
    result.items.forEach(updateJob);
}
