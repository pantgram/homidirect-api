/*
  Warnings:

  - You are about to drop the column `listingId` on the `Booking` table. All the data in the column will be lost.
  - You are about to drop the column `landlordId` on the `Listing` table. All the data in the column will be lost.
  - You are about to drop the `Image` table. If the table is not empty, all the data it contains will be lost.
  - You are about to drop the `_UserBookings` table. If the table is not empty, all the data it contains will be lost.
  - Added the required column `landlord_id` to the `Booking` table without a default value. This is not possible if the table is not empty.
  - Added the required column `listing_id` to the `Booking` table without a default value. This is not possible if the table is not empty.
  - Added the required column `tenant_id` to the `Booking` table without a default value. This is not possible if the table is not empty.
  - Added the required column `landlord_id` to the `Listing` table without a default value. This is not possible if the table is not empty.

*/
-- AlterTable
ALTER TABLE "public"."Booking" DROP COLUMN "listingId",
ADD COLUMN     "landlord_id" INTEGER NOT NULL,
ADD COLUMN     "listing_id" INTEGER NOT NULL,
ADD COLUMN     "tenant_id" INTEGER NOT NULL;

-- AlterTable
ALTER TABLE "public"."Listing" DROP COLUMN "landlordId",
ADD COLUMN     "landlord_id" INTEGER NOT NULL;

-- DropTable
DROP TABLE "public"."Image";

-- DropTable
DROP TABLE "public"."_UserBookings";

-- CreateTable
CREATE TABLE "public"."ListingImage" (
    "id" SERIAL NOT NULL,
    "url" TEXT NOT NULL,
    "listing_id" INTEGER NOT NULL,

    CONSTRAINT "ListingImage_pkey" PRIMARY KEY ("id")
);
