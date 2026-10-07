# -*- coding: utf-8 -*-
"""
Translation Tool for 'Clear' (ExHIBIT Engine)
Supports:
  - Export to Excel (.xlsx) [1 script = 1 sheet]
  - Export to Markdown (.md) [1 script = 1 .md file]
  - Import / Inject from .xlsx or .md into .rld with RU_F font remapping
"""

import os
import sys
import glob
import struct
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ─────────────────────────────────────────────────────────────────────────────
# RU_F таблица трансляции (Кириллица -> Символы шрифта CTNekokoi / ASCII)
# ─────────────────────────────────────────────────────────────────────────────
_RU_F_UPPER = {
    'A': 'А', 'B': 'Б', 'C': 'В', 'D': 'Г', 'E': 'Д', 'F': 'Е',
    'G': 'Ж', 'H': 'З', 'I': 'И', 'J': 'Й', 'K': 'К', 'L': 'Л',
    'M': 'М', 'N': 'Н', 'O': 'О', 'P': 'П', 'Q': 'Р', 'R': 'С',
    'S': 'Т', 'T': 'У', 'U': 'Ф', 'V': 'Х', 'W': 'Ц', 'X': 'Ч',
    'Y': 'Ш', 'Z': 'Щ',
}
_RU_F_LOWER = {k.lower(): v.lower() for k, v in _RU_F_UPPER.items()}

_CYR_TO_LATIN = {}
for _lat, _cyr in _RU_F_UPPER.items():
    _CYR_TO_LATIN[_cyr] = _lat
for _lat, _cyr in _RU_F_LOWER.items():
    _CYR_TO_LATIN[_cyr] = _lat

_CYR_SPECIAL = {
    'Ъ': '[',   'Ь': ']',   'ё': '`',
    'э': '{',   'ы': '|',   'я': '}',
    'Ы': '\xa1',
    'ь': '&',
    'ъ': '+',
    'Ю': '%',
    'ю': '$',
    '—': '-',
    'Я': '>',
    'Ё': '<',
    '«': '"',
    '»': '"',
    'Э': '=',
    'Й': 'J',   'й': 'j',
    '…': '...',
}

_FULL_TABLE = {}
_FULL_TABLE.update(_CYR_TO_LATIN)
_FULL_TABLE.update(_CYR_SPECIAL)

def apply_ru_f(text: str) -> str:
    if not text:
        return text
    text = str(text).replace('_x000D_', '').replace('\r', '')
    text = text.replace('…', '...')
    text = text.replace('（', '(').replace('）', ')')
    text = text.replace('「', '"').replace('」', '"')
    text = text.replace('『', '"').replace('』', '"')
    text = text.replace('【', '[').replace('】', ']')
    text = text.replace('　', ' ')
    text = text.replace('、', ', ').replace('。', '. ')
    text = text.replace('！', '!').replace('？', '?')
    return ''.join(_FULL_TABLE.get(ch, ch) for ch in text)

def auto_wrap_text(text: str, max_chars: int = 50) -> str:
    """Автоматический перенос строк по словам, если строка не содержит явных переносов или слишком длинная"""
    if not text:
        return text
    
    # Если уже есть переносы, обрабатываем каждую подстроку отдельно
    lines = text.split('\n')
    wrapped_lines = []
    
    for line in lines:
        if len(line) <= max_chars:
            wrapped_lines.append(line)
            continue
            
        words = line.split(' ')
        cur_line = []
        cur_len = 0
        
        for w in words:
            # Длина слова + пробел
            add_len = len(w) + (1 if cur_line else 0)
            if cur_len + add_len <= max_chars:
                cur_line.append(w)
                cur_len += add_len
            else:
                if cur_line:
                    wrapped_lines.append(' '.join(cur_line))
                cur_line = [w]
                cur_len = len(w)
                
        if cur_line:
            wrapped_lines.append(' '.join(cur_line))
            
    return '\n'.join(wrapped_lines)


# ─────────────────────────────────────────────────────────────────────────────
# Парсер RLD в структуры
# ─────────────────────────────────────────────────────────────────────────────
def parse_rld_file(rld_path: str):
    with open(rld_path, 'rb') as f:
        data = f.read()

    if data[:4] != b'\x00DLR':
        return None

    op_offset = struct.unpack('<I', data[8:12])[0]
    op_count = struct.unpack('<I', data[12:16])[0]

    curr = op_offset
    entries = []
    line_id = 1

    for i in range(op_count):
        pos = curr
        op_val = struct.unpack('<I', data[curr:curr+4])[0]
        curr += 4
        op_code = op_val & 0xFFFF
        init_count = (op_val >> 16) & 0xFF
        str_count = (op_val >> 24) & 0x0F

        curr += init_count * 4
        strs = []
        for _ in range(str_count):
            end = data.find(b'\x00', curr)
            strs.append((curr, data[curr:end]))
            curr = end + 1

        # Опкод 0x1C: реплики/повествование [speaker, text]
        if op_code == 0x1C and len(strs) >= 2:
            sp_off, speaker_bytes = strs[0]
            text_off, text_bytes = strs[1]
            speaker_str = speaker_bytes.decode('cp932', errors='replace')
            text_str = text_bytes.decode('cp932', errors='replace')

            entries.append({
                'id': line_id,
                'offset': text_off,
                'speaker_offset': sp_off,
                'speaker': speaker_str,
                'orig': text_str.replace('\n', '[n]'),
            })
            line_id += 1

        # Опкод 0x15: системные реплики / выборы
        elif op_code == 0x15 and len(strs) >= 1:
            for s_off, s_bytes in strs:
                s_str = s_bytes.decode('cp932', errors='replace')
                entries.append({
                    'id': line_id,
                    'offset': s_off,
                    'speaker': 'SYS',
                    'orig': s_str.replace('\n', '[n]'),
                })
                line_id += 1

    return entries

# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПОРТ: MARKDOWN (.md) — 1 файл скрипта = 1 md файл
# ─────────────────────────────────────────────────────────────────────────────
def export_md(input_dir='rld_backup', output_dir='md'):
    os.makedirs(output_dir, exist_ok=True)
    rld_files = sorted(glob.glob(os.path.join(input_dir, '*.rld')))
    print(f"Exporting to Markdown: {len(rld_files)} scripts...")

    count = 0
    for rf in rld_files:
        base = os.path.splitext(os.path.basename(rf))[0]
        entries = parse_rld_file(rf)
        if not entries:
            continue

        md_path = os.path.join(output_dir, f"{base}.md")
        with open(md_path, 'w', encoding='utf-8') as out:
            out.write(f"# Script: {base}\n\n")
            out.write("| ID | Offset | Speaker | Original (JP) | Translation (RU) |\n")
            out.write("|---:|:------:|:-------:|:--------------|:-----------------|\n")
            for e in entries:
                # экранируем вертикальную черту для Markdown таблицы
                clean_jp = e['orig'].replace('|', '\\|')
                clean_sp = e['speaker'].replace('|', '\\|')
                out.write(f"| {e['id']} | 0x{e['offset']:08X} | {clean_sp} | {clean_jp} |  |\n")
        count += 1

    print(f"Done! Created {count} Markdown files in '{output_dir}/'.")

# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПОРТ: EXCEL (.xlsx) — 1 файл скрипта = 1 лист
# ─────────────────────────────────────────────────────────────────────────────
def export_xlsx(input_dir='rld_backup', output_file='clear_translation.xlsx'):
    rld_files = sorted(glob.glob(os.path.join(input_dir, '*.rld')))
    print(f"Exporting to Excel: {len(rld_files)} scripts into '{output_file}'...")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Удаляем дефолтный лист

    header_font = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='2F5597', end_color='2F5597', fill_type='solid')
    align_center = Alignment(horizontal='center', vertical='center')
    align_left = Alignment(horizontal='left', vertical='center')

    count = 0
    for rf in rld_files:
        sheet_name = os.path.splitext(os.path.basename(rf))[0][:31]
        entries = parse_rld_file(rf)
        if not entries:
            continue

        ws = wb.create_sheet(title=sheet_name)
        ws.row_dimensions[1].height = 25

        headers = ['ID', 'File', 'Offset', 'Speaker', 'Original (JP)', 'Translation (RU)', 'Proofread (TLC)']
        ws.append(headers)

        for col_idx in range(1, 8):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = align_center

        for e in entries:
            row_data = [
                e['id'],
                sheet_name,
                f"0x{e['offset']:08X}",
                e['speaker'],
                e['orig'],
                '',  # Translation
                ''   # TLC
            ]
            ws.append(row_data)

        # Настройка ширины колонок
        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 14
        ws.column_dimensions['D'].width = 16
        ws.column_dimensions['E'].width = 45
        ws.column_dimensions['F'].width = 45
        ws.column_dimensions['G'].width = 45

        count += 1
        if count % 50 == 0:
            print(f"  Processed {count} sheets...")

    print(f"Saving workbook '{output_file}' (total {count} sheets)...")
    wb.save(output_file)
    print("Done Excel export!")

# ─────────────────────────────────────────────────────────────────────────────
# ИМПОРТ / СБОРКА ИЗ EXCEL (.xlsx)
# ─────────────────────────────────────────────────────────────────────────────
def inject_from_xlsx(xlsx_path='clear_translation.xlsx', orig_dir='rld_backup', out_dir='rld'):
    if not os.path.exists(xlsx_path):
        print(f"Error: {xlsx_path} not found!")
        return

    print(f"Loading Excel '{xlsx_path}'...")
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    count = 0

    for sheet in wb.sheetnames:
        ws = wb[sheet]
        translations = {}
        speaker_updates = {}

        orig_rld = os.path.join(orig_dir, f"{sheet}.rld")
        tx_to_sp = {}
        if os.path.exists(orig_rld):
            entries = parse_rld_file(orig_rld)
            for e in entries:
                if 'speaker_offset' in e:
                    tx_to_sp[e['offset']] = (e['speaker_offset'], e['speaker'])

        for row in range(2, ws.max_row + 1):
            offset_val = ws.cell(row=row, column=3).value
            sp_val = ws.cell(row=row, column=4).value
            tl = ws.cell(row=row, column=6).value
            tlc = ws.cell(row=row, column=7).value

            chosen = tlc if (tlc is not None and str(tlc).strip() != '') else tl
            try:
                off_int = int(str(offset_val), 16) if isinstance(offset_val, str) else int(offset_val)
                if chosen is not None and str(chosen).strip() != '':
                    raw_val = str(chosen).replace('\r', '').replace('_x000D_', '').strip()
                    translations[off_int] = raw_val

                if sp_val is not None and off_int in tx_to_sp:
                    sp_str = str(sp_val).strip()
                    sp_off, orig_sp = tx_to_sp[off_int]
                    if sp_str != '' and sp_str != '記述' and sp_str != orig_sp:
                        translations[sp_off] = sp_str
            except Exception:
                pass

        if translations:
            out_rld = os.path.join(out_dir, f"{sheet}.rld")
            if os.path.exists(orig_rld):
                inject_single_file(orig_rld, translations, out_rld)
                count += 1

    print(f"Done! Injected translations from Excel into {count} rld files.")

# ─────────────────────────────────────────────────────────────────────────────
# ИМПОРТ / СБОРКА ИЗ MARKDOWN (.md)
# ─────────────────────────────────────────────────────────────────────────────
def inject_from_md(md_dir='md', orig_dir='rld_backup', out_dir='rld'):
    md_files = glob.glob(os.path.join(md_dir, '*.md'))
    print(f"Importing translations from Markdown ({len(md_files)} files)...")
    count = 0

    for mf in md_files:
        base = os.path.splitext(os.path.basename(mf))[0]
        translations = {}

        orig_rld = os.path.join(orig_dir, f"{base}.rld")
        tx_to_sp = {}
        if os.path.exists(orig_rld):
            entries = parse_rld_file(orig_rld)
            for e in entries:
                if 'speaker_offset' in e:
                    tx_to_sp[e['offset']] = (e['speaker_offset'], e['speaker'])

        with open(mf, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith('|'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 6:
                    offset_str = parts[2]
                    sp_str = parts[3]
                    tl_str = parts[5]
                    if offset_str.startswith('0x'):
                        try:
                            off_int = int(offset_str, 16)
                            if tl_str != '':
                                translations[off_int] = tl_str

                            if off_int in tx_to_sp and sp_str != '' and sp_str != '記述':
                                sp_off, orig_sp = tx_to_sp[off_int]
                                if sp_str != orig_sp:
                                    translations[sp_off] = sp_str
                        except Exception:
                            pass

        if translations:
            out_rld = os.path.join(out_dir, f"{base}.rld")
            if os.path.exists(orig_rld):
                inject_single_file(orig_rld, translations, out_rld)
                count += 1

    print(f"Done! Injected translations from Markdown into {count} rld files.")

# ─────────────────────────────────────────────────────────────────────────────
# Низкоуровневая вставка строк в RLD бинарник
# ─────────────────────────────────────────────────────────────────────────────
def inject_single_file(orig_rld_path: str, translations: dict, out_rld_path: str):
    with open(orig_rld_path, 'rb') as f:
        buffer = f.read()

    new_buf = bytearray()
    curr_pos = 0

    sorted_offsets = sorted(translations.keys())
    for off in sorted_offsets:
        if off >= len(buffer):
            continue

        new_buf.extend(buffer[curr_pos:off])
        old_end = buffer.find(b'\x00', off)
        if old_end == -1:
            old_end = off

        raw_text = translations[off].replace('\\n', '\n').replace('[n]', '\n')
        # Автоматический перенос строк по словам (максимум 42 символа в строке, чтобы не вылезать за пределы окна)
        raw_text = auto_wrap_text(raw_text, max_chars=53)
        # Автоматическая конвертация кириллицы в символы шрифта CTNekokoi
        remapped_text = apply_ru_f(raw_text)
        new_bytes = remapped_text.encode('cp1252', errors='replace')

        new_buf.extend(new_bytes)
        new_buf.append(0)

        curr_pos = old_end + 1

    if curr_pos < len(buffer):
        new_buf.extend(buffer[curr_pos:])

    os.makedirs(os.path.dirname(out_rld_path), exist_ok=True)
    with open(out_rld_path, 'wb') as f:
        f.write(new_buf)

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def print_help():
    print("""
Clear Translation Tool:
  python translate_tool.py export-md     - Экспорт всех скриптов в Markdown (.md, 1 файл = 1 скрипт)
  python translate_tool.py export-xlsx   - Экспорт всех скриптов в Excel (.xlsx, 1 лист = 1 скрипт)
  python translate_tool.py inject-md     - Сборка игры из переведённых .md файлов
  python translate_tool.py inject-xlsx   - Сборка игры из переведённого clear_translation.xlsx
""")

def main():
    if len(sys.argv) < 2:
        print_help()
        return

    cmd = sys.argv[1].lower()
    if cmd == 'export-md':
        export_md()
    elif cmd == 'export-xlsx':
        export_xlsx()
    elif cmd == 'inject-md':
        inject_from_md()
    elif cmd == 'inject-xlsx':
        inject_from_xlsx()
    else:
        print_help()

if __name__ == '__main__':
    main()
