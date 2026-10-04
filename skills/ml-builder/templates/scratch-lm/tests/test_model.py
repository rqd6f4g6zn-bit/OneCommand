import torch

from scratch_lm.model import GPT, GPTConfig
from scratch_lm.tokenizer import EOT, train_tokenizer


def tiny() -> GPT:
    torch.manual_seed(0)
    return GPT(GPTConfig(vocab_size=50, block_size=16, n_layer=1, n_head=2, n_embd=16, dropout=0.0))


def test_shapes_and_loss():
    m = tiny()
    x = torch.randint(50, (2, 16))
    logits, loss = m(x, x)
    assert logits.shape == (2, 16, 50) and loss.item() > 0


def test_attention_is_causal():
    m = tiny().eval()
    a = torch.randint(50, (1, 16))
    b = a.clone()
    b[0, 10:] = (b[0, 10:] + 1) % 50  # change only the future
    la, _ = m(a)
    lb, _ = m(b)
    assert torch.allclose(la[0, :10], lb[0, :10], atol=1e-5)


def test_tokenizer_roundtrip_and_eot():
    tok = train_tokenizer(["Hallo Welt, das ist unser eigenes Modell."] * 20, vocab_size=300)
    text = "Hallo Welt"
    assert tok.decode(tok.encode(text).ids) == text
    assert tok.token_to_id(EOT) is not None
