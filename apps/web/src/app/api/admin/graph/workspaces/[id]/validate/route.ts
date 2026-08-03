import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

type Issue = { severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"; code: string; message: string; nodeId?: string; edgeId?: string };
type GraphEdge = { id: string; sourceId: string; targetId: string; relation: string };

const HIERARCHICAL_RELATIONS = new Set(["ANSWERS", "GOVERNED_BY", "REQUIRES", "APPLIES_TO", "ESCALATES_TO"]);
const hierarchyPair = (edge: GraphEdge) => edge.relation === "ESCALATES_TO" ? { parent: edge.sourceId, child: edge.targetId } : { parent: edge.targetId, child: edge.sourceId };

function graphHasCycle(graph: Map<string, string[]>, nodeIds: string[]) {
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (nodeId: string): boolean => {
    if (visiting.has(nodeId)) return true;
    if (visited.has(nodeId)) return false;
    visiting.add(nodeId);
    for (const target of graph.get(nodeId) ?? []) if (visit(target)) return true;
    visiting.delete(nodeId);
    visited.add(nodeId);
    return false;
  };
  return nodeIds.some(visit);
}

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const workspace = await prisma.graphWorkspace.findUnique({ where: { id }, include: { draftNodes: true, draftEdges: true } });
  if (!workspace) return NextResponse.json({ error: "WORKSPACE_NOT_FOUND" }, { status: 404 });

  const issues: Issue[] = [];
  const activeNodes = workspace.draftNodes.filter((node) => !node.archived);
  const nodeById = new Map(activeNodes.map((node) => [node.id, node]));
  const normalizedNames = new Map<string, string>();
  const connected = new Set(workspace.draftEdges.flatMap((edge) => [edge.sourceId, edge.targetId]));
  for (const node of activeNodes) {
    if (!node.name.trim()) issues.push({ severity: "HIGH", code: "NODE_NAME_REQUIRED", message: "Node chưa có tên", nodeId: node.id });
    if (node.mandatory && !["POLICY", "TERMS", "RULE"].includes(node.kind)) issues.push({ severity: "CRITICAL", code: "MANDATORY_NODE_INVALID", message: "Chỉ POLICY, TERMS hoặc RULE được đánh dấu bắt buộc", nodeId: node.id });
    if (node.mandatory && !node.content.trim()) issues.push({ severity: "CRITICAL", code: "MANDATORY_CONTENT_REQUIRED", message: "Policy bắt buộc phải có nội dung", nodeId: node.id });
    const normalizedName = node.name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
    const duplicateId = normalizedNames.get(normalizedName);
    if (duplicateId) issues.push({ severity: "HIGH", code: "DUPLICATE_NODE_NAME", message: `Node trùng tên với ${duplicateId}`, nodeId: node.id });
    else normalizedNames.set(normalizedName, node.id);
    if (activeNodes.length > 1 && !connected.has(node.id)) issues.push({ severity: "MEDIUM", code: "ORPHAN_NODE", message: "Node chưa được nối vào knowledge graph", nodeId: node.id });
  }

  const relationPairs = new Map<string, Set<string>>();
  const hierarchy = new Map<string, string[]>();
  const parentCounts = new Map<string, number>();
  for (const edge of workspace.draftEdges as GraphEdge[]) {
    if (!nodeById.has(edge.sourceId) || !nodeById.has(edge.targetId)) issues.push({ severity: "HIGH", code: "EDGE_NODE_MISSING", message: "Quan hệ tham chiếu node không còn tồn tại", edgeId: edge.id });
    if (edge.sourceId === edge.targetId) issues.push({ severity: "HIGH", code: "SELF_EDGE", message: "Không cho phép node tự nối chính nó", edgeId: edge.id });
    const pairKey = `${edge.sourceId}:${edge.targetId}`;
    const relations = relationPairs.get(pairKey) ?? new Set<string>();
    relations.add(edge.relation);
    relationPairs.set(pairKey, relations);
    if (!HIERARCHICAL_RELATIONS.has(edge.relation)) continue;
    const pair = hierarchyPair(edge);
    hierarchy.set(pair.parent, [...(hierarchy.get(pair.parent) ?? []), pair.child]);
    parentCounts.set(pair.child, (parentCounts.get(pair.child) ?? 0) + 1);
    const target = nodeById.get(edge.targetId);
    if (edge.relation === "GOVERNED_BY" && target && !["POLICY", "TERMS", "RULE", "DOCUMENT"].includes(target.kind)) issues.push({ severity: "HIGH", code: "INVALID_GOVERNING_PARENT", message: "GOVERNED_BY phải trỏ tới POLICY, TERMS, RULE hoặc DOCUMENT", edgeId: edge.id });
    if (edge.relation === "ESCALATES_TO" && target && !["ESCALATION", "ACTION"].includes(target.kind)) issues.push({ severity: "HIGH", code: "INVALID_ESCALATION_TARGET", message: "ESCALATES_TO phải trỏ tới ESCALATION hoặc ACTION", edgeId: edge.id });
  }
  for (const [pair, relations] of relationPairs) if (relations.has("ALLOWS") && relations.has("PROHIBITS")) issues.push({ severity: "CRITICAL", code: "CONTRADICTORY_RELATION", message: `Quan hệ ${pair} vừa cho phép vừa cấm` });
  for (const [nodeId, count] of parentCounts) if (count > 1) issues.push({ severity: "HIGH", code: "MULTIPLE_PRIMARY_PARENTS", message: "Node có nhiều hơn một quan hệ cha phân cấp", nodeId });
  const nodeIds = activeNodes.map((node) => node.id);
  if (graphHasCycle(hierarchy, nodeIds)) issues.push({ severity: "CRITICAL", code: "HIERARCHY_CYCLE", message: "Quan hệ phân cấp tạo thành vòng lặp" });

  const supersedes = new Map<string, string[]>();
  for (const edge of (workspace.draftEdges as GraphEdge[]).filter((item) => item.relation === "SUPERSEDES")) supersedes.set(edge.sourceId, [...(supersedes.get(edge.sourceId) ?? []), edge.targetId]);
  if (graphHasCycle(supersedes, nodeIds)) issues.push({ severity: "CRITICAL", code: "SUPERSEDES_CYCLE", message: "Quan hệ thay thế tài liệu tạo thành vòng lặp" });

  const valid = !issues.some((issue) => issue.severity === "HIGH" || issue.severity === "CRITICAL");
  await prisma.$transaction([
    prisma.graphValidationIssue.deleteMany({ where: { workspaceId: id } }),
    ...issues.map((issue) => prisma.graphValidationIssue.create({ data: { workspaceId: id, ...issue } })),
    prisma.graphWorkspace.update({ where: { id }, data: { validation: { valid, issueCount: issues.length, checkedAt: new Date().toISOString() } } }),
  ]);
  return NextResponse.json({ valid, issues });
}
