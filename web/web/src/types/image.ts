export type ImageReferenceRole = "main" | "annotation" | "material" | "structure" | "lighting" | "style" | "content" | "reference";
export type AnnotationPlan = {
    ready: boolean;
    model: string;
    summary: string;
    edits: Array<{ instruction: string; evidence: string; sourceImage: number; location: string; bbox: number[]; anchor: number[] }>;
    warnings: string[];
};
export type GeneratedImage = { id: string; dataUrl: string; annotationPlan?: AnnotationPlan };
export const imageRoleLabels: Record<ImageReferenceRole, string> = { main: "底图", annotation: "批注图", material: "材质", structure: "结构", lighting: "灯光", style: "风格", content: "物件", reference: "参考" };
export type ReferenceImage = {
    id: string;
    name: string;
    type: string;
    dataUrl: string;
    url?: string;
    storageKey?: string;
    role?: ImageReferenceRole;
};
