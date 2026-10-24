import { useEffect, useState } from "react";
import { Button, theme } from "antd";
import { Download, RefreshCw } from "lucide-react";
import { readCommercialSession } from "@/services/commercial-auth";
import { recoverGenerationImage, refreshGenerationJobs, useGenerationJobs } from "@/services/generation-jobs";

const labels: Record<string, string> = { uploading_request: "发送图片", preparing: "准备参考图", uploading: "上传参考图", submitting: "提交任务", waiting: "上游排队 / 生成", checking: "查询原任务", downloading: "下载原图", validating: "校验与保存", recovering: "恢复原任务", awaiting_recovery: "原任务已保留，等待继续取图", completed: "原图已保存", failed: "任务未完成" };

export function GenerationProgress() {
    const { token } = theme.useToken();
    const jobs = useGenerationJobs((state) => state.jobs);
    const [clock, setClock] = useState(Date.now());
    const [recovering, setRecovering] = useState<string[]>([]);
    const [owner, setOwner] = useState(readCommercialSession()?.user.id);
    useEffect(() => {
        const timer = window.setInterval(() => {
            setClock(Date.now());
            const id = readCommercialSession()?.user.id;
            if (id !== owner) {
                useGenerationJobs.getState().clear();
                setOwner(id);
            }
        }, 1000);
        if (owner) void refreshGenerationJobs().catch(() => {});
        const refresh = window.setInterval(() => { if (readCommercialSession()) void refreshGenerationJobs().catch(() => {}); }, 5000);
        return () => { window.clearInterval(timer); window.clearInterval(refresh); };
    }, [owner]);
    const visible = Object.values(jobs).filter((job) => job.stage !== "failed" && (job.stage !== "completed" || clock / 1000 - (job.updatedAt || 0) < 15)).slice(-3);
    if (!owner || !visible.length) return null;
    return <aside data-generation-progress className="fixed right-3 top-20 z-[90] w-[min(320px,calc(100vw-24px))] space-y-2 rounded-xl border p-3 text-sm" style={{ background: token.colorBgElevated, borderColor: token.colorBorder, color: token.colorText }} aria-live="polite">
        {visible.map((job) => {
            const elapsed = Math.max(0, Math.round((job.elapsedSeconds || 0) + (job.status === "reserved" && job.updatedAt ? clock / 1000 - job.updatedAt : 0)));
            return <div key={job.taskKey} className="space-y-1.5">
                <div className="flex justify-between gap-3"><span>{labels[job.stage || ""] || "等待处理"}</span><span className="shrink-0 tabular-nums">{elapsed}秒</span></div>
                <div className="truncate text-xs" style={{ color: token.colorTextSecondary }}>{job.model}{job.reusedImages ? ` · 已复用 ${job.reusedImages} 张参考图` : ""}</div>
                {job.durations ? <div className="flex flex-wrap gap-x-3 text-xs" style={{ color: token.colorTextSecondary }}>{["uploading", "waiting", "downloading"].filter((stage) => job.durations?.[stage] != null).map((stage) => <span key={stage}>{labels[stage]} {Math.round(job.durations![stage])}秒</span>)}</div> : null}
                {job.canRecover ? <div><div className="mb-1 text-xs">原任务已保留，继续取图不重复扣费。</div><Button size="small" icon={<RefreshCw className="size-3" />} loading={recovering.includes(job.taskKey)} onClick={() => {
                    setRecovering((keys) => [...keys, job.taskKey]);
                    void recoverGenerationImage(job.taskKey).catch(() => {}).finally(() => setRecovering((keys) => keys.filter((key) => key !== job.taskKey)));
                }}>继续取图</Button></div> : null}
                {job.stage === "completed" ? job.data?.map((image, index) => <a className="mr-3 inline-flex items-center gap-1 text-xs underline" key={image.url} href={image.url} download><Download className="size-3" />下载原图{job.data!.length > 1 ? index + 1 : ""}</a>) : null}
            </div>;
        })}
    </aside>;
}
