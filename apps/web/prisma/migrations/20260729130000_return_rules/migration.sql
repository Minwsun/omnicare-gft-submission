CREATE TABLE "ProductReturnProfile" (
  "id" TEXT NOT NULL,
  "productId" TEXT NOT NULL,
  "returnable" BOOLEAN NOT NULL DEFAULT true,
  "sealedRequired" BOOLEAN NOT NULL DEFAULT false,
  "accessoriesRequired" BOOLEAN NOT NULL DEFAULT false,
  "evidenceTypes" JSONB NOT NULL,
  "exclusions" JSONB NOT NULL,
  CONSTRAINT "ProductReturnProfile_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "ProductReturnProfile_productId_key" ON "ProductReturnProfile"("productId");
ALTER TABLE "ProductReturnProfile" ADD CONSTRAINT "ProductReturnProfile_productId_fkey" FOREIGN KEY ("productId") REFERENCES "Product"("id") ON DELETE CASCADE ON UPDATE CASCADE;

CREATE TABLE "ReturnPolicyRule" (
  "id" TEXT NOT NULL,
  "category" TEXT NOT NULL,
  "reasonCode" TEXT NOT NULL,
  "windowDays" INTEGER NOT NULL,
  "returnable" BOOLEAN NOT NULL,
  "sealedRequired" BOOLEAN NOT NULL DEFAULT false,
  "evidenceTypes" JSONB NOT NULL,
  "conditions" JSONB NOT NULL,
  "exceptions" JSONB NOT NULL,
  "authorityLevel" INTEGER NOT NULL DEFAULT 100,
  "effectiveFrom" TIMESTAMP(3) NOT NULL,
  "effectiveTo" TIMESTAMP(3),
  "documentId" TEXT NOT NULL,
  "versionId" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "ReturnPolicyRule_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "ReturnPolicyRule_category_reasonCode_effectiveFrom_effectiveTo_idx" ON "ReturnPolicyRule"("category", "reasonCode", "effectiveFrom", "effectiveTo");
