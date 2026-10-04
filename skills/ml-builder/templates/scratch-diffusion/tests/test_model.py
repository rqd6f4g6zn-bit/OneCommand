import torch

from scratch_diffusion.diffusion import Diffusion
from scratch_diffusion.model import UNet, UNetConfig


def test_image_unet_predicts_noise_of_the_input_shape():
    m = UNet(UNetConfig(dims=2, base=16, mults=[1, 2], attention=True, dropout=0.0))
    x = torch.randn(2, 3, 16, 16)
    assert m(x, torch.tensor([1, 500])).shape == x.shape


def test_video_unet_keeps_frames_and_supports_labels():
    m = UNet(UNetConfig(dims=3, base=16, mults=[1, 2], attention=False, dropout=0.0, num_classes=3))
    x = torch.randn(2, 3, 4, 16, 16)
    assert m(x, torch.tensor([3, 900]), torch.tensor([0, 2])).shape == x.shape


def test_noise_schedule_and_sampler():
    d = Diffusion(100)
    assert d.alpha_bar[0] > 0.99 and d.alpha_bar[-1] < 0.01
    m = UNet(UNetConfig(dims=2, base=16, mults=[1], attention=False, dropout=0.0)).eval()
    out = d.sample(m, (2, 3, 8, 8), steps=5)
    assert out.shape == (2, 3, 8, 8) and out.abs().max() <= 1


def test_normaliser_roundtrip_and_bounds():
    from scratch_diffusion.data import Normaliser
    x = torch.rand(8, 3, 4, 4) * 0.2 + 0.75  # bright data, like screenshots
    n = Normaliser.fit(x)
    z = n.encode(x)
    assert abs(z.mean().item()) < 1e-4 and abs(z.std().item() - 1) < 0.05
    assert torch.allclose(n.decode(z), x, atol=1e-5)
    lo, hi = n.bounds()
    assert (lo < z.amin(dim=(0, 2, 3))).all() and (hi > z.amax(dim=(0, 2, 3))).all()
