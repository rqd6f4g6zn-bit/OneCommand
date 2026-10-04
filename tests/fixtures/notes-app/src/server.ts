import * as http from "node:http";
import { PrismaClient } from "@prisma/client";
import { validateTitle } from "./notes";
import type { CreateNoteResponse, ListNotesResponse } from "./api-contract";

const prisma = new PrismaClient();
const port = Number(process.env.PORT ?? 3000);

const page = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Notes</title></head>
<body><h1>Notes</h1>
<form id="f"><label>Title <input name="title" /></label><button type="submit">Add note</button></form>
<p id="error" role="alert"></p><ul id="list"></ul>
<script>
async function load() {
  const notes = await (await fetch('/api/notes')).json();
  document.getElementById('list').innerHTML = notes.map(n => '<li>' + n.title.replace(/</g, '&lt;') + '</li>').join('');
}
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const title = new FormData(e.target).get('title');
  const res = await fetch('/api/notes', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title }) });
  document.getElementById('error').textContent = res.ok ? '' : 'Title is required';
  if (res.ok) { e.target.reset(); load(); }
};
load();
</script></body></html>`;

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.url === "/api/notes" && req.method === "GET") {
      const notes = await prisma.note.findMany({ orderBy: { id: "asc" } });
      const body = notes.map((n) => ({ id: n.id, title: n.title })) satisfies ListNotesResponse;
      res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(body));
      return;
    }
    if (req.url === "/api/notes" && req.method === "POST") {
      let title: string | null = null;
      try {
        title = validateTitle(JSON.parse(await readBody(req)).title);
      } catch {
        title = null;
      }
      if (!title) {
        res.writeHead(400, { "content-type": "application/json" }).end('{"error":"title required"}');
        return;
      }
      const note = await prisma.note.create({ data: { title } });
      const body = { id: note.id, title: note.title } satisfies CreateNoteResponse;
      res.writeHead(201, { "content-type": "application/json" }).end(JSON.stringify(body));
      return;
    }
    res.writeHead(200, { "content-type": "text/html" }).end(page);
  } catch (err) {
    res.writeHead(500).end(String(err));
  }
});

server.listen(port, "127.0.0.1");
