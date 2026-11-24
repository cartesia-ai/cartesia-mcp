import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// MCP Apps hosts load one HTML document, so everything is inlined into it.
export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    outDir: "../cartesia_mcp/static",
    emptyOutDir: false,
    rollupOptions: { input: "tts-player.html" },
  },
});
