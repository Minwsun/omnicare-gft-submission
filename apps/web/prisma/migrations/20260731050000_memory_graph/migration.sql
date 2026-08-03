CREATE TABLE "ConversationMemory" (
  "conversationId" TEXT NOT NULL,
  "customerId" TEXT,
  "summary" TEXT NOT NULL DEFAULT '',
  "activeContext" JSONB NOT NULL DEFAULT '{}',
  "unresolvedQuestions" JSONB NOT NULL DEFAULT '[]',
  "graphAnchors" JSONB NOT NULL DEFAULT '[]',
  "messageCount" INTEGER NOT NULL DEFAULT 0,
  "version" INTEGER NOT NULL DEFAULT 1,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "ConversationMemory_pkey" PRIMARY KEY ("conversationId"),
  CONSTRAINT "ConversationMemory_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "ConversationMemory_customerId_updatedAt_idx" ON "ConversationMemory"("customerId", "updatedAt");

CREATE TABLE "MemoryNode" (
  "id" TEXT NOT NULL,
  "customerId" TEXT NOT NULL,
  "conversationId" TEXT,
  "type" TEXT NOT NULL,
  "key" TEXT NOT NULL,
  "label" TEXT NOT NULL,
  "data" JSONB NOT NULL DEFAULT '{}',
  "confidence" DOUBLE PRECISION NOT NULL DEFAULT 1,
  "sourceMessageId" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT true,
  "expiresAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "MemoryNode_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "MemoryNode_customerId_type_key_key" ON "MemoryNode"("customerId", "type", "key");
CREATE INDEX "MemoryNode_customerId_type_active_updatedAt_idx" ON "MemoryNode"("customerId", "type", "active", "updatedAt");
CREATE INDEX "MemoryNode_conversationId_active_idx" ON "MemoryNode"("conversationId", "active");

CREATE TABLE "MemoryEdge" (
  "id" TEXT NOT NULL,
  "customerId" TEXT NOT NULL,
  "conversationId" TEXT,
  "sourceId" TEXT NOT NULL,
  "targetId" TEXT NOT NULL,
  "relation" TEXT NOT NULL,
  "weight" DOUBLE PRECISION NOT NULL DEFAULT 1,
  "metadata" JSONB NOT NULL DEFAULT '{}',
  "active" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "MemoryEdge_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "MemoryEdge_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "MemoryNode"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "MemoryEdge_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "MemoryNode"("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX "MemoryEdge_sourceId_targetId_relation_key" ON "MemoryEdge"("sourceId", "targetId", "relation");
CREATE INDEX "MemoryEdge_customerId_relation_active_idx" ON "MemoryEdge"("customerId", "relation", "active");
CREATE INDEX "MemoryEdge_conversationId_active_idx" ON "MemoryEdge"("conversationId", "active");

CREATE TABLE "CustomerMemoryFact" (
  "id" TEXT NOT NULL,
  "customerId" TEXT NOT NULL,
  "category" TEXT NOT NULL,
  "key" TEXT NOT NULL,
  "value" JSONB NOT NULL,
  "confidence" DOUBLE PRECISION NOT NULL DEFAULT 1,
  "sourceConversationId" TEXT,
  "sourceMessageId" TEXT,
  "provenance" TEXT NOT NULL,
  "active" BOOLEAN NOT NULL DEFAULT true,
  "expiresAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "CustomerMemoryFact_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "CustomerMemoryFact_customerId_category_key_key" ON "CustomerMemoryFact"("customerId", "category", "key");
CREATE INDEX "CustomerMemoryFact_customerId_active_expiresAt_idx" ON "CustomerMemoryFact"("customerId", "active", "expiresAt");

CREATE TABLE "MemorySnapshot" (
  "id" TEXT NOT NULL,
  "conversationId" TEXT NOT NULL,
  "customerId" TEXT,
  "summary" TEXT NOT NULL,
  "state" JSONB NOT NULL,
  "version" INTEGER NOT NULL,
  "active" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "MemorySnapshot_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "MemorySnapshot_conversationId_active_createdAt_idx" ON "MemorySnapshot"("conversationId", "active", "createdAt");
