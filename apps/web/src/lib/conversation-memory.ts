import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";

const TRANSACTION_INTENTS = new Set(["ORDER_TRACKING", "ORDER_CANCELLATION", "PAYMENT_STATUS", "REFUND_STATUS", "RETURN_ELIGIBILITY", "PRODUCT_DISCOVERY", "CHECKOUT"]);
const CONTEXT_RESET_INTENTS = new Set(["OUT_OF_SCOPE"]);

type MemoryResult = {
  intent?: string;
  resolved_context?: Record<string, unknown>;
  missing_facts?: string[];
  verified_facts?: Array<{ key: string; value: Prisma.InputJsonValue; source?: string }>;
  confidence?: number;
};

function redactSensitive(value: string) {
  return value
    .replace(/\b\d{6}\b/g, "[REDACTED_OTP]")
    .replace(/\b(?:\d[ -]*?){13,19}\b/g, "[REDACTED_CARD]")
    .replace(/(?:password|mật khẩu|api[_ -]?key)\s*[:=]\s*\S+/gi, "$1=[REDACTED]");
}

function compactSummary(messages: Array<{ direction: string; content: string }>) {
  const turns = messages.slice(-8).map((message) => `${message.direction === "INBOUND" ? "Khách" : "Agent"}: ${redactSensitive(message.content).replace(/\s+/g, " ").slice(0, 500)}`);
  return turns.join("\n").slice(-4000);
}

export async function loadConversationContext(conversationId: string, customerId: string, pageContext: Record<string, unknown>) {
  const [memory, facts, recentMessages] = await Promise.all([
    prisma.conversationMemory.findUnique({ where: { conversationId } }),
    prisma.customerMemoryFact.findMany({ where: { customerId, active: true, OR: [{ expiresAt: null }, { expiresAt: { gt: new Date() } }] }, orderBy: { updatedAt: "desc" }, take: 12 }),
    prisma.message.findMany({ where: { conversationId }, orderBy: { createdAt: "desc" }, take: 12, select: { direction: true, content: true } }),
  ]);
  return {
    ...pageContext,
    conversationHistory: recentMessages.reverse(),
    memory: {
      summary: memory?.summary || "",
      activeContext: memory?.activeContext || {},
      unresolvedQuestions: memory?.unresolvedQuestions || [],
      graphAnchors: memory?.graphAnchors || [],
      customerFacts: facts.map((fact) => ({ category: fact.category, key: fact.key, value: fact.value, confidence: fact.confidence, provenance: fact.provenance })),
    },
  };
}

export async function persistConversationMemory(params: { conversationId: string; customerId: string; inboundMessageId: string; result: MemoryResult }) {
  const { conversationId, customerId, inboundMessageId, result } = params;
  const [existing, messages] = await Promise.all([
    prisma.conversationMemory.findUnique({ where: { conversationId } }),
    prisma.message.findMany({ where: { conversationId }, orderBy: { createdAt: "desc" }, take: 10, select: { direction: true, content: true } }),
  ]);
  const intent = String(result.intent || "");
  const oldContext = (existing?.activeContext || {}) as Record<string, unknown>;
  const resolved = (result.resolved_context || {}) as Record<string, unknown>;
  const activeContext: Record<string, unknown> = CONTEXT_RESET_INTENTS.has(intent) ? {} : { ...oldContext, ...resolved, ...(TRANSACTION_INTENTS.has(intent) ? { activeIntent: intent } : {}) };
  const orderId = typeof activeContext.orderId === "string" ? activeContext.orderId : undefined;
  const productId = typeof activeContext.productId === "string" ? activeContext.productId : undefined;
  const checkoutId = typeof activeContext.checkoutId === "string" ? activeContext.checkoutId : undefined;
  const anchors = [`customer:${customerId}`, `conversation:${conversationId}`, ...(orderId ? [`order:${customerId}:${orderId}`] : []), ...(productId ? [`product:${productId}`] : []), ...(checkoutId ? [`checkout:${checkoutId}`] : [])];
  const summary = compactSummary(messages.reverse());
  const nextVersion = (existing?.version || 0) + 1;
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);

  await prisma.$transaction(async (tx) => {
    await tx.conversationMemory.upsert({
      where: { conversationId },
      update: { customerId, summary, activeContext: activeContext as Prisma.InputJsonValue, unresolvedQuestions: (result.missing_facts || []) as Prisma.InputJsonValue, graphAnchors: anchors, messageCount: { increment: 2 }, version: nextVersion },
      create: { conversationId, customerId, summary, activeContext: activeContext as Prisma.InputJsonValue, unresolvedQuestions: (result.missing_facts || []) as Prisma.InputJsonValue, graphAnchors: anchors, messageCount: messages.length, version: nextVersion },
    });
    await tx.memorySnapshot.updateMany({ where: { conversationId, active: true }, data: { active: false } });
    await tx.memorySnapshot.create({ data: { conversationId, customerId, summary, state: { activeContext, unresolvedQuestions: result.missing_facts || [], anchors } as Prisma.InputJsonValue, version: nextVersion } });

    const customerNodeId = `customer:${customerId}`;
    const conversationNodeId = `conversation:${conversationId}`;
    await tx.memoryNode.upsert({ where: { id: customerNodeId }, update: { label: customerId, active: true }, create: { id: customerNodeId, customerId, type: "CUSTOMER", key: customerId, label: customerId } });
    await tx.memoryNode.upsert({ where: { id: conversationNodeId }, update: { label: summary.slice(-180) || "Cuộc trò chuyện", data: { activeContext } as Prisma.InputJsonValue, active: true }, create: { id: conversationNodeId, customerId, conversationId, type: "CONVERSATION", key: conversationId, label: summary.slice(-180) || "Cuộc trò chuyện", data: { activeContext } as Prisma.InputJsonValue } });
    await tx.memoryEdge.upsert({ where: { sourceId_targetId_relation: { sourceId: customerNodeId, targetId: conversationNodeId, relation: "DISCUSSED_IN" } }, update: { active: true }, create: { id: `edge:${customerId}:${conversationId}`, customerId, conversationId, sourceId: customerNodeId, targetId: conversationNodeId, relation: "DISCUSSED_IN" } });

    if (orderId) {
      const orderNodeId = `order:${customerId}:${orderId}`;
      await tx.memoryNode.upsert({ where: { id: orderNodeId }, update: { label: orderId, sourceMessageId: inboundMessageId, active: true, expiresAt }, create: { id: orderNodeId, customerId, conversationId, type: "ORDER", key: orderId, label: orderId, sourceMessageId: inboundMessageId, expiresAt } });
      await tx.memoryEdge.upsert({ where: { sourceId_targetId_relation: { sourceId: conversationNodeId, targetId: orderNodeId, relation: "ACTIVE_CONTEXT" } }, update: { active: true, metadata: { intent } }, create: { id: `edge:${conversationId}:${orderId}:active`, customerId, conversationId, sourceId: conversationNodeId, targetId: orderNodeId, relation: "ACTIVE_CONTEXT", metadata: { intent } } });
      for (const fact of result.verified_facts || []) {
        await tx.customerMemoryFact.upsert({
          where: { customerId_category_key: { customerId, category: "TRANSACTION", key: `${orderId}:${fact.key}` } },
          update: { value: fact.value as Prisma.InputJsonValue, confidence: result.confidence || 1, sourceConversationId: conversationId, sourceMessageId: inboundMessageId, provenance: fact.source || "TOOL", active: true, expiresAt },
          create: { customerId, category: "TRANSACTION", key: `${orderId}:${fact.key}`, value: fact.value as Prisma.InputJsonValue, confidence: result.confidence || 1, sourceConversationId: conversationId, sourceMessageId: inboundMessageId, provenance: fact.source || "TOOL", expiresAt },
        });
      }
    }
  });
}
