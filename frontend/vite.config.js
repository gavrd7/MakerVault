import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Emscripten's WASM loader must resolve its own bundled asset rather than
  // being prebundled by Vite's dev dependency optimizer.
  optimizeDeps: { exclude: ["manifold-3d"] },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/chunk-[name]-[hash].js",
        assetFileNames: (assetInfo) => assetInfo.name?.endsWith(".css") ? "assets/app.css" : "assets/[name][extname]"
      }
    }
  }
});
