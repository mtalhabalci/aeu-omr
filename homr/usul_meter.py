"""The bar a long usul is written in.

Atkoşar prints "28/4 (4/4)": the usul's cycle, and in parentheses the bar its cycle is divided into by dashed lines,
a solid line ending the cycle. The model reads the usul alone; the bar shows in the measures. Written as measures of
28/4 they would fit the time signature, but a 28/4 measure cannot break across systems (Verovio, on a phone). So the
page's bars are kept, and the bar is written as MusicXML 4.0's interchangeable time signature, in parentheses:

    <time><beats>28</beats><beat-type>4</beat-type>
      <interchangeable><time-relation>parentheses</time-relation><beats>4</beats><beat-type>4</beat-type></interchangeable>
    </time>

A section (the measures from one <time> to the next) gets one when most of its measures share one length and that
length divides the usul exactly: more than half of them and at least two, as homr.transformer.vocabulary
fix_measure_sums agrees a length. Not every measure: on handwriting a misread duration or an upbeat leaves a few
measures off, and they are what a reader should look at, not every measure of the work. A section whose measures
agree on no such length keeps its time signature as read.
"""

import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction

import musicxml.xmlelement.xmlelement as mxl

MAX_BEAT_TYPE = 64


def _int(text: str | None) -> int | None:
    return int(text) if text is not None and text.strip().isdigit() else None


def meter_of(time: ET.Element) -> Fraction | None:
    """A <time>'s length as a fraction of a whole note; None for a composite (3+2) or a senza-misura."""
    beats, beat_type = _int(time.findtext("beats")), _int(time.findtext("beat-type"))
    return Fraction(beats, beat_type) if beats and beat_type else None


def bar_of(time: ET.Element) -> Fraction | None:
    """The length of the interchangeable time signature a <time> carries, or None."""
    other = time.find("interchangeable")
    return meter_of(other) if other is not None else None


def measure_length(measure: ET.Element, divisions: int) -> Fraction:
    """The notes and rests of a measure as a fraction of a whole note: the longest of its voices."""
    voices: Counter = Counter()
    for note in measure.findall("note"):
        if note.find("chord") is None and note.find("grace") is None:
            voices[(note.findtext("staff") or "1", note.findtext("voice") or "1")] += int(note.findtext("duration") or 0)
    return Fraction(max(voices.values(), default=0), divisions * 4)


def _bar(length: Fraction, beat_type: int) -> tuple[int, int] | None:
    """length as beats of the usul's beat type, or of a finer one where it needs it (2 quarters under 32/8: 4/8)."""
    while beat_type <= MAX_BEAT_TYPE:
        beats = length * beat_type
        if beats.denominator == 1:
            return int(beats), beat_type
        beat_type *= 2
    return None


def section_bars(part: ET.Element) -> dict[int, tuple[int, int]]:
    """For each measure (index in the part) holding a <time>, the bar its section is divided into, where there is one.
    """
    measures = part.findall("measure")
    divisions = 1
    sections: list[tuple[int, Fraction, int, list[Fraction]]] = []  # (measure index, usul, beat type, lengths)
    for index, measure in enumerate(measures):
        for attributes in measure.findall("attributes"):
            divisions = _int(attributes.findtext("divisions")) or divisions
            time = attributes.find("time")
            if time is not None:
                meter = meter_of(time)
                sections.append((index, meter, _int(time.findtext("beat-type")) or 0, []) if meter else
                                (index, Fraction(0), 0, []))
        if not sections or measure.find("attributes/measure-style/multiple-rest") is not None:
            continue
        length = measure_length(measure, divisions)
        if length:
            sections[-1][3].append(length)
    bars = {}
    for index, meter, beat_type, lengths in sections:
        if not meter or len(lengths) < 2:
            continue
        common, count = Counter(lengths).most_common(1)[0]
        if count < 2 or 2 * count <= len(lengths) or common >= meter or (meter / common).denominator != 1:
            continue
        bar = _bar(common, beat_type)
        if bar is not None:
            bars[index] = bar
    return bars


def _interchangeable_element(bar: tuple[int, int]) -> ET.Element:
    other = ET.Element("interchangeable")
    ET.SubElement(other, "time-relation").text = "parentheses"
    ET.SubElement(other, "beats").text = str(bar[0])
    ET.SubElement(other, "beat-type").text = str(bar[1])
    return other


def mark_bars(part: ET.Element) -> None:
    """Write the bar of each section into its time signatures, on a part built as an ElementTree."""
    measures = part.findall("measure")
    for index, bar in section_bars(part).items():
        for time in measures[index].findall("attributes/time"):
            if time.find("interchangeable") is None and time.find("senza-misura") is None:
                time.append(_interchangeable_element(bar))


def mark_bars_mxl(part: mxl.XMLPart) -> None:
    """The same on a part built with the musicxml library, which generate_xml writes."""
    bars = section_bars(ET.fromstring(part.to_string()))
    if not bars:
        return
    measures = part.get_children_of_type(mxl.XMLMeasure)
    for index, (beats, beat_type) in bars.items():
        for attributes in measures[index].get_children_of_type(mxl.XMLAttributes):
            for time in attributes.get_children_of_type(mxl.XMLTime):
                if time.get_children_of_type(mxl.XMLInterchangeable):
                    continue
                other = mxl.XMLInterchangeable()
                other.add_child(mxl.XMLTimeRelation(value_="parentheses"))
                other.add_child(mxl.XMLBeats(value_=str(beats)))
                other.add_child(mxl.XMLBeatType(value_=str(beat_type)))
                time.add_child(other)
