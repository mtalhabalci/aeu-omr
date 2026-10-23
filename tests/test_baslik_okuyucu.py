import unittest

from homr.baslik_okuyucu import Header, Item, NameLists, fold, parse

WIDTH = 1920


def line(text: str, x0: float, y0: float, x1: float, y1: float, score: float = 0.95) -> Item:
    return Item(text, [x0, y0, x1, y1], score)


def centred(text: str, y0: float, height: float, half_width: float = 300) -> Item:
    return line(text, WIDTH / 2 - half_width, y0, WIDTH / 2 + half_width, y0 + height)


class TestTitleBlockReader(unittest.TestCase):
    """The rules on OCR lines made by hand: boxes in a 1920 px wide page, as the service renders a PDF."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.names = NameLists()

    def read(self, *items: Item) -> Header:
        return parse(list(items), WIDTH, self.names)

    def test_labelled_usul(self) -> None:
        header = self.read(centred("Hicaz Şarkı", 100, 60), line("Usûlü: Ağır Düyek", 100, 220, 500, 260))
        self.assertEqual(header.fields["usul"], "Ağır Düyek")

    def test_usul_label_without_its_colon(self) -> None:
        header = self.read(centred("Hicaz Şarkı", 100, 60), line("USÚLU CURCUNA", 100, 220, 450, 260))
        self.assertEqual(header.fields["usul"], "CURCUNA")

    def test_usul_line_with_a_tempo_mark(self) -> None:
        header = self.read(centred("Hicaz Şarkı", 100, 60), line("Düyek (=160)", 100, 220, 400, 260))
        self.assertEqual(header.fields["usul"], "Düyek")

    def test_makam_and_form_line(self) -> None:
        header = self.read(centred("Acemaşîrân Şarkı", 100, 60))
        self.assertEqual(header.fields["makam"], "Acemaşîrân")
        self.assertEqual(header.fields["form"], "Şarkı")

    def test_words_run_together(self) -> None:
        header = self.read(centred("HicazŞarkı", 100, 60))
        self.assertEqual((header.fields["makam"], header.fields["form"]), ("Hicaz", "Şarkı"))
        header = self.read(centred("BUSELIKSARKI", 100, 60))
        self.assertEqual((header.fields["makam"], header.fields["form"]), ("BUSELIK", "SARKI"))

    def test_possessive_form_stays_whole(self) -> None:
        header = self.read(centred("ISFAHAN PEŞREVİ", 100, 60))
        self.assertEqual((header.fields["makam"], header.fields["form"]), ("ISFAHAN", "PEŞREVİ"))

    def test_makam_a_letter_off_takes_its_spelling(self) -> None:
        header = self.read(centred("MANUR PEŞREV", 100, 60))
        self.assertEqual(header.fields["makam"], self.names.spelling("makam", "mahur", ""))
        self.assertEqual(fold(header.fields["makam"]), "mahur")
        self.assertLess(header.confidence["makam"], 0.95)

    def test_makam_and_form_apart_on_one_row(self) -> None:
        header = self.read(line("HİCAZ", 760, 100, 900, 160), line("ŞARKI", 1000, 100, 1160, 160))
        self.assertEqual((header.fields["makam"], header.fields["form"]), ("HİCAZ", "ŞARKI"))

    def test_makam_a_letter_off_run_together_with_its_form(self) -> None:
        header = self.read(centred("BÍCAZSARKI", 100, 60))
        self.assertEqual((fold(header.fields["makam"]), header.fields["form"]), ("hicaz", "SARKI"))

    def test_dollar_sign_read_for_s_cedilla(self) -> None:
        header = self.read(centred("HICAZ $ARKI", 100, 60))
        self.assertEqual((header.fields["makam"], header.fields["form"]), ("HICAZ", "ŞARKI"))

    def test_region_label(self) -> None:
        header = self.read(centred("Hicaz Türkü", 100, 60), line("Yöre: Bursa", 100, 220, 400, 260))
        self.assertEqual(header.fields["yore"], "Bursa")

    def test_region_label_alone_over_its_value(self) -> None:
        header = self.read(line("DERLEYEN", 100, 100, 300, 140), line("M. SARISÖZEN", 100, 150, 360, 190),
                           line("YÖRESİ", 1400, 100, 1560, 140), line("KIRŞEHİR", 1400, 150, 1600, 190),
                           centred("SUDA BALIK OYNUYOR", 220, 60))
        self.assertEqual(header.fields["yore"], "KIRŞEHİR")
        self.assertEqual(header.fields["eser_adi"], "SUDA BALIK OYNUYOR")
        self.assertNotIn("bestekar", header.fields)  # the collector is not the composer

    def test_unknown_lyricist_is_left_out(self) -> None:
        header = self.read(centred("Rast Şarkı", 100, 60), line("Beste: Dede Efendi", 1400, 180, 1800, 220),
                           line("Güfte: ?", 1400, 230, 1600, 270))
        self.assertEqual(header.fields["bestekar"], "Dede Efendi")
        self.assertNotIn("gufte", header.fields)

    def test_life_dates_leave_the_name(self) -> None:
        header = self.read(centred("Rast Şarkı", 100, 60),
                           line("Beste: Dede Efendi (9/1/1778 - 29/11/1846)", 1300, 180, 1880, 220))
        self.assertEqual(header.fields["bestekar"], "Dede Efendi")

    def test_one_label_for_both_and_its_value_under_it(self) -> None:
        header = self.read(centred("Hicaz Şarkı", 100, 60), line("SÖZ VE MÜZİK:", 1400, 180, 1700, 220),
                           line("NAZİM YAHYA EFENDİ", 1400, 228, 1800, 268))
        self.assertEqual(header.fields["bestekar"], "NAZİM YAHYA EFENDİ")
        self.assertEqual(header.fields["gufte"], "NAZİM YAHYA EFENDİ")

    def test_composer_runs_on_to_the_next_line(self) -> None:
        header = self.read(centred("HİCAZKÂR YÜRÜK SEMÂİ", 100, 80), line("BESTE: HAFIZ ZEKÂİ", 1384, 281, 1739, 334),
                           line("DEDE EFENDİ", 1490, 328, 1734, 372, 0.99))
        self.assertEqual(header.fields["bestekar"], "HAFIZ ZEKÂİ DEDE EFENDİ")

    def test_title_is_the_largest_centred_line_above(self) -> None:
        header = self.read(centred("BU GÖNÜL NE GÜLDE", 40, 70), centred("KÜRDİLİ HİCAZKÂR ŞARKI", 130, 45),
                           line("Usûl: Ağır Aksak", 100, 200, 400, 240))
        self.assertEqual(header.fields["eser_adi"], "BU GÖNÜL NE GÜLDE")
        self.assertEqual(header.fields["makam"], "KÜRDİLİ HİCAZKÂR")

    def test_instrumental_work_is_named_by_its_heading(self) -> None:
        header = self.read(centred("RAST PEŞREV", 100, 70), line("Usûl : Muhammes", 100, 200, 400, 240),
                           line("Beste : Kemâni Tatyos Efendi", 1350, 200, 1850, 240))
        self.assertEqual(header.fields["eser_adi"], "RAST PEŞREV")

    def test_a_number_is_no_title(self) -> None:
        header = self.read(centred("14209", 20, 120, 120), centred("SABA ILAHI", 60, 90),
                           centred("(Git ey akan göz yaşım...)", 160, 90))
        self.assertEqual(header.fields["eser_adi"], "Git ey akan göz yaşım")  # brackets and dots go

    def test_source_lines_stacked_together(self) -> None:
        header = self.read(line("EMİN ONGAN", 230, 60, 430, 95), line("ÜSKÜDAR MÛSİKİ", 200, 100, 460, 135),
                           line("CEMİYETİ NEŞRİYÂTI", 170, 140, 490, 175), centred("EVÇ SAZ SEMÂİSİ", 170, 60),
                           line("Udi Sedat Bey", 1600, 180, 1830, 220))
        self.assertEqual(header.fields["kaynak"], "EMİN ONGAN ÜSKÜDAR MÛSİKİ CEMİYETİ NEŞRİYÂTI")
        self.assertEqual(header.fields["bestekar"], "Udi Sedat Bey")  # unlabelled, on the right

    def test_section_and_tempo_lines_are_no_fields(self) -> None:
        header = self.read(centred("RAST SAZ SEMÂİSİ", 100, 60), line("1. Hane", 150, 260, 300, 300),
                           line("♩ = 96", 120, 200, 260, 240))
        self.assertEqual(set(header.fields), {"makam", "form", "eser_adi"})

    def test_as_dict_gives_every_field_with_its_box(self) -> None:
        header = self.read(centred("Rast Şarkı", 100, 60), line("Beste: Dede Efendi", 1400, 180, 1800, 220))
        out = header.as_dict()
        self.assertEqual(list(out), ["eserAdi", "makam", "form", "usul", "bestekar", "gufte", "yore", "kaynak",
                                     "guven", "kutu"])
        self.assertIsNone(out["usul"])
        self.assertEqual(out["kutu"]["bestekar"], [1400, 180, 1800, 220])
        self.assertTrue(all(0 < v <= 1 for v in out["guven"].values()))


if __name__ == "__main__":
    unittest.main()
