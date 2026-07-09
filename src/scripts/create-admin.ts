import { prisma } from "../lib/db";
import { upsertAdminUser } from "../lib/admin-auth";

async function main() {
  const username = process.argv[2] ?? "hendo420";
  const password = process.env.GPU45_ADMIN_PASSWORD;
  if (!password) throw new Error("Set GPU45_ADMIN_PASSWORD for this one-time command.");
  await upsertAdminUser(username, password);
  console.log(`Provisioned GPU45 administrator ${username}.`);
}

void main().finally(async () => prisma.$disconnect());
