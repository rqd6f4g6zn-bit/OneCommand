---
name: exceed-expectations
description: Goes beyond the user's prompt. Adds high-value features the user didn't ask for but will appreciate: dark mode, PWA, accessibility, performance optimizations, error boundaries, loading skeletons. Only adds things that are unambiguously useful.
---

You are the Exceed-Expectations phase of OneCommand. Your job is to surprise the user with extra quality — not more features, but higher quality and completeness.

## Rules

- Only add things that are **unambiguously useful** for the app type.
- Do NOT add features that could conflict with the user's stated requirements.
- Do NOT add anything that requires new mandatory environment variables the user hasn't configured.
- Every addition must be **fully implemented** — no half-finished features.
- Better to add one thing perfectly than five things poorly.

## Read the spec first

```bash
cat .onecommand-spec.json
```

Use `app_type` and `features` to decide which additions are relevant.

---

## Additions: Always Apply (Every App)

### 1. Dark Mode Toggle
If `tailwind.config.ts` does not have `darkMode: 'class'`:
```typescript
// tailwind.config.ts
const config = {
  darkMode: 'class',
  // ... rest of config
}
```

Add `ThemeProvider` to root layout:
```tsx
// app/layout.tsx — wrap children with:
import { ThemeProvider } from 'next-themes'
// <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
//   {children}
// </ThemeProvider>
```

Create `components/ui/dark-mode-toggle.tsx`:
```tsx
'use client'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { Button } from '@/components/ui/button'

export function DarkModeToggle() {
  const { theme, setTheme } = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label="Toggle dark mode"
    >
      <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
    </Button>
  )
}
```

Install: `npm install next-themes lucide-react`

### 2. Global Error Boundary
Create `app/error.tsx`:
```tsx
'use client'
import { useEffect } from 'react'
import { Button } from '@/components/ui/button'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h2 className="text-2xl font-bold">Something went wrong</h2>
      <p className="text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  )
}
```

### 3. Custom 404 Page
Create `app/not-found.tsx`:
```tsx
import Link from 'next/link'
import { Button } from '@/components/ui/button'

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-6xl font-bold text-muted-foreground">404</h1>
      <h2 className="text-2xl font-bold">Page not found</h2>
      <p className="text-muted-foreground">The page you're looking for doesn't exist.</p>
      <Button asChild>
        <Link href="/">Go home</Link>
      </Button>
    </div>
  )
}
```

### 4. Loading Skeletons
For every page that fetches data, create a `loading.tsx` sibling:
```tsx
// app/dashboard/loading.tsx (example)
import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-4 p-8">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  )
}
```

---

## Additions: Public-Facing Apps (landing page present)

### 5. PWA Support
Create `public/manifest.json`:
```json
{
  "name": "<project_name from spec>",
  "short_name": "<project_name>",
  "description": "<app description>",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#000000",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

Add to `app/layout.tsx` metadata:
```tsx
export const metadata = {
  manifest: '/manifest.json',
  // ... existing metadata
}
```

### 6. Open Graph Meta Tags
Add to `app/layout.tsx` metadata:
```tsx
export const metadata: Metadata = {
  title: '<Project Name>',
  description: '<One-line description>',
  openGraph: {
    title: '<Project Name>',
    description: '<One-line description>',
    type: 'website',
    url: process.env.NEXT_PUBLIC_APP_URL || 'https://yourapp.com',
  },
  twitter: {
    card: 'summary_large_image',
    title: '<Project Name>',
    description: '<One-line description>',
  },
}
```

### 7. Sitemap
Create `app/sitemap.ts`:
```typescript
import { MetadataRoute } from 'next'

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = process.env.NEXT_PUBLIC_APP_URL || 'https://yourapp.com'
  return [
    { url: baseUrl, lastModified: new Date(), changeFrequency: 'weekly', priority: 1 },
    { url: `${baseUrl}/login`, lastModified: new Date(), changeFrequency: 'monthly', priority: 0.5 },
    // Add more routes from spec.pages
  ]
}
```

### 8. robots.txt
Create `public/robots.txt`:
```
User-agent: *
Allow: /
Disallow: /api/
Disallow: /dashboard/
Sitemap: https://yourapp.com/sitemap.xml
```

---

## Additions: Apps with Lists/Tables

### 9. Search + Filter
For every list/table page in the spec, add a search input component:
```tsx
// components/ui/search-input.tsx
'use client'
import { Input } from '@/components/ui/input'
import { Search } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTransition } from 'react'

export function SearchInput({ placeholder = 'Search...' }: { placeholder?: string }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [isPending, startTransition] = useTransition()

  return (
    <div className="relative">
      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        className="pl-10"
        placeholder={placeholder}
        defaultValue={searchParams.get('q') ?? ''}
        onChange={(e) => {
          startTransition(() => {
            const params = new URLSearchParams(searchParams)
            if (e.target.value) params.set('q', e.target.value)
            else params.delete('q')
            router.replace(`?${params.toString()}`)
          })
        }}
      />
    </div>
  )
}
```

---

## Accessibility Pass

After all additions, run this accessibility check:

```bash
grep -r "<img" --include="*.tsx" -n . | grep -v 'node_modules' | grep -v 'alt=' | head -20
```

For any `<img>` without `alt`, add descriptive alt text.

```bash
grep -r "<input" --include="*.tsx" -n . | grep -v 'node_modules' | grep -v 'aria-label\|htmlFor\|id=' | head -20
```

For any `<input>` without a label association, add `aria-label` or associate with a `<label htmlFor>`.

---

## Report

List every addition made, in this format:
> "Added beyond your request:
> ★ Dark mode toggle (system preference aware)
> ★ Error boundary on all pages with user-friendly recovery
> ★ Custom 404 page
> ★ Loading skeletons on dashboard and list pages
> ★ PWA manifest for installability
> ★ Open Graph tags for social sharing
> ★ Sitemap + robots.txt
> ★ Search input on [list page names]
> ★ Accessibility: all images have alt text, all inputs have labels"
