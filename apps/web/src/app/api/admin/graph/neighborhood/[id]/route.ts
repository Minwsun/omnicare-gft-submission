import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const limit = Math.min(100, Number(new URL(request.url).searchParams.get("limit") || 60));
  const center = await prisma.knowledgeEntity.findUnique({ where: { id } });
  if (!center) return NextResponse.json({ error: "NODE_NOT_FOUND" }, { status: 404 });
  const edges = await prisma.knowledgeEdge.findMany({
    where: { OR: [{ sourceId: id }, { targetId: id }] },
    include: { source: true, target: true },
    take: limit,
  });
  const nodes = new Map([[center.id, center], ...edges.flatMap((edge) => [[edge.source.id, edge.source], [edge.target.id, edge.target]] as const)]);
  return NextResponse.json({
    centerId: id,
    nodes: [...nodes.values()].map((node) => ({ id: node.id, type: node.type, label: node.canonicalName, metadata: node.metadata })),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.sourceId, target: edge.targetId, relation: edge.relation, weight: edge.weight })),
  });
}
