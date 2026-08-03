import Link from "next/link";
import { notFound } from "next/navigation";

import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

export default async function KnowledgePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const now = new Date();
  const document = await prisma.knowledgeDocument.findFirst({
    where: { slug, visibility: "PUBLIC", archivedAt: null, currentVersion: { status: "PUBLISHED", searchable: true, effectiveFrom: { lte: now }, OR: [{ effectiveTo: null }, { effectiveTo: { gt: now } }] } },
    include: { currentVersion: true, category: true },
  });
  if (!document?.currentVersion) notFound();
  return <main className="shell help"><Link className="back-link" href="/help">← Trung tâm trợ giúp</Link><p className="eyebrow">{document.type} · {document.category.name}</p><h1>{document.currentVersion.title}</h1><p>{document.currentVersion.summary}</p><article className="data-card"><p>{document.currentVersion.content}</p></article><div className="fact-grid"><div><small>Phiên bản</small><b>{document.currentVersion.semanticVersion}</b></div><div><small>Hiệu lực</small><b>{document.currentVersion.effectiveFrom.toLocaleDateString("vi-VN")}</b></div><div><small>Cập nhật</small><b>{document.currentVersion.publishedAt?.toLocaleDateString("vi-VN")}</b></div></div></main>;
}
