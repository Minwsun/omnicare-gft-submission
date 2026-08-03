import { NextResponse } from "next/server";
import { z } from "zod";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const schema = z.object({ confirmSlug: z.string().min(1).max(240) });

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin=await requireAdmin();
  if(!admin)return NextResponse.json({error:"FORBIDDEN"},{status:403});
  const {id}=await params;
  const document=await prisma.knowledgeDocument.findUnique({where:{id},select:{id:true,type:true,visibility:true,authorityLevel:true,currentVersion:{select:{title:true,summary:true,content:true,semanticVersion:true}}}});
  if(!document?.currentVersion)return NextResponse.json({error:"DOCUMENT_NOT_FOUND"},{status:404});
  return NextResponse.json({...document,title:document.currentVersion.title,summary:document.currentVersion.summary,content:document.currentVersion.content,version:document.currentVersion.semanticVersion});
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_DELETE_CONFIRMATION" }, { status: 400 });
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, select: { slug: true, archivedAt: true, versions: { select: { id: true } } } });
  if (!document) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  if (parsed.data.confirmSlug !== document.slug) return NextResponse.json({ error: "DELETE_CONFIRMATION_MISMATCH" }, { status: 400 });
  if (!document.archivedAt) return NextResponse.json({ error: "ARCHIVE_REQUIRED" }, { status: 409 });

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
  if (Object.values(dependencies).some((count) => count > 0)) return NextResponse.json({ error: "DOCUMENT_HAS_DEPENDENCIES", dependencies }, { status: 409 });

  await prisma.$transaction(async (tx) => {
    await tx.knowledgeDocument.update({ where: { id }, data: { currentVersionId: null } });
    await tx.knowledgeDocument.delete({ where: { id } });
    await tx.auditLog.create({ data: { actorId: admin.id, actorRole: "ADMIN", action: "KNOWLEDGE_DOCUMENT_DELETED", entityType: "KnowledgeDocumentTombstone", entityId: id, payload: { slug: document.slug, versionIds, deletedAt: new Date().toISOString() } } });
  });
  return NextResponse.json({ documentId: id, status: "DELETED" });
}
