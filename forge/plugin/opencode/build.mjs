import { rm, mkdir } from "node:fs/promises";
import { build } from "esbuild";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });
await build({
  entryPoints: ["src/plugin.ts"],
  outfile: "dist/index.js",
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  external: ["@opencode-ai/plugin"],
  sourcemap: true,
});
