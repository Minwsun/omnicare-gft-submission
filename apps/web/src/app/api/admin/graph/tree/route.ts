import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(request: Request) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parentId = new URL(request.url).searchParams.get("parentId");
  const snapshot = await prisma.knowledgeGraphSnapshot.findFirst({ where: { active: true }, orderBy: { createdAt: "desc" } });
  if (!snapshot) return NextResponse.json({ snapshot: null, nodes: [] });
  const nodes = await prisma.knowledgeSummaryNode.findMany({ where: { snapshotId: snapshot.id, active: true, parentId }, orderBy: [{ level: "desc" }, { title: "asc" }], take: 200 });
  const childCounts = await prisma.knowledgeSummaryNode.groupBy({ by: ["parentId"], where: { snapshotId: snapshot.id, active: true, parentId: { in: nodes.map((node) => node.id) } }, _count: true });
  const counts = new Map(childCounts.map((item) => [item.parentId, item._count]));
  return NextResponse.json({ snapshot, nodes: nodes.map((node) => ({ ...node, childCount: counts.get(node.id) || 0 })) });
}
