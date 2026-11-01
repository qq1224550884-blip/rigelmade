export type ImageReferenceRole = "main" | "annotation" | "material" | "structure" | "lighting" | "style" | "content" | "reference";
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
