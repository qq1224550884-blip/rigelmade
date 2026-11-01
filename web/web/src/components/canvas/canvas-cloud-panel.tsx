import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { App, Button, Empty, Modal, Popconfirm, Spin } from "antd";
import { Cloud, CloudUpload, RefreshCw } from "lucide-react";
import { listCloudCanvases, openCloudCanvas, saveCloudCanvas, type CloudCanvas } from "@/services/canvas-cloud";
import { commercialRequest, readCommercialSession } from "@/services/commercial-auth";
import type { CanvasProject } from "@/stores/canvas/use-canvas-store";

export function CanvasCloudPanel({ project }: { project?: CanvasProject }) {
    const { message } = App.useApp();
    const navigate = useNavigate();
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [saving, setSaving] = useState(false);
    const [items, setItems] = useState<CloudCanvas[]>([]);
    const [error, setError] = useState("");
    const bound = project?.cloud?.owner === readCommercialSession()?.user.id ? project?.cloud : undefined;
    const saved = bound && bound.savedAt === project?.updatedAt;
    const fail = (error: unknown) => message.error(error instanceof Error ? error.message : "账号画布操作失败，请重试。");
    const load = async () => {
        setBusy(true);
        setError("");
        try { setItems((await listCloudCanvases()).items); }
        catch (error) { setError(error instanceof Error ? error.message : "读取失败，请重试。"); }
        finally { setBusy(false); }
    };
    const save = async () => {
        if (!project || saving) return;
        setSaving(true);
        try { await saveCloudCanvas(project); message.success("画布和原图已保存到当前账号，可在其他电脑打开。"); }
        catch (error) { fail(error); }
        finally { setSaving(false); }
    };
    const restore = async (item: CloudCanvas) => {
        setBusy(true);
        try { const id = await openCloudCanvas(item); setOpen(false); navigate(`/canvas/${id}`); }
        catch (error) { fail(error); }
        finally { setBusy(false); }
    };
    const remove = async (item: CloudCanvas) => {
        setBusy(true);
        try { await commercialRequest(`/api/canvas/projects/${item.id}?revision=${item.revision}`, { method: "DELETE" }); await load(); }
        catch (error) { fail(error); setBusy(false); }
    };
    return <>
        {project ? <Button type="text" size="small" icon={<CloudUpload className="size-4" />} loading={saving} onClick={() => void save()} title={saved ? "已保存到账号" : "保存当前画布及原图到登录账号"} aria-label="保存到账号"><span className="hidden sm:inline">{saved ? "已保存到账号" : "保存到账号"}</span></Button> : null}
        <Button type="text" size="small" icon={<Cloud className="size-4" />} aria-label="账号画布" onClick={() => { setOpen(true); void load(); }}><span className="hidden sm:inline">账号画布</span></Button>
        <Modal title="账号画布" open={open} onCancel={() => setOpen(false)} footer={null} width={760} destroyOnHidden>
            <p className="mb-4 text-sm opacity-70">保存包含节点、批注和原图。打开时创建本地副本，保留本机未保存的内容。编辑后请再次点击“保存到账号”。</p>
            <Button type="text" icon={<RefreshCw className="size-4" />} onClick={() => void load()} disabled={busy}>刷新列表</Button>
            {error ? <p role="alert" className="py-4">{error}</p> : null}
            <Spin spinning={busy}>
                {!items.length && !error ? <Empty description="账号中还没有画布；打开本地画布后点击保存到账号。" /> : items.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-current/10 py-4">
                    <div className="min-w-0 flex-1"><div className="truncate font-medium">{item.title}</div><div className="mt-1 text-xs opacity-60">{item.nodeCount} 个节点 · {(item.bytes / 1048576).toFixed(1)} MB · {new Date(item.updatedAt).toLocaleString()} · 版本 {item.revision}</div></div>
                    <Button disabled={busy} onClick={() => void restore(item)}>打开副本</Button>
                    <Popconfirm title="删除账号中的画布？" description="本机副本会保留。云端原图会一起删除。" onConfirm={() => remove(item)}><Button type="text" danger disabled={busy}>删除</Button></Popconfirm>
                </div>)}
            </Spin>
            <p className="mt-4 text-xs opacity-60">每个画布最多 64MB，账号共 512MB；仅当前账号可读取。断网时仍可在本机编辑。</p>
        </Modal>
    </>;
}
