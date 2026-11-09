# Fonts

The launcher uses three open fonts. Each keeps its own licence, in this folder.

| File | Family | Made from | Licence |
|---|---|---|---|
| `DMTQWide-ExtraBold.ttf`, `DMTQWide-ExtraBoldItalic.ttf` | DMTQ Wide | The site's DMTQ Wide (`server/portal/fonts`), a cut of [Saira](https://github.com/Omnibus-Type/Saira) at its widest, Latin only, as TrueType | [Saira-OFL.txt](Saira-OFL.txt) |
| `Pretendard-*.ttf` | Pretendard | [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9, unchanged | [Pretendard-OFL.txt](Pretendard-OFL.txt) |
| `MaterialIcons-Regular.ttf` | Material Icons | [Material Icons](https://github.com/google/material-design-icons), unchanged | [MaterialIcons-LICENSE.txt](MaterialIcons-LICENSE.txt) |

DMTQ Wide is a modified version of Saira, so it carries a name of its own as the SIL Open Font License asks; it is under
the same licence. `client/packaging/fonts.py` makes the TrueType files again from the site's.
