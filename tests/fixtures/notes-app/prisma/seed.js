const { PrismaClient } = require("@prisma/client");
const prisma = new PrismaClient();
prisma.note.deleteMany()
  .then(() => prisma.note.create({ data: { title: "Welcome" } }))
  .finally(() => prisma.$disconnect());
