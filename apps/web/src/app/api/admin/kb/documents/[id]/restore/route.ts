import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, select: { currentVersionId: true, archivedAt: true } });
  if (!document) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  if (!document.archivedAt) return NextResponse.json({ documentId: id, status: "PUBLISHED", idempotent: true });
  if (!document.currentVersionId) return NextResponse.json({ error: "ACTIVE_VERSION_REQUIRED" }, { status: 409 });

  await prisma.$transaction(async (tx) => {
    await tx.knowledgeVersion.update({ where: { id: document.currentVersionId! }, data: { searchable: true, effectiveTo: null } });
    await tx.knowledgeChunk.updateMany({ where: { versionId: document.currentVersionId! }, data: { retrievalEnabled: true } });
    await tx.knowledgeDocument.update({ where: { id }, data: { archivedAt: null } });
    await tx.auditLog.create({ data: { actorId: admin.id, actorRole: "ADMIN", action: "KNOWLEDGE_DOCUMENT_RESTORED", entityType: "KnowledgeDocument", entityId: id, payload: { versionId: document.currentVersionId } } });
  });
  return NextResponse.json({ documentId: id, versionId: document.currentVersionId, status: "PUBLISHED", searchable: true });
}
