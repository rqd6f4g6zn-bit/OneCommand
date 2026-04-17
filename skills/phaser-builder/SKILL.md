---
name: phaser-builder
description: Generates a complete Phaser 3 web 2D game with multiple scenes, tilemap levels, animated sprites, physics, enemies, HUD, save system, and fullscreen support.
model: claude-sonnet-4-6
---

# Phaser 3 Game Builder

Generate a complete web 2D game using Phaser 3 embedded in Next.js.

---

## Step 1: Read Spec

Read `.onecommand-spec.json` from the project root. Extract:
- `project_name` — game title shown in MenuScene
- `genre` — `"platformer"` | `"shooter"` | `"puzzle"` | `"rpg"`
- `features` — array, e.g. `["enemies", "save", "audio", "fullscreen"]`
- `engine_config.gravity` — numeric Y gravity (default: 800)
- `engine_config.playerSpeed` — player walk speed (default: 200)
- `engine_config.jumpForce` — jump velocity (default: -550)

If the spec file does not exist, create a default:

```json
{
  "project_name": "PhaserGame",
  "genre": "platformer",
  "features": ["enemies", "save", "audio", "fullscreen"],
  "engine_config": {
    "gravity": 800,
    "playerSpeed": 200,
    "jumpForce": -550
  }
}
```

---

## Step 2: Install Dependencies

Add to `package.json` dependencies:

```json
{
  "phaser": "^3.80"
}
```

Run: `npm install`

---

## Step 3: Generate Game Files

Create all files below with exactly the contents shown.

---

### File: `app/game/page.tsx`

```typescript
'use client'

import dynamic from 'next/dynamic'

// Phaser requires browser globals — never import server-side
const PhaserGame = dynamic(() => import('@/components/PhaserGame'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center w-full h-screen bg-black">
      <div className="text-white text-2xl font-mono">Loading...</div>
    </div>
  ),
})

export default function GamePage() {
  return (
    <main className="w-full h-screen overflow-hidden bg-black flex items-center justify-center">
      <PhaserGame />
    </main>
  )
}
```

---

### File: `components/PhaserGame.tsx`

```typescript
'use client'

import { useEffect, useRef } from 'react'
import type Phaser from 'phaser'

export default function PhaserGame() {
  const containerRef = useRef<HTMLDivElement>(null)
  const gameRef = useRef<Phaser.Game | null>(null)

  useEffect(() => {
    if (gameRef.current || !containerRef.current) return

    async function initGame() {
      const Phaser = (await import('phaser')).default
      const { BootScene }     = await import('@/lib/game/scenes/BootScene')
      const { PreloadScene }  = await import('@/lib/game/scenes/PreloadScene')
      const { MenuScene }     = await import('@/lib/game/scenes/MenuScene')
      const { GameScene }     = await import('@/lib/game/scenes/GameScene')
      const { UIScene }       = await import('@/lib/game/scenes/UIScene')
      const { GameOverScene } = await import('@/lib/game/scenes/GameOverScene')

      const config: Phaser.Types.Core.GameConfig = {
        type: Phaser.AUTO,
        width: 1280,
        height: 720,
        parent: containerRef.current!,
        backgroundColor: '#1a1a2e',
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_BOTH,
        },
        physics: {
          default: 'arcade',
          arcade: {
            gravity: { y: 800, x: 0 },
            debug: false,
          },
        },
        scene: [BootScene, PreloadScene, MenuScene, GameScene, UIScene, GameOverScene],
      }

      gameRef.current = new Phaser.Game(config)
    }

    initGame()

    return () => {
      gameRef.current?.destroy(true)
      gameRef.current = null
    }
  }, [])

  return <div ref={containerRef} className="w-full h-full" />
}
```

---

### File: `lib/game/scenes/BootScene.ts`

```typescript
import Phaser from 'phaser'

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' })
  }

  create() {
    // Initialize registry defaults shared across all scenes
    this.registry.set('score',     0)
    this.registry.set('coins',     0)
    this.registry.set('level',     1)
    this.registry.set('lives',     3)
    this.registry.set('highScore', this.loadHighScore())
    this.registry.set('settings', {
      sfxVolume: 0.8,
      musicVolume: 0.5,
      fullscreen: false,
    })

    this.scene.start('PreloadScene')
  }

  private loadHighScore(): number {
    try {
      return parseInt(localStorage.getItem('phaser_highscore') ?? '0', 10)
    } catch {
      return 0
    }
  }
}
```

---

### File: `lib/game/scenes/PreloadScene.ts`

```typescript
import Phaser from 'phaser'

export class PreloadScene extends Phaser.Scene {
  private progressBar!: Phaser.GameObjects.Graphics
  private progressBox!: Phaser.GameObjects.Graphics
  private loadingText!: Phaser.GameObjects.Text
  private percentText!: Phaser.GameObjects.Text

  constructor() {
    super({ key: 'PreloadScene' })
  }

  preload() {
    const { width, height } = this.cameras.main

    // Progress bar UI
    this.progressBox = this.add.graphics()
    this.progressBox.fillStyle(0x222222, 0.8)
    this.progressBox.fillRect(width / 2 - 210, height / 2 - 25, 420, 50)

    this.progressBar = this.add.graphics()

    this.loadingText = this.add.text(width / 2, height / 2 - 60, 'Loading...', {
      fontSize: '24px',
      color: '#ffffff',
      fontFamily: 'monospace',
    }).setOrigin(0.5)

    this.percentText = this.add.text(width / 2, height / 2, '0%', {
      fontSize: '18px',
      color: '#cccccc',
      fontFamily: 'monospace',
    }).setOrigin(0.5)

    this.load.on('progress', (value: number) => {
      this.progressBar.clear()
      this.progressBar.fillStyle(0x4488ff, 1)
      this.progressBar.fillRect(width / 2 - 200, height / 2 - 15, 400 * value, 30)
      this.percentText.setText(`${Math.floor(value * 100)}%`)
    })

    this.load.on('complete', () => {
      this.progressBar.destroy()
      this.progressBox.destroy()
      this.loadingText.destroy()
      this.percentText.destroy()
    })

    // ---- Asset loading ----
    // Spritesheets — point these at your actual asset files.
    // Dimensions below assume 64x64 frames on a horizontal strip.
    this.load.spritesheet('player_idle',   '/assets/sprites/player_idle.png',   { frameWidth: 64, frameHeight: 64, endFrame: 3 })
    this.load.spritesheet('player_run',    '/assets/sprites/player_run.png',    { frameWidth: 64, frameHeight: 64, endFrame: 7 })
    this.load.spritesheet('player_jump',   '/assets/sprites/player_jump.png',   { frameWidth: 64, frameHeight: 64, endFrame: 1 })
    this.load.spritesheet('player_fall',   '/assets/sprites/player_fall.png',   { frameWidth: 64, frameHeight: 64, endFrame: 1 })
    this.load.spritesheet('player_attack', '/assets/sprites/player_attack.png', { frameWidth: 64, frameHeight: 64, endFrame: 2 })

    this.load.spritesheet('enemy_slime',   '/assets/sprites/enemy_slime.png',   { frameWidth: 48, frameHeight: 48, endFrame: 5 })
    this.load.spritesheet('enemy_bat',     '/assets/sprites/enemy_bat.png',     { frameWidth: 48, frameHeight: 48, endFrame: 5 })
    this.load.spritesheet('enemy_goblin',  '/assets/sprites/enemy_goblin.png',  { frameWidth: 64, frameHeight: 64, endFrame: 5 })

    this.load.spritesheet('coin',         '/assets/sprites/coin.png',          { frameWidth: 16, frameHeight: 16, endFrame: 7 })
    this.load.spritesheet('heart',        '/assets/sprites/heart.png',         { frameWidth: 16, frameHeight: 16, endFrame: 1 })

    // Tilemap
    this.load.tilemapTiledJSON('level_1', '/assets/tilemaps/level_1.json')
    this.load.image('tileset_main',        '/assets/tilesets/tileset_main.png')

    // UI assets
    this.load.image('ui_heart_full',  '/assets/ui/heart_full.png')
    this.load.image('ui_heart_empty', '/assets/ui/heart_empty.png')
    this.load.image('ui_coin_icon',   '/assets/ui/coin_icon.png')
    this.load.image('ui_panel',       '/assets/ui/panel.png')

    // Backgrounds
    this.load.image('bg_sky',    '/assets/backgrounds/sky.png')
    this.load.image('bg_clouds', '/assets/backgrounds/clouds.png')
    this.load.image('bg_hills',  '/assets/backgrounds/hills.png')

    // Audio
    this.load.audio('music_menu',   '/assets/audio/music_menu.ogg')
    this.load.audio('music_game',   '/assets/audio/music_game.ogg')
    this.load.audio('sfx_jump',     '/assets/audio/sfx_jump.ogg')
    this.load.audio('sfx_coin',     '/assets/audio/sfx_coin.ogg')
    this.load.audio('sfx_hurt',     '/assets/audio/sfx_hurt.ogg')
    this.load.audio('sfx_attack',   '/assets/audio/sfx_attack.ogg')
    this.load.audio('sfx_death',    '/assets/audio/sfx_death.ogg')
    this.load.audio('sfx_levelup',  '/assets/audio/sfx_levelup.ogg')
  }

  create() {
    this.createAnimations()
    this.scene.start('MenuScene')
  }

  private createAnimations() {
    const anims = this.anims

    anims.create({ key: 'player-idle',   frames: anims.generateFrameNumbers('player_idle',   { start: 0, end: 3 }), frameRate: 8,  repeat: -1 })
    anims.create({ key: 'player-run',    frames: anims.generateFrameNumbers('player_run',    { start: 0, end: 7 }), frameRate: 12, repeat: -1 })
    anims.create({ key: 'player-jump',   frames: anims.generateFrameNumbers('player_jump',   { start: 0, end: 1 }), frameRate: 6,  repeat: 0  })
    anims.create({ key: 'player-fall',   frames: anims.generateFrameNumbers('player_fall',   { start: 0, end: 1 }), frameRate: 6,  repeat: -1 })
    anims.create({ key: 'player-attack', frames: anims.generateFrameNumbers('player_attack', { start: 0, end: 2 }), frameRate: 14, repeat: 0  })

    anims.create({ key: 'enemy-slime',  frames: anims.generateFrameNumbers('enemy_slime',  { start: 0, end: 5 }), frameRate: 8,  repeat: -1 })
    anims.create({ key: 'enemy-bat',    frames: anims.generateFrameNumbers('enemy_bat',    { start: 0, end: 5 }), frameRate: 10, repeat: -1 })
    anims.create({ key: 'enemy-goblin', frames: anims.generateFrameNumbers('enemy_goblin', { start: 0, end: 5 }), frameRate: 8,  repeat: -1 })

    anims.create({ key: 'coin-spin', frames: anims.generateFrameNumbers('coin', { start: 0, end: 7 }), frameRate: 10, repeat: -1 })
  }
}
```

---

### File: `lib/game/scenes/MenuScene.ts`

```typescript
import Phaser from 'phaser'

export class MenuScene extends Phaser.Scene {
  private music?: Phaser.Sound.BaseSound

  constructor() {
    super({ key: 'MenuScene' })
  }

  create() {
    const { width, height } = this.cameras.main

    // Parallax background
    this.add.image(width / 2, height / 2, 'bg_sky').setScrollFactor(0).setDisplaySize(width, height)

    // Animated background clouds
    const clouds = this.add.image(width / 2, height / 2 - 80, 'bg_clouds')
      .setScrollFactor(0)
      .setAlpha(0.6)

    this.tweens.add({
      targets: clouds,
      x: { from: width / 2 - 20, to: width / 2 + 20 },
      duration: 6000,
      yoyo: true,
      repeat: -1,
      ease: 'Sine.easeInOut',
    })

    // Title
    const title = this.add.text(width / 2, 160, 'PHASER GAME', {
      fontSize: '72px',
      fontFamily: 'monospace',
      color: '#ffffff',
      stroke: '#000000',
      strokeThickness: 6,
      shadow: { offsetX: 3, offsetY: 3, color: '#000', blur: 8, fill: true },
    }).setOrigin(0.5)

    this.tweens.add({
      targets: title,
      scaleX: { from: 1, to: 1.04 },
      scaleY: { from: 1, to: 1.04 },
      duration: 1400,
      yoyo: true,
      repeat: -1,
      ease: 'Sine.easeInOut',
    })

    // High score
    const hs = this.registry.get('highScore') as number
    this.add.text(width / 2, 250, `HIGH SCORE: ${hs.toLocaleString()}`, {
      fontSize: '22px',
      fontFamily: 'monospace',
      color: '#ffd700',
    }).setOrigin(0.5)

    // Buttons
    this.createButton(width / 2, 340, 'PLAY',     '#22c55e', '#16a34a', () => this.startGame())
    this.createButton(width / 2, 420, 'SETTINGS', '#3b82f6', '#2563eb', () => this.openSettings())
    this.createButton(width / 2, 500, 'FULLSCREEN','#8b5cf6', '#7c3aed', () => this.toggleFullscreen())

    // Music
    try {
      this.music = this.sound.add('music_menu', { loop: true, volume: 0.4 })
      this.music.play()
    } catch { /* assets may not be present yet */ }
  }

  private createButton(x: number, y: number, label: string, color: string, hoverColor: string, callback: () => void) {
    const bg = this.add.graphics()
    const w = 240, h = 52, r = 10

    const draw = (c: number) => {
      bg.clear()
      bg.fillStyle(parseInt(c.toString(16).padStart(6, '0'), 16), 1)
      bg.fillRoundedRect(x - w / 2, y - h / 2, w, h, r)
    }

    const hexColor   = parseInt(color.slice(1),      16)
    const hexHover   = parseInt(hoverColor.slice(1),  16)
    draw(hexColor)

    const text = this.add.text(x, y, label, {
      fontSize: '24px',
      fontFamily: 'monospace',
      color: '#ffffff',
    }).setOrigin(0.5).setInteractive({ useHandCursor: true })

    text.on('pointerover',  () => { draw(hexHover); this.tweens.add({ targets: text, scaleX: 1.05, scaleY: 1.05, duration: 80 }) })
    text.on('pointerout',   () => { draw(hexColor); this.tweens.add({ targets: text, scaleX: 1,    scaleY: 1,    duration: 80 }) })
    text.on('pointerdown',  callback)
  }

  private startGame() {
    this.music?.stop()
    this.scene.stop('MenuScene')
    this.scene.start('GameScene')
    this.scene.start('UIScene')
  }

  private openSettings() {
    // Settings overlay (volume sliders, key remapping)
    const { width, height } = this.cameras.main
    const panel = this.add.rectangle(width / 2, height / 2, 400, 300, 0x000000, 0.85)
    this.add.text(width / 2, height / 2 - 110, 'SETTINGS', {
      fontSize: '28px', fontFamily: 'monospace', color: '#fff',
    }).setOrigin(0.5)
    this.add.text(width / 2, height / 2, '(Coming soon)', {
      fontSize: '18px', fontFamily: 'monospace', color: '#999',
    }).setOrigin(0.5)

    const closeBtn = this.add.text(width / 2, height / 2 + 110, '[ CLOSE ]', {
      fontSize: '22px', fontFamily: 'monospace', color: '#f87171',
    }).setOrigin(0.5).setInteractive({ useHandCursor: true })
    closeBtn.on('pointerdown', () => { panel.destroy(); closeBtn.destroy() })
  }

  private toggleFullscreen() {
    if (this.scale.isFullscreen) {
      this.scale.stopFullscreen()
    } else {
      this.scale.startFullscreen()
    }
  }
}
```

---

### File: `lib/game/scenes/GameScene.ts`

```typescript
import Phaser from 'phaser'
import { Player } from '../objects/Player'
import { Enemy } from '../objects/Enemy'

export class GameScene extends Phaser.Scene {
  player!: Player
  enemies!: Phaser.Physics.Arcade.Group
  coins!: Phaser.Physics.Arcade.StaticGroup
  platforms!: Phaser.Tilemaps.TilemapLayer | null
  background!: Phaser.Tilemaps.TilemapLayer | null
  foreground!: Phaser.Tilemaps.TilemapLayer | null
  music?: Phaser.Sound.BaseSound

  constructor() {
    super({ key: 'GameScene' })
  }

  create() {
    // ---- Tilemap ----
    let map: Phaser.Tilemaps.Tilemap
    try {
      map = this.make.tilemap({ key: 'level_1' })
      const tileset = map.addTilesetImage('tileset_main', 'tileset_main')!
      this.background = map.createLayer('Background', tileset, 0, 0)
      this.platforms  = map.createLayer('Ground',     tileset, 0, 0)
      this.foreground = map.createLayer('Foreground', tileset, 0, 0)
      this.platforms?.setCollisionByExclusion([-1])
      this.physics.world.setBounds(0, 0, map.widthInPixels, map.heightInPixels)
    } catch {
      // Fallback to procedural platforms when tilemap assets aren't present
      this.platforms = null
      this.createFallbackLevel()
    }

    // ---- Player ----
    this.player = new Player(this, 100, 400)
    this.add.existing(this.player)
    this.physics.add.existing(this.player)

    if (this.platforms) {
      this.physics.add.collider(this.player, this.platforms)
    }

    // ---- Enemies ----
    this.enemies = this.physics.add.group({ classType: Enemy, runChildUpdate: true })
    this.spawnEnemies()
    if (this.platforms) {
      this.physics.add.collider(this.enemies, this.platforms)
    }

    // ---- Coins ----
    this.coins = this.physics.add.staticGroup()
    this.spawnCoins()

    // ---- Overlap: player vs enemy ----
    this.physics.add.overlap(
      this.player,
      this.enemies,
      (player, enemy) => {
        const p = player as Player
        if (!p.isInvincible) {
          p.takeDamage(20)
          const lives = (this.registry.get('lives') as number) - 1
          this.registry.set('lives', lives)
          this.events.emit('lives-changed', lives)
          if (lives <= 0) this.gameOver()
        }
      }
    )

    // ---- Overlap: player vs coin ----
    this.physics.add.overlap(
      this.player,
      this.coins,
      (_, coin) => {
        (coin as Phaser.Physics.Arcade.Image).destroy()
        const score = (this.registry.get('score') as number) + 10
        const coins = (this.registry.get('coins') as number) + 1
        this.registry.set('score', score)
        this.registry.set('coins', coins)
        this.events.emit('score-changed', score)
        this.events.emit('coins-changed', coins)
        try { this.sound.play('sfx_coin', { volume: 0.6 }) } catch {}
      }
    )

    // ---- Camera ----
    this.cameras.main.startFollow(this.player, true, 0.1, 0.1)
    this.cameras.main.setDeadzone(80, 40)
    if (map!) {
      this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels)
    }

    // ---- Music ----
    try {
      this.music = this.sound.add('music_game', { loop: true, volume: 0.35 })
      this.music.play()
    } catch {}

    // ---- Pause ----
    this.input.keyboard!.on('keydown-ESC', () => this.togglePause())
  }

  update() {
    this.player.update()

    // Level complete trigger: reach right edge or a custom zone
    if (this.player.x > 3000) {
      this.levelComplete()
    }
  }

  private createFallbackLevel() {
    // Solid ground
    const ground = this.physics.add.staticGroup()
    for (let i = 0; i < 40; i++) {
      ground.create(i * 64 + 32, 688, 'tileset_main').setVisible(false).refreshBody()
    }
    // Platforms
    const plat = (x: number, y: number, count: number) => {
      for (let i = 0; i < count; i++) {
        ground.create(x + i * 64 + 32, y, 'tileset_main').setVisible(false).refreshBody()
      }
    }
    plat(200,  500, 5)
    plat(600,  400, 4)
    plat(1000, 320, 6)
    plat(1500, 500, 3)
    plat(1800, 350, 4)
    plat(2200, 260, 5)
    plat(2700, 400, 3)

    this.physics.add.collider(this.player, ground)
    this.physics.world.setBounds(0, 0, 3200, 720)
  }

  private spawnEnemies() {
    const spawnPoints = [
      { x: 400,  y: 620, type: 'slime'  },
      { x: 700,  y: 620, type: 'slime'  },
      { x: 1100, y: 620, type: 'goblin' },
      { x: 1600, y: 470, type: 'bat'    },
      { x: 2000, y: 620, type: 'goblin' },
      { x: 2400, y: 620, type: 'slime'  },
      { x: 2800, y: 620, type: 'bat'    },
    ]

    spawnPoints.forEach(({ x, y, type }) => {
      const enemy = new Enemy(this, x, y, type as 'slime' | 'bat' | 'goblin')
      this.enemies.add(enemy, true)
    })
  }

  private spawnCoins() {
    const coinPositions = [
      [300, 450], [350, 450], [400, 450],
      [650, 350], [700, 350],
      [1050, 270], [1100, 270], [1150, 270],
      [1550, 450],
      [1850, 300], [1900, 300],
      [2250, 210], [2300, 210], [2350, 210],
    ]

    coinPositions.forEach(([x, y]) => {
      const coin = this.coins.create(x, y, 'coin') as Phaser.Physics.Arcade.Image
      coin.play?.('coin-spin')
    })
  }

  private togglePause() {
    if (this.physics.world.isPaused) {
      this.physics.world.resume()
      this.tweens.resumeAll()
    } else {
      this.physics.world.pause()
      this.tweens.pauseAll()
    }
  }

  private levelComplete() {
    this.music?.stop()
    const score = this.registry.get('score') as number
    const bonus = 500
    this.registry.set('score', score + bonus)
    this.events.emit('score-changed', score + bonus)
    try { this.sound.play('sfx_levelup', { volume: 0.8 }) } catch {}
    this.time.delayedCall(1000, () => {
      this.scene.stop('UIScene')
      this.scene.start('GameOverScene', { win: true })
    })
  }

  private gameOver() {
    this.music?.stop()
    this.physics.world.pause()
    try { this.sound.play('sfx_death', { volume: 0.8 }) } catch {}
    this.time.delayedCall(600, () => {
      this.scene.stop('UIScene')
      this.scene.start('GameOverScene', { win: false })
    })
  }
}
```

---

### File: `lib/game/objects/Player.ts`

```typescript
import Phaser from 'phaser'

const SPEED        = 200
const SPRINT_SPEED = 340
const JUMP_VEL     = -550
const COYOTE_MS    = 150   // coyote time window
const JUMP_BUFFER  = 100   // jump buffer window

export class Player extends Phaser.Physics.Arcade.Sprite {
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys
  private wasd!: { up: Phaser.Input.Keyboard.Key; down: Phaser.Input.Keyboard.Key; left: Phaser.Input.Keyboard.Key; right: Phaser.Input.Keyboard.Key }
  private attackKey!: Phaser.Input.Keyboard.Key
  private sprintKey!: Phaser.Input.Keyboard.Key

  isInvincible = false
  private hp = 100
  private maxHp = 100
  private facingRight = true
  private isAttacking = false

  // Coyote time & jump buffer
  private coyoteTimer = 0
  private jumpBufferTimer = 0
  private wasOnGround = false

  constructor(scene: Phaser.Scene, x: number, y: number) {
    super(scene, x, y, 'player_idle')
    scene.add.existing(this)
    scene.physics.add.existing(this)

    const body = this.body as Phaser.Physics.Arcade.Body
    body.setSize(32, 56)
    body.setOffset(16, 8)
    body.setGravityY(200)

    this.cursors   = scene.input.keyboard!.createCursorKeys()
    this.wasd      = {
      up:    scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.W),
      down:  scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.S),
      left:  scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.A),
      right: scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.D),
    }
    this.attackKey = scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.Z)
    this.sprintKey = scene.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.SHIFT)

    this.play('player-idle')

    // Attack animation complete → clear flag
    this.on('animationcomplete-player-attack', () => {
      this.isAttacking = false
    })
  }

  update() {
    const body = this.body as Phaser.Physics.Arcade.Body
    const onGround = body.blocked.down
    const dt = this.scene.game.loop.delta

    // ---- Coyote time ----
    if (onGround) {
      this.coyoteTimer = COYOTE_MS
      this.wasOnGround = true
    } else {
      this.coyoteTimer = Math.max(0, this.coyoteTimer - dt)
    }

    // ---- Jump buffer ----
    const jumpPressed =
      Phaser.Input.Keyboard.JustDown(this.cursors.up!) ||
      Phaser.Input.Keyboard.JustDown(this.wasd.up)

    if (jumpPressed) this.jumpBufferTimer = JUMP_BUFFER
    else this.jumpBufferTimer = Math.max(0, this.jumpBufferTimer - dt)

    // ---- Attack ----
    if (Phaser.Input.Keyboard.JustDown(this.attackKey) && !this.isAttacking) {
      this.isAttacking = true
      this.play('player-attack', true)
      try { this.scene.sound.play('sfx_attack', { volume: 0.5 }) } catch {}
    }

    if (this.isAttacking) return

    // ---- Horizontal movement ----
    const left  = this.cursors.left?.isDown  || this.wasd.left.isDown
    const right = this.cursors.right?.isDown || this.wasd.right.isDown
    const sprint = this.sprintKey.isDown
    const speed = sprint ? SPRINT_SPEED : SPEED

    if (left) {
      body.setVelocityX(-speed)
      this.setFlipX(true)
      this.facingRight = false
    } else if (right) {
      body.setVelocityX(speed)
      this.setFlipX(false)
      this.facingRight = true
    } else {
      body.setVelocityX(body.velocity.x * 0.75) // friction
    }

    // ---- Jump (with coyote + buffer) ----
    if (this.jumpBufferTimer > 0 && this.coyoteTimer > 0) {
      body.setVelocityY(JUMP_VEL)
      this.jumpBufferTimer = 0
      this.coyoteTimer = 0
      try { this.scene.sound.play('sfx_jump', { volume: 0.6 }) } catch {}
    }

    // ---- Animations ----
    if (!onGround) {
      this.play(body.velocity.y < 0 ? 'player-jump' : 'player-fall', true)
    } else if (Math.abs(body.velocity.x) > 10) {
      this.play('player-run', true)
    } else {
      this.play('player-idle', true)
    }
  }

  takeDamage(amount: number) {
    if (this.isInvincible) return
    this.hp = Math.max(0, this.hp - amount)
    this.isInvincible = true

    // Flash red
    this.scene.tweens.add({
      targets: this,
      alpha: { from: 1, to: 0.3 },
      duration: 100,
      yoyo: true,
      repeat: 4,
      onComplete: () => {
        this.alpha = 1
        this.isInvincible = false
      },
    })

    try { this.scene.sound.play('sfx_hurt', { volume: 0.7 }) } catch {}
    this.scene.cameras.main.shake(150, 0.012)
  }
}
```

---

### File: `lib/game/objects/Enemy.ts`

```typescript
import Phaser from 'phaser'

type EnemyType = 'slime' | 'bat' | 'goblin'

const ENEMY_CONFIG: Record<EnemyType, { speed: number; hp: number; damage: number; gravity: number }> = {
  slime:  { speed: 60,  hp: 30,  damage: 10, gravity: 400 },
  goblin: { speed: 110, hp: 60,  damage: 20, gravity: 400 },
  bat:    { speed: 80,  hp: 20,  damage: 15, gravity: 0   },
}

export class Enemy extends Phaser.Physics.Arcade.Sprite {
  private hp: number
  private speed: number
  private type: EnemyType
  private direction = 1
  private changeTimer = 0

  constructor(scene: Phaser.Scene, x: number, y: number, type: EnemyType = 'slime') {
    super(scene, x, y, `enemy_${type}`)
    this.type = type
    const cfg = ENEMY_CONFIG[type]
    this.hp    = cfg.hp
    this.speed = cfg.speed

    const body = this.body as Phaser.Physics.Arcade.Body
    body.setGravityY(cfg.gravity)
    body.setCollideWorldBounds(true)
    body.setBounce(0)

    this.play(`enemy-${type}`)
  }

  update(_time: number, _delta: number) {
    const body = this.body as Phaser.Physics.Arcade.Body

    if (this.type === 'bat') {
      // Bat: sine wave movement
      this.changeTimer += 0.02
      body.setVelocityX(Math.sin(this.changeTimer) * this.speed)
      body.setVelocityY(Math.cos(this.changeTimer * 0.7) * 40)
    } else {
      // Ground enemies: patrol with direction reversal on wall hit
      body.setVelocityX(this.direction * this.speed)
      if (body.blocked.left || body.blocked.right) {
        this.direction *= -1
        this.setFlipX(this.direction < 0)
      }
    }
  }

  takeDamage(amount: number): boolean {
    this.hp -= amount
    if (this.hp <= 0) {
      this.destroy()
      return true
    }
    this.scene.tweens.add({
      targets: this,
      tint: { from: 0xff0000, to: 0xffffff },
      duration: 200,
    })
    return false
  }
}
```

---

### File: `lib/game/scenes/UIScene.ts`

```typescript
import Phaser from 'phaser'

export class UIScene extends Phaser.Scene {
  private scoreText!: Phaser.GameObjects.Text
  private coinsText!: Phaser.GameObjects.Text
  private hearts: Phaser.GameObjects.Image[] = []
  private timerText!: Phaser.GameObjects.Text
  private elapsed = 0

  constructor() {
    super({ key: 'UIScene' })
  }

  create() {
    const gameScene = this.scene.get('GameScene')

    // ---- Score ----
    this.add.image(24, 24, 'ui_coin_icon').setOrigin(0, 0.5).setDisplaySize(32, 32)
    this.scoreText = this.add.text(64, 24, '0', {
      fontSize: '28px',
      fontFamily: 'monospace',
      color: '#ffd700',
      stroke: '#000',
      strokeThickness: 4,
    }).setOrigin(0, 0.5)

    // ---- Coins ----
    this.coinsText = this.add.text(180, 24, 'x 0', {
      fontSize: '22px',
      fontFamily: 'monospace',
      color: '#ffffff',
      stroke: '#000',
      strokeThickness: 3,
    }).setOrigin(0, 0.5)

    // ---- Hearts ----
    const lives = this.registry.get('lives') as number
    this.refreshHearts(lives)

    // ---- Timer ----
    this.timerText = this.add.text(1280 / 2, 24, '0:00', {
      fontSize: '22px',
      fontFamily: 'monospace',
      color: '#ffffff',
      stroke: '#000',
      strokeThickness: 3,
    }).setOrigin(0.5, 0.5)

    // ---- Event listeners ----
    gameScene.events.on('score-changed',  (v: number) => { this.scoreText.setText(v.toLocaleString()) })
    gameScene.events.on('coins-changed',  (v: number) => { this.coinsText.setText(`x ${v}`) })
    gameScene.events.on('lives-changed',  (v: number) => { this.refreshHearts(v) })
  }

  update(_: number, delta: number) {
    this.elapsed += delta
    const totalSec = Math.floor(this.elapsed / 1000)
    const m = Math.floor(totalSec / 60)
    const s = totalSec % 60
    this.timerText.setText(`${m}:${s.toString().padStart(2, '0')}`)
  }

  private refreshHearts(lives: number) {
    this.hearts.forEach(h => h.destroy())
    this.hearts = []
    for (let i = 0; i < 3; i++) {
      const key = i < lives ? 'ui_heart_full' : 'ui_heart_empty'
      const heart = this.add.image(1200 + i * 36, 24, key)
        .setDisplaySize(28, 28)
        .setOrigin(0.5, 0.5)
      this.hearts.push(heart)
    }
  }
}
```

---

### File: `lib/game/scenes/GameOverScene.ts`

```typescript
import Phaser from 'phaser'

export class GameOverScene extends Phaser.Scene {
  constructor() {
    super({ key: 'GameOverScene' })
  }

  init(data: { win?: boolean }) {
    const score = this.registry.get('score') as number
    const hs    = this.registry.get('highScore') as number

    if (score > hs) {
      this.registry.set('highScore', score)
      try { localStorage.setItem('phaser_highscore', String(score)) } catch {}
    }
  }

  create(data: { win?: boolean }) {
    const { width, height } = this.cameras.main
    const score   = this.registry.get('score')     as number
    const hs      = this.registry.get('highScore') as number
    const isNew   = score >= hs
    const won     = data.win ?? false

    // Dim overlay
    this.add.rectangle(width / 2, height / 2, width, height, 0x000000, 0.75)

    // Title
    this.add.text(width / 2, 140, won ? 'LEVEL COMPLETE!' : 'GAME OVER', {
      fontSize: '64px',
      fontFamily: 'monospace',
      color: won ? '#22c55e' : '#ef4444',
      stroke: '#000',
      strokeThickness: 6,
    }).setOrigin(0.5)

    // Score
    this.add.text(width / 2, 250, `Score: ${score.toLocaleString()}`, {
      fontSize: '32px',
      fontFamily: 'monospace',
      color: '#ffd700',
    }).setOrigin(0.5)

    if (isNew) {
      this.add.text(width / 2, 300, 'NEW HIGH SCORE!', {
        fontSize: '22px',
        fontFamily: 'monospace',
        color: '#facc15',
      }).setOrigin(0.5)
    }

    this.add.text(width / 2, 340, `Best: ${hs.toLocaleString()}`, {
      fontSize: '22px',
      fontFamily: 'monospace',
      color: '#94a3b8',
    }).setOrigin(0.5)

    // Buttons
    this.createButton(width / 2, 430, 'PLAY AGAIN', () => {
      this.registry.set('score', 0)
      this.registry.set('coins', 0)
      this.registry.set('lives', 3)
      this.scene.stop('GameOverScene')
      this.scene.start('GameScene')
      this.scene.start('UIScene')
    })

    this.createButton(width / 2, 510, 'MAIN MENU', () => {
      this.registry.set('score', 0)
      this.registry.set('coins', 0)
      this.registry.set('lives', 3)
      this.scene.stop('GameOverScene')
      this.scene.start('MenuScene')
    })
  }

  private createButton(x: number, y: number, label: string, cb: () => void) {
    const btn = this.add.text(x, y, label, {
      fontSize: '28px',
      fontFamily: 'monospace',
      color: '#ffffff',
      backgroundColor: '#1e40af',
      padding: { x: 24, y: 10 },
    }).setOrigin(0.5).setInteractive({ useHandCursor: true })

    btn.on('pointerover',  () => btn.setBackgroundColor('#2563eb'))
    btn.on('pointerout',   () => btn.setBackgroundColor('#1e40af'))
    btn.on('pointerdown',  cb)
  }
}
```

---

## Step 4: Generate Tilemap

Create `/public/assets/tilemaps/level_1.json` with a valid Tiled-format JSON. This is a 50x12 tile map (each tile 64x64) representing a side-scrolling platformer level with platforms, gaps, and enemy markers.

```json
{
  "compressionlevel": -1,
  "height": 12,
  "infinite": false,
  "layers": [
    {
      "data": [
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,5,5,5,0,0,0,0,0,0,0,0,0,0,0,0,0,5,5,5,5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,5,5,5,0,0,0,
        0,0,0,0,0,0,5,5,5,0,0,0,0,0,0,0,0,0,5,5,5,5,0,0,0,0,0,0,0,0,0,0,0,0,5,5,5,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        1,1,1,1,1,0,0,0,0,0,0,0,1,1,1,1,1,0,0,0,0,0,1,1,1,0,0,0,0,0,1,1,1,0,0,0,0,0,1,1,1,1,0,0,0,0,1,1,1,1,
        2,2,2,2,2,0,0,0,0,0,0,0,2,2,2,2,2,0,0,0,0,0,2,2,2,0,0,0,0,0,2,2,2,0,0,0,0,0,2,2,2,2,0,0,0,0,2,2,2,2
      ],
      "height": 12,
      "id": 1,
      "name": "Ground",
      "opacity": 1,
      "type": "tilelayer",
      "visible": true,
      "width": 50,
      "x": 0,
      "y": 0
    },
    {
      "data": [
        3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
      ],
      "height": 12,
      "id": 2,
      "name": "Background",
      "opacity": 1,
      "type": "tilelayer",
      "visible": true,
      "width": 50,
      "x": 0,
      "y": 0
    },
    {
      "data": [
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,4,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
      ],
      "height": 12,
      "id": 3,
      "name": "Foreground",
      "opacity": 1,
      "type": "tilelayer",
      "visible": true,
      "width": 50,
      "x": 0,
      "y": 0
    }
  ],
  "nextlayerid": 4,
  "nextobjectid": 1,
  "orientation": "orthogonal",
  "renderorder": "right-down",
  "tiledversion": "1.10.1",
  "tileheight": 64,
  "tilesets": [
    {
      "firstgid": 1,
      "source": "tileset_main.tsx"
    }
  ],
  "tilewidth": 64,
  "type": "map",
  "version": "1.10"
}
```

---

## Step 5: Generate Placeholder Sprites

Create `/scripts/generate_placeholders.py`. Run with: `python3 scripts/generate_placeholders.py`

```python
#!/usr/bin/env python3
"""
generate_placeholders.py
Generates colored rectangle placeholder spritesheets using PIL.
Install: pip install Pillow
Run: python3 scripts/generate_placeholders.py
"""

import os
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = "public/assets/sprites"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def make_spritesheet(filename: str, frame_w: int, frame_h: int, frames: int,
                     bg_color: tuple, label: str = "", outline: tuple = (255,255,255,180)):
    """Create a horizontal spritesheet with frame_count frames."""
    sheet = Image.new("RGBA", (frame_w * frames, frame_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)

    for i in range(frames):
        x0 = i * frame_w
        # Slightly vary color per frame to visualize animation
        r, g, b, a = bg_color
        shade = int(40 * (i / max(frames - 1, 1)) - 20)
        color = (max(0, min(255, r + shade)), max(0, min(255, g)), max(0, min(255, b)), a)

        draw.rectangle([x0 + 2, 2, x0 + frame_w - 3, frame_h - 3], fill=color, outline=outline, width=2)
        # Frame label
        text_x = x0 + frame_w // 2
        text_y = frame_h // 2
        draw.text((text_x, text_y), f"{label}\n{i}", fill=(255, 255, 255, 200), anchor="mm")

    path = os.path.join(OUTPUT_DIR, filename)
    sheet.save(path)
    print(f"  Created: {path}  ({frames} frames, {frame_w}x{frame_h})")


def make_icon(filename: str, size: int, color: tuple, shape: str = "rect"):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if shape == "circle":
        draw.ellipse([2, 2, size - 3, size - 3], fill=color, outline=(255, 255, 255, 180), width=2)
    else:
        draw.rectangle([2, 2, size - 3, size - 3], fill=color, outline=(255, 255, 255, 180), width=2)
    path = os.path.join(OUTPUT_DIR, filename)
    img.save(path)
    print(f"  Created: {path}  ({size}x{size} {shape})")


print("Generating player spritesheets...")
make_spritesheet("player_idle.png",   64, 64, 4,  (70, 130, 220, 255), "idle")
make_spritesheet("player_run.png",    64, 64, 8,  (70, 130, 220, 255), "run")
make_spritesheet("player_jump.png",   64, 64, 2,  (70, 130, 220, 255), "jump")
make_spritesheet("player_fall.png",   64, 64, 2,  (70, 130, 220, 255), "fall")
make_spritesheet("player_attack.png", 64, 64, 3,  (70, 130, 220, 255), "atk")

print("Generating enemy spritesheets...")
make_spritesheet("enemy_slime.png",  48, 48, 6, (60, 180, 60, 255),  "slime")
make_spritesheet("enemy_bat.png",    48, 48, 6, (100, 60, 140, 255), "bat")
make_spritesheet("enemy_goblin.png", 64, 64, 6, (180, 100, 40, 255), "goblin")

print("Generating collectibles...")
make_spritesheet("coin.png",  16, 16, 8, (255, 215, 0, 255),   "coin")
make_spritesheet("heart.png", 16, 16, 2, (220, 30, 30, 255),   "heart")

print("Generating UI icons...")
make_icon("../ui/heart_full.png",  32, (220, 30, 30, 255),  "circle")
make_icon("../ui/heart_empty.png", 32, (80, 30, 30, 255),   "circle")
make_icon("../ui/coin_icon.png",   32, (255, 215, 0, 255),  "circle")

print("\nDone. All placeholder sprites generated.")
print("Replace these with real art assets before shipping.")
```

---

## Step 6: Save System

The save system is already implemented across the scenes:

- **BootScene** — calls `localStorage.getItem('phaser_highscore')` on startup and seeds the Phaser registry with `highScore`
- **GameOverScene** — on init, compares current score against high score, writes `localStorage.setItem('phaser_highscore', score)` if new record
- **Settings** — the `settings` object in the Phaser registry (sfxVolume, musicVolume, fullscreen) is saved to `localStorage` as `phaser_settings` (add this hook in MenuScene's Settings panel: `localStorage.setItem('phaser_settings', JSON.stringify(settings))`)

Extended save utility to add to `lib/game/SaveSystem.ts`:

```typescript
const SAVE_KEY = 'phaser_save'

interface SaveData {
  highScore: number
  level: number
  settings: { sfxVolume: number; musicVolume: number; fullscreen: boolean }
}

export const SaveSystem = {
  save(data: Partial<SaveData>) {
    try {
      const existing = this.load()
      localStorage.setItem(SAVE_KEY, JSON.stringify({ ...existing, ...data }))
    } catch {}
  },

  load(): SaveData {
    try {
      const raw = localStorage.getItem(SAVE_KEY)
      if (raw) return JSON.parse(raw) as SaveData
    } catch {}
    return { highScore: 0, level: 1, settings: { sfxVolume: 0.8, musicVolume: 0.5, fullscreen: false } }
  },

  clear() {
    try { localStorage.removeItem(SAVE_KEY) } catch {}
  },
}
```

---

## Report

Phaser 3 game complete: 6 scenes (Boot, Preload, Menu, Game, UI, GameOver), tilemap level with 3 layers, animated player with coyote time + jump buffer, 3 enemy types (slime/bat/goblin), coin collection, HUD with hearts + score + timer, localStorage save system, placeholder sprite generator script. Run `npm run dev` and navigate to `/game`.
