"""Build PowerPoint (.pptx), Word (.docx) and Excel (.xlsx) files from structured content.

Standard library only (zipfile + Office Open XML), so the plugin needs no installs. Agents call it through the
build_file tool. Content shapes (all text may use **bold**):

  pptx  {"subtitle": str, "slides": [{"title": str, "bullets": [str | {"text": str, "level": 0|1}],
                                      "table": {"columns": [str], "rows": [[cell]]}, "note": str}]}
  docx  {"subtitle": str, "sections": [{"heading": str, "level": 1-3, "paragraphs": [str],
                                        "bullets": [str | {"text", "level"}], "table": {...}}]}
  xlsx  {"sheets": [{"name": str, "columns": [str], "rows": [[str | number]]}]}

`sources` (list of citations) becomes a final Sources slide, section or sheet.
"""
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from .store import Invalid

FORMATS = ("pptx", "docx", "xlsx")
NAVY, ACCENT, INK, MUTED, LINE, PALE = "1F3A5F", "2457D6", "1B1F27", "6A7280", "C8CED8", "EEF1F5"
_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

CT = "application/vnd.openxmlformats-officedocument"
R_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


# ---------------------------------------------------------------- shared helpers
def x(s):
    return escape(_BAD.sub("", "" if s is None else str(s)), {'"': "&quot;"})


def segments(text):
    """'a **b** c' -> [('a ', False), ('b', True), (' c', False)]"""
    parts = str(text if text is not None else "").split("**")
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p] or [("", False)]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _types(overrides, defaults=()):
    d = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
         '<Default Extension="xml" ContentType="application/xml"/>'] + list(defaults)
    o = [f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides]
    return (XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + "".join(d + o) + "</Types>")


def _rels(items):
    return (XML + f'<Relationships xmlns="{R_PKG}">' + "".join(
        f'<Relationship Id="{i}" Type="{t}" Target="{x(target)}"/>' for i, t, target in items) + "</Relationships>")


def _root_rels(main):
    return _rels([("rId1", f"{R_OFFICE}/officeDocument", main),
                  ("rId2", f"{R_PKG}/metadata/core-properties", "docProps/core.xml"),
                  ("rId3", f"{R_OFFICE}/extended-properties", "docProps/app.xml")])


def _core(title):
    t = _now()
    return (XML + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
            ' xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{x(title)}</dc:title><dc:creator>Flight Safety Command</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{t}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{t}</dcterms:modified></cp:coreProperties>')


def _app():
    return (XML + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
            ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>Flight Safety Command</Application></Properties>")


def _write(path, parts):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:  # [Content_Types].xml first
            z.writestr(name, data)


def _texts(items, what):
    if items is None:
        return []
    if not isinstance(items, list):
        raise Invalid(f"{what} must be a list")
    out = []
    for it in items:
        if isinstance(it, dict):
            text, level = it.get("text", ""), int(it.get("level", 0) or 0)
        else:
            text, level = it, 0
        text = str(text).strip()
        if text:
            out.append((text, 1 if level > 0 else 0))
    return out


def _table(t, where, max_cols=10, max_rows=200):
    if t is None:
        return None
    if not isinstance(t, dict) or not isinstance(t.get("columns"), list) or not t["columns"]:
        raise Invalid(f"{where}: table needs columns (a list of headers) and rows (a list of lists)")
    cols = [str(c) for c in t["columns"]]
    rows = t.get("rows") or []
    if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
        raise Invalid(f"{where}: table rows must be a list of lists")
    if len(cols) > max_cols:
        raise Invalid(f"{where}: at most {max_cols} table columns")
    if len(rows) > max_rows:
        raise Invalid(f"{where}: at most {max_rows} table rows; split it")
    rows = [[("" if c is None else c) for c in (r + [""] * len(cols))[:len(cols)]] for r in rows]
    return cols, rows


def _sources(sources):
    return [str(s).strip() for s in (sources or []) if str(s).strip()]


# ---------------------------------------------------------------- PowerPoint
EMU = 914400  # per inch
W, H = 12192000, 6858000  # 16:9


def _emu(inches):
    return int(inches * EMU)


def _p_runs(text, size, color=INK, bold=False):
    out = []
    for seg, b in segments(text):
        battr = ' b="1"' if (bold or b) else ""
        out.append(f'<a:r><a:rPr lang="en-US" sz="{size}"{battr} dirty="0"><a:solidFill><a:srgbClr val="{color}"/>'
                   f'</a:solidFill><a:latin typeface="Calibri"/></a:rPr><a:t>{x(seg)}</a:t></a:r>')
    return "".join(out)


def _sp_text(sid, name, xin, yin, win, hin, paras, anchor="t"):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{x(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{_emu(xin)}" y="{_emu(yin)}"/><a:ext cx="{_emu(win)}" cy="{_emu(hin)}"/>'
            '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:normAutofit/>'
            f"</a:bodyPr><a:lstStyle/>{''.join(paras)}</p:txBody></p:sp>")


def _sp_rect(sid, name, xin, yin, win, hin, fill):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{x(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{_emu(xin)}" y="{_emu(yin)}"/><a:ext cx="{_emu(win)}" cy="{_emu(hin)}"/>'
            f'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{fill}"/>'
            "</a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>")


def _para(text, size, color=INK, bold=False, align=None):
    algn = f' algn="{align}"' if align else ""
    return f"<a:p><a:pPr{algn}/>{_p_runs(text, size, color, bold)}</a:p>"


def _bullet(text, level, size):
    mar, ind, char = (342900, -342900, "•") if level == 0 else (742950, -285750, "–")
    sz = size if level == 0 else max(size - 200, 1200)
    return (f'<a:p><a:pPr marL="{mar}" indent="{ind}" lvl="{level}"><a:spcBef><a:spcPts val="900"/></a:spcBef>'
            f'<a:buFont typeface="Arial"/><a:buChar char="{char}"/></a:pPr>{_p_runs(text, sz)}</a:p>')


def _bullet_size(bullets, compact):
    n = sum(len(t) for t, _ in bullets) + 40 * len(bullets)
    size = 2000 if n < 300 else 1800 if n < 480 else 1600 if n < 700 else 1400
    return min(size, 1600) if compact else size


def _text_height(bullets, size):
    """Rough height in inches of a bullet list in the 12.1in body box (to place a table right below it)."""
    pt = size / 100
    chars_per_line = int(12.1 * 72 / (pt * 0.5))
    lines = sum(max(1, -(-len(t) // chars_per_line)) for t, _ in bullets)
    return lines * pt * 1.25 / 72 + len(bullets) * 9 / 72 + 0.1


def _ln(side):
    return (f'<a:{side} w="6350"><a:solidFill><a:srgbClr val="{LINE}"/></a:solidFill></a:{side}>')


def _gf_table(sid, xin, yin, win, cols, rows):
    n = len(cols)
    colw = _emu(win) // n
    size = 1400 if len(rows) <= 8 else 1200 if len(rows) <= 14 else 1000
    rowh = _emu(0.36 if size >= 1400 else 0.3)

    def cell(text, head, band):
        fill = NAVY if head else (PALE if band else "FFFFFF")
        color = "FFFFFF" if head else INK
        return (f"<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p>{_p_runs(text, size, color, head)}</a:p></a:txBody>"
                f'<a:tcPr marL="91440" marR="91440" marT="45720" marB="45720">{_ln("lnL")}{_ln("lnR")}{_ln("lnT")}'
                f'{_ln("lnB")}<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill></a:tcPr></a:tc>')
    trs = [f'<a:tr h="{rowh}">' + "".join(cell(c, True, False) for c in cols) + "</a:tr>"]
    for i, r in enumerate(rows):
        trs.append(f'<a:tr h="{rowh}">' + "".join(cell(c, False, i % 2 == 1) for c in r) + "</a:tr>")
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{sid}" name="Table"/><p:cNvGraphicFramePr>'
            '<a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{_emu(xin)}" y="{_emu(yin)}"/><a:ext cx="{colw * n}" cy="{rowh * (len(rows) + 1)}"/>'
            '</p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
            '<a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>' + "".join(f'<a:gridCol w="{colw}"/>' for _ in cols)
            + "</a:tblGrid>" + "".join(trs) + "</a:tbl></a:graphicData></a:graphic></p:graphicFrame>")


def _slide(shapes):
    return (XML + f'<p:sld xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>'
            '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>'
            "</p:grpSpPr>" + "".join(shapes) + "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>")


def _title_slide(title, subtitle):
    date = datetime.now().strftime("%d %b %Y")
    paras_t = [_para(title, 4000, "FFFFFF", True)]
    paras_s = [_para(subtitle, 2000, "C8D3E6")] if subtitle else [_para("", 2000, "C8D3E6")]
    return _slide([
        _sp_rect(2, "Background", 0, 0, 13.333, 7.5, NAVY),
        _sp_rect(3, "Accent", 0.8, 4.0, 1.4, 0.07, ACCENT),
        _sp_text(4, "Title", 0.8, 1.6, 11.7, 2.25, paras_t, "b"),
        _sp_text(5, "Subtitle", 0.8, 4.25, 11.7, 1.2, paras_s, "t"),
        _sp_text(6, "Footer", 0.8, 6.65, 11.7, 0.4, [_para(f"Flight Safety Command · {date}", 1200, "C8D3E6")]),
    ])


def _content_slide(num, s):
    shapes = [_sp_rect(2, "Top bar", 0, 0, 13.333, 0.12, NAVY),
              _sp_text(3, "Title", 0.6, 0.4, 12.1, 0.95, [_para(s["title"], 2800, NAVY, True)], "b"),
              _sp_rect(4, "Accent", 0.6, 1.45, 1.1, 0.06, ACCENT)]
    bullets, table = s["bullets"], s["table"]
    table_y = 1.75
    if bullets:
        size = _bullet_size(bullets, bool(table))
        h = min(_text_height(bullets, size), 1.95) if table else 4.95
        shapes.append(_sp_text(5, "Body", 0.6, 1.7, 12.1, h, [_bullet(t, lv, size) for t, lv in bullets]))
        table_y = 1.7 + h + 0.25
    if table:
        cols, rows = table
        shapes.append(_gf_table(6, 0.6, table_y, 12.1, cols, rows))
    if s["note"]:
        shapes.append(_sp_text(7, "Note", 0.6, 6.85, 10.8, 0.4, [_para(s["note"], 1100, MUTED)], "b"))
    shapes.append(_sp_text(8, "Slide number", 11.9, 6.85, 0.8, 0.4, [_para(str(num), 1100, MUTED, align="r")], "b"))
    return _slide(shapes)


def _pptx_master():
    tree = ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>'
            '<a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
            "</a:xfrm></p:grpSpPr></p:spTree>")
    master = (XML + f'<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}"><p:cSld><p:bg><p:bgRef '
              f'idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>{tree}</p:cSld>'
              '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3"'
              ' accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
              '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
              '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="3200"/></a:lvl1pPr></p:titleStyle><p:bodyStyle>'
              '<a:lvl1pPr><a:defRPr sz="2000"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr/>'
              "</a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>")
    layout = (XML + f'<p:sldLayout xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}" type="blank" preserve="1">'
              f'<p:cSld name="Blank">{tree}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    accents = [ACCENT, "1A8A4A", "B7791F", "C53030", "6B46C1", "0F766E"]
    fill3 = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    theme = (XML + f'<a:theme xmlns:a="{NS_A}" name="Flight Safety"><a:themeElements>'
             f'<a:clrScheme name="Flight Safety"><a:dk1><a:srgbClr val="{INK}"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/>'
             f'</a:lt1><a:dk2><a:srgbClr val="{NAVY}"/></a:dk2><a:lt2><a:srgbClr val="{PALE}"/></a:lt2>'
             + "".join(f'<a:accent{i}><a:srgbClr val="{c}"/></a:accent{i}>' for i, c in enumerate(accents, 1))
             + f'<a:hlink><a:srgbClr val="{ACCENT}"/></a:hlink><a:folHlink><a:srgbClr val="{MUTED}"/></a:folHlink>'
             '</a:clrScheme><a:fontScheme name="Flight Safety"><a:majorFont><a:latin typeface="Calibri"/>'
             '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/>'
             '<a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Flight Safety">'
             f"<a:fillStyleLst>{fill3}</a:fillStyleLst><a:lnStyleLst>"
             + "".join(f'<a:ln w="{w}"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
                       for w in (6350, 12700, 19050))
             + "</a:lnStyleLst><a:effectStyleLst>" + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3
             + f"</a:effectStyleLst><a:bgFillStyleLst>{fill3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements>"
             "<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>")
    return master, layout, theme


def build_pptx(path, title, content, sources=None):
    slides_in = content.get("slides")
    if not isinstance(slides_in, list) or not slides_in:
        raise Invalid("pptx content needs slides: [{title, bullets?, table?, note?}]")
    if len(slides_in) > 60:
        raise Invalid("At most 60 slides")
    slides = []
    for i, s in enumerate(slides_in, 1):
        if not isinstance(s, dict) or not str(s.get("title", "")).strip():
            raise Invalid(f"Slide {i} needs a title")
        bullets = _texts(s.get("bullets"), f"Slide {i} bullets")
        if len(bullets) > 12:
            raise Invalid(f"Slide {i} has {len(bullets)} bullets; keep it to 12 or fewer (split the slide)")
        table = _table(s.get("table"), f"Slide {i}", max_cols=8, max_rows=15)
        slides.append({"title": str(s["title"]).strip(), "bullets": bullets, "table": table,
                       "note": str(s.get("note") or "").strip()})
    src = _sources(sources)
    if src:
        for k in range(0, len(src), 10):
            slides.append({"title": "Sources" if k == 0 else "Sources (continued)", "table": None, "note": "",
                           "bullets": [(t, 0) for t in src[k:k + 10]]})
    xml_slides = [_title_slide(title, content.get("subtitle"))]
    xml_slides += [_content_slide(n, s) for n, s in enumerate(slides, 2)]
    master, layout, theme = _pptx_master()
    n = len(xml_slides)
    overrides = [("/ppt/presentation.xml", f"{CT}.presentationml.presentation.main+xml"),
                 ("/ppt/slideMasters/slideMaster1.xml", f"{CT}.presentationml.slideMaster+xml"),
                 ("/ppt/slideLayouts/slideLayout1.xml", f"{CT}.presentationml.slideLayout+xml"),
                 ("/ppt/theme/theme1.xml", f"{CT}.theme+xml"),
                 ("/ppt/presProps.xml", f"{CT}.presentationml.presProps+xml"),
                 ("/ppt/viewProps.xml", f"{CT}.presentationml.viewProps+xml"),
                 ("/ppt/tableStyles.xml", f"{CT}.presentationml.tableStyles+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml", f"{CT}.extended-properties+xml")]
    overrides += [(f"/ppt/slides/slide{i}.xml", f"{CT}.presentationml.slide+xml") for i in range(1, n + 1)]
    pres_rels = [("rId1", f"{R_OFFICE}/slideMaster", "slideMasters/slideMaster1.xml")]
    pres_rels += [(f"rId{i + 1}", f"{R_OFFICE}/slide", f"slides/slide{i}.xml") for i in range(1, n + 1)]
    pres_rels += [(f"rId{n + 2}", f"{R_OFFICE}/theme", "theme/theme1.xml"),
                  (f"rId{n + 3}", f"{R_OFFICE}/presProps", "presProps.xml"),
                  (f"rId{n + 4}", f"{R_OFFICE}/viewProps", "viewProps.xml"),
                  (f"rId{n + 5}", f"{R_OFFICE}/tableStyles", "tableStyles.xml")]
    presentation = (XML + f'<p:presentation xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}" saveSubsetFonts="1">'
                    '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
                    + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
                    + f'</p:sldIdLst><p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    parts = [("[Content_Types].xml", _types(overrides)), ("_rels/.rels", _root_rels("ppt/presentation.xml")),
             ("docProps/core.xml", _core(title)), ("docProps/app.xml", _app()),
             ("ppt/presentation.xml", presentation), ("ppt/_rels/presentation.xml.rels", _rels(pres_rels)),
             ("ppt/slideMasters/slideMaster1.xml", master),
             ("ppt/slideMasters/_rels/slideMaster1.xml.rels",
              _rels([("rId1", f"{R_OFFICE}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                     ("rId2", f"{R_OFFICE}/theme", "../theme/theme1.xml")])),
             ("ppt/slideLayouts/slideLayout1.xml", layout),
             ("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
              _rels([("rId1", f"{R_OFFICE}/slideMaster", "../slideMasters/slideMaster1.xml")])),
             ("ppt/theme/theme1.xml", theme),
             ("ppt/presProps.xml", XML + f'<p:presentationPr xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}"/>'),
             ("ppt/viewProps.xml", XML + f'<p:viewPr xmlns:a="{NS_A}" xmlns:r="{R_OFFICE}" xmlns:p="{NS_P}"/>'),
             ("ppt/tableStyles.xml", XML + f'<a:tblStyleLst xmlns:a="{NS_A}" def="{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}"/>')]
    for i, sx in enumerate(xml_slides, 1):
        parts.append((f"ppt/slides/slide{i}.xml", sx))
        parts.append((f"ppt/slides/_rels/slide{i}.xml.rels",
                      _rels([("rId1", f"{R_OFFICE}/slideLayout", "../slideLayouts/slideLayout1.xml")])))
    _write(path, parts)
    return {"slides": n}


# ---------------------------------------------------------------- Word
def _w_runs(text, bold=False, color=None):
    out = []
    for seg, b in segments(text):
        rpr = ("<w:b/>" if (bold or b) else "") + (f'<w:color w:val="{color}"/>' if color else "")
        out.append(f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}<w:t xml:space="preserve">{x(seg)}</w:t></w:r>')
    return "".join(out)


def _w_p(text, style=None, num_level=None):
    ppr = ""
    if style or num_level is not None:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        if num_level is not None:
            ppr += f'<w:numPr><w:ilvl w:val="{num_level}"/><w:numId w:val="1"/></w:numPr>'
        ppr += "</w:pPr>"
    return f"<w:p>{ppr}{_w_runs(text)}</w:p>"


def _w_table(cols, rows):
    total = 9026  # A4 text width in twips with 1" margins
    cw = total // len(cols)

    def tc(text, head, band):
        fill = NAVY if head else (PALE if band else None)
        shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="{cw}" w:type="dxa"/>{shd}</w:tcPr>'
                f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/></w:pPr>'
                f'{_w_runs(text, head, "FFFFFF" if head else None)}</w:p></w:tc>')
    trs = ['<w:tr><w:trPr><w:tblHeader/></w:trPr>' + "".join(tc(c, True, False) for c in cols) + "</w:tr>"]
    trs += ["<w:tr>" + "".join(tc(c, False, i % 2 == 1) for c in r) + "</w:tr>" for i, r in enumerate(rows)]
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
            '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0"'
            ' w:noVBand="1"/></w:tblPr><w:tblGrid>' + "".join(f'<w:gridCol w:w="{cw}"/>' for _ in cols)
            + "</w:tblGrid>" + "".join(trs) + "</w:tbl><w:p/>")


DOCX_STYLES = (XML + f'<w:styles xmlns:w="{NS_W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri"'
               ' w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/>'
               '<w:lang w:val="en-GB"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120"'
               ' w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
               '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
               '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
               '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="80"/></w:pPr><w:rPr><w:b/>'
               f'<w:color w:val="{NAVY}"/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>'
               '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/>'
               '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr>'
               f'<w:color w:val="{MUTED}"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>'
               + "".join(
                   f'<w:style w:type="paragraph" w:styleId="Heading{lv}"><w:name w:val="heading {lv}"/>'
                   f'<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>'
                   f'<w:pPr><w:keepNext/><w:spacing w:before="{sb}" w:after="80"/><w:outlineLvl w:val="{lv - 1}"/></w:pPr>'
                   f'<w:rPr><w:b/><w:color w:val="{NAVY}"/><w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr></w:style>'
                   for lv, sz, sb in ((1, 32, 360), (2, 26, 240), (3, 23, 200)))
               + '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/>'
               '<w:basedOn w:val="Normal"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:after="60"/>'
               '</w:pPr></w:style><w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal'
               ' Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left'
               ' w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>'
               '</w:tblCellMar></w:tblPr></w:style><w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table'
               ' Grid"/><w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders>'
               + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="{LINE}"/>'
                         for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
               + "</w:tblBorders></w:tblPr></w:style></w:styles>")

DOCX_NUMBERING = (XML + f'<w:numbering xmlns:w="{NS_W}"><w:abstractNum w:abstractNumId="0">'
                  '<w:multiLevelType w:val="hybridMultilevel"/>'
                  + "".join(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
                            f'<w:lvlText w:val="{ch}"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720 * (i + 1)}"'
                            ' w:hanging="360"/></w:pPr></w:lvl>' for i, ch in ((0, "•"), (1, "–")))
                  + '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')


def build_docx(path, title, content, sources=None):
    sections = content.get("sections")
    if not isinstance(sections, list) or not sections:
        raise Invalid("docx content needs sections: [{heading, level?, paragraphs?, bullets?, table?}]")
    if len(sections) > 200:
        raise Invalid("At most 200 sections")
    body = [_w_p(title, "Title")]
    if content.get("subtitle"):
        body.append(_w_p(content["subtitle"], "Subtitle"))
    for i, s in enumerate(sections, 1):
        if not isinstance(s, dict):
            raise Invalid(f"Section {i} must be an object")
        if str(s.get("heading", "")).strip():
            lv = min(max(int(s.get("level", 1) or 1), 1), 3)
            body.append(_w_p(str(s["heading"]).strip(), f"Heading{lv}"))
        paras = s.get("paragraphs") or []
        if isinstance(paras, str):
            paras = [paras]
        for p in paras:
            if str(p).strip():
                body.append(_w_p(str(p).strip()))
        for text, lv in _texts(s.get("bullets"), f"Section {i} bullets"):
            body.append(_w_p(text, "ListBullet", lv))
        t = _table(s.get("table"), f"Section {i}")
        if t:
            body.append(_w_table(*t))
    src = _sources(sources)
    if src:
        body.append(_w_p("Sources", "Heading1"))
        body += [_w_p(t, "ListBullet", 0) for t in src]
    doc = (XML + f'<w:document xmlns:w="{NS_W}" xmlns:r="{R_OFFICE}"><w:body>' + "".join(body)
           + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440"'
           ' w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    overrides = [("/word/document.xml", f"{CT}.wordprocessingml.document.main+xml"),
                 ("/word/styles.xml", f"{CT}.wordprocessingml.styles+xml"),
                 ("/word/numbering.xml", f"{CT}.wordprocessingml.numbering+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml", f"{CT}.extended-properties+xml")]
    _write(path, [("[Content_Types].xml", _types(overrides)), ("_rels/.rels", _root_rels("word/document.xml")),
                  ("docProps/core.xml", _core(title)), ("docProps/app.xml", _app()),
                  ("word/document.xml", doc), ("word/styles.xml", DOCX_STYLES), ("word/numbering.xml", DOCX_NUMBERING),
                  ("word/_rels/document.xml.rels",
                   _rels([("rId1", f"{R_OFFICE}/styles", "styles.xml"),
                          ("rId2", f"{R_OFFICE}/numbering", "numbering.xml")]))])
    return {"sections": len(sections)}


# ---------------------------------------------------------------- Excel
def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_name(name, used):
    n = re.sub(r"[\[\]:*?/\\]", " ", str(name or "Sheet")).strip().strip("'")[:31] or "Sheet"
    base, k = n, 2
    while n.lower() in used:
        suffix = f" ({k})"
        n = base[:31 - len(suffix)] + suffix
        k += 1
    used.add(n.lower())
    return n


def _cell(ref, v, style):
    if isinstance(v, bool):
        v = "Yes" if v else "No"
    if isinstance(v, (int, float)) and v == v and abs(v) != float("inf"):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{x(v)}</t></is></c>'


def _sheet_xml(cols, rows):
    widths = [min(max(len(str(c)) + 2, 10), 60) for c in cols]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = min(max(widths[i], len(str(v)) + 2), 60)
    out = ['<row r="1">' + "".join(_cell(f"{_col(i + 1)}1", c, 1) for i, c in enumerate(cols)) + "</row>"]
    for n, r in enumerate(rows, 2):
        out.append(f'<row r="{n}">' + "".join(_cell(f"{_col(i + 1)}{n}", v, 2) for i, v in enumerate(r)) + "</row>")
    return (XML + f'<worksheet xmlns="{NS_X}" xmlns:r="{R_OFFICE}"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><cols>'
            + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
            + "</cols><sheetData>" + "".join(out) + "</sheetData>"
            '<pageMargins left="0.5" right="0.5" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
            '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')


XLSX_STYLES = (XML + f'<styleSheet xmlns="{NS_X}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/>'
               '<family val="2"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/>'
               '<family val="2"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill>'
               f'<patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF{NAVY}"/>'
               '<bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/>'
               '<bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0"'
               ' borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"'
               ' xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
               '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment'
               ' vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0"'
               ' builtinId="0"/></cellStyles></styleSheet>')


def build_xlsx(path, title, content, sources=None):
    sheets_in = content.get("sheets")
    if not isinstance(sheets_in, list) or not sheets_in:
        raise Invalid("xlsx content needs sheets: [{name, columns, rows}]")
    if len(sheets_in) > 30:
        raise Invalid("At most 30 sheets")
    used, sheets = set(), []
    for i, s in enumerate(sheets_in, 1):
        if not isinstance(s, dict):
            raise Invalid(f"Sheet {i} must be an object")
        cols, rows = _table({"columns": s.get("columns"), "rows": s.get("rows")}, f"Sheet {i}",
                            max_cols=50, max_rows=20000)
        sheets.append((_sheet_name(s.get("name") or f"Sheet {i}", used), cols, rows))
    src = _sources(sources)
    if src:
        sheets.append((_sheet_name("Sources", used), ["Source"], [[t] for t in src]))
    n = len(sheets)
    overrides = [("/xl/workbook.xml", f"{CT}.spreadsheetml.sheet.main+xml"),
                 ("/xl/styles.xml", f"{CT}.spreadsheetml.styles+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml", f"{CT}.extended-properties+xml")]
    overrides += [(f"/xl/worksheets/sheet{i}.xml", f"{CT}.spreadsheetml.worksheet+xml") for i in range(1, n + 1)]
    wb = (XML + f'<workbook xmlns="{NS_X}" xmlns:r="{R_OFFICE}"><bookViews><workbookView/></bookViews><sheets>'
          + "".join(f'<sheet name="{x(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(sheets, 1))
          + "</sheets></workbook>")
    rels = [(f"rId{i}", f"{R_OFFICE}/worksheet", f"worksheets/sheet{i}.xml") for i in range(1, n + 1)]
    rels.append((f"rId{n + 1}", f"{R_OFFICE}/styles", "styles.xml"))
    parts = [("[Content_Types].xml", _types(overrides)), ("_rels/.rels", _root_rels("xl/workbook.xml")),
             ("docProps/core.xml", _core(title)), ("docProps/app.xml", _app()),
             ("xl/workbook.xml", wb), ("xl/_rels/workbook.xml.rels", _rels(rels)), ("xl/styles.xml", XLSX_STYLES)]
    parts += [(f"xl/worksheets/sheet{i}.xml", _sheet_xml(c, r)) for i, (_, c, r) in enumerate(sheets, 1)]
    _write(path, parts)
    return {"sheets": [name for name, _, _ in sheets]}


BUILDERS = {"pptx": build_pptx, "docx": build_docx, "xlsx": build_xlsx}


def build(path, fmt, title, content, sources=None):
    if fmt not in BUILDERS:
        raise Invalid(f"format must be one of {', '.join(FORMATS)}")
    if not str(title or "").strip():
        raise Invalid("The file needs a title")
    if not isinstance(content, dict):
        raise Invalid("content must be an object (see the build_file tool description)")
    return BUILDERS[fmt](path, str(title).strip(), content, sources)
