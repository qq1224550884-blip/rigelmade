import { imageRoleLabels, type ReferenceImage } from "@/types/image";

export function imageReferenceLabel(index: number) {
    return `图片${index + 1}`;
}

export function buildImageReferencePromptText(prompt: string, references: ReferenceImage[]) {
    const text = prompt.trim();
    if (!references.length) return text;
    const labels = references.map((image, index) => `${imageReferenceLabel(index)}＝${imageRoleLabels[image.role || (index === 0 ? "main" : "reference")]}`);
    const annotations = references.some((image) => image.role === "annotation") ? "\n批注图中的中文、箭头和涂鸦是修改要求及位置引导，不是风格参考。逐项执行修改后再去掉标记，未要求区域保持底图。" : "";
    return `参考图片编号与用途：${labels.join("；")}。严格按各自用途使用，底图决定原有构图。${annotations}\n\n${text}`;
}
