import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono, Space_Grotesk } from 'next/font/google'
import './globals.css'

// All three faces go through next/font so they are self-hosted from this
// origin and preloaded. globals.css previously pulled the latter two with a
// CSS @import of fonts.googleapis.com, which is render-blocking and
// serialised: the browser had to fetch the stylesheet, parse it, discover the
// import, then hit two more origins before any text could paint in them.
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
})

const spaceGrotesk = Space_Grotesk({
  subsets: ['latin'],
  variable: '--font-space-grotesk',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Digits Dont Lie — Fraud Detection & Statistical Analysis',
  description:
    'Detect fraud with Benford\'s Law analysis, Luhn checksum validation, and statistical anomaly detection. Verify documents, card numbers, and financial data.',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'light dark',
  // Without this every env(safe-area-inset-*) in globals.css resolves to 0 —
  // which is what they were all doing. The stylesheet has been written against
  // those insets since the first mobile pass (the action bar, .safe-x, .safe-b,
  // the footer's bottom clearance), so none of that clearance was actually
  // being applied on a notched phone: the action bar sat under the home
  // indicator and the header under the status bar.
  //
  // Inert on desktop and on any phone without such hardware — env() insets are
  // 0 there, which is exactly what they were before this line existed.
  viewportFit: 'cover',
  themeColor: [
    // Was #F5F5F7 — a leftover from before the light theme moved to warm paper.
    // On a phone the browser chrome painted that cool grey directly against the
    // page's #F4F1EC, and the seam was visible.
    { media: '(prefers-color-scheme: light)', color: '#F4F1EC' },
    { media: '(prefers-color-scheme: dark)', color: '#1E1E1E' },
  ],
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    // suppressHydrationWarning: the script below adds a class to <html> before
    // React hydrates, so the server's markup and the client's necessarily differ
    // on that one attribute. Nothing else about the tree is affected.
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} ${spaceGrotesk.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Runs before first paint, so the page is already the right theme when
            it appears. The toggle applies this class from an effect, which is
            too late — a light-mode user would see a full dark render flash past
            first. Wrapped in try/catch because localStorage throws outright in
            some privacy modes, and a theme preference is not worth a blank page.
            
            Light is the default when nothing is stored, rather than following
            prefers-color-scheme. This is shown on a projector in a lit room,
            where dark mode is the wrong choice regardless of what the presenting
            machine's OS is set to — and the machine's OS is exactly what the
            media query was reading. An explicit choice from the toggle is still
            honoured; only the unset case changed. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var s=localStorage.getItem('ddl-theme');var d=s==='dark';var c=document.documentElement.classList;c.toggle('dark',d);c.toggle('light',!d);}catch(e){document.documentElement.classList.add('light');}})();`,
          }}
        />
      </head>
      <body className="font-sans antialiased bg-surface-page">
        {children}
        {/* Gated on being deployed to Vercel, not on NODE_ENV. `next start`
            — the way this app is run for a live demo on a laptop — sets
            NODE_ENV=production too, so the old gate let <Analytics /> mount
            off-platform, where its beacon script does not exist. Every visitor
            then took a 404 on /_vercel/insights/script.js plus a MIME-type
            refusal, so a devtools console opened in front of an audience showed
            two errors before anyone touched the app. VERCEL is set by the build
            environment on Vercel and nowhere else, which is the actual
            condition under which that script resolves. */}
        {process.env.VERCEL === '1' && <Analytics />}
      </body>
    </html>
  )
}
