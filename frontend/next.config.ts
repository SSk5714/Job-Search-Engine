import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/v1 is proxied to FastAPI so the
// session cookie stays same-site and the backend URL never reaches the client.
const apiUrl = process.env.JOBPILOT_API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` }];
  },
};

export default config;
