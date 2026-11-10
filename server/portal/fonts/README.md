# Fonts

The site's fonts are cut down from two open fonts, both under the SIL Open Font License 1.1. A cut-down font is a
modified version, and both licenses reserve the original name, so each file here has a name of its own.

| Here | Made from | License |
|---|---|---|
| `dmtq-condensed-*.woff2` (DMTQ Condensed) | [Saira](https://github.com/Omnibus-Type/Saira) at its narrow width, Latin | [OFL-Saira.txt](OFL-Saira.txt) |
| `dmtq-wide-*.woff2` (DMTQ Wide) | Saira at its widest (`wdth` 125), Latin | [OFL-Saira.txt](OFL-Saira.txt) |
| `dmtq-text-2-latin.woff2`, `dmtq-text-2-hangul.woff2` (DMTQ Text) | [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9, variable, KS X 1001 syllables, Latin and punctuation, in two files by script: Latin and punctuation; Hangul syllables and jamo with CJK punctuation | [OFL-Pretendard.txt](OFL-Pretendard.txt) |

These modified versions are under the same license as the fonts they come from.

The text face's two files are one font cut in two with fontTools (`pyftsubset` with every layout feature and every name
kept), each with the characters it has as its `unicode-range` in `../style.css`: a page without Korean on it loads the
first alone.

Browsers keep these files for a year without asking again (`server/apache/site.conf`): a font that changes takes a new
name, as the text face's number went up when it was cut in two.
