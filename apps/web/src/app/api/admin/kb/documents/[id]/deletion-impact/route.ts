import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, select: { id: true, slug: true, archivedAt: true, versions: { select: { id: true } } } });
  if (!document) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  const versionIds = document.versions.map((version) => version.id);
  const entityIds = (await prisma.knowledgeEntity.findMany({ where: { versionId: { in: versionIds } }, select: { id: true } })).map((entity) => entity.id);
  const [retrievals, feedback, graphNodes, mandatoryClaims, externalEdges] = await Promise.all([
    prisma.aiRetrievalResult.count({ where: { versionId: { in: versionIds } } }),
    prisma.knowledgeFeedback.count({ where: { documentId: id } }),
    prisma.graphDraftNode.count({ where: { documentId: id } }),
    prisma.knowledgeClaim.count({ where: { versionId: { in: versionIds }, predicate: "mandatory_policy" } }),
    entityIds.length ? prisma.knowledgeEdge.count({ where: { targetId: { in: entityIds }, versionId: { notIn: versionIds } } }) : Promise.resolve(0),
  ]);
  const dependencies = { retrievals, feedback, graphNodes, mandatoryClaims, externalEdges };
  const allowed = Boolean(document.archivedAt) && Object.values(dependencies).every((count) => count === 0);
  return NextResponse.json({ documentId: id, slug: document.slug, archived: Boolean(document.archivedAt), allowed, dependencies });
}
