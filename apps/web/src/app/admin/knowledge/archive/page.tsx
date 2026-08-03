import { prisma } from "@/lib/prisma";
import ArchiveManager from "./archive-manager";

export default async function KnowledgeArchivePage() {
  const documents = await prisma.knowledgeDocument.findMany({ where: { archivedAt: { not: null } }, include: { currentVersion: true }, orderBy: { archivedAt: "desc" }, take: 300 });
  return <><p className="eyebrow">KNOWLEDGE ARCHIVE</p><ArchiveManager initialDocuments={documents.map((document)=>({ id:document.id, title:document.currentVersion?.title ?? document.slug, type:document.type, archivedAt:document.archivedAt!.toISOString(), version:document.currentVersion?.semanticVersion ?? "N/A" }))}/></>;
}
