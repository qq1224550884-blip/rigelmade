import { useEffect, useRef, useState, type PointerEvent } from "react";
import { App, Button, Checkbox, Empty, Input, Modal, Segmented, Select, Tabs } from "antd";
import { Columns2, Pencil, Trash2, Undo2 } from "lucide-react";
import { nanoid } from "nanoid";
import { CanvasNodeType, type CanvasConnection, type CanvasNodeData, type CanvasNodeMetadata } from "@/types/canvas";
import type { CanvasProject } from "@/stores/canvas/use-canvas-store";
import { uploadImage } from "@/services/image-storage";
import { createCanvasNode, imageMetadata } from "@/lib/canvas/canvas-node-factory";
import { canvasThemes } from "@/lib/canvas-theme";
import { imageAspectRatio, imageSizeForQuality } from "@/lib/image-resolution";
import { useThemeStore } from "@/stores/use-theme-store";
import { CanvasCloudPanel } from "./canvas-cloud-panel";

type Mark = NonNullable<CanvasNodeMetadata["annotations"]>[number];
type Props = { project: CanvasProject; selectedIds: Set<string>; onApply: (nodes: CanvasNodeData[], connections: CanvasConnection[], selectId?: string) => void };
const clamp = (n: number) => Math.max(0, Math.min(1, n));

export function CanvasStudioTools({ project, selectedIds, onApply }: Props) {
    const theme = canvasThemes[useThemeStore((state) => state.theme)];
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const [tab, setTab] = useState("annotation");
    const [baseId, setBaseId] = useState("");
    const [annotationId, setAnnotationId] = useState<string>();
    const [materialIds, setMaterialIds] = useState<string[]>([]);
    const [marks, setMarks] = useState<Mark[]>([]);
    const [notes, setNotes] = useState("");
    const [lockOutside, setLockOutside] = useState(false);
    const [draft, setDraft] = useState<Mark | null>(null);
    const [busy, setBusy] = useState(false);
    const [compareA, setCompareA] = useState("");
    const [compareB, setCompareB] = useState("");
    const [compareMode, setCompareMode] = useState("slider");
    const [split, setSplit] = useState(50);
    const start = useRef<{ x: number; y: number } | null>(null);
    const uploadRef = useRef<HTMLInputElement>(null);
    const images = project.nodes.filter((node) => node.type === CanvasNodeType.Image && node.metadata?.content);
    const base = images.find((node) => node.id === baseId);
    const annotated = images.find((node) => node.id === annotationId);
    const a = images.find((node) => node.id === compareA), b = images.find((node) => node.id === compareB);
    const options = images.map((node) => ({ value: node.id, label: node.title || node.id }));
    useEffect(() => {
        setMarks(base?.metadata?.annotations || []);
        setNotes(base?.metadata?.annotationNotes || "");
        setLockOutside(Boolean(base?.metadata?.annotationLockOutside));
        setDraft(null);
    }, [baseId]);
    const launch = (nextTab: string) => {
        const selected = images.filter((node) => selectedIds.has(node.id));
        const right = selected[selected.length - 1] || images[images.length - 1];
        const original = images.find((node) => node.metadata?.storageKey === right?.metadata?.references?.[0]);
        setBaseId(selected[0]?.id || images[0]?.id || "");
        setCompareA(original?.id || selected[0]?.id || images[0]?.id || "");
        setCompareB(right?.id || "");
        setTab(nextTab);
        setOpen(true);
    };
    const point = (event: PointerEvent<HTMLDivElement>) => {
        const rect = event.currentTarget.getBoundingClientRect();
        return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) };
    };
    const down = (event: PointerEvent<HTMLDivElement>) => {
        if (event.button !== 0 || !base || marks.length >= 30) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = point(event);
        setDraft({ id: nanoid(), ...start.current, width: 0, height: 0, text: "" });
    };
    const move = (event: PointerEvent<HTMLDivElement>) => {
        if (!start.current) return;
        const end = point(event), from = start.current;
        setDraft((mark) => mark && ({ ...mark, x: Math.min(from.x, end.x), y: Math.min(from.y, end.y), width: Math.abs(end.x - from.x), height: Math.abs(end.y - from.y) }));
    };
    const up = (event: PointerEvent<HTMLDivElement>) => {
        if (!start.current) return;
        const end = point(event), from = start.current;
        const width = Math.max(.025, Math.abs(end.x - from.x)), height = Math.max(.025, Math.abs(end.y - from.y));
        setMarks((current) => [...current, { id: nanoid(), x: Math.min(1 - width, Math.min(from.x, end.x)), y: Math.min(1 - height, Math.min(from.y, end.y)), width, height, text: "" }]);
        start.current = null;
        setDraft(null);
    };
    const saveMarks = () => {
        if (!base) return;
        onApply(project.nodes.map((node) => node.id === base.id ? { ...node, metadata: { ...node.metadata, annotations: marks, annotationNotes: notes, annotationLockOutside: lockOutside } } : node), project.connections);
        message.success("批注位置和文字已保存在本机画布，原图未改变。");
    };
    const uploadAnnotation = async (file?: File) => {
        if (!file || !base) return;
        if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 10 * 1024 * 1024) { message.error("请选择不超过 10MB 的 PNG、JPG 或 WebP 批注图。"); return; }
        setBusy(true);
        try {
            const stored = await uploadImage(file);
            const node = createCanvasNode(CanvasNodeType.Image, { x: base.position.x + base.width / 2, y: base.position.y + base.height + 200 }, imageMetadata(stored));
            node.title = `批注图 · ${file.name}`;
            onApply([...project.nodes, node], project.connections);
            setAnnotationId(node.id);
        } catch (error) { message.error(error instanceof Error ? error.message : "批注图上传失败，请重试。"); }
        finally { setBusy(false); if (uploadRef.current) uploadRef.current.value = ""; }
    };
    const createTask = async () => {
        if (!base || busy) return;
        if (marks.some((mark) => !mark.text.trim())) { message.warning("请填写每个框选区域的修改要求。"); return; }
        if (!marks.length && !annotated && !notes.trim()) { message.warning("请框选并填写批注，选择已有批注图，或填写修改清单。"); return; }
        setBusy(true);
        try {
            const added: CanvasNodeData[] = [];
            let guide = annotated;
            if (marks.length) {
                const stored = await uploadImage(await renderAnnotation(base, marks));
                guide = createCanvasNode(CanvasNodeType.Image, { x: base.position.x + base.width / 2, y: base.position.y + base.height + 220 }, imageMetadata(stored));
                guide.title = `批注图 · ${base.title}`;
                added.push(guide);
            }
            const checklist = [notes.trim(), ...marks.map((mark, index) => `${index + 1}. 左${Math.round(mark.x * 100)}% 上${Math.round(mark.y * 100)}%，宽${Math.round(mark.width * 100)}% 高${Math.round(mark.height * 100)}%：${mark.text.trim()}`)].filter(Boolean).join("\n");
            const refs = [base, ...(guide ? [guide] : []), ...images.filter((node) => materialIds.includes(node.id) && node.id !== base.id && node.id !== guide?.id)];
            const task = createCanvasNode(CanvasNodeType.Image, { x: base.position.x + base.width + 320, y: base.position.y + base.height / 2 }, {
                count: 1,
                quality: "medium",
                size: imageSizeForQuality("medium", imageAspectRatio(`${base.metadata?.naturalWidth || base.width}x${base.metadata?.naturalHeight || base.height}`)),
                editMaskStorageKey: marks.length && lockOutside ? (await uploadImage(await renderRegionMask(base, marks))).storageKey : undefined,
                prompt: "请根据批注图和已核对的修改清单修改底图。逐项完成修改，保留未要求改变的空间、镜头和结构，输出干净的独立效果图。",
                annotationNotes: checklist,
                referenceOrder: refs.map((node) => node.id),
                referenceRoles: Object.fromEntries(refs.map((node, index) => [node.id, index === 0 ? "main" : node.id === guide?.id ? "annotation" : "material"])),
            });
            task.title = `批注改图 · ${base.title}`;
            const nodes = project.nodes.map((node) => node.id === base.id ? { ...node, metadata: { ...node.metadata, annotations: marks, annotationNotes: notes, annotationLockOutside: lockOutside } } : node);
            const edges = refs.map((node) => ({ id: nanoid(), fromNodeId: node.id, toNodeId: task.id }));
            onApply([...nodes, ...added, task], [...project.connections, ...edges], task.id);
            setOpen(false);
            message.success("已建立改图任务。检查图片用途、清单和模型后，点击生成。");
        } catch (error) { message.error(error instanceof Error ? error.message : "建立改图任务失败，请重试。"); }
        finally { setBusy(false); }
    };
    const annotationTab = <div className="space-y-4">
        <p className="text-sm opacity-70">选择干净底图，在图上拖出修改区域，再填写文字。也可上传已经画好箭头、涂鸦或文字的批注图。</p>
        <label className="block text-sm">干净底图<Select aria-label="干净底图" className="mt-1 w-full" value={baseId || undefined} onChange={(id) => { setBaseId(id); setAnnotationId(undefined); }} options={options} showSearch optionFilterProp="label" placeholder="先将底图导入画布" /></label>
        {base ? <div className="grid gap-4 md:grid-cols-[minmax(0,1.6fr)_minmax(240px,1fr)]">
            <div>
                <div className="relative cursor-crosshair select-none overflow-hidden rounded" style={{ touchAction: "none" }} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { start.current = null; setDraft(null); }}>
                    <img src={base.metadata?.content} alt="框选批注底图" draggable={false} className="pointer-events-none block w-full" />
                    {[...marks, ...(draft ? [draft] : [])].map((mark, index) => <div key={mark.id} className="pointer-events-none absolute border-2" style={{ left: `${mark.x * 100}%`, top: `${mark.y * 100}%`, width: `${mark.width * 100}%`, height: `${mark.height * 100}%`, borderColor: "#ef4444" }}><span className="absolute left-0 top-0 max-w-48 truncate px-1 text-xs" style={{ background: theme.node.panel, color: theme.node.text }}>{index + 1} {mark.text}</span></div>)}
                </div>
                <div className="mt-2 flex items-center gap-2"><Button type="text" icon={<Undo2 className="size-4" />} disabled={!marks.length} onClick={() => setMarks((current) => current.slice(0, -1))}>撤销框选</Button><span className="text-xs opacity-60">拖动框选，最多 30 处；坐标随原图保存。</span></div>
                <div className="mt-3 flex gap-2"><Select allowClear className="min-w-0 flex-1" aria-label="已有批注图" value={annotationId} onChange={setAnnotationId} options={options.filter((item) => item.value !== baseId)} placeholder="或选择画布中的批注图" /><Button onClick={() => uploadRef.current?.click()} loading={busy}>上传批注图</Button></div>
                {marks.length && annotated ? <p className="mt-2 text-xs opacity-70">本次使用新绘制的框选批注图；要使用上传图，请先撤销全部框选。</p> : null}
                {annotated && !marks.length ? <img src={annotated.metadata?.content} alt="待执行的批注图" className="mt-3 max-h-48 w-full object-contain" /> : null}
            </div>
            <div className="space-y-3">
                <div className="font-medium">修改清单</div>
                {base.metadata?.annotationPlan ? <details className="text-sm"><summary className="cursor-pointer">查看这张图的批注读取记录（{base.metadata.annotationPlan.edits.length}项）</summary><p className="mt-2 text-xs opacity-70">{base.metadata.annotationPlan.summary}</p><ol className="max-h-56 list-decimal space-y-2 overflow-y-auto py-2 pl-5">{base.metadata.annotationPlan.edits.map((edit, index) => <li key={index}>{edit.instruction}<div className="text-xs opacity-60">位置：{edit.location}；依据：{edit.evidence}</div></li>)}</ol>{base.metadata.annotationPlan.warnings.map((warning, index) => <p key={index} className="text-xs opacity-70">{warning}</p>)}<Button size="small" type="text" onClick={() => setNotes(base.metadata!.annotationPlan!.edits.map((edit, index) => `${index + 1}. ${edit.location}：${edit.instruction}`).join("\n"))}>复制到修改清单继续调整</Button></details> : null}
                <div className="max-h-64 space-y-2 overflow-y-auto">{marks.map((mark, index) => <div key={mark.id} className="flex gap-2"><span className="pt-1.5 text-xs">{index + 1}</span><Input.TextArea aria-label={`批注${index + 1}修改要求`} placeholder="这个区域要怎样修改？" autoSize={{ minRows: 1, maxRows: 4 }} value={mark.text} onChange={(event) => setMarks((current) => current.map((item) => item.id === mark.id ? { ...item, text: event.target.value } : item))} /><Button type="text" aria-label={`删除批注${index + 1}`} icon={<Trash2 className="size-3.5" />} onClick={() => setMarks((current) => current.filter((item) => item.id !== mark.id))} /></div>)}</div>
                <Input.TextArea aria-label="补充批注修改清单" value={notes} onChange={(event) => setNotes(event.target.value)} autoSize={{ minRows: 4, maxRows: 9 }} placeholder="上传批注图时，可在这里核对或补充修改清单；不确定的位置请明确说明。" />
                <label className="block text-sm">材质参考（可选）<Select aria-label="材质参考" mode="multiple" className="mt-1 w-full" value={materialIds} onChange={setMaterialIds} options={options.filter((item) => item.value !== baseId && item.value !== annotationId)} placeholder="只借用材质，保持底图构图" /></label>
                <Checkbox checked={lockOutside} onChange={(event) => setLockOutside(event.target.checked)} disabled={!marks.length}>锁定框选外内容</Checkbox>
                <p className="text-xs opacity-60">默认让模型自然融合。开启锁定后，框外保留原图；框选需覆盖新增物体的完整范围，超出框的部分会被截断。</p>
                <p className="text-xs opacity-60">点击生成后先读取批注文字和位置，再按清单改图；看不清或位置不明确时停止生图。识别清单随结果保存，可展开核对。建立任务不消耗积分，生成仍按所选模型计费。</p>
                <div className="flex flex-wrap gap-2"><Button onClick={saveMarks} disabled={busy}>保存批注</Button><Button type="primary" onClick={() => void createTask()} loading={busy}>建立改图任务</Button></div>
            </div>
        </div> : <Empty description="先导入底图，再开始批注" />}
        <input ref={uploadRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void uploadAnnotation(event.target.files?.[0])} />
    </div>;
    const compareTab = <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3"><label>原图 A<Select aria-label="对比原图" className="mt-1 w-full" value={compareA || undefined} onChange={setCompareA} options={options} /></label><label>结果 B<Select aria-label="对比结果" className="mt-1 w-full" value={compareB || undefined} onChange={setCompareB} options={options} /></label></div>
        <Segmented value={compareMode} onChange={setCompareMode} options={[{ label: "滑杆对比", value: "slider" }, { label: "并排查看", value: "side" }]} />
        {a && b ? compareMode === "side" ? <div className="grid grid-cols-2 items-start gap-2"><img src={a.metadata?.content} alt={`原图 A：${a.title}`} className="w-full" /><img src={b.metadata?.content} alt={`结果 B：${b.title}`} className="w-full" /></div> : <>
            <div className="relative overflow-hidden rounded" style={{ aspectRatio: `${a.metadata?.naturalWidth || a.width} / ${a.metadata?.naturalHeight || a.height}` }}>
                <img src={a.metadata?.content} alt="对比原图 A" className="absolute inset-0 h-full w-full object-contain" />
                <img src={b.metadata?.content} alt="对比结果 B" className="absolute inset-0 h-full w-full object-contain" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />
                <div className="pointer-events-none absolute bottom-0 top-0 w-px" style={{ left: `${split}%`, background: theme.node.text }} />
                <span className="absolute left-2 top-2 rounded px-2 py-1 text-xs" style={{ background: theme.node.panel }}>原图 A</span><span className="absolute right-2 top-2 rounded px-2 py-1 text-xs" style={{ background: theme.node.panel }}>结果 B</span>
            </div>
            <input aria-label="原图结果对比滑杆" type="range" min={0} max={100} value={split} onChange={(event) => setSplit(Number(event.target.value))} className="w-full" />
            {(a.metadata?.naturalWidth || a.width) / (a.metadata?.naturalHeight || a.height) !== (b.metadata?.naturalWidth || b.width) / (b.metadata?.naturalHeight || b.height) ? <p className="text-xs opacity-60">两张图片比例不同，按完整图片居中显示；可切换并排查看。</p> : null}
        </> : <Empty description="选择两张图片，检查修改区域和未修改区域" />}
        <p className="text-xs opacity-60">对比使用原图，不调用 AI，也不消耗积分。</p>
    </div>;
    return <>
        <Button type="text" size="small" icon={<Pencil className="size-4" />} onClick={() => launch("annotation")}><span className="hidden sm:inline">批注改图</span></Button>
        <Button type="text" size="small" icon={<Columns2 className="size-4" />} onClick={() => launch("compare")} aria-label="原图结果对比"><span className="hidden sm:inline">对比</span></Button>
        <Modal title="专业效果图工作台" open={open} onCancel={() => !busy && setOpen(false)} footer={null} width={1120} destroyOnHidden styles={{ body: { maxHeight: "78dvh", overflowY: "auto" } }}>
            <Tabs activeKey={tab} onChange={setTab} items={[{ key: "annotation", label: "批注改图", children: annotationTab }, { key: "compare", label: "原图对比", children: compareTab }, { key: "cloud", label: "保存与跨设备", children: <div className="space-y-4 py-4"><p>本机编辑会自动保存。需要换电脑继续时，请将当前版本保存到账号。</p><CanvasCloudPanel project={project} /></div> }]} />
        </Modal>
    </>;
}

async function renderAnnotation(base: CanvasNodeData, marks: Mark[]) {
    const image = new Image();
    image.src = base.metadata?.content || "";
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("无法创建批注图，请重试。");
    context.drawImage(image, 0, 0);
    const font = Math.max(18, Math.round(Math.min(canvas.width, canvas.height) / 42));
    context.lineWidth = Math.max(3, font / 6);
    context.font = `600 ${font}px sans-serif`;
    marks.forEach((mark, index) => {
        const x = mark.x * canvas.width, y = mark.y * canvas.height, width = mark.width * canvas.width, height = mark.height * canvas.height;
        context.strokeStyle = "#ef4444";
        context.strokeRect(x, y, width, height);
        const text = `${index + 1}. ${mark.text}`;
        const maxWidth = Math.min(canvas.width - x, Math.max(width, canvas.width * .32));
        const lines: string[] = []; let line = "";
        for (const char of text) { if (context.measureText(line + char).width > maxWidth - 12 && line) { lines.push(line); line = char; } else line += char; }
        if (line) lines.push(line);
        const labelY = Math.min(y, Math.max(0, canvas.height - lines.length * font * 1.35 - 8));
        context.fillStyle = "rgba(255,255,255,.94)";
        context.fillRect(x, labelY, maxWidth, lines.length * font * 1.35 + 8);
        context.fillStyle = "#b91c1c";
        lines.forEach((value, row) => context.fillText(value, x + 4, labelY + font * (1.1 + row * 1.35)));
    });
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("批注图导出失败。")), "image/png"));
}

async function renderRegionMask(base: CanvasNodeData, marks: Mark[]) {
    const canvas = document.createElement("canvas");
    canvas.width = base.metadata?.naturalWidth || base.width;
    canvas.height = base.metadata?.naturalHeight || base.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("无法创建局部选区。");
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const feather = Math.max(3, Math.round(Math.min(canvas.width, canvas.height) / 160));
    marks.forEach((mark) => {
        const left = Math.floor(mark.x * canvas.width), top = Math.floor(mark.y * canvas.height);
        const right = Math.min(canvas.width, Math.ceil((mark.x + mark.width) * canvas.width)), bottom = Math.min(canvas.height, Math.ceil((mark.y + mark.height) * canvas.height));
        for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
            const t = Math.min(1, Math.min(x - left, right - 1 - x, y - top, bottom - 1 - y) / feather);
            const alpha = Math.round(255 * (1 - t * t * (3 - 2 * t)));
            const index = (y * canvas.width + x) * 4 + 3;
            pixels.data[index] = Math.min(pixels.data[index], alpha);
        }
    });
    context.putImageData(pixels, 0, 0);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("局部选区导出失败。")), "image/png"));
}
