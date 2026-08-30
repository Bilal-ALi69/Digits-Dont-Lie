/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the workspace root. Without this Turbopack walks upward looking for a
  // lockfile and finds an unrelated one in the home directory, then warns that
  // it is ignoring it. Anchoring to this directory removes the ambiguity.
  turbopack: {
    root: import.meta.dirname,
  },
  images: {
    unoptimized: true,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
        ],
      },
    ]
  },
}

export default nextConfig
