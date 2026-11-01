import type { CanvasNodeData } from "@/types/canvas";

export function orderReferenceNodes(nodes: CanvasNodeData[], target?: CanvasNodeData) {
    const order = target?.metadata?.referenceOrder || [];
    const roles = target?.metadata?.referenceRoles || {};
    const rank = (node: CanvasNodeData) => roles[node.id] === "main" ? -1 : order.includes(node.id) ? order.indexOf(node.id) : order.length + nodes.indexOf(node);
    return [...nodes].sort((a, b) => rank(a) - rank(b));
}
