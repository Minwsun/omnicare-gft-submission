-- CreateEnum
CREATE TYPE "KnowledgeEntityType" AS ENUM ('CONCEPT', 'INTENT', 'POLICY_RULE', 'CUSTOMER_RIGHT', 'PRODUCT', 'ORDER_STATUS', 'PAYMENT_STATUS', 'ACTION', 'INCIDENT');

-- CreateEnum
CREATE TYPE "KnowledgeRelationType" AS ENUM ('ANSWERS', 'GOVERNED_BY', 'REQUIRES', 'ALLOWS', 'PROHIBITS', 'APPLIES_TO', 'ESCALATES_TO', 'AFFECTED_BY', 'SUPERSEDES', 'RELATED_TO');

-- CreateEnum
CREATE TYPE "GraphBuildStatus" AS ENUM ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED');

-- CreateTable
CREATE TABLE "UserAccount" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "role" "PersonaRole" NOT NULL,
    "customerId" TEXT,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "UserAccount_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AuthSession" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "tokenHash" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revokedAt" TIMESTAMP(3),

    CONSTRAINT "AuthSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LoginAttempt" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "ipHash" TEXT NOT NULL,
    "success" BOOLEAN NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "LoginAttempt_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KnowledgeGraphBuild" (
    "id" TEXT NOT NULL,
    "versionId" TEXT NOT NULL,
    "status" "GraphBuildStatus" NOT NULL DEFAULT 'PENDING',
    "extractorVersion" TEXT NOT NULL,
    "entityCount" INTEGER NOT NULL DEFAULT 0,
    "edgeCount" INTEGER NOT NULL DEFAULT 0,
    "claimCount" INTEGER NOT NULL DEFAULT 0,
    "error" TEXT,
    "startedAt" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KnowledgeGraphBuild_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KnowledgeEntity" (
    "id" TEXT NOT NULL,
    "versionId" TEXT NOT NULL,
    "chunkId" TEXT NOT NULL,
    "type" "KnowledgeEntityType" NOT NULL,
    "canonicalName" TEXT NOT NULL,
    "normalizedKey" TEXT NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KnowledgeEntity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KnowledgeEdge" (
    "id" TEXT NOT NULL,
    "versionId" TEXT NOT NULL,
    "chunkId" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "relation" "KnowledgeRelationType" NOT NULL,
    "weight" DOUBLE PRECISION NOT NULL DEFAULT 1,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KnowledgeEdge_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "KnowledgeClaim" (
    "id" TEXT NOT NULL,
    "versionId" TEXT NOT NULL,
    "chunkId" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "predicate" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "polarity" INTEGER NOT NULL DEFAULT 1,
    "authorityLevel" INTEGER NOT NULL,
    "effectiveFrom" TIMESTAMP(3) NOT NULL,
    "effectiveTo" TIMESTAMP(3),
    "scope" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "KnowledgeClaim_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "UserAccount_email_key" ON "UserAccount"("email");

-- CreateIndex
CREATE UNIQUE INDEX "UserAccount_customerId_key" ON "UserAccount"("customerId");

-- CreateIndex
CREATE UNIQUE INDEX "AuthSession_tokenHash_key" ON "AuthSession"("tokenHash");

-- CreateIndex
CREATE INDEX "AuthSession_userId_expiresAt_idx" ON "AuthSession"("userId", "expiresAt");

-- CreateIndex
CREATE INDEX "LoginAttempt_email_createdAt_idx" ON "LoginAttempt"("email", "createdAt");

-- CreateIndex
CREATE INDEX "LoginAttempt_ipHash_createdAt_idx" ON "LoginAttempt"("ipHash", "createdAt");

-- CreateIndex
CREATE INDEX "KnowledgeGraphBuild_versionId_status_idx" ON "KnowledgeGraphBuild"("versionId", "status");

-- CreateIndex
CREATE INDEX "KnowledgeEntity_type_normalizedKey_idx" ON "KnowledgeEntity"("type", "normalizedKey");

-- CreateIndex
CREATE UNIQUE INDEX "KnowledgeEntity_versionId_type_normalizedKey_key" ON "KnowledgeEntity"("versionId", "type", "normalizedKey");

-- CreateIndex
CREATE INDEX "KnowledgeEdge_sourceId_relation_idx" ON "KnowledgeEdge"("sourceId", "relation");

-- CreateIndex
CREATE INDEX "KnowledgeEdge_targetId_relation_idx" ON "KnowledgeEdge"("targetId", "relation");

-- CreateIndex
CREATE UNIQUE INDEX "KnowledgeEdge_sourceId_targetId_relation_chunkId_key" ON "KnowledgeEdge"("sourceId", "targetId", "relation", "chunkId");

-- CreateIndex
CREATE INDEX "KnowledgeClaim_subject_predicate_effectiveFrom_effectiveTo_idx" ON "KnowledgeClaim"("subject", "predicate", "effectiveFrom", "effectiveTo");

-- AddForeignKey
ALTER TABLE "UserAccount" ADD CONSTRAINT "UserAccount_customerId_fkey" FOREIGN KEY ("customerId") REFERENCES "Customer"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuthSession" ADD CONSTRAINT "AuthSession_userId_fkey" FOREIGN KEY ("userId") REFERENCES "UserAccount"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeGraphBuild" ADD CONSTRAINT "KnowledgeGraphBuild_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "KnowledgeVersion"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEntity" ADD CONSTRAINT "KnowledgeEntity_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "KnowledgeVersion"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEntity" ADD CONSTRAINT "KnowledgeEntity_chunkId_fkey" FOREIGN KEY ("chunkId") REFERENCES "KnowledgeChunk"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEdge" ADD CONSTRAINT "KnowledgeEdge_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "KnowledgeVersion"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEdge" ADD CONSTRAINT "KnowledgeEdge_chunkId_fkey" FOREIGN KEY ("chunkId") REFERENCES "KnowledgeChunk"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEdge" ADD CONSTRAINT "KnowledgeEdge_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "KnowledgeEntity"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeEdge" ADD CONSTRAINT "KnowledgeEdge_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "KnowledgeEntity"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeClaim" ADD CONSTRAINT "KnowledgeClaim_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "KnowledgeVersion"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "KnowledgeClaim" ADD CONSTRAINT "KnowledgeClaim_chunkId_fkey" FOREIGN KEY ("chunkId") REFERENCES "KnowledgeChunk"("id") ON DELETE CASCADE ON UPDATE CASCADE;
