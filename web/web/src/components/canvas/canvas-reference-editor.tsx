import { Button, Input, Select } from "antd";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { imageRoleLabels, type ImageReferenceRole } from "@/types/image";
import type { CanvasNodeData, CanvasNodeMetadata } from "@/types/canvas";
import type { CanvasResourceReference } from "@/lib/canvas/canvas-resource-references";

export function CanvasReferenceEditor({ node, references, onChange, onRemove }: { node: CanvasNodeData; references: CanvasResourceReference[]; onChange: (id: string, patch: Partial<CanvasNodeMetadata>) => void; onRemove?: (id: string, referenceId: string) => void }) {
    const images = references.filter((reference) => reference.active && reference.kind === "image");
    if (!images.length) return null;
    const roles = node.metadata?.referenceRoles || {};
    const ownBase = Boolean(node.metadata?.content);
    const move = (index: number, delta: number) => {
        const ids = images.map((image) => image.nodeId);
        [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
        // The first image always remains the base; moving another image to the front makes it the new base.
        const nextRoles = { ...roles };
        images.forEach((image) => { if (nextRoles[image.nodeId] === "main") nextRoles[image.nodeId] = "reference"; });
        nextRoles[ids[0]] = "main";
        onChange(node.id, { referenceOrder: ids, referenceRoles: nextRoles, ...(ids[0] !== images[0].nodeId ? { editMaskStorageKey: undefined } : {}) });
    };
    const setRole = (id: string, role: ImageReferenceRole) => {
        const next = { ...roles, [id]: role };
        const ids = images.map((image) => image.nodeId);
        if (role === "main") {
            images.forEach((image) => { if (image.nodeId !== id && (next[image.nodeId] === "main" || image === images[0])) next[image.nodeId] = "reference"; });
            onChange(node.id, { referenceRoles: next, referenceOrder: [id, ...ids.filter((item) => item !== id)], ...(id !== images[0].nodeId ? { editMaskStorageKey: undefined } : {}) });
        } else onChange(node.id, { referenceRoles: next });
    };
    return <div className="mt-2 space-y-2 text-xs" onMouseDown={(event) => event.stopPropagation()}>
        <div className="opacity-65">图片用途与顺序 · 第一张为底图</div>
        {images.map((image, index) => <div key={image.nodeId} className="flex min-w-0 items-center gap-1">
            <img src={image.previewUrl} alt={image.title} className="size-8 shrink-0 rounded object-contain" />
            <span className="w-10 shrink-0">图片{index + 1}</span>
            <Select size="small" aria-label={`图片${index + 1}用途`} value={index === 0 ? "main" : roles[image.nodeId] === "main" ? "reference" : roles[image.nodeId] || "reference"} onChange={(role) => setRole(image.nodeId, role)} options={Object.entries(imageRoleLabels).filter(([role]) => index === 0 ? role === "main" : !ownBase || role !== "main").map(([value, label]) => ({ value, label }))} className="min-w-20 flex-1" />
            <Button size="small" type="text" aria-label={`上移图片${index + 1}`} disabled={!index || (ownBase && index === 1)} icon={<ArrowUp className="size-3" />} onClick={() => move(index, -1)} />
            <Button size="small" type="text" aria-label={`下移图片${index + 1}`} disabled={index === images.length - 1 || (ownBase && index === 0)} icon={<ArrowDown className="size-3" />} onClick={() => move(index, 1)} />
            <Button size="small" type="text" aria-label={`移除图片${index + 1}`} disabled={ownBase && index === 0} icon={<X className="size-3" />} onClick={() => onRemove?.(node.id, image.nodeId)} />
        </div>)}
        {images.some((image) => roles[image.nodeId] === "annotation") ? <label className="block pt-1"><span className="mb-1 block">批注修改清单（可补充位置、颜色和要求）</span><Input.TextArea aria-label="批注修改清单" value={node.metadata?.annotationNotes || ""} onChange={(event) => onChange(node.id, { annotationNotes: event.target.value })} autoSize={{ minRows: 2, maxRows: 8 }} placeholder="例：红圈处改为草坪；黄色轮廓位置添加一棵小树。" /></label> : null}
    </div>;
}
