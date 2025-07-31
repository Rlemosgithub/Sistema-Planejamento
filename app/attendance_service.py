import os
from datetime import datetime, date
import pandas as pd

class AttendanceService:
    def __init__(self, upload_folder):
        self.folder = upload_folder
        self._load_calendar()
        self._load_efetivo()
        self._load_vac_inss()
        self._load_adm_term()
        self._load_atestados()

    def _load_calendar(self):
        path = os.path.join(self.folder, 'calendar.xlsx')
        if os.path.exists(path):
            df = pd.read_excel(path, sheet_name=0, dtype={'DATA': object, 'COBRAR?': str})
            df['DATA'] = pd.to_datetime(df['DATA'], format='%d/%m/%Y', dayfirst=True, errors='coerce')
            self.cobrar_days = df.loc[
                df['COBRAR?'].str.strip().str.lower() == 'sim',
                'DATA'
            ].dt.strftime('%d/%m/%Y').tolist()
        else:
            self.cobrar_days = []

    def _load_efetivo(self):
        path = os.path.join(self.folder, 'Efetivo.xlsx')
        if os.path.exists(path):
            df = pd.read_excel(path, sheet_name=0, dtype=str)
            status_col = df.columns[2]
            self.eff_mods = df.loc[
                df[status_col].str.strip() == 'MOD',
                df.columns[0]
            ].str.strip().tolist()
        else:
            self.eff_mods = []

    def _load_vac_inss(self):
        path = os.path.join(self.folder, 'ferias_inss.xlsx')
        if os.path.exists(path):
            vac = pd.read_excel(path, sheet_name='Férias')
            vac.columns = vac.columns.str.strip()
            col_map = {}
            for c in vac.columns:
                k = c.lower().replace('-', ' ').replace('_', ' ').strip()
                if 'início' in k or 'inicio' in k:
                    col_map[c] = 'vac_inicio'
                elif 'término' in k or 'termino' in k:
                    col_map[c] = 'vac_termino'
            vac = vac.rename(columns=col_map)
            vac['vac_inicio']  = pd.to_datetime(vac['vac_inicio'],  format='%d/%m/%Y', errors='coerce').dt.date
            vac['vac_termino'] = pd.to_datetime(vac['vac_termino'], format='%d/%m/%Y', errors='coerce').dt.date
            vac['NOME']       = vac['NOME'].str.strip()
            vac['DISCIPLINA'] = vac['DISCIPLINA'].fillna('').astype(str)
            self.vac_df = vac

            ins = pd.read_excel(path, sheet_name='INSS')
            ins.columns = ins.columns.str.strip()
            ins['inicio']  = pd.to_datetime(ins['Início'],  format='%d/%m/%Y', errors='coerce').dt.date
            ins['termino'] = pd.to_datetime(ins['Término'], format='%d/%m/%Y', errors='coerce').dt.date
            ins['OBSERVAÇÃO'] = ins['NOME'].str.strip()
            ins['DISCIPLINA'] = ins['DISCIPLINA'].fillna('').astype(str)
            self.inss_df = ins[['OBSERVAÇÃO','DISCIPLINA','inicio','termino']]
        else:
            self.vac_df  = pd.DataFrame(columns=['NOME','DISCIPLINA','vac_inicio','vac_termino'])
            self.inss_df = pd.DataFrame(columns=['NOME','DISCIPLINA','inicio','termino'])

    def _load_adm_term(self):
        path = os.path.join(self.folder, 'Efetivo.xlsx')
        if os.path.exists(path):
            adm = pd.read_excel(path, sheet_name=1, dtype=str)
            adm_ts = pd.to_datetime(
                adm[adm.columns[2]], format='%d/%m/%Y',
                dayfirst=True, errors='coerce'
            ).dt.date.fillna(date.min)
            self.adm_df = pd.DataFrame({
                'OBSERVAÇÃO': adm[adm.columns[0]].str.strip(),
                'DISCIPLINA': adm[adm.columns[1]].fillna('').astype(str),
                'DATA': adm_ts
            })
            term = pd.read_excel(path, sheet_name=2, dtype=str)
            term_ts = pd.to_datetime(
                term[term.columns[2]], format='%d/%m/%Y',
                dayfirst=True, errors='coerce'
            ).dt.date.fillna(date.max)
            self.term_df = pd.DataFrame({
                'OBSERVAÇÃO': term[term.columns[0]].str.strip(),
                'DISCIPLINA': term[term.columns[1]].fillna('').astype(str),
                'DATA': term_ts
            })
        else:
            self.adm_df  = pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATA'])
            self.term_df = pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATA'])

    def _load_atestados(self):
        path = os.path.join(self.folder, 'atestado_falta.xlsx')
        if os.path.exists(path):
            at = pd.read_excel(path, sheet_name='Atestados', dtype=str)
            dt = pd.to_datetime(
                at['DATARDO_STR'], format='%d/%m/%Y',
                errors='coerce'
            ).dt.date
            self.at_df = pd.DataFrame({
                'OBSERVAÇÃO': at['OBSERVAÇÃO'].str.strip(),
                'DISCIPLINA': at['DISCIPLINA'].fillna('').astype(str),
                'DATA': dt,
                'DESVIO': at['DESVIO'].str.strip()
            })
        else:
            self.at_df = pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATA','DESVIO'])

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Recebe df com colunas:
          ['OBSERVAÇÃO','DISCIPLINA','DATARDO','DATARDO_STR','HORA NORMAL','HORA EXTRA']
        Retorna:
          ['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','CLASS']
        onde CLASS ∈ {'F','I','DL','AG','AT','D','X',''}
        """
        # filtra apenas MOD
        df = df[df['OBSERVAÇÃO'].isin(self.eff_mods)].copy()
        # soma horas
        grp = df.groupby(
            ['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR'],
            as_index=False
        ).agg({'HORA NORMAL':'sum','HORA EXTRA':'sum'})
        grp['TOTAL'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
        # cross-join pessoas × datas
        people = grp[['OBSERVAÇÃO','DISCIPLINA']].drop_duplicates().assign(key=1)
        days   = pd.DataFrame({'DATARDO_STR': self.cobrar_days}).assign(key=1)
        grid   = people.merge(days, on='key').drop('key', axis=1)
        df_all = grid.merge(grp, on=['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR'], how='left').fillna(0)
        # classificação inicial
        df_all['CLASS'] = 'X'
        df_all['DT'] = df_all['DATARDO_STR'].apply(lambda x: datetime.strptime(x,'%d/%m/%Y').date())
        # já registrou horas → sem classificação
        df_all.loc[df_all['TOTAL']>0, 'CLASS'] = ''
        # desligamento
        m = df_all.merge(self.term_df, on=['OBSERVAÇÃO','DISCIPLINA'], how='left')
        df_all.loc[m['DT']>m['DATA'], 'CLASS'] = 'DL'
        # férias
        m = df_all.merge(self.vac_df, left_on=['OBSERVAÇÃO','DISCIPLINA'], right_on=['NOME','DISCIPLINA'], how='left')
        mask = (df_all['CLASS']=='X') & (m['vac_inicio']<=m['DT']) & (m['DT']<=m['vac_termino'])
        df_all.loc[mask, 'CLASS'] = 'F'
        # INSS
        m = df_all.merge(self.inss_df, on=['OBSERVAÇÃO','DISCIPLINA'], how='left')
        mask = (df_all['CLASS']=='X') & (m['inicio']<=m['DT']) & (m['DT']<=m['termino'])
        df_all.loc[mask, 'CLASS'] = 'I'
        # AG (antes da admissão)
        m = df_all.merge(self.adm_df, on=['OBSERVAÇÃO','DISCIPLINA'], how='left')
        df_all.loc[(df_all['CLASS']=='X') & (df_all['DT']<m['DATA']), 'CLASS'] = 'AG'
        # AT / D
        m = df_all.merge(self.at_df, on=['OBSERVAÇÃO','DISCIPLINA'], how='left')
        df_all.loc[(df_all['CLASS']=='X') & (df_all['DT']==m['DATA']), 'CLASS'] = m['DESVIO']
        return df_all[['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','CLASS']]
