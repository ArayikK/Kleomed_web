#!/usr/bin/env python3
"""Проставляет в страницах метку версии для style.css и main.js.

Ссылки в разметке идут с `?v=<хэш>`. Nginx отдаёт эти два файла с длинным
кешем, поэтому браузер берёт их заново только когда меняется сам адрес —
то есть когда меняется хэш. Пока метку правили руками, она успела отстать
от файлов, и вернувшиеся посетители получали старые стили после выкладки.

Запускать перед каждой выкладкой:

    python stamp.py          # проставить метки
    python stamp.py --check  # только проверить, ничего не писать

`--check` возвращает код 1, если метки отстали, — годится для проверки
перед rsync.
"""

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SITE = ROOT / "site"

# путь в разметке -> файл на диске
ASSETS = {
    "css/style.css": SITE / "css" / "style.css",
    "js/main.js": SITE / "js" / "main.js",
    # Фото врача меняли уже дважды, и метка при нём стояла руками («?v=4»).
    # Ей место здесь по той же причине, что и стилям: заменил файл — адрес
    # обязан поменяться сам, иначе у вернувшихся останется прежний снимок.
    "img/doctor-zeynalyan.webp": SITE / "img" / "doctor-zeynalyan.webp",
}


def digest(path):
    """Первые 8 знаков sha256 — той же длины метка, что стояла раньше."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def main():
    check_only = "--check" in sys.argv

    stamps = {}
    for ref, path in ASSETS.items():
        if not path.exists():
            sys.exit("нет файла: %s" % path)
        stamps[ref] = digest(path)

    stale = []
    touched = []

    for page in sorted(SITE.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        out = text
        for ref, stamp in stamps.items():
            # ?v=… может и отсутствовать — тогда добавляем
            pattern = re.compile(re.escape(ref) + r"(\?v=[^\"']*)?")

            def swap(m, ref=ref, stamp=stamp):
                return "%s?v=%s" % (ref, stamp)

            out = pattern.sub(swap, out)
        if out != text:
            stale.append(page.name)
            if not check_only:
                page.write_text(out, encoding="utf-8")
                touched.append(page.name)

    for ref, stamp in stamps.items():
        print("%-16s v=%s" % (ref, stamp))

    if check_only:
        if stale:
            print("метки отстали в %d стр.: %s" % (len(stale), ", ".join(stale)))
            return 1
        print("метки совпадают с файлами")
        return 0

    print("обновлено страниц: %d" % len(touched) if touched else "всё уже было проставлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
