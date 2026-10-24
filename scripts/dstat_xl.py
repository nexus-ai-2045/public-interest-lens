"""Excel(xls/xlsx)読み込みの共通関数。run: python -I scripts/dstat_xl.py FILE [max_sheets] [max_rows] で中身を表示"""
import sys


def sheets(path):
    """[(sheet名, [行のリスト])] を返す。"""
    out = []
    if path.endswith('.xls'):
        import xlrd
        wb = xlrd.open_workbook(path)
        for ws in wb.sheets():
            rows = [[(c if c != '' else None) for c in ws.row_values(i)] for i in range(ws.nrows)]
            out.append((ws.name, rows))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        for ws in wb.worksheets:
            out.append((ws.title, [list(r) for r in ws.iter_rows(values_only=True)]))
    return out


if __name__ == '__main__':
    s = sheets(sys.argv[1])
    ns = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    nr = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    print('SHEETS', [n for n, _ in s])
    for n, rows in s[:ns]:
        print('==', n, len(rows))
        for i, r in enumerate(rows[:nr]):
            print(i + 1, r[:9])
