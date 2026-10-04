"""U-Net noise predictor, randomly initialised. dims=2 for images (C,H,W), dims=3 for videos (C,T,H,W)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import torch
from torch import nn
from torch.nn import functional as F


@dataclass
class UNetConfig:
    dims: int = 2
    channels: int = 3
    base: int = 64
    mults: list[int] = field(default_factory=lambda: [1, 2, 2])
    attention: bool = True
    dropout: float = 0.1
    num_classes: int = 0  # > 0: class-conditional (labels from the dataset folders)

    def to_dict(self) -> dict:
        return asdict(self)


def timestep_embedding(t: torch.Tensor, dim: int) -> torch.Tensor:
    half = dim // 2
    freqs = torch.exp(-math.log(10000) * torch.arange(half, device=t.device) / half)
    args = t.float()[:, None] * freqs[None]
    return torch.cat([args.sin(), args.cos()], dim=1)


class ResBlock(nn.Module):
    def __init__(self, conv, cin: int, cout: int, temb: int, dropout: float):
        super().__init__()
        self.n1, self.c1 = nn.GroupNorm(8, cin), conv(cin, cout, 3, padding=1)
        self.t = nn.Linear(temb, cout)
        self.n2, self.c2 = nn.GroupNorm(8, cout), conv(cout, cout, 3, padding=1)
        self.drop = nn.Dropout(dropout)
        self.skip = conv(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x: torch.Tensor, emb: torch.Tensor) -> torch.Tensor:
        h = self.c1(F.silu(self.n1(x)))
        h = h + self.t(emb).view(*emb.shape[:1], -1, *([1] * (x.dim() - 2)))
        h = self.c2(self.drop(F.silu(self.n2(h))))
        return h + self.skip(x)


class Attention(nn.Module):
    """Self-attention over spatial positions (images only)."""

    def __init__(self, ch: int):
        super().__init__()
        self.norm, self.qkv, self.out = nn.GroupNorm(8, ch), nn.Conv2d(ch, 3 * ch, 1), nn.Conv2d(ch, ch, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, h, w = x.shape
        q, k, v = self.qkv(self.norm(x)).reshape(b, 3, c, h * w).unbind(1)
        y = F.scaled_dot_product_attention(q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2))
        return x + self.out(y.transpose(1, 2).reshape(b, c, h, w))


class UNet(nn.Module):
    def __init__(self, cfg: UNetConfig):
        super().__init__()
        self.cfg = cfg
        conv = nn.Conv2d if cfg.dims == 2 else nn.Conv3d
        # videos: downsample space only, keep every frame
        self.scale = 2 if cfg.dims == 2 else (1, 2, 2)
        temb = cfg.base * 4
        self.temb = nn.Sequential(nn.Linear(cfg.base, temb), nn.SiLU(), nn.Linear(temb, temb))
        self.label = nn.Embedding(cfg.num_classes, temb) if cfg.num_classes else None
        self.inp = conv(cfg.channels, cfg.base, 3, padding=1)
        chans = [cfg.base * m for m in cfg.mults]
        self.down, self.downsample = nn.ModuleList(), nn.ModuleList()
        cin = cfg.base
        skips = []
        for i, ch in enumerate(chans):
            self.down.append(nn.ModuleList([ResBlock(conv, cin, ch, temb, cfg.dropout),
                                            ResBlock(conv, ch, ch, temb, cfg.dropout)]))
            skips.append(ch)
            cin = ch
            last = i == len(chans) - 1
            self.downsample.append(nn.Identity() if last else
                                   conv(ch, ch, 3, stride=self.scale, padding=1))
        self.mid1 = ResBlock(conv, cin, cin, temb, cfg.dropout)
        self.mid_attn = Attention(cin) if cfg.attention and cfg.dims == 2 else nn.Identity()
        self.mid2 = ResBlock(conv, cin, cin, temb, cfg.dropout)
        self.up, self.upconv = nn.ModuleList(), nn.ModuleList()
        for i, ch in reversed(list(enumerate(chans))):
            skip = skips[i]
            self.up.append(nn.ModuleList([ResBlock(conv, cin + skip, ch, temb, cfg.dropout),
                                          ResBlock(conv, ch, ch, temb, cfg.dropout)]))
            cin = ch
            self.upconv.append(conv(ch, ch, 3, padding=1) if i > 0 else nn.Identity())
        self.out = nn.Sequential(nn.GroupNorm(8, cin), nn.SiLU(), conv(cin, cfg.channels, 3, padding=1))
        nn.init.zeros_(self.out[-1].weight)
        nn.init.zeros_(self.out[-1].bias)

    def num_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def forward(self, x: torch.Tensor, t: torch.Tensor, y: torch.Tensor | None = None) -> torch.Tensor:
        emb = self.temb(timestep_embedding(t, self.cfg.base))
        if self.label is not None and y is not None:
            emb = emb + self.label(y)
        h = self.inp(x)
        hs = []
        for (r1, r2), down in zip(self.down, self.downsample):
            h = r2(r1(h, emb), emb)
            hs.append(h)
            h = down(h)
        h = self.mid2(self.mid_attn(self.mid1(h, emb)), emb)
        for (r1, r2), upconv in zip(self.up, self.upconv):
            skip = hs.pop()
            if h.shape[2:] != skip.shape[2:]:
                h = F.interpolate(h, size=skip.shape[2:], mode="nearest")
            h = r2(r1(torch.cat([h, skip], dim=1), emb), emb)
            h = upconv(h)
        return self.out(h)
