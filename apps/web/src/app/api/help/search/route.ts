import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams.get("q")?.trim();
  if (!query) return NextResponse.json({ results: [] });
  const now = new Date();
  const results = await prisma.knowledgeDocument.findMany({
    where: { visibility: "PUBLIC", archivedAt: null, currentVersion: { status: "PUBLISHED", searchable: true, effectiveFrom: { lte: now }, OR: [{ effectiveTo: null }, { effectiveTo: { gt: now } }], AND: [{ OR: [{ title: { contains: query, mode: "insensitive" } }, { content: { contains: query, mode: "insensitive" } }] }] } },
    include: { currentVersion: true },
    take: 20,
  });
  return NextResponse.json({ results: results.map((document) => ({ id: document.id, slug: document.slug, type: document.type, title: document.currentVersion?.title, summary: document.currentVersion?.summary, version: document.currentVersion?.semanticVersion })) });
}
