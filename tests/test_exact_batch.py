"""Staffs read together read as each reads alone (training/architecture/transformer/exact_batch.py)."""
import torch
import torch.nn.functional as F
from torch import nn

from homr.transformer.configs import Config
from training.architecture.transformer.decoder import get_decoder
from training.architecture.transformer.exact_batch import _cat_without_copy, _linear, exact_rows


def _readings(symbols: list) -> list[tuple]:
    return [(s.rhythm, s.pitch, s.lift, s.articulation, s.position, s.confidence) for s in symbols]


def test_a_linear_layer_gives_each_row_what_it_gives_the_row_alone() -> None:
    torch.manual_seed(0)
    for bias in (True, False):
        layer = nn.Linear(512, 2048, bias=bias)
        x = torch.randn(6, 1, 512)
        together = _linear(layer, x)
        for i in range(6):
            assert torch.equal(together[i : i + 1], F.linear(x[i : i + 1], layer.weight, layer.bias))


def test_nothing_appended_hands_the_cache_back_and_anything_else_is_concatenated() -> None:
    cache = torch.randn(3, 8, 5, 64)
    assert _cat_without_copy((cache, cache[:, :, :0]), dim=-2) is cache
    new = torch.randn(3, 8, 1, 64)
    assert torch.equal(_cat_without_copy((cache, new), dim=-2), torch.cat((cache, new), dim=-2))
    empty = torch.zeros(3, 8, 0, 64)
    assert torch.equal(_cat_without_copy((empty, new), dim=-2), new)


def test_the_decoder_reads_staffs_together_as_it_reads_each_alone() -> None:
    """A decoder with random weights, a few steps, on the CPU: symbols and confidences bit for bit."""
    torch.manual_seed(1)
    config = Config()
    decoder = get_decoder(config).eval()
    decoder.device = torch.device("cpu")
    decoder.max_seq_len = 12
    contexts = [torch.randn(1, 1281, config.decoder_dim) for _ in range(3)]
    start, nonote = torch.tensor([[1]]), torch.tensor([[0]])
    with torch.no_grad():
        alone = [decoder.generate(start, nonote, context=c) for c in contexts]
        together = decoder.generate_batch(contexts)
    assert [_readings(a) for a in alone] == [_readings(t) for t in together]


def test_exact_rows_leaves_the_decoder_as_it_was() -> None:
    import x_transformers.x_transformers as x_transformers_module  # noqa: PLC0415

    decoder = get_decoder(Config())
    with exact_rows(decoder.net):
        pass
    assert all("forward" not in m.__dict__ for m in decoder.net.modules())
    assert x_transformers_module.cat is torch.cat
