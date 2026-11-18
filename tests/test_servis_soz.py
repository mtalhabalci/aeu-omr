from servis.nota_servisi import (
    INSTRUMENTAL_FORM_CONFIDENCE,
    OCR_MIN_CONFIDENCE,
    OCR_MIN_SYLLABLES,
    instrumental_form,
    lyrics_summary,
    ocr_lyrics_kept,
)


def _syllable(staff: int, score: float, on_note: bool = True) -> dict:
    return {"porte": staff, "kita": 1, "hece": "na", "olcu": 1 if on_note else None, "nota": 0 if on_note else None,
            "x": 0.0, "notaX": 0.0 if on_note else None, "guven": score}


def test_the_threshold_of_ocr_lyrics() -> None:
    assert (OCR_MIN_SYLLABLES, OCR_MIN_CONFIDENCE) == (20, 0.85)
    sure = [_syllable(1, 0.95) for _ in range(20)]
    assert ocr_lyrics_kept(sure, {1})
    assert not ocr_lyrics_kept(sure[:19], {1})  # too few
    assert not ocr_lyrics_kept([_syllable(1, 0.84) for _ in range(40)], {1})  # not sure enough
    # guven is the mean score times the share written: syllables no note took lower it
    unbound = sure + [_syllable(1, 0.95, on_note=False) for _ in range(5)]
    assert lyrics_summary(list(unbound), {"ocr"}, None)["guven"] == 0.76
    assert not ocr_lyrics_kept(unbound, {1})


def test_only_the_staffs_ocr_read_are_weighed() -> None:
    text_layer = [_syllable(1, 1.0) for _ in range(30)]  # staff 1 from a PDF's text layer
    ocr = [_syllable(2, 0.6) for _ in range(5)]  # staff 2 read by OCR, few and unsure
    assert ocr_lyrics_kept(text_layer + ocr, set())  # OCR read none: as before
    assert not ocr_lyrics_kept(text_layer + ocr, {2})
    assert ocr_lyrics_kept(text_layer, {2})  # OCR read nothing that took a note


def _header(form: str | None, confidence: float | None) -> dict:
    return {"form": form, "guven": {} if confidence is None else {"form": confidence}}


def test_ocr_is_left_out_only_for_a_surely_read_instrumental_form() -> None:
    sure = INSTRUMENTAL_FORM_CONFIDENCE
    for form in ("Peşrev", "PEŞREV", "Saz Semâisi", "Sazsemâîsi", "SAZ SEMAİSİ", "Longa", "Sirto"):
        assert instrumental_form(_header(form, sure)), form
    assert not instrumental_form(_header("Peşrev", sure - 0.01))  # uncertain
    assert not instrumental_form(_header("Peşrev", None))
    assert not instrumental_form(_header("Şarkı", 0.99))
    assert not instrumental_form(_header("Saz Eseri", 0.99))  # not in the list
    assert not instrumental_form(_header(None, None))
    assert not instrumental_form(None)  # no title block
