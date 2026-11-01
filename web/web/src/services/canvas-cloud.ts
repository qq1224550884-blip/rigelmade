import { nanoid } from "nanoid";
import { commercialRequest, readCommercialSession } from "./commercial-auth";
import { createCanvasArchive } from "@/lib/canvas/canvas-export";
import { readZip } from "@/lib/zip";
import { setImageBlob } from "./image-storage";
import { setMediaBlob } from "./file-storage";
import { useCanvasStore, type CanvasProject } from "@/stores/canvas/use-canvas-store";
import type { CanvasExportFile } from "@/types/canvas-export";

export type CloudCanvas = { id: string; title: string; revision: number; updatedAt: number; bytes: number; nodeCount: number };
export const listCloudCanvases = () => commercialRequest<{ items: CloudCanvas[] }>("/api/canvas/projects");

export async function saveCloudCanvas(project: CanvasProject) {
    const session = readCommercialSession();
    if (!session) throw new Error("请先登录，再保存到账号。");
    const bound = project.cloud?.owner === session.user.id ? project.cloud : undefined;
    const cloudId = bound?.id || project.id;
    // Only an explicit save associates this device-local project with an account.
    const snapshot = await createCanvasArchive([{ ...project, id: cloudId, cloud: undefined }], true);
    if (snapshot.size > 64 * 1024 * 1024) throw new Error("单个画布最多 64MB，请拆分项目后保存。");
    const form = new FormData();
    form.set("revision", String(bound?.revision || 0));
    form.set("snapshot", snapshot, "canvas.zip");
    if (readCommercialSession()?.user.id !== session.user.id) throw new Error("登录账号已改变，未上传画布。请确认当前账号后重试。");
    const result = await commercialRequest<CloudCanvas>(`/api/canvas/projects/${cloudId}`, { method: "PUT", body: form, headers: { Authorization: `Bearer ${session.token}` } });
    if (readCommercialSession()?.user.id !== session.user.id) throw new Error("登录账号已改变，请重新打开账号画布列表确认保存结果。");
    useCanvasStore.getState().updateProject(project.id, { cloud: { owner: session.user.id, id: cloudId, revision: result.revision, savedAt: project.updatedAt } });
    return result;
}

export async function openCloudCanvas(item: CloudCanvas) {
    const session = readCommercialSession();
    if (!session) throw new Error("请先登录。");
    const response = await fetch(`/api/canvas/projects/${item.id}`, { headers: { Authorization: `Bearer ${session.token}` }, cache: "no-store" });
    if (!response.ok) throw new Error("读取账号画布失败，请刷新列表或重新登录。");
    const revision = Number(response.headers.get("X-Canvas-Revision"));
    const archive = await readZip(await response.blob());
    const manifest = archive.get("projects.json");
    if (!manifest) throw new Error("账号画布缺少项目文档。");
    const data = JSON.parse(await manifest.text()) as CanvasExportFile;
    const entry = data.projects[0];
    if (!entry || data.version !== 3 || entry.project.id !== item.id) throw new Error("账号画布格式无效。");
    const keyMap = new Map<string, string>();
    for (const file of entry.files) {
        const raw = archive.get(file.path);
        if (!raw || raw.size !== file.bytes) throw new Error("账号画布的原图不完整，未替换本地项目。");
        const key = `${file.storageKey.split(":")[0]}:${nanoid()}`;
        const blob = raw.slice(0, raw.size, file.mimeType);
        await (key.startsWith("image:") ? setImageBlob(key, blob) : setMediaBlob(key, blob));
        keyMap.set(file.storageKey, key);
    }
    const remap = (value: unknown): unknown => {
        if (typeof value === "string") return keyMap.get(value) || (value.startsWith("blob:") ? "" : value);
        if (Array.isArray(value)) return value.map(remap);
        if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, val]) => [key, remap(val)]));
        return value;
    };
    if (readCommercialSession()?.user.id !== session.user.id) throw new Error("登录账号已改变，请重新打开画布。");
    // Open a local copy so an unsaved local project is never overwritten.
    const store = useCanvasStore.getState();
    const id = store.importProject(remap(entry.project) as CanvasProject);
    const restored = useCanvasStore.getState().openProject(id)!;
    store.updateProject(id, { cloud: { owner: session.user.id, id: item.id, revision, savedAt: restored.updatedAt } });
    return id;
}
