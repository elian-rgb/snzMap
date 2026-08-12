import { serveStatic } from "hono/bun";
import type { ViteDevServer } from "vite";
import { createServer as createViteServer } from "vite";
import { Hono } from "hono";
import { basicAuth } from "hono/basic-auth";

type Mode = "development" | "production";
const app = new Hono();

const mode: Mode =
  process.env.NODE_ENV === "production" ? "production" : "development";

const LOCAL_PORT = 5892;

if (mode === "production") {
  configureProduction(app);
} else {
  await configureDevelopment(app);
}

const port = process.env.PORT ? parseInt(process.env.PORT, 10) : LOCAL_PORT;

export default { fetch: app.fetch, port, idleTimeout: 255 };

function gate() {
  // Light deterrent on an internal research console, not real security.
  return basicAuth({
    username: process.env.CONSOLE_USER || "snz",
    password: process.env.CONSOLE_PASSWORD || "netzero",
  });
}

function configureProduction(app: Hono) {
  app.get("/console", gate(), serveStatic({ path: "./dist/index.html" }));
  app.get("/console/", gate(), serveStatic({ path: "./dist/index.html" }));
  app.use("/assets/*", serveStatic({ root: "./dist" }));
  app.use("/data/*", serveStatic({ root: "./dist" }));
  app.get("/", (c) => c.redirect("/console"));
}

async function configureDevelopment(app: Hono): Promise<ViteDevServer> {
  const vite = await createViteServer({
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: "custom",
  });

  // `hmr: false` above turns off more than live reloading. Vite invalidates its module graph
  // as part of the HMR path, so with HMR off `transformRequest` keeps returning the transform
  // it produced the first time and the browser is served the pre-edit module forever — while
  // `no-store` makes every fetch look fresh. That is worse than having no reloading at all:
  // an edit appears to have been made and verified when what was actually tested was the code
  // from before it. Dropping the graph on any source change restores "a reload shows what is
  // on disk" without bringing back the websocket this server deliberately does not run.
  vite.watcher.on("change", (file) => {
    if (file.includes("/node_modules/")) return;
    vite.moduleGraph.invalidateAll();
  });

  app.use("/console", gate());
  app.use("/console/*", gate());

  const noStore = { "Cache-Control": "no-store, must-revalidate" };

  app.use("*", async (c, next) => {
    const url = c.req.path;
    try {
      if (url === "/" || url === "/console" || url === "/console/") {
        let template = await Bun.file("./index.html").text();
        template = await vite.transformIndexHtml(url, template);
        return c.html(template, { headers: noStore });
      }

      // venues.geojson and the other layer files live in ./public/data.
      const publicFile = Bun.file(`./public${url}`);
      if (await publicFile.exists()) {
        const stat = await publicFile.stat();
        if (stat && !stat.isDirectory()) {
          return new Response(publicFile, { headers: noStore });
        }
      }

      let result;
      try {
        result = await vite.transformRequest(url);
      } catch (err) {
        // A module under /src/ that fails to transform must not fall through to the SPA
        // template. Answering it with index.html gives the browser a 200 and HTML where it
        // asked for JavaScript, so the import fails silently, React never mounts, and the
        // page goes blank with nothing in the console to say why.
        if (url.startsWith("/src/")) {
          vite.ssrFixStacktrace(err as Error);
          console.error(`[vite] transform failed for ${url}\n`, err);
          return c.text(`Transform failed for ${url}: ${(err as Error).message}`, 500);
        }
        result = null;
      }
      if (result) {
        return new Response(result.code, {
          headers: { "Content-Type": "application/javascript", ...noStore },
        });
      }

      let template = await Bun.file("./index.html").text();
      template = await vite.transformIndexHtml("/console", template);
      return c.html(template, { headers: noStore });
    } catch (error) {
      vite.ssrFixStacktrace(error as Error);
      console.error(error);
      return c.text("Internal Server Error", 500);
    }
  });

  return vite;
}
