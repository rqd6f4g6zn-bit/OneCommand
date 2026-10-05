"""DDPM training objective (predict the noise) and a deterministic DDIM sampler."""

from __future__ import annotations

import math

import torch
from torch.nn import functional as F


class Diffusion:
    def __init__(self, timesteps: int = 1000):
        self.T = timesteps
        s = 0.008  # cosine schedule (Nichol & Dhariwal)
        x = torch.linspace(0, timesteps, timesteps + 1)
        abar = torch.cos(((x / timesteps) + s) / (1 + s) * math.pi / 2) ** 2
        abar = abar / abar[0]
        self.alpha_bar = abar[1:].clamp(1e-5, 1.0)

    def q_sample(self, x0: torch.Tensor, t: torch.Tensor, noise: torch.Tensor) -> torch.Tensor:
        ab = self.alpha_bar.to(x0.device)[t].view(-1, *([1] * (x0.dim() - 1)))
        return ab.sqrt() * x0 + (1 - ab).sqrt() * noise

    def loss(self, model, x0: torch.Tensor, y: torch.Tensor | None = None) -> torch.Tensor:
        t = torch.randint(0, self.T, (x0.shape[0],), device=x0.device)
        noise = torch.randn_like(x0)
        return F.mse_loss(model(self.q_sample(x0, t, noise), t, y), noise)

    @torch.no_grad()
    def sample(self, model, shape: tuple[int, ...], steps: int = 50, y: torch.Tensor | None = None,
               generator: torch.Generator | None = None, lo: torch.Tensor | float = -1.0,
               hi: torch.Tensor | float = 1.0) -> torch.Tensor:
        """lo/hi: the data range in model space (per channel when the data is normalised)."""
        device = next(model.parameters()).device
        view = (1, -1) + (1,) * (len(shape) - 2)
        lo = torch.as_tensor(lo, dtype=torch.float32, device=device).reshape(-1).view(view)
        hi = torch.as_tensor(hi, dtype=torch.float32, device=device).reshape(-1).view(view)
        x = torch.randn(shape, generator=generator).to(device)
        ts = torch.linspace(self.T - 1, 0, steps).long()
        ab = self.alpha_bar.to(device)
        for i, t in enumerate(ts):
            tt = torch.full((shape[0],), int(t), device=device, dtype=torch.long)
            eps = model(x, tt, y)
            a_t = ab[t]
            x0 = torch.maximum(torch.minimum((x - (1 - a_t).sqrt() * eps) / a_t.sqrt(), hi), lo)
            # Keep x0 and eps consistent after clipping, otherwise the trajectory drifts off the data.
            eps = (x - a_t.sqrt() * x0) / (1 - a_t).sqrt()
            a_prev = ab[ts[i + 1]] if i + 1 < len(ts) else torch.tensor(1.0, device=device)
            x = a_prev.sqrt() * x0 + (1 - a_prev).sqrt() * eps
        return torch.maximum(torch.minimum(x, hi), lo)
