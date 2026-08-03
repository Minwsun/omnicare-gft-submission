import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, select: { id: true, currentVersionId: true, archivedAt: true } });
  if (!document) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  if (document.archivedAt) return NextResponse.json({ documentId: id, status: "ARCHIVED", idempotent: true });
  const now = new Date();
  await prisma.$transaction(async (tx) => {
    await tx.knowledgeDocument.update({ where: { id }, data: { archivedAt: now } });
    if (document.currentVersionId) {
      await tx.knowledgeVersion.update({ where: { id: document.currentVersionId }, data: { searchable: false, effectiveTo: now } });
      await tx.knowledgeChunk.updateMany({ where: { versionId: document.currentVersionId }, data: { retrievalEnabled: false } });
      await tx.knowledgeSummaryNode.updateMany({ where: { versionId: document.currentVersionId }, data: { active: false } });
    }
    await tx.knowledgeVisualizationRevision.updateMany({ where: { documentId: id, active: true }, data: { active: false } });
    await tx.auditLog.create({ data: { actorId: admin.id, actorRole: "ADMIN", action: "KNOWLEDGE_DOCUMENT_ARCHIVED", entityType: "KnowledgeDocument", entityId: id, payload: { versionId: document.currentVersionId, archivedAt: now.toISOString() } } });
  });
  const activeRebuild = await prisma.knowledgeIngestionRun.findFirst({ where: { status: { in: ["QUEUED", "RUNNING", "RETRY"] }, payload: { path: ["mode"], equals: "REBUILD_ALL" } } });
  if (!activeRebuild) await prisma.knowledgeIngestionRun.create({ data: { id: `kbir_${randomUUID()}`, documentId: id, versionId: document.currentVersionId, model: process.env.LLM_REASONING_MODEL || "cx/gpt-5.6-terra", priority: "LOW", payload: { mode: "REBUILD_ALL", reason: "DOCUMENT_ARCHIVED", documentId: id, actorId: admin.id } } });
  return NextResponse.json({ documentId: id, versionId: document.currentVersionId, status: "ARCHIVED", archivedAt: now });
}
