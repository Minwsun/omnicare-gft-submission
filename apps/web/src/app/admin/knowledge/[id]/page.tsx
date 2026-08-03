import { notFound } from "next/navigation";

import { prisma } from "@/lib/prisma";

export default async function KnowledgeDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, include: { versions: { include: { chunks: true, graphBuilds: true, entities: true, claims: true }, orderBy: { createdAt: "desc" } }, category: true } });
  if (!document) notFound();
  return <><p className="eyebrow">{document.type} · {document.visibility}</p><h1>{document.versions[0]?.title}</h1><p>{document.versions[0]?.summary}</p><div className="fact-grid"><div><small>Versions</small><b>{document.versions.length}</b></div><div><small>Entities</small><b>{document.versions.reduce((sum, version) => sum + version.entities.length, 0)}</b></div><div><small>Claims</small><b>{document.versions.reduce((sum, version) => sum + version.claims.length, 0)}</b></div></div><article className="data-card"><p>{document.versions[0]?.content}</p></article></>;
}
