/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.API_URL || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
