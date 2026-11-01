// Adapted from infinite-canvas v0.20.0: previews are local derivatives, never generation inputs.
export const PREVIEW_EDGE = 768;
export async function createImageThumbnail(blob: Blob) {
    const image = await createImageBitmap(blob);
    try {
        const ratio = Math.min(1, PREVIEW_EDGE / Math.max(image.width, image.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(image.width * ratio));
        canvas.height = Math.max(1, Math.round(image.height * ratio));
        const context = canvas.getContext("2d");
        if (!context) return null;
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        return await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/webp", 0.86));
    } finally { image.close(); }
}
