#!/usr/bin/env python3
import os
import argparse
from typing import List
import pandas as pd

def find_date_columns(df: pd.DataFrame) -> List[str]:
    """
    Retorna a lista de colunas que podem ser convertidas para datetime.
    """
    date_cols: List[str] = []
    for col in df.columns:
        series = df[col].dropna().astype(str)
        try:
            pd.to_datetime(series, dayfirst=True, errors='raise')
            date_cols.append(col)
        except Exception:
            pass
    return date_cols

def analyze_folder(folder: str):
    print(f"\n🔎  Analisando pasta: {folder}\n")
    if not os.path.isdir(folder):
        print("⛔️  Diretório não encontrado.")
        return

    files = [f for f in os.listdir(folder)
             if f.lower().endswith(('.xls', '.xlsx'))]
    print(f"  • Arquivos encontrados: {len(files)}\n")
    if not files:
        return

    # Cabeçalho
    print(f"{'Arquivo':60}Colunas de Data")
    print("-" * 90)
    for fname in files:
        path = os.path.join(folder, fname)
        try:
            df = pd.read_excel(path, dtype=str)
            dates = find_date_columns(df)
        except Exception as e:
            dates = [f"Erro ao ler: {e}"]
        print(f"{fname:60}{', '.join(dates) or '— nenhuma'}")

def main():
    parser = argparse.ArgumentParser(
        description="Lista, para cada arquivo Excel numa pasta, as colunas reconhecidas como datas."
    )
    parser.add_argument(
        '-f', '--folder',
        default=r"C:\Users\ruan_cruz\Desktop\Automações\Beck-up\Validação - 02-07\test\Validação\uploads",
        help="Caminho da pasta com os arquivos Excel"
    )
    args = parser.parse_args()
    analyze_folder(args.folder)

if __name__ == "__main__":
    main()
