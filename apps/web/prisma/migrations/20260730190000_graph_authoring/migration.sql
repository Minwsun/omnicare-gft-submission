CREATE TYPE "GraphNodeKind" AS ENUM ('DOCUMENT','FAQ','POLICY','TERMS','RULE','INTENT','ACTION','PRODUCT_SCOPE','ORDER_STATUS','PAYMENT_STATUS','INCIDENT','ESCALATION');
CREATE TYPE "GraphImportance" AS ENUM ('LOW','MEDIUM','HIGH','CRITICAL');

CREATE TABLE "GraphDraftNode" (
  "id" TEXT NOT NULL PRIMARY KEY, "workspaceId" TEXT NOT NULL, "kind" "GraphNodeKind" NOT NULL,
  "name" TEXT NOT NULL, "summary" TEXT NOT NULL DEFAULT '', "content" TEXT NOT NULL DEFAULT '',
  "importance" "GraphImportance" NOT NULL DEFAULT 'MEDIUM', "visibility" "KnowledgeVisibility" NOT NULL DEFAULT 'INTERNAL',
  "mandatory" BOOLEAN NOT NULL DEFAULT false, "archived" BOOLEAN NOT NULL DEFAULT false,
  "positionX" DOUBLE PRECISION NOT NULL DEFAULT 0, "positionY" DOUBLE PRECISION NOT NULL DEFAULT 0,
  "metadata" JSONB, "documentId" TEXT, "versionId" TEXT, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "GraphDraftNode_workspaceId_fkey" FOREIGN KEY ("workspaceId") REFERENCES "GraphWorkspace"("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "GraphDraftNode_workspaceId_kind_importance_idx" ON "GraphDraftNode"("workspaceId","kind","importance");

CREATE TABLE "GraphDraftEdge" (
  "id" TEXT NOT NULL PRIMARY KEY, "workspaceId" TEXT NOT NULL, "sourceId" TEXT NOT NULL, "targetId" TEXT NOT NULL,
  "relation" "KnowledgeRelationType" NOT NULL, "weight" DOUBLE PRECISION NOT NULL DEFAULT 1, "metadata" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "GraphDraftEdge_workspaceId_fkey" FOREIGN KEY ("workspaceId") REFERENCES "GraphWorkspace"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "GraphDraftEdge_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "GraphDraftNode"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "GraphDraftEdge_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "GraphDraftNode"("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX "GraphDraftEdge_workspaceId_sourceId_targetId_relation_key" ON "GraphDraftEdge"("workspaceId","sourceId","targetId","relation");
CREATE INDEX "GraphDraftEdge_workspaceId_relation_idx" ON "GraphDraftEdge"("workspaceId","relation");

CREATE TABLE "GraphValidationIssue" (
  "id" TEXT NOT NULL PRIMARY KEY, "workspaceId" TEXT NOT NULL, "severity" "GraphImportance" NOT NULL,
  "code" TEXT NOT NULL, "message" TEXT NOT NULL, "nodeId" TEXT, "edgeId" TEXT, "resolved" BOOLEAN NOT NULL DEFAULT false,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "GraphValidationIssue_workspaceId_fkey" FOREIGN KEY ("workspaceId") REFERENCES "GraphWorkspace"("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "GraphValidationIssue_workspaceId_resolved_severity_idx" ON "GraphValidationIssue"("workspaceId","resolved","severity");
