from homr.lyrics import StaffLyrics, Word, add_lyrics, staff_lyrics, syllables


def test_syllables() -> None:
    assert syllables("yele") == ["ye", "le"]
    assert syllables("kaynarsın") == ["kay", "nar", "sın"]
    assert syllables("Türkçe") == ["Türk", "çe"]
    assert syllables("saat") == ["sa", "at"]
    assert syllables("n'olur") == ["n'o", "lur"]
    assert syllables("Câ") == ["Câ"]


def _note(step: str, octave: int, extra: str = "") -> str:
    return (f"<note>{extra}<pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>4</duration>"
            "<voice>1</voice><type>quarter</type><staff>1</staff><notations /></note>")


def _score(*measures: list[str]) -> str:
    body = "".join(f'<measure number="{n}">{"".join(notes)}</measure>' for n, notes in enumerate(measures, 1))
    return f'<score-partwise><part-list><score-part id="P1"/></part-list><part id="P1">{body}</part></score-partwise>'


def test_lines_verses_and_not_sung() -> None:
    staff = (100, 100, 900, 140)  # a staff 40 px high
    words = [Word("Yi", (190, 160, 210, 172)), Word("ne", (290, 160, 310, 172)),
             Word("Pür", (190, 176, 215, 188)),  # verse 2, under verse 1
             Word("ARANAĞMESİ", (400, 160, 520, 172)),  # a section's name
             Word("v", (600, 160, 606, 172)),  # a sign of the music font
             Word("Yine bir gülnihal aldı bu gönlümü", (100, 400, 700, 412))]  # far below: the poem
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [[w.text for w in line] for line in lines] == [["Yi", "ne"], ["Pür"]]


def test_add_lyrics_to_the_notes_under_them() -> None:
    # G4 (place 4), B4 (place 6), a rest, A4 (place 5); heads at x 200, 300, -, 500
    rest = "<note><rest /><duration>4</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>"
    xml = _score([_note("G", 4), _note("B", 4)], [rest, _note("A", 4)])
    heads = [[(200, 4), (300, 6), (500, 5)]]
    lyrics = [StaffLyrics([[Word("Yi", (190, 160, 210, 172)), Word("ne", (292, 160, 312, 172)),
                            Word("bir", (488, 160, 512, 172))]])]
    out, record = add_lyrics(xml, [(1, 2)], heads, lyrics, [(100, 100, 900, 140)])
    assert [(r["hece"], r["olcu"], r["nota"]) for r in record] == [("Yi", 1, 0), ("ne", 1, 1), ("bir", 2, 1)]
    assert out.count("<lyric ") == 3
    assert '<lyric number="1"><syllabic>single</syllabic><text>bir</text></lyric></note>' in out
    assert "<rest /><duration>4</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>" in out


def test_a_missed_head_shifts_nothing() -> None:
    xml = _score([_note("G", 4), _note("B", 4), _note("D", 5)])
    heads = [[(200, 4), (400, 8)]]  # the B's head was not found
    lyrics = [StaffLyrics([[Word("a", (395, 160, 405, 172))]])]
    _, record = add_lyrics(xml, [(1, 1)], heads, lyrics, [(100, 100, 900, 140)])
    assert (record[0]["olcu"], record[0]["nota"]) == (1, 2)  # the D, not the B


def test_several_parts_are_left_alone() -> None:
    xml = '<score-partwise><part-list><score-part id="P1"/><score-part id="P2"/></part-list></score-partwise>'
    out, record = add_lyrics(xml, [], [], [], [])
    assert out == xml and record == []


def test_tempo_words_and_letter_spaced_directions_are_not_sung() -> None:
    staff = (100, 100, 900, 140)
    words = [Word("Yi", (190, 160, 210, 172)), Word("Çabuk", (300, 160, 350, 172))]
    words += [Word(c, (500 + 9 * i, 160, 507 + 9 * i, 172)) for i, c in enumerate("Karar")]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [[w.text for w in line] for line in lines] == [["Yi"]]


def test_credits_directions_in_parentheses_and_usul_names_are_not_sung() -> None:
    staff = (100, 100, 900, 140)
    words = [Word("Yi", (190, 160, 210, 172)), Word("(2'ye)", (300, 160, 350, 172)), Word("ne", (400, 160, 420, 172)),
             Word("Aksak", (600, 160, 650, 172)),
             Word("Güfte:", (190, 180, 240, 192)), Word("Fâik", (250, 180, 290, 192)), Word("Ali", (300, 180, 330, 192))]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [[w.text for w in line] for line in lines] == [["Yi", "ne"]]


def test_syllables_in_capitals_are_sung_a_heading_and_a_name_are_not() -> None:
    # words and boxes of a typeset türkü's text layer (Aksaray'dan Geçer İken, page 2): all its lyrics in capitals,
    # the arranger's name beside the last line
    staff = (45.0, 470.0, 555.0, 505.0)
    words = [Word("Faruk", (506.9, 512.5, 527.4, 522.6)), Word("Þahin", (530.2, 512.5, 550.4, 522.6))]
    words += [Word(t, (x0, 519.9, x1, 529.0)) for t, x0, x1 in (
        ("HEY", 83.3, 100.4), ("DA", 184.3, 196.7), ("LE", 201.8, 211.9), ("DE", 217.4, 228.9), ("DA", 271.7, 284.1),
        ("LE", 289.2, 299.2), ("DA", 337.4, 349.8), ("LE", 355.0, 365.0), ("DE", 370.6, 382.0), ("DA", 425.0, 437.4),
        ("LE", 442.6, 452.6), ("DA", 490.6, 502.9), ("LE", 508.1, 518.1))]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [" ".join(w.text for w in line) for line in lines] == ["HEY DA LE DE DA LE DA LE DE DA LE DA LE"]
    # a line of syllables in capitals is sung (HEY HEY HEY too); a heading in capitals is not
    staff = (100.0, 100.0, 900.0, 140.0)
    words = [Word(t, (x, 160, x + 20, 172)) for t, x in (("HEY", 200), ("HEY", 400), ("HEY", 600))]
    words += [Word("GİRİŞ", (300, 176, 350, 188)), Word("SAZI", (360, 176, 400, 188))]
    words += [Word(t, (x, 192, x + 20, 204)) for t, x in (("VE", 200), ("RİN", 300), ("BE", 400), ("NİM", 500))]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [" ".join(w.text for w in line) for line in lines] == ["HEY HEY HEY", "VE RİN BE NİM"]


def test_a_name_inside_a_line_of_syllables_is_left_out() -> None:
    staff = (100.0, 100.0, 900.0, 140.0)
    words = [Word(t, (x, 160, x + 30, 172)) for t, x in (("Gül", 200), ("ni", 300), ("hal", 400), ("Faruk", 700),
                                                          ("Şahin", 750))]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [" ".join(w.text for w in line) for line in lines] == ["Gül ni hal"]


def test_a_word_in_capitals_alone_and_the_poem_with_a_name_in_it_are_not_sung() -> None:
    staff = (100.0, 100.0, 900.0, 140.0)
    words = [Word("Yi", (200, 160, 220, 172)), Word("ne", (300, 160, 320, 172)),
             Word("RAST", (200, 176, 240, 188)),  # the makam's name
             Word("Tanburi", (200, 192, 260, 204)), Word("Büyük", (270, 192, 320, 204)),  # a name and title (Bey)
             Word("Osman", (330, 192, 380, 204)), Word("Bey", (390, 192, 420, 204))]
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [" ".join(w.text for w in line) for line in lines] == ["Yi ne"]


def test_a_heading_a_title_and_an_usul_in_capitals_are_not_sung() -> None:
    staff = (100.0, 100.0, 900.0, 140.0)

    def line(y: float, texts: list[str], gap: float) -> list[Word]:
        out, x = [], 120.0
        for t in texts:
            out.append(Word(t, (x, y, x + 9 * len(t), y + 12)))
            x += 9 * len(t) + gap
        return out

    words = line(160, ["ÇOK", "BEK", "LE", "DİM", "AK", "ŞAM"], 40)  # syllables, each under its note: sung
    words += line(176, ["RAST", "MARŞ"], 3)  # a heading: its words a space apart
    words += line(192, ["EVÇ", "SAZ", "SEMÂİSİ"], 3)
    words += line(208, ["BİR", "AŞK", "GERÇEK", "BİR", "DE", "ÖLÜM"], 4)  # a title
    words += line(224, ["DÜM", "TEK", "TE", "KE", "DÜM", "TEK"], 40)  # the usul's syllables
    lines = staff_lyrics(words, [staff], 1000)[0].lines
    assert [" ".join(w.text for w in line) for line in lines] == ["ÇOK BEK LE DİM AK ŞAM"]


def test_a_misread_syllable_an_unclosed_parenthesis_and_joined_capitals_keep_the_line() -> None:
    # OCR lines of three Atkoşar scans (13514, 12902, 14130), their syllables under their notes
    staff = (100.0, 100.0, 1900.0, 140.0)

    def line(y: float, texts: list[str]) -> list[Word]:
        # read by OCR: hand lettering, written from its note
        return [Word(t, (120.0 + 110 * i, y, 120.0 + 110 * i + 9 * len(t), y + 14), 0.9, True)
                for i, t in enumerate(texts)]

    # 'son' read as '50n' is no date: the line is sung
    words = line(160, ["den", "50n", "ra", "is", "fer", "vi", "san"])
    assert [" ".join(w.text for w in x) for x in staff_lyrics(words, [staff], 1000)[0].lines] == ["den ra is fer vi san"]
    # '(-SAZ' whose ')' OCR missed: only the direction is left out, not the syllables after it
    words = line(160, ["i", "cin", "dar", "Göz", "le", "ri", "(-SAZ", "göz", "le", "ri", "-SAZ", "göz", "le", "ri", "nem"])
    assert [" ".join(w.text for w in x) for x in staff_lyrics(words, [staff], 1000)[0].lines] == [
        "i cin dar Göz le ri göz le ri göz le ri nem"]
    # handwritten syllables in capitals, a few joined by OCR (HIDI, ELI, KII): sung, not a heading
    words = line(160, ["EY", "$Â", "HIDI", "GAYB", "AL", "ELI", "NI", "HAK-", "KII", "ZÂ", "RIN"])
    kept = staff_lyrics(words, [staff], 1000)[0].lines
    assert len(kept) == 1 and kept[0][0].text == "EY" and kept[0][-1].text == "RIN"
    # a colon read in the dots after a held syllable is no credit; a credit in parentheses is one, though unclosed
    words = line(160, ["ben", "de", "ği", "iim", ":.SAZ"]) + line(190, ["(8.T.:", "Sgushos", "Fuad", "Edip", "Baks1"])
    assert [" ".join(w.text for w in x) for x in staff_lyrics(words, [staff], 1000)[0].lines] == ["ben de ği i im"]
    # on a typeset page's exact text layer the rules stay strict: a ')' is never missed there
    typeset = [Word(t, (120.0 + 110 * i, 160, 120.0 + 110 * i + 9 * len(t), 174)) for i, t in enumerate(
        ["Yi", "ne", "(Tüm", "sazlar....", "çalar"])]
    assert [" ".join(w.text for w in x) for x in staff_lyrics(typeset, [staff], 1000)[0].lines] == ["Yi ne"]
