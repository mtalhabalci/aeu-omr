"""Several staffs through the decoder at once, each computed as it is alone, bit for bit.

Batched, a staff's reading is not the reading it gets alone: on the CPU a matrix product over 8 rows sums each row
in another order than over one (F.linear of 8 rows differed from 8 single rows in every row, by ~3e-6), and so does
attention. Greedy decoding turns such a difference into another symbol now and then. The service must give a staff
the same notes, and the same confidences, whether it is read alone or with the rest of its page.

Two operations of the decoder depend on the batch: its linear layers and its attention. Inside exact_rows:

- a linear layer applied to one position per row (every decoding step) runs as one batched matrix product over
  per-row matrices (torch.baddbmm / torch.bmm), whose rows are each summed as F.linear sums a single row, and come
  out equal to it; on CPU 2.2-2.5x faster than the rows one by one. Over several positions (the encoder's output,
  once per staff) each row goes through F.linear on its own.
- attention runs row by row.
- GELU gets its input as one block of memory. The feed-forward's GLU splits a row into halves; for one row a half
  is contiguous and torch computes GELU with oneDNN, for several rows the halves are strided and torch computes
  it with its own kernel, which differs in the last bit for most values. A contiguous copy takes oneDNN for any
  number of rows (and is no copy for one).

Everything else in the decoder (embeddings, layer norms, the other activations, residual sums, argmax) works on
each row alone and is batched as it is.

One change saves work rather than keeping the reading: at every step after the first the cross attention appends
nothing to its cached keys and values, and torch.cat copied them all to do so (~42 MB a staff a step); inside
exact_rows x_transformers' cat hands such a cache back as it is, the same values in the same memory layout. With
it 24 staffs read together took half the time they took one by one (CPU, 4 threads).
"""
import types
from collections.abc import Iterator
from contextlib import contextmanager

import torch
import torch.nn.functional as F
import x_transformers.x_transformers as x_transformers_module
from torch import nn
from x_transformers.attend import Attend


def _linear(self: nn.Linear, x: torch.Tensor) -> torch.Tensor:
    if x.dim() != 3 or x.shape[0] == 1 or x.shape[1] == 0:  # (no positions: the encoder's output once cached)
        return F.linear(x, self.weight, self.bias)
    rows, positions, _ = x.shape
    if positions != 1:
        return torch.cat([F.linear(x[i : i + 1], self.weight, self.bias) for i in range(rows)])
    weight = self.weight.t().unsqueeze(0).expand(rows, -1, -1)
    if self.bias is None:
        return torch.bmm(x, weight)
    return torch.baddbmm(self.bias.view(1, 1, -1).expand(rows, 1, -1), x, weight)


def _cat_without_copy(tensors, dim: int = 0, **kwargs) -> torch.Tensor:  # noqa: ANN001
    """torch.cat, which returns the first of two tensors as it is when the second adds nothing along dim: at every
    step after the first the cross attention appends its empty keys and values to the cached ones, and torch.cat
    copied the cache (~42 MB a staff) to do it."""
    if not kwargs and len(tensors) == 2:
        first, second = tensors
        if first.dim() == second.dim() > 0 and first.dtype == second.dtype and first.device == second.device:
            d = dim % first.dim()
            if (second.shape[d] == 0 and first.is_contiguous() and first.shape[:d] == second.shape[:d]
                    and first.shape[d + 1:] == second.shape[d + 1:]):
                return first
    return torch.cat(tensors, dim=dim, **kwargs)


def _gelu(self: nn.GELU, x: torch.Tensor) -> torch.Tensor:
    return F.gelu(x.contiguous(), approximate=self.approximate)


def _attention_by_row(attention):  # noqa: ANN001, ANN202  (Attend.flash_attn, bound)
    def by_row(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, mask: torch.Tensor | None = None,
               attn_bias: torch.Tensor | None = None, flash_pack_seq_kwargs: dict | None = None):  # noqa: ANN202
        rows = q.shape[0]
        if rows == 1:
            return attention(q, k, v, mask=mask, attn_bias=attn_bias, flash_pack_seq_kwargs=flash_pack_seq_kwargs)

        def row(t: torch.Tensor | None, i: int) -> torch.Tensor | None:
            return t[i : i + 1] if t is not None and t.shape[0] == rows else t

        outs, intermediates = [], None
        for i in range(rows):
            out, intermediates = attention(row(q, i), row(k, i), row(v, i), mask=row(mask, i),
                                           attn_bias=row(attn_bias, i), flash_pack_seq_kwargs=flash_pack_seq_kwargs)
            outs.append(out)
        return torch.cat(outs), intermediates

    return by_row


@contextmanager
def exact_rows(net: nn.Module) -> Iterator[None]:
    """Within it, net computes each row of a batch as it computes that row alone (see the module's docstring).
    The modules of net, and x_transformers' cat, are changed for its duration: nothing else may run the model, or
    another x_transformers model, meanwhile (the service reads one page at a time, under its lock)."""
    linears = [m for m in net.modules() if isinstance(m, nn.Linear)]
    gelus = [m for m in net.modules() if isinstance(m, nn.GELU)]
    attends = [m for m in net.modules() if isinstance(m, Attend)]
    if any(not a.flash for a in attends):
        raise ValueError("exact_rows reads attention by row only on the flash path (scaled_dot_product_attention)")
    cat = x_transformers_module.cat
    try:
        for m in linears:
            m.forward = types.MethodType(_linear, m)
        for m in gelus:
            m.forward = types.MethodType(_gelu, m)
        for a in attends:
            a.flash_attn = _attention_by_row(a.flash_attn)
        x_transformers_module.cat = _cat_without_copy
        yield
    finally:
        x_transformers_module.cat = cat
        for m in linears + gelus:
            m.__dict__.pop("forward", None)
        for a in attends:
            a.__dict__.pop("flash_attn", None)
