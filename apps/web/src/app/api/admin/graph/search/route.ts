import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(request: Request) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const query = new URL(request.url).searchParams.get("q")?.trim();
  const nodes = await prisma.knowledgeEntity.findMany({
    where: query ? { OR: [{ canonicalName: { contains: query, mode: "insensitive" } }, { normalizedKey: { contains: query.toLowerCase() } }] } : {},
    take: 30,
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json({ nodes: nodes.map((node) => ({ id: node.id, type: node.type, label: node.canonicalName })) });
}
