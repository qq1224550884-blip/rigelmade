import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { format, resolveConfig } from "prettier";

const DEFAULT_SOURCE = "http://192.168.110.79:18769/%E6%B4%97%E5%9B%BE%E6%8F%90%E7%A4%BA%E8%AF%8D%E5%B7%A5%E5%85%B7%E7%AE%B1.html";
const expectedCounts = { template: 9, module: 15, external: 222 };
const source = process.argv[2] || DEFAULT_SOURCE;
const scriptDir = fileURLToPath(new URL(".", import.meta.url));
const outputDir = resolve(scriptDir, "../public/prompt-sources");
const imageDir = resolve(outputDir, "wash-image-examples");
const prettierConfig = (await resolveConfig(resolve(scriptDir, "../package.json"))) || {};

const html = await loadSource(source);
const templates = parseBilingualArticles(html, "template", "完整模板");
const modules = parseBilingualArticles(html, "module", "模块词条");
const examples = await parseExamples(html);

assertCount("template", templates.length / 2);
assertCount("module", modules.length / 2);
assertCount("external", examples.length);

await mkdir(outputDir, { recursive: true });
await writeJson("wash-image-templates.json", templates);
await writeJson("wash-image-modules.json", modules);
await writeJson("wash-image-examples.json", examples);

console.log(`Imported ${templates.length + modules.length + examples.length} prompts (${templates.length} templates, ${modules.length} modules, ${examples.length} examples).`);

async function loadSource(value) {
    if (/^https?:\/\//i.test(value)) {
        const response = await fetch(value);
        if (!response.ok) throw new Error(`Failed to fetch ${value}: HTTP ${response.status}`);
        return response.text();
    }
    return readFile(resolve(value), "utf8");
}

function parseBilingualArticles(document, className, kind) {
    return articleBodies(document, className).flatMap((body, index) => {
        const { title, description } = parseSummary(body);
        const zh = textOf(matchRequired(body, /<pre\s+class="zh"[^>]*>([\s\S]*?)<\/pre>/i, `${title} Chinese prompt`));
        const en = textOf(matchRequired(body, /<pre\s+class="en"[^>]*>([\s\S]*?)<\/pre>/i, `${title} English prompt`));
        const number = String(index + 1).padStart(2, "0");
        const prefix = className === "template" ? "wash-template" : "wash-module";
        const common = {
            description: description || `洗图${kind}：${title}`,
            coverUrl: "",
            referenceImageUrls: [],
            preview: "",
            createdAt: "",
            updatedAt: "",
            sourceUrl: "",
        };
        return [
            { ...common, id: `${prefix}-${number}-zh`, title: `${title}（中文）`, prompt: zh, tags: ["洗图", kind, "中文"] },
            { ...common, id: `${prefix}-${number}-en`, title: `${title}（English）`, prompt: en, tags: ["洗图", kind, "English"] },
        ];
    });
}

async function parseExamples(document) {
    const bodies = articleBodies(document, "external");
    await mkdir(imageDir, { recursive: true });
    return Promise.all(
        bodies.map(async (body, index) => {
            const { title, description } = parseSummary(body);
            const prompt = textOf(matchRequired(body, /<pre[^>]*>([\s\S]*?)<\/pre>/i, `${title} prompt`));
            const image = matchRequired(body, /<img[^>]+src="data:image\/([^;]+);base64,([A-Za-z0-9+/=]+)"/i, `${title} image`, true);
            const attribution = matchRequired(body, /<p\s+class="source"[^>]*>[\s\S]*?<a\s+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>\s*·\s*([^<]+)<\/p>/i, `${title} attribution`, true);
            const sourceId = textOf(attribution[3]);
            const id = `wash-example-${sourceId || String(index + 1).padStart(4, "0")}`;
            const extension = imageExtension(image[1]);
            const imageName = `${id}.${extension}`;
            const imagePath = resolve(imageDir, imageName);
            const imageBuffer = Buffer.from(image[2], "base64");
            if (!imageBuffer.length) throw new Error(`Empty image for ${title}`);
            await writeFile(imagePath, imageBuffer);
            const imageUrl = `./wash-image-examples/${imageName}`;
            const categoryTags = description
                .split("/")
                .map((value) => value.trim())
                .filter(Boolean);
            return {
                id,
                title,
                prompt,
                description,
                coverUrl: imageUrl,
                referenceImageUrls: [imageUrl],
                tags: ["洗图", "参考案例", ...categoryTags],
                preview: "",
                createdAt: "",
                updatedAt: "",
                author: textOf(attribution[2]),
                sourceUrl: decodeHtml(attribution[1]),
            };
        }),
    );
}

function articleBodies(document, className) {
    const pattern = new RegExp(`<article\\s+class="${className}"[^>]*>([\\s\\S]*?)<\\/article>`, "gi");
    return [...document.matchAll(pattern)].map((match) => match[1]);
}

function parseSummary(body) {
    const summary = matchRequired(body, /<summary>([\s\S]*?)<\/summary>/i, "article summary");
    const descriptionMatch = summary.match(/<small>([\s\S]*?)<\/small>/i);
    return {
        title: textOf(summary.replace(/<small>[\s\S]*?<\/small>/i, "")),
        description: descriptionMatch ? textOf(descriptionMatch[1]) : "",
    };
}

function textOf(value) {
    return decodeHtml(value.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, ""))
        .replace(/\r\n/g, "\n")
        .trim();
}

function decodeHtml(value) {
    const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
    return value.replace(/&(#x?[0-9a-f]+|amp|lt|gt|quot|apos|nbsp);/gi, (_, entity) => {
        if (entity[0] !== "#") return named[entity.toLowerCase()] || `&${entity};`;
        const hexadecimal = entity[1].toLowerCase() === "x";
        return String.fromCodePoint(Number.parseInt(entity.slice(hexadecimal ? 2 : 1), hexadecimal ? 16 : 10));
    });
}

function matchRequired(value, pattern, label, fullMatch = false) {
    const match = value.match(pattern);
    if (!match) throw new Error(`Missing ${label}`);
    return fullMatch ? match : match[1];
}

function imageExtension(mimeSubtype) {
    const normalized = mimeSubtype.toLowerCase();
    if (normalized === "jpeg" || normalized === "jpg") return "jpg";
    if (normalized === "png" || normalized === "webp" || normalized === "gif") return normalized;
    throw new Error(`Unsupported image type: ${mimeSubtype}`);
}

function assertCount(kind, actual) {
    const expected = expectedCounts[kind];
    if (actual !== expected) throw new Error(`Expected ${expected} ${kind} articles, found ${actual}`);
}

async function writeJson(name, value) {
    await writeFile(resolve(outputDir, name), await format(JSON.stringify(value), { ...prettierConfig, parser: "json" }), "utf8");
}
