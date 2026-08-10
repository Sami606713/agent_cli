/** @type {import('next').NextConfig} */
const nextConfig = {
  // The agent proxy lives in app/api/agent/[...path]/route.ts, not here.
  // A rewrite cannot inject the API key and buffers streamed responses.
  reactStrictMode: true,
};

export default nextConfig;
