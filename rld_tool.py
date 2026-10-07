# -*- coding: utf-8 -*-
"""
RLD Tool for Visual Novel 'Clear' (ExHIBIT Engine)
Extracts and injects dialogue text while applying font remapping (Cyrillic -> Latin ASCII).
"""

import os
import sys
import glob
import struct

# ─────────────────────────────────────────────────────────────────────────────
# Таблица перемаппинга (Кириллица -> Символы шрифта CTNekokoi / ASCII)
# Взята из вашего build_translation.py
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
    '—': '#',
    'Я': '>',
    'Ё': '<',
    '«': '"',
    '»': '"',
    'Э': '=',
    'Й': 'J',   'й': 'j',
    '…': '...',
}

_REMAP_TABLE = {}
_REMAP_TABLE.update(_CYR_TO_LATIN)
_REMAP_TABLE.update(_CYR_SPECIAL)

def encode_remap(text: str) -> str:
    """Конвертирует русский текст в перемаппированные символы шрифта"""
    if not text:
        return text
    text = text.replace('\r', '').replace('…', '...')
    text = text.replace('（', '(').replace('）', ')')
    text = text.replace('「', '"').replace('」', '"')
    text = text.replace('『', '"').replace('』', '"')
    text = text.replace('【', '[').replace('】', ']')
    text = text.replace('　', ' ')
    text = text.replace('、', ', ').replace('。', '. ')
    text = text.replace('！', '!').replace('？', '?')
    return ''.join(_REMAP_TABLE.get(ch, ch) for ch in text)

# ─────────────────────────────────────────────────────────────────────────────
# Парсинг и дамп RLD
# ─────────────────────────────────────────────────────────────────────────────
def dump_rld(rld_path: str, txt_path: str):
    with open(rld_path, 'rb') as f:
        data = f.read()

    if data[:4] != b'\x00DLR':
        print(f"Skipping {rld_path}: not a valid RLD file")
        return False

    op_offset = struct.unpack('<I', data[8:12])[0]
    op_count = struct.unpack('<I', data[12:16])[0]

    curr = op_offset
    entries = []

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
            s_bytes = data[curr:end]
            strs.append((curr, s_bytes))
            curr = end + 1

        # Опкод 0x1C: реплики/повествование [спикер, текст]
        if op_code == 0x1C and len(strs) >= 2:
            speaker_off, speaker_bytes = strs[0]
            text_off, text_bytes = strs[1]
            try:
                speaker_str = speaker_bytes.decode('cp932')
            except Exception:
                speaker_str = speaker_bytes.decode('cp932', errors='replace')
            try:
                text_str = text_bytes.decode('cp932')
            except Exception:
                text_str = text_bytes.decode('cp932', errors='replace')

            entries.append({
                'offset': text_off,
                'speaker': speaker_str,
                'orig': text_str.replace('\n', '[n]'),
            })

        # Опкод 0x15: выборы / системные надписи
        elif op_code == 0x15 and len(strs) >= 1:
            for s_off, s_bytes in strs:
                try:
                    s_str = s_bytes.decode('cp932')
                except Exception:
                    s_str = s_bytes.decode('cp932', errors='replace')
                entries.append({
                    'offset': s_off,
                    'speaker': 'SYS',
                    'orig': s_str.replace('\n', '[n]'),
                })

    if not entries:
        return False

    os.makedirs(os.path.dirname(txt_path), exist_ok=True)
    with open(txt_path, 'w', encoding='utf-8') as out:
        for e in entries:
            out.write(f"◇{e['offset']:08X}◇ [{e['speaker']}]\n")
            out.write(f"○ {e['orig']}\n")
            out.write(f"● {e['orig']}\n\n")

    return True

# ─────────────────────────────────────────────────────────────────────────────
# Инжект перевода в RLD
# ─────────────────────────────────────────────────────────────────────────────
def inject_rld(orig_rld_path: str, txt_path: str, out_rld_path: str):
    with open(orig_rld_path, 'rb') as f:
        buffer = f.read()

    translations = {}
    current_offset = None

    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('◇') and '◇' in line[1:]:
                end_idx = line.find('◇', 1)
                current_offset = int(line[1:end_idx], 16)
            elif line.startswith('● ') and current_offset is not None:
                trans_text = line[2:]
                translations[current_offset] = trans_text
                current_offset = None

    if not translations:
        return False

    # Сборка нового бинарника с подстановкой текста
    new_buf = bytearray()
    curr_pos = 0

    sorted_offsets = sorted(translations.keys())
    for off in sorted_offsets:
        # Дописываем неизмененный кусок до строки
        new_buf.extend(buffer[curr_pos:off])

        # Находим длину старой строки
        old_end = buffer.find(b'\x00', off)
        old_len = old_end - off

        # Получаем перевод и применяем шрифт-ремаппинг
        raw_text = translations[off].replace('[n]', '\n')
        remapped_text = encode_remap(raw_text)

        # Кодируем в ascii/cp1252 байты
        new_bytes = remapped_text.encode('cp1252', errors='replace')
        new_buf.extend(new_bytes)
        new_buf.append(0)  # нуль-терминатор

        curr_pos = old_end + 1

    # Дописываем остаток файла
    if curr_pos < len(buffer):
        new_buf.extend(buffer[curr_pos:])

    os.makedirs(os.path.dirname(out_rld_path), exist_ok=True)
    with open(out_rld_path, 'wb') as f:
        f.write(new_buf)

    return True

# ─────────────────────────────────────────────────────────────────────────────
# Главное меню CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python rld_tool.py dump   - Dump all scripts from rld/ to txt/")
        print("  python rld_tool.py inject - Inject translation from txt/ into rld/")
        return

    mode = sys.argv[1].lower()

    if mode == 'dump':
        rld_files = glob.glob('rld/*.rld')
        print(f"Found {len(rld_files)} rld files. Dumping...")
        count = 0
        for rf in rld_files:
            base = os.path.basename(rf).replace('.rld', '.txt')
            txt_path = os.path.join('txt', base)
            if dump_rld(rf, txt_path):
                count += 1
        print(f"Done! Dumped {count} scripts with dialogue into txt/ folder.")

    elif mode == 'inject':
        txt_files = glob.glob('txt/*.txt')
        print(f"Found {len(txt_files)} txt files. Injecting...")
        count = 0
        for tf in txt_files:
            base = os.path.basename(tf).replace('.txt', '.rld')
            # Берем оригинал из бэкапа, чтобы не портить исходник
            orig_rld = os.path.join('rld_backup', base)
            if not os.path.exists(orig_rld):
                orig_rld = os.path.join('rld', base)
            out_rld = os.path.join('rld', base)
            if inject_rld(orig_rld, tf, out_rld):
                count += 1
        print(f"Done! Injected {count} scripts into rld/.")

if __name__ == '__main__':
    main()
