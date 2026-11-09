"""Endings (voltas) as a page draws them, from what the reader wrote.

The reader misses some ending brackets and adds others, and the MusicXML writer numbers an ending by the one
that closed in the measure before it. On Zeki Atkoşar's handwritten pages, read against the page (09.11.2026,
230 works):

- The start of an ending is missed: "... repeatEnd voltaStop ..." or "... bolddoublebarline voltaStop ..."
  with no ending open, most often where the bracket begins a staff or carries a word ("MEYÂN'A", "KARAR")
  for its number. The writer then closed an ending that never opened and numbered the next one 2 or 3 (54
  works where the first ending was not 1). The ending is the measure that barline closes: half of SymbTr's
  first endings (1,760 of 3,445) are one measure long, and so were 71 of 83 such endings on the pages. When
  it is longer, a player still plays one measure less too many than with no start at all.
- After the second ending the reader adds "repeatEnd voltaStop voltaStart": a backward repeat and a third
  ending that never closes (13283: the page has "2." closed by a hook and a double barline). The section then
  played three times. A third ending that does close is kept: that is a page with three endings.
- Any other ending closed with none open is no ending; where it closes a measure it is a barline.
"""

from homr.transformer.vocabulary import EncodedSymbol

# what a staff opens with, before its first measure's notes
_STAFF_START = ("newline", "clef", "keyAccidental", "timeSignature")


def _is_close(rhythm: str) -> bool:
    return rhythm.startswith(("voltaStop", "voltaDiscontinue"))


def _closes_measure(rhythm: str) -> bool:
    return "barline" in rhythm or rhythm in ("repeatEnd", "repeatEndStart") or _is_close(rhythm)


def _is_music(rhythm: str) -> bool:
    return rhythm.startswith(("note", "rest", "chord", "measureRepeat"))


def _closes_later(voice: list[EncodedSymbol], index: int) -> bool:
    """Whether the ending opened at index is closed before another opens or the piece ends."""
    for symbol in voice[index + 1 :]:
        if symbol.rhythm.startswith("voltaStart"):
            return False
        if _is_close(symbol.rhythm) or symbol.rhythm in ("repeatEnd", "repeatEndStart"):
            return True
    return False


def _last(out: list[EncodedSymbol], skip_breaks: bool = True) -> int | None:
    for j in range(len(out) - 1, -1, -1):
        if not (skip_breaks and out[j].rhythm.startswith(_STAFF_START)):
            return j
    return None


def mend_voltas(voice: list[EncodedSymbol]) -> tuple[list[EncodedSymbol], list[tuple[int, str]]]:
    """The symbols with their endings mended, and what was mended: (staff number from 1, "baslangic" for an
    ending's start put back, "ucuncu" for a third ending left out, "kapanis" for a closing without an
    ending)."""
    out: list[EncodedSymbol] = []
    mended: list[tuple[int, str]] = []
    staff = 1
    ending_open = False
    run = 0  # endings in a row, the last one closed with no music after it
    after_close = False
    music = False  # notes since the last barline
    repeat_closed_ending = False  # the last repeatEnd closed an open ending
    for index, symbol in enumerate(voice):
        rhythm = symbol.rhythm
        if rhythm == "newline":
            staff += 1
        if rhythm.startswith("voltaStart"):
            run = run + 1 if after_close else 1
            if run >= 3 and not _closes_later(voice, index):
                last = _last(out)
                before = _last(out[:last]) if last is not None else None
                if last is not None and before is not None and _is_close(out[last].rhythm) \
                        and out[before].rhythm == "repeatEnd":
                    del out[before]
                mended.append((staff, "ucuncu"))
                run -= 1
                continue
            ending_open = True
            after_close = False
        elif _is_close(rhythm) and not ending_open:
            last = _last(out)
            before = out[last].rhythm if last is not None else ""
            if before == "repeatEnd" and repeat_closed_ending:
                out.append(symbol)  # the same ending closed twice: the writer keeps one
                continue
            if last is not None and ("barline" in before or before in ("repeatEnd", "repeatEndStart")):
                # a bracket ends on this barline and its start was not read: the ending is the measure it closes
                start = next((j + 1 for j in range(last - 1, -1, -1) if _closes_measure(out[j].rhythm)
                              or out[j].rhythm == "repeatStart"), 0)
                while start < last and out[start].rhythm.startswith(_STAFF_START):
                    start += 1
                out.insert(start, EncodedSymbol("voltaStart"))
                out.append(symbol)
                mended.append((staff, "baslangic"))
                run, after_close, music = 1, True, False
                continue
            if music:
                out.append(EncodedSymbol("barline"))
                music = False
            mended.append((staff, "kapanis"))
            continue
        elif _is_close(rhythm):
            ending_open = False
            after_close, music = True, False
        elif rhythm in ("repeatEnd", "repeatEndStart"):
            repeat_closed_ending = ending_open
            if ending_open:
                ending_open = False
                after_close = True
            music = False
        elif "barline" in rhythm or rhythm == "repeatStart":
            music = False
        elif _is_music(rhythm):
            music = True
            after_close = False  # a measure between two endings: the next one starts a new row
        out.append(symbol)
    return out, mended
