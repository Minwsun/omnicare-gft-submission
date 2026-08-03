CREATE TYPE "GraphWorkspaceStatus" AS ENUM ('DRAFT', 'REVIEW', 'PUBLISHED', 'REJECTED');
CREATE TABLE "GraphWorkspace" (
  "id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "status" "GraphWorkspaceStatus" NOT NULL DEFAULT 'DRAFT',
  "centerNodeId" TEXT,
  "nodes" JSONB NOT NULL,
  "edges" JSONB NOT NULL,
  "validation" JSONB,
  "createdBy" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "GraphWorkspace_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "GraphWorkspace_status_updatedAt_idx" ON "GraphWorkspace"("status", "updatedAt");
