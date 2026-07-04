import "@testing-library/jest-dom/vitest";

process.env.DATABASE_URL ??= "file:./prisma/dev.db";
process.env.GPU45_MODE ??= "mock";
