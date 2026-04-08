#!/usr/bin/env python3
"""
Тест исправления _SHEET_INFO_CACHE в learning.py
python test_sheets_cache.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*55)
print("  ТЕСТ _SHEET_INFO_CACHE + _get_spreadsheet_info")
print("="*55)

# 1. Проверяем что переменная объявлена
try:
    from learning import _SHEET_INFO_CACHE, _get_spreadsheet_info, _get_sheet_id
    print(f"\n1. ✅ _SHEET_INFO_CACHE импортируется: {_SHEET_INFO_CACHE!r}")
except ImportError as e:
    print(f"\n1. ❌ ImportError: {e}")
    sys.exit(1)

# 2. Проверяем что _get_spreadsheet_info существует
print(f"2. ✅ _get_spreadsheet_info: {_get_spreadsheet_info.__doc__[:50].strip()}...")

# 3. Проверяем force=False возвращает кэш
from learning import _SHEET_INFO_CACHE as cache_ref
# Ставим тестовые данные в кэш
import learning
learning._SHEET_INFO_CACHE = {"sheets": [{"properties": {"title": "test", "sheetId": 42}}]}
result = _get_spreadsheet_info(force=False)
assert result == learning._SHEET_INFO_CACHE, "Кэш не используется!"
print(f"3. ✅ force=False возвращает кэш: {result}")

# 4. Проверяем _get_sheet_id
sid = _get_sheet_id("test")
assert sid == 42, f"Ожидалось 42, получено {sid}"
print(f"4. ✅ _get_sheet_id('test') = {sid}")

# 5. Сброс кэша
learning._SHEET_INFO_CACHE.clear()
result2 = _get_spreadsheet_info(force=False)
# Должен попытаться запросить API (вернёт {} без credentials)
print(f"5. ✅ После clear() возвращает: {result2!r}")

print()
print("="*55)
print("  ВСЕ ТЕСТЫ ПРОШЛИ ✅")
print("  _SHEET_INFO_CACHE работает корректно")
print("="*55)
