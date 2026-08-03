ALTER TABLE "Product"
ADD COLUMN "brand" TEXT NOT NULL DEFAULT 'OmniShop',
ADD COLUMN "description" TEXT NOT NULL DEFAULT '',
ADD COLUMN "price" DECIMAL(14,2) NOT NULL DEFAULT 0,
ADD COLUMN "stock" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN "rating" DECIMAL(3,2) NOT NULL DEFAULT 0,
ADD COLUMN "soldCount" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN "active" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN "metadata" JSONB NOT NULL DEFAULT '{}';
CREATE INDEX "Product_category_active_stock_idx" ON "Product"("category", "active", "stock");
CREATE INDEX "Product_price_idx" ON "Product"("price");
CREATE TABLE "CheckoutSession" (
  "id" TEXT NOT NULL PRIMARY KEY, "customerId" TEXT NOT NULL, "conversationId" TEXT NOT NULL,
  "productId" TEXT NOT NULL, "addressId" TEXT, "quantity" INTEGER NOT NULL DEFAULT 1,
  "paymentMethod" TEXT, "unitPrice" DECIMAL(14,2) NOT NULL, "totalAmount" DECIMAL(14,2) NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'DRAFT', "orderId" TEXT, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL, "expiresAt" TIMESTAMP(3) NOT NULL
);
CREATE UNIQUE INDEX "CheckoutSession_orderId_key" ON "CheckoutSession"("orderId");
CREATE INDEX "CheckoutSession_customerId_conversationId_status_idx" ON "CheckoutSession"("customerId", "conversationId", "status");
ALTER TABLE "CheckoutSession" ADD CONSTRAINT "CheckoutSession_customerId_fkey" FOREIGN KEY ("customerId") REFERENCES "Customer"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "CheckoutSession" ADD CONSTRAINT "CheckoutSession_productId_fkey" FOREIGN KEY ("productId") REFERENCES "Product"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "CheckoutSession" ADD CONSTRAINT "CheckoutSession_addressId_fkey" FOREIGN KEY ("addressId") REFERENCES "Address"("id") ON DELETE SET NULL ON UPDATE CASCADE;
