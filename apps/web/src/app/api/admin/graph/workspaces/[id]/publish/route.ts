import { createHash, randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const documentType = (kind: string) => ({ FAQ: "FAQ", POLICY: "POLICY", TERMS: "TERMS", INCIDENT: "INCIDENT", ACTION: "SOP", ESCALATION: "SOP", RULE: "POLICY" }[kind] || "GUIDE") as "FAQ" | "POLICY" | "TERMS" | "INCIDENT" | "SOP" | "GUIDE";
const entityType = (kind: string) => ({ INTENT: "INTENT", POLICY: "POLICY_RULE", TERMS: "POLICY_RULE", RULE: "POLICY_RULE", PRODUCT_SCOPE: "PRODUCT", ORDER_STATUS: "ORDER_STATUS", PAYMENT_STATUS: "PAYMENT_STATUS", ACTION: "ACTION", ESCALATION: "ACTION", INCIDENT: "INCIDENT" }[kind] || "CONCEPT") as "CONCEPT" | "INTENT" | "POLICY_RULE" | "CUSTOMER_RIGHT" | "PRODUCT" | "ORDER_STATUS" | "PAYMENT_STATUS" | "ACTION" | "INCIDENT";
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("vi-VN").replace(/\s+/g, " ").trim();
const hash = (value: string) => createHash("sha256").update(normalize(value)).digest("hex");
const slugify = (value: string) => normalize(value).replace(/đ/g, "d").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 70) || "knowledge";

function categoryId(title: string) {
  const value = normalize(title);
  if (/bao mat|tai khoan|dang nhap|xac minh/.test(value)) return "account";
  if (/tra hang|doi tra|hoan tien|refund/.test(value)) return "refund";
  if (/giao hang|van chuyen|nhan hang/.test(value)) return "shipping";
  if (/thanh toan|the tin dung|vi dien tu|paylater/.test(value)) return "payment";
  if (/voucher|khuyen mai|ma giam/.test(value)) return "voucher";
  if (/bao hanh|san pham|hang hoa/.test(value)) return "warranty";
  if (/khieu nai|tranh chap|to cao/.test(value)) return "dispute";
  if (/dieu khoan|phap ly|quyen rieng tu|privacy/.test(value)) return "legal";
  if (/su co|trang thai dich vu|incident/.test(value)) return "status";
  return "orders";
}

function metadata(value: Prisma.JsonValue | null) {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const workspace = await prisma.graphWorkspace.findUnique({ where: { id }, include: { issues: { where: { resolved: false } }, draftNodes: { where: { archived: false }, orderBy: { createdAt: "asc" } }, draftEdges: true } });
  if (!workspace) return NextResponse.json({ error: "WORKSPACE_NOT_FOUND" }, { status: 404 });
  if (workspace.status !== "DRAFT") return NextResponse.json({ error: "WORKSPACE_ALREADY_LOCKED" }, { status: 409 });
  if (workspace.issues.some((issue) => issue.severity === "HIGH" || issue.severity === "CRITICAL")) return NextResponse.json({ error: "GRAPH_VALIDATION_FAILED", issues: workspace.issues }, { status: 409 });
  if (!workspace.draftNodes.length) return NextResponse.json({ error: "EMPTY_GRAPH" }, { status: 409 });

  const root = workspace.draftNodes.find((node) => metadata(node.metadata).placement) ?? workspace.draftNodes.find((node) => ["DOCUMENT", "FAQ", "POLICY", "TERMS"].includes(node.kind)) ?? workspace.draftNodes[0];
  const rootMetadata = metadata(root.metadata);
  const title = typeof rootMetadata.sourceTitle === "string" ? rootMetadata.sourceTitle : root.name;
  const canonicalDocumentId = typeof rootMetadata.canonicalDocumentId === "string" ? rootMetadata.canonicalDocumentId : undefined;
  const uniqueContents = [...new Set(workspace.draftNodes.map((node) => node.content.trim() || node.summary.trim() || node.name).filter(Boolean))];
  const fullContent = uniqueContents.join("\n\n");
  const sourceHash = typeof rootMetadata.sourceHash === "string" ? rootMetadata.sourceHash : hash(fullContent);
  const now = new Date();

  const result = await prisma.$transaction(async (tx) => {
    let document = canonicalDocumentId ? await tx.knowledgeDocument.findUnique({ where: { id: canonicalDocumentId }, include: { currentVersion: true, versions: true } }) : null;
    if (!document) {
      const duplicateChunk = await tx.knowledgeChunk.findFirst({ where: { contentHash: sourceHash, retrievalEnabled: true }, include: { version: { include: { document: true } } } });
      if (duplicateChunk) {
        await tx.graphWorkspace.update({ where: { id }, data: { status: "PUBLISHED", validation: { valid: true, duplicate: true, canonicalDocumentId: duplicateChunk.version.documentId } } });
        await tx.graphDraftNode.updateMany({ where: { workspaceId: id }, data: { documentId: duplicateChunk.version.documentId, versionId: duplicateChunk.versionId } });
        return { documentId: duplicateChunk.version.documentId, versionId: duplicateChunk.versionId, chunks: 0, entities: 0, edges: 0, duplicate: true };
      }
    }

    const documentId = document?.id ?? `kb_${randomUUID()}`;
    const versionId = `kbv_${randomUUID()}`;
    const semanticVersion = document ? `1.${document.versions.length}.0` : "1.0.0";
    if (!document) {
      let slug = slugify(title);
      const slugExists = await tx.knowledgeDocument.findFirst({ where: { slug, locale: "vi-VN" }, select: { id: true } });
      if (slugExists) slug = `${slug}-${documentId.slice(-6)}`;
      document = await tx.knowledgeDocument.create({ data: { id: documentId, slug, locale: "vi-VN", type: documentType(root.kind), visibility: root.visibility, marketplace: root.marketplace, authorityLevel: root.importance === "CRITICAL" ? 100 : root.importance === "HIGH" ? 85 : root.importance === "MEDIUM" ? 70 : 50, categoryId: categoryId(title), ownerId: admin.id }, include: { currentVersion: true, versions: true } });
    } else if (document.currentVersionId) {
      await tx.knowledgeVersion.update({ where: { id: document.currentVersionId }, data: { effectiveTo: now, searchable: false } });
    }

    await tx.knowledgeVersion.create({ data: { id: versionId, documentId, semanticVersion, title, summary: root.summary || fullContent.slice(0, 700), content: fullContent, status: "PUBLISHED", effectiveFrom: now, searchable: false, changeSummary: `Published from graph workspace ${workspace.name}`, publishedAt: now, publishedBy: admin.id } });

    const entityIds = new Map<string, string>();
    const chunkIds = new Map<string, string>();
    for (const node of workspace.draftNodes) {
      const content = node.content.trim() || node.summary.trim() || node.name;
      const chunkId = `kbc_${randomUUID()}`;
      const entityId = `kbe_${randomUUID()}`;
      await tx.knowledgeChunk.create({ data: { id: chunkId, versionId, section: node.name, content, contentHash: node.id === root.id ? sourceHash : hash(content), retrievalEnabled: true, tokenCount: Math.max(1, Math.ceil(content.length / 4)) } });
      await tx.knowledgeEntity.create({ data: { id: entityId, versionId, chunkId, type: entityType(node.kind), canonicalName: node.name, normalizedKey: `${node.kind.toLowerCase()}-${hash(node.name).slice(0, 20)}`, metadata: { graphWorkspaceId: id, graphNodeId: node.id, kind: node.kind, importance: node.importance, mandatory: node.mandatory, visibility: node.visibility, hierarchyPath: [categoryId(title), title, node.name] } } });
      if (node.mandatory || ["RULE", "POLICY", "TERMS"].includes(node.kind)) await tx.knowledgeClaim.create({ data: { versionId, chunkId, subject: node.name, predicate: node.mandatory ? "mandatory_policy" : "governs", value: content, polarity: /không được|cấm|không hỗ trợ/i.test(content) ? -1 : 1, authorityLevel: node.mandatory ? 100 : document.authorityLevel, effectiveFrom: now, scope: { graphWorkspaceId: id, graphNodeId: node.id, categoryId: categoryId(title) } } });
      await tx.graphDraftNode.update({ where: { id: node.id }, data: { documentId, versionId } });
      entityIds.set(node.id, entityId);
      chunkIds.set(node.id, chunkId);
    }

    let edgeCount = 0;
    for (const edge of workspace.draftEdges) {
      const sourceId = entityIds.get(edge.sourceId), targetId = entityIds.get(edge.targetId), chunkId = chunkIds.get(edge.sourceId);
      if (!sourceId || !targetId || !chunkId) continue;
      await tx.knowledgeEdge.create({ data: { id: `kbedge_${randomUUID()}`, versionId, chunkId, sourceId, targetId, relation: edge.relation, weight: edge.weight, metadata: { graphWorkspaceId: id, graphDraftEdgeId: edge.id } } });
      edgeCount += 1;
    }

    const placement = metadata(root.metadata).placement;
    const primaryParentId = placement && typeof placement === "object" && !Array.isArray(placement) && typeof (placement as Record<string, unknown>).primaryParentId === "string" ? String((placement as Record<string, unknown>).primaryParentId) : null;
    const rootEntityId = entityIds.get(root.id);
    const rootChunkId = chunkIds.get(root.id);
    if (primaryParentId && rootEntityId && rootChunkId) {
      const externalParent = await tx.knowledgeEntity.findUnique({ where: { id: primaryParentId }, select: { id: true } });
      if (externalParent) {
        await tx.knowledgeEdge.create({ data: { id: `kbedge_${randomUUID()}`, versionId, chunkId: rootChunkId, sourceId: rootEntityId, targetId: externalParent.id, relation: ["RULE", "POLICY", "TERMS", "FAQ"].includes(root.kind) ? "GOVERNED_BY" : "RELATED_TO", weight: 0.95, metadata: { graphWorkspaceId: id, placement: true } } });
        edgeCount += 1;
      }
    }

    await tx.knowledgeGraphBuild.create({ data: { versionId, status: "COMPLETED", extractorVersion: "unified-graphrag-2.0", entityCount: entityIds.size, edgeCount, claimCount: workspace.draftNodes.filter((node) => node.mandatory || ["RULE", "POLICY", "TERMS"].includes(node.kind)).length, startedAt: now, completedAt: now } });
    await tx.knowledgeDocument.update({ where: { id: documentId }, data: { currentVersionId: versionId } });
    await tx.knowledgeVersion.update({ where: { id: versionId }, data: { searchable: true } });
    await tx.auditLog.create({ data: { actorId: admin.id, actorRole: "ADMIN", action: "UNIFIED_KNOWLEDGE_GRAPH_PUBLISHED", entityType: "KnowledgeDocument", entityId: documentId, payload: { workspaceId: id, versionId, chunks: chunkIds.size, entities: entityIds.size, edges: edgeCount, sourceHash } } });
    await tx.graphWorkspace.update({ where: { id }, data: { status: "PUBLISHED", validation: { valid: true, publishedAt: now.toISOString(), documentId, versionId, checksum: sourceHash } } });
    return { documentId, versionId, chunks: chunkIds.size, entities: entityIds.size, edges: edgeCount, duplicate: false };
  }, { timeout: 30000 });

  return NextResponse.json({ workspaceId: id, ...result, searchable: true });
}
