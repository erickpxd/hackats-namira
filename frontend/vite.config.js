import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const createApiProxy = () => ({
  "/api": {
    target: "http://127.0.0.1:8765",
    changeOrigin: true,
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq, request) => {
        if (request.headers.origin) {
          proxyReq.setHeader("Origin", "http://127.0.0.1:8765");
        }
      });
    },
  },
  "/evidence": {
    target: "http://127.0.0.1:8765",
    changeOrigin: true,
  },
});

export default defineConfig({
  root: ".",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: createApiProxy(),
  },
  preview: {
    host: "127.0.0.1",
    proxy: createApiProxy(),
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: (asset) =>
          asset.name && asset.name.endsWith(".css")
            ? "assets/app.css"
            : "assets/[name][extname]",
      },
    },
  },
});
