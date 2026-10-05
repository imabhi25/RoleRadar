import path from "node:path";
export default {
  root: path.resolve(__dirname, "../../frontend"),
  server: { fs: { strict: false } },
  test: { environment: "jsdom", include: [path.resolve(__dirname, "ui_render.audit.ts")], testTimeout: 900000 },
};
