"""Excel 筛选表导出、读取与校验。"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable, List
from xml.etree import ElementTree as ET

from .models import Article

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_HEADERS = [
    "是否导入",
    "编号",
    "题名",
    "作者",
    "期刊",
    "年",
    "卷",
    "期",
    "栏目",
    "页码",
    "有摘要",
    "有PDF",
    "摘要",
    "文章链接",
    "PDF链接",
    "备注",
]


class SpreadsheetValidationError(ValueError):
    """筛选表与当前 pending 数据不一致或格式不可读取。"""


def pendingFingerprint(articles: List[Article], pendingMeta: dict) -> str:
    payload = {
        "capturedAt": pendingMeta.get("capturedAt", ""),
        "captureType": pendingMeta.get("captureType", ""),
        "note": pendingMeta.get("note", ""),
        "articles": [
            {
                "index": getattr(article, "_globalIndex", i),
                "title": article.title,
                "key": article.articleKey(),
                "journal": article.journal,
                "year": article.year,
                "volume": article.volume,
                "issue": article.issue,
                "articleUrl": article.articleUrl,
            }
            for i, article in enumerate(articles, 1)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def exportReviewSpreadsheet(
    path: Path | str,
    articles: List[Article],
    pendingMeta: dict,
    selectedIndexes: Iterable[int] | None = None,
) -> Path:
    """导出待筛文章为 Excel 文件，用户在“是否导入”列填“是”后再导入。"""
    outputPath = Path(path)
    outputPath.parent.mkdir(parents=True, exist_ok=True)
    selected = set(selectedIndexes or [])
    fingerprint = pendingFingerprint(articles, pendingMeta)
    metadata = [
        ("capturedAt", pendingMeta.get("capturedAt", "")),
        ("captureType", pendingMeta.get("captureType", "")),
        ("note", pendingMeta.get("note", "")),
        ("articleCount", str(len(articles))),
        ("pendingFingerprint", fingerprint),
    ]

    rows = [_HEADERS]
    hyperlinks: list[tuple[str, str, str]] = []
    for rowIndex, article in enumerate(articles, 2):
        index = getattr(article, "_globalIndex", rowIndex - 1) or rowIndex - 1
        articleCell = f"N{rowIndex}"
        pdfCell = f"O{rowIndex}"
        if article.articleUrl:
            hyperlinks.append((articleCell, f"rId{len(hyperlinks) + 1}", article.articleUrl))
        if article.pdfUrl:
            hyperlinks.append((pdfCell, f"rId{len(hyperlinks) + 1}", article.pdfUrl))
        rows.append([
            "是" if index in selected else "",
            str(index),
            article.title,
            "; ".join(article.authors or []),
            article.journal,
            str(article.year or ""),
            str(article.volume or ""),
            str(article.issue or ""),
            article.section or "",
            article.pagesStr(),
            "是" if article.abstract else "否",
            "是" if article.pdfUrl else "否",
            article.abstract or "",
            "文章页" if article.articleUrl else "",
            "PDF" if article.pdfUrl else "",
            "",
        ])

    instructions = [
        ["说明", "在“筛选”页的“是否导入”列选择“是”的文章会被导入 Zotero。"],
        ["注意", "不要修改编号和题名；导入时会校验表格是否对应当前 pending.json。"],
        ["导入命令", "dhgleaner import --spreadsheet data/review_selection.xlsx"],
    ]
    metaRows = [["字段", "值"], *metadata]

    with zipfile.ZipFile(outputPath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _writeXlsxParts(zf, rows, instructions, metaRows, hyperlinks)
    return outputPath


def loadSpreadsheetSelection(path: Path | str, articles: List[Article], pendingMeta: dict) -> List[Article]:
    workbookPath = Path(path)
    if not workbookPath.exists():
        raise SpreadsheetValidationError(f"筛选表不存在: {workbookPath}")

    rowsBySheet = _readWorkbookRows(workbookPath)
    metaRows = rowsBySheet.get("元数据") or []
    storedFingerprint = _metadataValue(metaRows, "pendingFingerprint")
    currentFingerprint = pendingFingerprint(articles, pendingMeta)
    if not storedFingerprint:
        raise SpreadsheetValidationError("筛选表缺少 pendingFingerprint，请重新导出。")
    if storedFingerprint != currentFingerprint:
        raise SpreadsheetValidationError("筛选表对应的 pending.json 已变化，请重新导出后再筛选。")

    rows = rowsBySheet.get("筛选") or []
    if not rows:
        raise SpreadsheetValidationError("筛选表缺少“筛选”工作表。")
    header = rows[0]
    try:
        flagCol = header.index("是否导入")
        indexCol = header.index("编号")
        titleCol = header.index("题名")
    except ValueError as e:
        raise SpreadsheetValidationError("筛选表缺少必要列：是否导入、编号、题名。") from e

    byIndex = {int(getattr(article, "_globalIndex", i) or i): article for i, article in enumerate(articles, 1)}
    selectedIndexes: list[int] = []
    seen = set()
    for rowNumber, row in enumerate(rows[1:], 2):
        flag = _cell(row, flagCol).strip()
        if not _isSelected(flag):
            continue
        rawIndex = _cell(row, indexCol).strip()
        try:
            index = int(float(rawIndex))
        except ValueError as e:
            raise SpreadsheetValidationError(f"第 {rowNumber} 行编号不是数字: {rawIndex}") from e
        article = byIndex.get(index)
        if not article:
            raise SpreadsheetValidationError(f"第 {rowNumber} 行编号不存在于当前 pending: {index}")
        title = _cell(row, titleCol).strip()
        if title != article.title:
            raise SpreadsheetValidationError(f"第 {rowNumber} 行题名已变化，请重新导出筛选表: {title}")
        if index not in seen:
            selectedIndexes.append(index)
            seen.add(index)

    return [byIndex[index] for index in selectedIndexes]


def _isSelected(value: str) -> bool:
    return value.strip().lower() in {"是", "y", "yes", "1", "true", "导入"}


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _metadataValue(rows: list[list[str]], key: str) -> str:
    for row in rows:
        if len(row) >= 2 and row[0] == key:
            return row[1]
    return ""


def _writeXlsxParts(
    zf: zipfile.ZipFile,
    reviewRows: list[list[str]],
    instructionRows: list[list[str]],
    metadataRows: list[list[str]],
    hyperlinks: list[tuple[str, str, str]],
):
    zf.writestr("[Content_Types].xml", _contentTypesXml())
    zf.writestr("_rels/.rels", _packageRelsXml())
    zf.writestr("xl/workbook.xml", _workbookXml())
    zf.writestr("xl/_rels/workbook.xml.rels", _workbookRelsXml())
    zf.writestr("xl/styles.xml", _stylesXml())
    zf.writestr("xl/worksheets/sheet1.xml", _worksheetXml(reviewRows, sheetName="筛选", hyperlinks=hyperlinks))
    zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", _worksheetRelsXml(hyperlinks))
    zf.writestr("xl/worksheets/sheet2.xml", _worksheetXml(instructionRows, sheetName="说明"))
    zf.writestr("xl/worksheets/sheet3.xml", _worksheetXml(metadataRows, sheetName="元数据"))


def _contentTypesXml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""


def _packageRelsXml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_NS_PACKAGE_REL}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbookXml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_REL}">
  <sheets>
    <sheet name="筛选" sheetId="1" r:id="rId1"/>
    <sheet name="说明" sheetId="2" r:id="rId2"/>
    <sheet name="元数据" sheetId="3" r:id="rId3"/>
  </sheets>
</workbook>"""


def _workbookRelsXml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_NS_PACKAGE_REL}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _stylesXml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{_NS_MAIN}">
  <fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
</styleSheet>"""


def _worksheetXml(rows: list[list[str]], sheetName: str, hyperlinks: list[tuple[str, str, str]] | None = None) -> str:
    cols = ""
    if sheetName == "筛选":
        widths = [12, 8, 36, 22, 16, 8, 8, 8, 16, 10, 10, 10, 54, 12, 12, 22]
        cols = "<cols>" + "".join(
            f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
            for i, width in enumerate(widths, 1)
        ) + "</cols>"

    rowXml = []
    for rowIndex, row in enumerate(rows, 1):
        cells = []
        for colIndex, value in enumerate(row, 1):
            ref = f"{_columnName(colIndex)}{rowIndex}"
            style = ' s="1"' if rowIndex == 1 else ""
            cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t>{_xml(value)}</t></is></c>')
        rowXml.append(f'<row r="{rowIndex}">{"".join(cells)}</row>')

    extras = ""
    if sheetName == "筛选":
        endRow = max(1, len(rows))
        extras += f'<autoFilter ref="A1:P{endRow}"/>'
        extras += (
            '<dataValidations count="1">'
            f'<dataValidation type="list" allowBlank="1" showDropDown="0" sqref="A2:A{endRow}">'
            '<formula1>"是,"</formula1>'
            "</dataValidation>"
            "</dataValidations>"
        )
        if hyperlinks:
            extras += "<hyperlinks>" + "".join(
                f'<hyperlink ref="{cellRef}" r:id="{relId}"/>'
                for cellRef, relId, _ in hyperlinks
            ) + "</hyperlinks>"

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{_NS_MAIN}" xmlns:r="{_NS_REL}">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" xSplit="2" topLeftCell="C2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>
  {cols}
  <sheetData>{"".join(rowXml)}</sheetData>
  {extras}
</worksheet>"""


def _worksheetRelsXml(hyperlinks: list[tuple[str, str, str]]) -> str:
    relationships = "".join(
        f'<Relationship Id="{relId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{_xml(url)}" TargetMode="External"/>'
        for _, relId, url in hyperlinks
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_NS_PACKAGE_REL}">{relationships}</Relationships>"""


def _xml(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _columnName(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _readWorkbookRows(path: Path) -> dict[str, list[list[str]]]:
    try:
        with zipfile.ZipFile(path) as zf:
            sharedStrings = _readSharedStrings(zf)
            sheetNames = _readSheetNames(zf)
            result = {}
            for sheetIndex, sheetName in enumerate(sheetNames, 1):
                sheetPath = f"xl/worksheets/sheet{sheetIndex}.xml"
                if sheetPath in zf.namelist():
                    result[sheetName] = _readSheetRows(zf.read(sheetPath), sharedStrings)
            return result
    except zipfile.BadZipFile as e:
        raise SpreadsheetValidationError(f"无法读取 XLSX 文件: {path}") from e


def _readSheetNames(zf: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    return [sheet.attrib.get("name", "") for sheet in root.findall(f".//{{{_NS_MAIN}}}sheet")]


def _readSharedStrings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [_nodeText(si) for si in root.findall(f"{{{_NS_MAIN}}}si")]


def _readSheetRows(xmlBytes: bytes, sharedStrings: list[str]) -> list[list[str]]:
    root = ET.fromstring(xmlBytes)
    rows = []
    for row in root.findall(f".//{{{_NS_MAIN}}}row"):
        values = []
        for cell in row.findall(f"{{{_NS_MAIN}}}c"):
            colIndex = _cellColumnIndex(cell.attrib.get("r", "A1"))
            while len(values) < colIndex - 1:
                values.append("")
            values.append(_readCellValue(cell, sharedStrings))
        rows.append(values)
    return rows


def _readCellValue(cell: ET.Element, sharedStrings: list[str]) -> str:
    cellType = cell.attrib.get("t", "")
    if cellType == "inlineStr":
        inline = cell.find(f"{{{_NS_MAIN}}}is")
        return _nodeText(inline) if inline is not None else ""
    value = cell.find(f"{{{_NS_MAIN}}}v")
    text = value.text if value is not None and value.text is not None else ""
    if cellType == "s" and text:
        try:
            return sharedStrings[int(text)]
        except (IndexError, ValueError):
            return ""
    return text


def _nodeText(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext())


def _cellColumnIndex(ref: str) -> int:
    match = re.match(r"([A-Z]+)", ref)
    if not match:
        return 1
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - 64
    return index
