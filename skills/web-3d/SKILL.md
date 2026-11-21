---
name: web-3d
description: Builds 3D for websites and web apps — a 3D hero, a product viewer with AR, a product configurator, a scroll-driven scene, 3D data visualisation, an interactive background. Three.js with React Three Fiber and Drei (Next.js), vanilla Three.js or model-viewer (WordPress), glTF models optimised with gltf-transform, posters, reduced-motion and no-WebGL fallbacks, lazy loading, no third-party requests; hooks/scene3d.py checks every scene. Used in Phase 2 when the spec has "media.scenes". Games use threejs-builder instead.
---

*web-3d — Copyright © 2026 GK DigitalStudio UG*

You are the 3D engineer of OneCommand. 3D on a website has one job: show something a photo cannot (the
product from every side, the variant the visitor picks, a spatial idea). It must never cost the page its
speed, never leave a blank box on a phone without WebGL and never spin in front of someone who switched
motion off. You plan the scene, build it, and `hooks/scene3d.py check` decides whether it ships.

Games (a player, a goal, a game loop) are not this skill: they go through `game-engine-selector` and
`threejs-builder`.

## 1. Spec section (spec-analyzer)

```json
"media": {
  "scenes": [
    {"name": "hero", "kind": "hero", "purpose": "3D-Logo schwebt über dem Claim auf /",
     "model": null, "source": "procedural", "poster": "public/scenes/hero.jpg",
     "component": "components/three/HeroScene.tsx", "max_kb": 600},
    {"name": "sneaker", "kind": "configurator", "purpose": "Schuh in 4 Farben, Sohle wählbar, /produkt/air",
     "model": "public/models/sneaker.glb", "source": "own", "poster": "public/models/sneaker.jpg",
     "component": "components/three/SneakerConfigurator.tsx",
     "max_kb": 1500, "max_triangles": 80000, "max_texture_px": 2048, "ar": true}
  ]
}
```

| `kind` | What it is | Build it with |
|---|---|---|
| `hero` | Eye-catcher above the fold: logo, abstract shape, product hero | R3F, procedural geometry or one small model, slow ambient motion |
| `product` | Turn, zoom, look at one object, optional AR on the phone | `<model-viewer>` (simplest, AR built in) or R3F + `OrbitControls` |
| `configurator` | Visitor changes colour, material, parts; price and summary follow | R3F, materials swapped by state, HTML controls outside the canvas |
| `scroll` | Story told while scrolling: camera path, exploded view | R3F + Drei `ScrollControls`, or GSAP ScrollTrigger driving the camera |
| `data` | Globe, 3D chart, network, floor plan | R3F, `instancedMesh` for many points, HTML table as the accessible twin |
| `background` | Decorative shader or particle field behind content | R3F or one fullscreen shader, `aria-hidden`, pauses off-screen |

`model: null` means the scene is built from code (primitives, `ExtrudeGeometry` from an SVG logo, shaders).
`source`: `own` (the user's file), `procedural` (code), `cc0`, `licensed`. Budgets default to 1500 KB,
150 000 triangles and 2048 px textures; a `hero` or `background` should stay under 600 KB.

Only plan a scene when the prompt asks for 3D ("3D", "dreidimensional", "drehbar", "Konfigurator",
"360°", "AR", "WebGL", "Three.js") or the product is physical and the tier is premium. One strong scene
beats three weak ones.

## 2. Where the models come from (in this order)

1. **The user's files** in `assets/raw/` (`.glb`, `.gltf`, `.fbx`, `.obj`, `.usdz`, `.step` from CAD).
   Convert anything that is not glTF first: Blender headless
   (`blender -b -P convert.py -- in.fbx out.glb` with `bpy.ops.import_scene.fbx` + `bpy.ops.export_scene.gltf`),
   CAD (`.step`) via FreeCAD or Blender's STEP add-on, then decimate.
2. **Code**: logos as `ExtrudeGeometry` from the SVG path (`SVGLoader`), abstract shapes from primitives and
   `MeshTransmissionMaterial` / `MeshDistortMaterial`, terrain and particles from noise. No download, no licence.
3. **CC0 libraries**: Poly Haven (models, HDRIs, textures), Kenney, ambientCG. Download once into
   `assets/raw/`, never hot-link.
4. **Paid or generated models** (Sketchfab licensed, a text-to-3D API) only as a production dependency the
   user approves. Never ship a model without a known licence.

Every model that is not `own` or `procedural` gets a line in `assets/CREDITS.md`: file name, source URL,
author, licence. `scene3d.py check` fails without it.

## 3. Optimise every model (gltf-transform)

```bash
npx -y @gltf-transform/cli inspect assets/raw/sneaker.glb
npx -y @gltf-transform/cli optimize assets/raw/sneaker.glb public/models/sneaker.glb \
  --compress meshopt --texture-compress webp --texture-size 2048 --simplify true
python3 "$OC_ROOT/hooks/scene3d.py" inspect public/models/sneaker.glb
```

- Prefer `meshopt`: its decoder ships inside three.js, so nothing is fetched at runtime. `draco` compresses
  more but needs its decoder files: copy `node_modules/three/examples/jsm/libs/draco/gltf/` to
  `public/draco/` and pass that path (Drei loads it from gstatic.com otherwise, which the UI tour reports
  as a third-party request).
- KTX2 textures (`--texture-compress ktx2`, needs the `toktx` binary) save GPU memory on large scenes; copy
  `three/examples/jsm/libs/basis/` to `public/basis/` for the transcoder.
- Over budget after `optimize`: lower `--texture-size` to 1024, simplify harder
  (`gltf-transform simplify --ratio 0.5 --error 0.001`), remove hidden interior parts in Blender. Do not raise
  the budget.
- Next.js: generate a typed component per model with `npx gltfjsx public/models/sneaker.glb -t -o
  components/three/SneakerModel.tsx`. Its node and material names are what the configurator swaps.

## 4. Stack

| Platform | Libraries |
|---|---|
| Next.js / React | `three`, `@react-three/fiber`, `@react-three/drei`; optional `@react-three/postprocessing`, `maath`. R3F 9 + Drei 10 need React 19 (Next 15+); R3F 8 + Drei 9 for React 18. Check with `npm view @react-three/fiber peerDependencies`. |
| Product viewer only | `@google/model-viewer` from npm, bundled — never its CDN script |
| WordPress (spec has `wordpress`) | `three` bundled with esbuild into `wordpress/themes/<theme>/assets/js/scene-<name>.js`, enqueued with `wp_enqueue_script_module` (WP 6.5+) or `wp_enqueue_script(..., ['strategy' => 'defer', 'in_footer' => true])`; models in `assets/models/`. No CDN (the WordPress gate fails on it). |

`npm i three @react-three/fiber @react-three/drei && npm i -D @types/three`. Add `transpilePackages:
['three']` to `next.config` only if the build complains.

## 5. The wrapper every scene uses (Next.js)

The poster is the server-rendered LCP image and stays in place; the canvas loads only when the scene is near
the viewport, the device has WebGL and nothing fails. Reduced motion: decorative kinds (`hero`, `background`,
`scroll`) keep the poster; interactive kinds (`product`, `configurator`, `data`) stay live without
automatic motion.

```tsx
// components/three/Scene3D.tsx
'use client'

import Image from 'next/image'
import { Component, type ComponentType, type ReactNode, useEffect, useRef, useState } from 'react'

export type SceneProps = { reducedMotion: boolean; onReady: () => void }

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(error: unknown) {
    console.warn('3D scene disabled:', error)
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

export default function Scene3D({
  load, poster, label, decorative = false, interactive = false, className = 'aspect-[4/3] w-full',
}: {
  load: () => Promise<{ default: ComponentType<SceneProps> }>
  poster: string
  label: string
  decorative?: boolean
  interactive?: boolean
  className?: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const [Scene, setScene] = useState<ComponentType<SceneProps> | null>(null)
  const [ready, setReady] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReducedMotion(media.matches)
    const onChange = () => setReducedMotion(media.matches)
    media.addEventListener('change', onChange)
    if ((media.matches && !interactive) || !hasWebGL()) return () => media.removeEventListener('change', onChange)
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      io.disconnect()
      // the dynamic import runs in the browser only, so three.js is never in the first bundle or on the server
      load().then((mod) => setScene(() => mod.default)).catch((error) => console.warn('3D scene not loaded:', error))
    }, { rootMargin: '200px' })
    if (box.current) io.observe(box.current)
    return () => { io.disconnect(); media.removeEventListener('change', onChange) }
  }, [load, interactive])

  const still = (
    <Image src={poster} alt={decorative ? '' : label} fill priority sizes="100vw"
           className={`object-cover transition-opacity duration-500 ${ready ? 'opacity-0' : 'opacity-100'}`} />
  )

  return (
    <div ref={box} className={`relative overflow-hidden ${className}`}
         {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label })}>
      {still}
      {Scene && (
        <SceneBoundary fallback={null}>
          <div className={`absolute inset-0 transition-opacity duration-500 ${ready ? 'opacity-100' : 'opacity-0'}`}>
            <Scene reducedMotion={reducedMotion} onReady={() => setReady(true)} />
          </div>
        </SceneBoundary>
      )}
    </div>
  )
}
```

Each scene gets a small client slot named like the spec's scene (functions cannot be passed from a server
component), and the page renders the slot:

```tsx
// components/three/HeroSceneSlot.tsx
'use client'
import Scene3D from './Scene3D'

const load = () => import('./HeroScene')

export default function HeroSceneSlot() {
  return <Scene3D load={load} poster="/scenes/hero.jpg" label="Das Logo der Firma als glänzendes 3D-Objekt"
                  decorative className="h-[70vh] w-full" />
}
```

The container has a fixed size (aspect ratio or height), so nothing shifts when the canvas appears (CLS 0).

## 6. The canvas

```tsx
// components/three/HeroScene.tsx
'use client'

import { Canvas, useFrame } from '@react-three/fiber'
import { ContactShadows, Environment, Lightformer, PerformanceMonitor, AdaptiveDpr } from '@react-three/drei'
import { useRef, useState } from 'react'
import type { Mesh } from 'three'
import type { SceneProps } from './Scene3D'

function Shape({ reducedMotion }: { reducedMotion: boolean }) {
  const mesh = useRef<Mesh>(null)
  useFrame((_, delta) => {
    if (!mesh.current || reducedMotion) return
    mesh.current.rotation.y += delta * 0.25
  })
  return (
    <mesh ref={mesh} castShadow>
      <torusKnotGeometry args={[1, 0.32, 220, 32]} />
      <meshPhysicalMaterial color="#0f3d3e" roughness={0.15} metalness={0.6} clearcoat={1} />
    </mesh>
  )
}

export default function HeroScene({ reducedMotion, onReady }: SceneProps) {
  const [dpr, setDpr] = useState(1.5)
  return (
    <Canvas dpr={dpr} camera={{ position: [0, 0, 5], fov: 35 }} frameloop={reducedMotion ? 'demand' : 'always'}
            gl={{ antialias: true, powerPreference: 'high-performance' }} onCreated={() => onReady()}>
      <PerformanceMonitor onDecline={() => setDpr(1)} onIncline={() => setDpr(Math.min(2, window.devicePixelRatio))} />
      <AdaptiveDpr pixelated />
      <Shape reducedMotion={reducedMotion} />
      <ContactShadows position={[0, -1.6, 0]} opacity={0.35} blur={2.5} far={4} />
      <Environment resolution={256}>
        <Lightformer intensity={2} position={[0, 4, -6]} scale={[10, 4, 1]} />
        <Lightformer intensity={1} position={[-5, 1, -1]} rotation-y={Math.PI / 2} scale={[20, 1, 1]} />
      </Environment>
    </Canvas>
  )
}
```

Rules for every canvas:

- **No third-party requests.** `<Environment preset="…">` downloads HDRIs from a CDN: use `Lightformer`s
  (above) or a local file (`<Environment files="/hdr/studio_1k.hdr" />`, 1k HDR from Poly Haven, under 1.5 MB).
  `<Text>` and `<Text3D>` need a local `font` (`/fonts/<shipped-font>.woff` resp. a typeface JSON made from
  the brand font) — troika's default font is loaded from a CDN. Draco/KTX2 decoders local (section 3).
- **Frame loop:** static or orbit-only scenes use `frameloop="demand"` (renders on interaction only). Animated
  scenes pause when off-screen: `const visible = useIntersect(...)` from Drei, or set `frameloop` from the
  wrapper's observer.
- **Pixel ratio** capped at 2, lowered by `PerformanceMonitor`. Shadows: `ContactShadows` or one baked shadow
  texture, not real-time shadow maps on a hero.
- **Models** load with `useGLTF('/models/sneaker.glb')` inside `<Suspense fallback={null}>` and are preloaded
  only for the page that uses them (`useGLTF.preload` at module level of that scene file).
- **Colour:** R3F sets sRGB output and ACES tone mapping; brand colours from the design brief go in as
  hex — check them in the render, metallic materials darken colours.
- **Clean-up:** R3F disposes what it created. Anything made with `new` outside JSX (render targets,
  textures from `TextureLoader`) is disposed in a `useEffect` clean-up.
- **Mobile:** test the scene at 390 px width. Touch must still scroll the page: `OrbitControls` with
  `enableZoom={false}` on a scrolling page, or `touch-action: pan-y` on the container for horizontal-only
  rotation.

## 7. Recipes by kind

**product** — simplest: model-viewer (AR on Android via Scene Viewer, iOS via Quick Look with a `.usdz`
exported by Blender or `usdzconvert`):

```tsx
'use client'
import '@google/model-viewer'

<model-viewer src="/models/chair.glb" ios-src="/models/chair.usdz" poster="/models/chair.jpg"
  alt="Sessel Lina in Cognac-Leder, drehbar" camera-controls touch-action="pan-y" ar ar-modes="webxr scene-viewer quick-look"
  loading="lazy" reveal="auto" shadow-intensity="1" environment-image="neutral"
  style={{ width: '100%', aspectRatio: '1 / 1' }} />
```

Add `auto-rotate` only when reduced motion is off (read the media query and set the attribute). Declare the
element for TypeScript in `types/model-viewer.d.ts` (`JSX.IntrinsicElements['model-viewer']`).
With R3F instead: `<OrbitControls enablePan={false} minDistance={…} maxDistance={…} makeDefault />`, `<Bounds fit clip observe>`
around the model, `autoRotate={!reducedMotion}`.

**configurator** — state lives outside the canvas (one Zustand store or `useState` in the page) and in the URL
(`?farbe=sand&sohle=weiss`, so a configuration can be shared and the order form receives it):

- Every option is an HTML control (`<fieldset>` of radio buttons with visible labels, swatches with names),
  keyboard-usable; clicking a mesh part may also select, never only.
- Material swap by name from the gltfjsx component: `materials.Upper.color.set(variant.hex)` in a
  `useEffect`, or `KHR_materials_variants` when the model ships variants (`gltf-transform` keeps them).
- Price, availability and a text summary ("Air in Sand, Sohle Weiß — 139 €") update next to the canvas in an
  `aria-live="polite"` region. The summary, not the canvas, is what the cart and acceptance tests read.
- Camera moves to the part being configured (`CameraControls.setLookAt(..., true)`); with reduced motion the
  move is instant (`false`).
- Snapshot for the cart or a PDF: `gl.domElement.toDataURL('image/webp')` with `gl={{ preserveDrawingBuffer: true }}`
  only on the configurator canvas.

**scroll** — Drei `<ScrollControls pages={4} damping={0.2}>` with `useScroll().offset` driving the camera
along a `CatmullRomCurve3`, `<Scroll html>` for the text; or the page scrolls normally and GSAP ScrollTrigger
writes progress into a ref the scene reads in `useFrame`. Text stays real HTML in the document flow (SEO,
screen readers). Reduced motion: the poster plus the same text, no scroll-jacking.

**data** — thousands of points as one `instancedMesh` (set matrices in `useLayoutEffect`, colours via
`setColorAt`), labels with Drei `<Html>` only for the few that matter, hover via `onPointerMove` +
`instanceId`. A globe: `SphereGeometry` + a local equirectangular texture, points from lat/lon. The same data
is on the page as an HTML table or list (visually hidden when the design wants it) — the canvas alone is not
accessible.

**background** — one fullscreen plane with a `shaderMaterial` (noise gradient, grain) or `Points` with a few
thousand particles; `aria-hidden`, `pointer-events: none`, paused off-screen and with reduced motion,
contrast of the text on top checked against the brightest frame.

**WordPress** — the theme ships `assets/js/scene-<name>.js` (esbuild bundle of `three` + the scene, ES module),
a pattern or block renders the container with the poster `<img>` inside, and the script swaps in the canvas
on `IntersectionObserver`, checks `canvas.getContext('webgl2')`, honours `matchMedia('(prefers-reduced-motion:
reduce)')` and leaves the poster on any error. Product viewers: model-viewer bundled locally the same way.

## 8. Accessibility and content

- Meaningful scene: `role="img"` and an `aria-label` that says what is shown ("Sessel Lina in Cognac, drehbar").
  Decorative: `aria-hidden="true"`, poster `alt=""`.
- Interactive controls are HTML, focusable, with visible focus; the canvas itself is not a tab stop unless it
  has keyboard controls (arrow keys rotate — then say so in a visible hint).
- No information only inside the canvas: price, variant name, data values are also text on the page.
- Flashing or fast camera moves are never automatic. Auto-rotation ≤ 0.3 rad/s.

## 9. Test it

- `python3 "$OC_ROOT/hooks/scene3d.py" check --project-dir "$PROJECT_DIR"` — exit 0 before Phase 2 ends. It
  writes `.onecommand/scene3d.json` (sizes, triangles, textures per scene) for the delivery report.
- Acceptance tests (acceptance-tester) per scene: the poster is visible on first paint; after scrolling to it
  the canvas appears (`page.locator('canvas')` visible); with `test.use({ reducedMotion: 'reduce' })` a
  decorative scene keeps its poster; a configurator option click changes the summary text and the URL.
  Headless Chromium needs WebGL flags: `launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] }`
  in `playwright.config.ts` (the UI tour sets them itself).
- Look at the tour screenshots of the 3D pages: the scene is lit, the brand colour is right, the model is
  framed and not clipped on mobile.

## 10. Done when

- `scene3d.py check` exits 0: models within budget and compressed, posters under 200 KB and used, every
  component with reduced-motion handling, a no-WebGL fallback, lazy loading and an accessible name,
  credits complete.
- The UI tour reports no third-party request from the 3D pages, LCP and CLS within `performance_budget`.
- `assets/CREDITS.md` lists every model, HDRI and texture that is not own or procedural; the delivery report
  links it.
