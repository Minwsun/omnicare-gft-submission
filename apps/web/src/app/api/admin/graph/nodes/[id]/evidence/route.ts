import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const node = await prisma.knowledgeSummaryNode.findUnique({ where: { id } });
  if (!node) return NextResponse.json({ error: "NODE_NOT_FOUND" }, { status: 404 });
  const chunkIds = Array.isArray(node.sourceChunkIds) ? node.sourceChunkIds.filter((value): value is string => typeof value === "string") : [];
  const chunks = await prisma.knowledgeChunk.findMany({ where: { id: { in: chunkIds } }, include: { version: { include: { document: true } } }, take: 100 });
  return NextResponse.json({ node, chunks });
}
