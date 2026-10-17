import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const port = Number(process.env.PORT || 4173);
const contentTypes = {
  ".binarypb": "application/octet-stream",
  ".data": "application/octet-stream",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".wasm": "application/wasm",
};

export function createSmokeServer() {
  return createServer(async (request, response) => {
    const requested = request.url === "/" ? "index.html" : request.url.slice(1);
    const relative = requested === "app.js" ? "dist/app.js" : requested;
    const file = normalize(join(root, relative));
    if (!file.startsWith(normalize(root))) {
      response.writeHead(400).end("Bad request");
      return;
    }
    try {
      const body = await readFile(file);
      response.writeHead(200, { "content-type": contentTypes[extname(file)] || "application/octet-stream", "cache-control": "no-store" });
      response.end(body);
    } catch {
      response.writeHead(404).end("Not found");
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const server = createSmokeServer();
  server.listen(port, "localhost", () => {
    console.log(`P3 WebGazer smoke test: http://localhost:${port}/`);
    console.log("Stop with Ctrl+C.");
  });
}
