import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, run both the backend and `npm run dev`
// on the SAME machine so the proxy targets the local backend
export default defineConfig({
  plugins: [react(), tailwindcss()],

  server: {
    host: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
