import Link from "next/link";

import { prisma } from "@/lib/prisma";

const PAGE_SIZE = 24;

export default async function HelpPage({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  const requestedPage = Number((await searchParams).page || "1");
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const now = new Date();
  const where = { visibility: "PUBLIC" as const, archivedAt: null, currentVersion: { status: "PUBLISHED" as const, searchable: true, effectiveFrom: { lte: now }, OR: [{ effectiveTo: null }, { effectiveTo: { gt: now } }] } };
  const [documents, total] = await Promise.all([
    prisma.knowledgeDocument.findMany({ where, select: { id:true, slug:true, type:true, category:{select:{name:true}}, currentVersion:{select:{title:true,summary:true,semanticVersion:true}} }, orderBy: [{ authorityLevel: "desc" }, { updatedAt: "desc" }], skip:(page-1)*PAGE_SIZE, take:PAGE_SIZE }),
    prisma.knowledgeDocument.count({ where }),
  ]);
  const pages = Math.max(1, Math.ceil(total/PAGE_SIZE));
  return <main className="shell help"><Link className="back-link" href="/">← OmniCare</Link><p className="eyebrow">KNOWLEDGE PLATFORM</p><h1>Trung tâm trợ giúp</h1><p>{total} tài liệu public đang hiệu lực.</p><div className="data-list">{documents.map((document) => <Link className="data-card" key={document.id} href={`/help/${document.slug}`}><header><b>{document.currentVersion?.title}</b><span>{document.type}</span></header><p>{document.currentVersion?.summary}</p><small>{document.category.name} · v{document.currentVersion?.semanticVersion}</small></Link>)}</div><nav className="pagination">{page>1&&<Link href={`/help?page=${page-1}`}>← Trang trước</Link>}<span>Trang {page}/{pages}</span>{page<pages&&<Link href={`/help?page=${page+1}`}>Trang sau →</Link>}</nav></main>;
}
