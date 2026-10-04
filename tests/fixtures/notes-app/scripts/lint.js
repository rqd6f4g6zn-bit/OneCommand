// Tiny lint: no console.log left in src/ (stands in for ESLint without extra deps).
const fs = require("node:fs");
const path = require("node:path");
let errors = 0;
for (const file of fs.readdirSync("src")) {
  const lines = fs.readFileSync(path.join("src", file), "utf8").split("\n");
  lines.forEach((line, i) => {
    if (line.includes("console.log(")) {
      console.error(`src/${file}:${i + 1}:1  error  console.log is not allowed  no-console`);
      errors++;
    }
  });
}
process.exit(errors ? 1 : 0);
