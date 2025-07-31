import os
import io
import logging
import pandas as pd
from datetime import datetime, timedelta
from flask import (
    Blueprint, current_app, render_template,
    request, redirect, url_for, flash, send_file
)
from flask_login import login_required
from .auth import roles_required
from openpyxl import load_workbook

bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

def _load_df(filename):
    """
    Carrega todas as abas do Excel em um DataFrame e formata colunas essenciais.
    Garante que a primeira coluna vire 'OBSERVAÇÃO' se o cabeçalho original não bater,
    e mapeia a disciplina pela primeira aba de Efetivo.xlsx (colunas A e B).
    Também padroniza todas as colunas de texto para datetime no padrão MM/DD/YYYY.
    """
    folder = current_app.config['UPLOAD_FOLDER']
    path = os.path.join(folder, filename)
    try:
        wb = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception:
        logger.exception(f"Erro ao abrir {filename}")
        flash(f"Erro ao abrir o arquivo {filename}.", 'danger')
        return pd.DataFrame()

    # 1) junta todas as abas
    sheets = []
    for ws in wb.worksheets:
        vals = ws.values
        try:
            header = next(vals)
        except StopIteration:
            continue
        df_sheet = pd.DataFrame(vals, columns=header, dtype=str)
        sheets.append(df_sheet)
    df = pd.concat(sheets, ignore_index=True) if sheets else pd.DataFrame()
    if df.empty:
        return df

    # 2) se não houver coluna 'OBSERVAÇÃO', força a primeira coluna
    if 'OBSERVAÇÃO' not in df.columns:
        first = df.columns[0]
        df = df.rename(columns={first: 'OBSERVAÇÃO'})

    # 3) Normaliza TODAS as colunas de texto para datetime (MM/DD/YYYY)
    for col in df.columns:
        if df[col].dtype == object:
            # 1ª tentativa: formato europeu (dia primeiro)
            parsed = pd.to_datetime(
                df[col],
                dayfirst=True,
                infer_datetime_format=True,
                errors='coerce'
            )
            # 2ª tentativa: formato americano MM/DD/YYYY
            mask = parsed.isna() & df[col].notna()
            if mask.any():
                us_dates = pd.to_datetime(
                    df.loc[mask, col],
                    format='%m/%d/%Y',
                    errors='coerce'
                )
                parsed.loc[mask] = us_dates
            # aceita coluna como data se ao menos 10% convertido
            if parsed.notna().sum() >= len(df) * 0.1:
                df[col] = parsed

    # 4) consolida 'DATARDO' → 'DATARDO_STR'
    if 'DATARDO' in df.columns and pd.api.types.is_datetime64_any_dtype(df['DATARDO']):
        df['DATARDO_STR'] = df['DATARDO'].dt.strftime('%d/%m/%Y').fillna('')
    elif 'DATARDO_STR' not in df.columns:
        df['DATARDO_STR'] = ''

    # 5) horas numéricas
    for col in ['HORA NORMAL', 'HORA EXTRA']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # 6) limpa texto
    for col in ['OBSERVAÇÃO', 'ORDEM', 'OPERAÇÃO', 'T_ATIV']:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)

    # 7) mapeamento de DISCIPLINA via Efetivo.xlsx
    map_path = os.path.join(folder, 'Efetivo.xlsx')
    if os.path.exists(map_path):
        try:
            dm = pd.read_excel(map_path, usecols=[0, 1], dtype=str)
            dm.columns = ['OBSERVAÇÃO', 'DISCIPLINA']
            dm['OBSERVAÇÃO'] = dm['OBSERVAÇÃO'].str.strip()
            dm = dm.drop_duplicates('OBSERVAÇÃO')
            df = df.merge(dm, on='OBSERVAÇÃO', how='left')
        except Exception:
            logger.warning("Falha no mapeamento de disciplinas via Efetivo.xlsx", exc_info=True)

    # 8) garante coluna DISCIPLINA
    if 'DISCIPLINA' not in df.columns:
        df['DISCIPLINA'] = ''
    df['DISCIPLINA'] = df['DISCIPLINA'].fillna('').astype(str)

    logger.info(f"Arquivo {filename}: {len(df)} linhas carregadas")
    return df

def _sync_justificativas():
    """
    Sincroniza os dados de atestado_falta.xlsx com Justificativas.xlsx.
    Atualiza, adiciona ou remove registros de justificativas com base nos atestados,
    preservando justificativas não relacionadas a atestados.
    """
    folder = current_app.config['UPLOAD_FOLDER']
    atestado_path = os.path.join(folder, 'atestado_falta.xlsx')
    just_path = os.path.join(folder, 'Justificativas.xlsx')

    try:
        # Carrega atestado_falta.xlsx
        if os.path.exists(atestado_path):
            atestado_df = pd.read_excel(atestado_path, sheet_name='Atestados', dtype=str)
            atestado_df = atestado_df.fillna('').astype(str)
        else:
            atestado_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'DESVIO'])

        # Carrega Justificativas.xlsx (se existir)
        if os.path.exists(just_path):
            just_df = pd.read_excel(just_path, sheet_name='Justificativas', dtype=str)
            just_df = just_df.fillna('').astype(str)
        else:
            just_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA', 'FRENTE DE TRABALHO', 'CODIGO'])

        # Mapeia códigos de desvio para justificativas
        deviation_to_code = {
            'Atestado': 'AT',
            'Ausente': 'AU',
            'SP': 'SP',
            'DEP': 'DP'
        }

        # Converte registros de atestados em justificativas
        just_from_atestado = []
        for _, row in atestado_df.iterrows():
            code = deviation_to_code.get(row['DESVIO'], '')
            if code:
                just_from_atestado.append({
                    'OBSERVAÇÃO': row['OBSERVAÇÃO'],
                    'DISCIPLINA': row['DISCIPLINA'],
                    'DATA': row['DATARDO_STR'],  # Já está no formato DD/MM/YYYY
                    'FRENTE DE TRABALHO': row.get('FRENTE DE TRABALHO', ''),
                    'CODIGO': code
                })

        # Cria DataFrame com novas justificativas a partir de atestados
        new_just_df = pd.DataFrame(just_from_atestado)

        # Remove duplicatas mantendo apenas o registro mais recente
        if not new_just_df.empty:
            new_just_df = new_just_df.drop_duplicates(
                subset=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'],
                keep='last'
            )

        # Filtra justificativas existentes, preservando as não relacionadas a atestados
        atestado_codes = list(deviation_to_code.values())
        if not just_df.empty:
            non_atestado_just = just_df[~just_df['CODIGO'].isin(atestado_codes)]
        else:
            non_atestado_just = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA', 'FRENTE DE TRABALHO', 'CODIGO'])

        # Mescla justificativas não relacionadas com as novas justificativas de atestados
        updated_just_df = pd.concat([non_atestado_just, new_just_df], ignore_index=True)

        # Remove duplicatas finais
        updated_just_df = updated_just_df.drop_duplicates(
            subset=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'],
            keep='last'
        )

        # Salva o arquivo atualizado
        with pd.ExcelWriter(just_path, engine='openpyxl') as writer:
            updated_just_df.to_excel(writer, index=False, sheet_name='Justificativas')
        logger.info(f"Justificativas.xlsx atualizado com {len(updated_just_df)} registros")
    except Exception as e:
        logger.error(f"Erro ao sincronizar Justificativas.xlsx: {str(e)}")
        flash(f"Erro ao sincronizar justificativas: {str(e)}", 'danger')

@bp.route('/')
@login_required
def dashboard():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = 'dados.xlsx'
    path_file = os.path.join(folder, sel_file)

    if not os.path.exists(path_file):
        flash(f"Arquivo '{sel_file}' não encontrado na pasta de uploads.", 'danger')
        return render_template('dashboard.html',
            files=[],
            selected_file=None,
            disciplines=[], selected_discipline='All',
            dates=[], selected_date='All',
            error_options=['All', 'Ok', 'Erro'], selected_error='All',
            search_text='',
            cards=[], entries=[]
        )

    df = _load_df(sel_file)

    grp = (df.groupby(['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], as_index=False)
             .agg({'HORA NORMAL': 'sum', 'HORA EXTRA': 'sum'}))
    grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
    tol = 0.01
    grp['ERROR'] = ~(
        grp['TOTAL_HH'].between(7.95, 10.00)
    )
    df = df.merge(
        grp[['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'TOTAL_HH', 'ERROR']],
        on=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], how='left'
    )

    sel_disc = request.args.get('discipline', 'All')
    sel_date = request.args.get('date', 'All')
    sel_err = request.args.get('error', 'All')
    search_text = request.args.get('search', '').strip()

    if sel_disc != 'All':
        df = df[df['DISCIPLINA'] == sel_disc]
    if sel_date != 'All':
        df = df[df['DATARDO_STR'] == sel_date]
    if sel_err != 'All':
        df = df[df['ERROR'] == (sel_err == 'Erro')]
    if search_text:
        df = df[df['OBSERVAÇÃO'].str.contains(search_text, case=False, na=False)]

    disciplines = sorted(df['DISCIPLINA'].unique())
    dates = sorted(df['DATARDO_STR'].unique())

    cards = [
        {'title': 'Registros', 'value': len(df), 'icon': 'fa-file-alt'},
        {'title': 'Colaboradores', 'value': df['OBSERVAÇÃO'].nunique(), 'icon': 'fa-users'}
    ]
    entries = df.to_dict('records')

    return render_template('dashboard.html',
        files=[sel_file],
        selected_file=sel_file,
        disciplines=disciplines, selected_discipline=sel_disc,
        dates=dates, selected_date=sel_date,
        error_options=['All', 'Ok', 'Erro'], selected_error=sel_err,
        search_text=search_text,
        cards=cards, entries=entries
    )

@bp.route('/export_dashboard')
@login_required
@roles_required('admin', 'editor')
def export_dashboard():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')
    sel_date = request.args.get('date', 'All')
    sel_err = request.args.get('error', 'All')
    search = request.args.get('search', '').strip()

    df = _load_df(sel_file) if sel_file else pd.DataFrame()
    grp = (df.groupby(['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], as_index=False)
             .agg({'HORA NORMAL': 'sum', 'HORA EXTRA': 'sum'}))
    grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
    tol = 0.01
    grp['ERROR'] = ~(
        grp['TOTAL_HH'].between(7.95, 8.80) |
        grp['TOTAL_HH'].sub(9).abs().le(tol) |
        grp['TOTAL_HH'].sub(10).abs().le(tol)
    )
    df = df.merge(
        grp[['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'TOTAL_HH', 'ERROR']],
        on=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], how='left'
    )
    if sel_disc != 'All': df = df[df['DISCIPLINA'] == sel_disc]
    if sel_date != 'All': df = df[df['DATARDO_STR'] == sel_date]
    if sel_err != 'All': df = df[df['ERROR'] == (sel_err == 'Erro')]
    if search: df = df[df['OBSERVAÇÃO'].str.contains(search, case=False, na=False)]

    export_df = df[[
        'DATARDO_STR', 'OBSERVAÇÃO', 'DISCIPLINA', 'TOTAL_HH', 'ERROR', 'HORA NORMAL', 'HORA EXTRA'
    ]].copy()
    export_df.columns = [
        'DATA', 'COLABORADOR', 'DISCIPLINA', 'TOTAL HH', 'STATUS_ERRO', 'HH NORMAL', 'HH EXTRA'
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False, sheet_name='Dashboard')
    buf.seek(0)
    return send_file(
        buf,
        download_name=f"dashboard_export_{sel_file or 'all'}.xlsx",
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@bp.route('/save_justifications', methods=['POST'])
@login_required
@roles_required('admin', 'editor')
def save_justifications():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.form.get('file')
    records = []
    for key, val in request.form.items():
        if key.startswith('justifica_') and val.strip():
            idx = key.split('_', 1)[1]
            records.append({
                'OBSERVAÇÃO': request.form.get(f'obs_{idx}', ''),
                'DISCIPLINA': request.form.get(f'disc_{idx}', ''),
                'DATARDO_STR': request.form.get(f'date_{idx}', ''),
                'JUSTIFICATIVA': val.strip()
            })
    out = os.path.join(folder, 'justificativas.xlsx')
    if records:
        dfj = pd.DataFrame(records)
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            dfj.to_excel(writer, index=False, sheet_name='Justificativas')
        flash(f"{len(records)} justificativa(s) salvas em justificativas.xlsx", 'success')
    else:
        flash('Nenhuma justificativa para salvar.', 'warning')
    return redirect(url_for('main.dashboard', file=sel_file))

@bp.route('/export_all')
@login_required
@roles_required('admin', 'editor')
def export_all():
    sel_file = request.args.get('file')
    df = _load_df(sel_file)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        for disc, grp in df.groupby('DISCIPLINA'):
            grp.to_excel(writer, sheet_name=disc[:31], index=False)
        df.to_excel(writer, sheet_name='Todos', index=False)
    buf.seek(0)
    return send_file(buf,
        download_name=f"export_{sel_file}.xlsx",
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@bp.route('/upload', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def upload():
    if request.method == 'POST':
        h = request.files.get('file')
        d = request.files.get('discipline_file')
        if h and h.filename.lower().endswith(('.xls', '.xlsx')):
            h.save(os.path.join(current_app.config['UPLOAD_FOLDER'], h.filename))
            flash('Horas carregadas!', 'success')
        if d and d.filename.lower().endswith(('.xls', '.xlsx')):
            d.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'mapping.xlsx'))
            flash('Disciplinas carregadas!', 'success')
        a = request.files.get('admissions_file')
        if a and a.filename.lower().endswith(('.xls', '.xlsx')):
            a.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'admissoes_desligamentos.xlsx'))
            flash('Admissões/Desligamentos carregados!', 'success')
        v = request.files.get('vacation_file')
        if v and v.filename.lower().endswith(('.xls', '.xlsx')):
            v.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'ferias_inss.xlsx'))
            flash('Férias/INSS carregados!', 'success')
        return redirect(url_for('main.dashboard'))
    return render_template('upload.html')

@bp.route('/atestado', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def atestado():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')

    df_all = _load_df(sel_file) if sel_file else pd.DataFrame()
    if df_all.empty and sel_file:
        flash('Arquivo selecionado não encontrado ou inválido.', 'danger')
        return redirect(url_for('main.dashboard'))

    disciplines_all = sorted(df_all['DISCIPLINA'].unique()) if not df_all.empty else []
    df = df_all[df_all['DISCIPLINA'] == sel_disc] if sel_disc != 'All' else df_all
    collaborators = sorted(df['OBSERVAÇÃO'].unique()) if not df.empty else []
    dates = sorted(df['DATARDO_STR'].unique()) if not df.empty else []
    deviations = ['Atestado', 'Ausente', 'SP', 'DEP']
    path_xlsx = os.path.join(folder, 'atestado_falta.xlsx')

    try:
        hist = pd.read_excel(path_xlsx, sheet_name='Atestados', dtype=str) if os.path.exists(path_xlsx) else pd.DataFrame()
        hist = hist.fillna('').astype(str)
    except Exception as e:
        flash(f'Erro ao carregar justificativas: {str(e)}', 'danger')
        hist = pd.DataFrame()

    if request.method == 'POST':
        discipline = request.form.get('discipline')
        collaborator = request.form.get('collaborator')
        date = request.form.get('date')
        deviation = request.form.get('deviation')

        if not all([discipline, collaborator, date, deviation]):
            flash('Todos os campos obrigatórios (Disciplina, Colaborador, Data, Desvio) devem ser preenchidos.', 'danger')
            return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

        # Coleta todos os campos do formulário dinamicamente
        rec = {
            'OBSERVAÇÃO': collaborator,
            'DISCIPLINA': discipline,
            'DATARDO_STR': date,
            'DESVIO': deviation
        }
        for key, value in request.form.items():
            if key not in ['discipline', 'collaborator', 'date', 'deviation']:
                rec[key] = value.strip() if value else ''

        try:
            df_new = pd.DataFrame([rec])
            if not hist.empty:
                for col in hist.columns:
                    if col not in df_new.columns:
                        df_new[col] = ''
                df_new = df_new[hist.columns]
            hist = pd.concat([hist, df_new], ignore_index=True)
            with pd.ExcelWriter(path_xlsx, engine='openpyxl') as writer:
                hist.to_excel(writer, index=False, sheet_name='Atestados')
            flash('Registro salvo com sucesso.', 'success')
            # Sincroniza com Justificativas.xlsx
            _sync_justificativas()
        except Exception as e:
            flash(f'Erro ao salvar registro: {str(e)}', 'danger')

        return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

    columns = hist.columns.tolist() if not hist.empty else ['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'DESVIO']
    return render_template('atestado.html',
        file=sel_file,
        disciplines=disciplines_all,
        selected_discipline=sel_disc,
        collaborators=collaborators,
        dates=dates,
        deviations=deviations,
        justificativas=hist.to_dict('records'),
        columns=columns
    )

@bp.route('/atestado/delete/<int:idx>', methods=['POST'])
@login_required
@roles_required('admin', 'editor')
def atestado_delete(idx):
    folder = current_app.config['UPLOAD_FOLDER']
    path_xlsx = os.path.join(folder, 'atestado_falta.xlsx')
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')

    if not os.path.exists(path_xlsx):
        flash('Arquivo de justificativas não encontrado.', 'danger')
        return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

    try:
        df = pd.read_excel(path_xlsx, sheet_name='Atestados', dtype=str)
        df = df.fillna('').astype(str)
        if 0 <= idx < len(df):
            df = df.drop(df.index[idx]).reset_index(drop=True)
            with pd.ExcelWriter(path_xlsx, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Atestados')
            flash('Registro excluído com sucesso.', 'success')
            # Sincroniza com Justificativas.xlsx
            _sync_justificativas()
        else:
            flash('Índice inválido.', 'danger')
    except Exception as e:
        flash(f'Erro ao excluir registro: {str(e)}', 'danger')

    return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

@bp.route('/atestado/edit/<int:idx>', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'editor')
def atestado_edit(idx):
    folder = current_app.config['UPLOAD_FOLDER']
    path_xlsx = os.path.join(folder, 'atestado_falta.xlsx')
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')

    if not os.path.exists(path_xlsx):
        flash('Arquivo de justificativas não encontrado.', 'danger')
        return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

    try:
        df = pd.read_excel(path_xlsx, sheet_name='Atestados', dtype=str)
        df = df.fillna('').astype(str)
        if not (0 <= idx < len(df)):
            flash('Índice inválido.', 'danger')
            return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

        if request.method == 'POST':
            discipline = request.form.get('discipline')
            collaborator = request.form.get('collaborator')
            date = request.form.get('date')
            deviation = request.form.get('deviation')

            if not all([discipline, collaborator, date, deviation]):
                flash('Todos os campos obrigatórios (Disciplina, Colaborador, Data, Desvio) devem ser preenchidos.', 'danger')
                return redirect(url_for('main.atestado_edit', idx=idx, file=sel_file, discipline=sel_disc))

            # Atualiza todos os campos dinamicamente
            df.at[idx, 'OBSERVAÇÃO'] = collaborator
            df.at[idx, 'DISCIPLINA'] = discipline
            df.at[idx, 'DATARDO_STR'] = date
            df.at[idx, 'DESVIO'] = deviation
            for col in df.columns:
                if col not in ['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'DESVIO']:
                    df.at[idx, col] = request.form.get(col, '').strip()

            with pd.ExcelWriter(path_xlsx, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Atestados')
            flash('Registro atualizado com sucesso.', 'success')
            # Sincroniza com Justificativas.xlsx
            _sync_justificativas()
            return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

        record = df.iloc[idx].to_dict()
        df_all = _load_df(sel_file) if sel_file else pd.DataFrame()
        disciplines_all = sorted(df_all['DISCIPLINA'].unique()) if not df_all.empty else []
        df_filtered = df_all[df_all['DISCIPLINA'] == sel_disc] if sel_disc != 'All' else df_all
        collaborators = sorted(df_filtered['OBSERVAÇÃO'].unique()) if not df_filtered.empty else []
        dates = sorted(df_filtered['DATARDO_STR'].unique()) if not df_filtered.empty else []
        deviations = ['Atestado', 'Ausente', 'SP', 'DEP']
        columns = df.columns.tolist()

        return render_template('atestado_edit.html',
            idx=idx,
            file=sel_file,
            disciplines=disciplines_all,
            selected_discipline=sel_disc,
            collaborators=collaborators,
            dates=dates,
            deviations=deviations,
            entry=record,
            columns=columns
        )
    except Exception as e:
        flash(f'Erro ao processar edição: {str(e)}', 'danger')
        return redirect(url_for('main.atestado', file=sel_file, discipline=sel_disc))

@bp.route('/validation')
@login_required
@roles_required('admin', 'editor')
def validation():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.xls', '.xlsx')))

    # 1) Data de corte (dia anterior ao atual)
    cutoff_date = datetime.now().date() - timedelta(days=1)
    logger.info(f"Data de corte para cobrança: {cutoff_date.strftime('%d/%m/%Y')}")

    # 2) Calendário
    cal_path = os.path.join(folder, 'calendar.xlsx')
    has_calendar = os.path.exists(cal_path)
    cobrar_days = set()
    if has_calendar:
        cal_df = pd.read_excel(cal_path, sheet_name=0, dtype={'DATA': object, 'COBRAR?': str})
        cal_df['DATA'] = pd.to_datetime(cal_df['DATA'], dayfirst=True, errors='coerce')
        cobrar_days = set(
            cal_df.loc[
                (cal_df['COBRAR?'].str.strip().str.lower() == 'sim') &
                (cal_df['DATA'].dt.date <= cutoff_date),
                'DATA'
            ].dt.strftime('%d/%m/%Y').dropna()
        )
    else:
        logger.info("Nenhum calendar.xlsx encontrado, usando todas as datas até o dia anterior.")

    # 3) Férias & INSS
    fer_inss = os.path.join(folder, 'ferias_inss.xlsx')
    if os.path.exists(fer_inss):
        vac_df = pd.read_excel(fer_inss, sheet_name='Férias')
        vac_df.columns = vac_df.columns.str.strip()
        col_map = {}
        for col in vac_df.columns:
            low = col.lower().replace('_', ' ').replace('-', ' ').strip()
            if 'início' in low or 'inicio' in low:
                col_map[col] = 'Férias - Início'
            if 'término' in low or 'termino' in low:
                col_map[col] = 'Férias - Término'
        vac_df = vac_df.rename(columns=col_map)
        vac_df['Férias - Início'] = pd.to_datetime(vac_df['Férias - Início'], dayfirst=True, errors='coerce').dt.date
        vac_df['Férias - Término'] = pd.to_datetime(vac_df['Férias - Término'], dayfirst=True, errors='coerce').dt.date
        vac_df['NOME'] = vac_df['NOME'].str.strip()
        vac_df['DISCIPLINA'] = vac_df['DISCIPLINA'].fillna('').astype(str)

        inss_df = pd.read_excel(fer_inss, sheet_name='INSS', dtype=str)
        inss_df['Início'] = pd.to_datetime(inss_df['Início'], dayfirst=False, errors='coerce').dt.date
        inss_df['Término'] = pd.to_datetime(inss_df['Término'], dayfirst=False, errors='coerce').dt.date
        inss_df['NOME'] = inss_df['NOME'].str.strip()
        inss_df['DISCIPLINA'] = inss_df['DISCIPLINA'].fillna('').astype(str)
    else:
        vac_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Férias - Início', 'Férias - Término'])
        inss_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Início', 'Término'])

    # 4) Efetivo, admissões e desligamentos
    ef_path = os.path.join(folder, 'Efetivo.xlsx')
    if os.path.exists(ef_path):
        all_eff = pd.read_excel(ef_path, sheet_name=0, dtype=str)
        status_col = all_eff.columns[2]
        eff_names = all_eff.loc[all_eff[status_col].str.strip() == 'MOD', all_eff.columns[0]].str.strip().tolist()
        eff_disciplines = all_eff.loc[all_eff[status_col].str.strip() == 'MOD', all_eff.columns[1]].str.strip().tolist()
        eff_df = pd.DataFrame({'OBSERVAÇÃO': eff_names, 'DISCIPLINA': eff_disciplines})

        adm_raw = pd.read_excel(ef_path, sheet_name=1, dtype=str)
        adm_df = pd.DataFrame({
            'OBSERVAÇÃO': adm_raw.iloc[:, 0].str.strip(),
            'DISCIPLINA': adm_raw.iloc[:, 1].fillna('').astype(str),
            'DATA': pd.to_datetime(adm_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
        })

        term_raw = pd.read_excel(ef_path, sheet_name=2, dtype=str)
        term_df = pd.DataFrame({
            'OBSERVAÇÃO': term_raw.iloc[:, 0].str.strip(),
            'DISCIPLINA': term_raw.iloc[:, 1].fillna('').astype(str),
            'DATA': pd.to_datetime(term_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
        })
    else:
        eff_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA'])
        eff_names = []
        adm_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])
        term_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])

    # 5) Justificativas
    just_path = os.path.join(folder, 'Justificativas.xlsx')
    if os.path.exists(just_path):
        just_raw = pd.read_excel(just_path, sheet_name='Justificativas')
        just_raw['OBSERVAÇÃO'] = just_raw['OBSERVAÇÃO'].str.strip()
        just_raw['DISCIPLINA'] = just_raw['DISCIPLINA'].fillna('').str.strip()
        just_raw['DATA'] = pd.to_datetime(just_raw['DATA'], dayfirst=True, errors='coerce')
        just_raw['DATARDO_STR'] = just_raw['DATA'].dt.strftime('%d/%m/%Y')
        just_raw['FRENTE DE TRABALHO'] = just_raw['FRENTE DE TRABALHO'].fillna('').astype(str)
        just_raw['CODIGO'] = just_raw['CODIGO'].fillna('').astype(str).str.strip()
        just_df = just_raw[['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO']]
    else:
        just_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO'])

    # 6) Prepara pivot
    pivot = []
    dates_list = []
    disciplines = []
    columns = []

    if sel_file:
        # 6.1) Carrega e normaliza horas
        df = _load_df(sel_file)
        for std in ['HORA NORMAL', 'HORA EXTRA']:
            if std not in df.columns:
                m = next((c for c in df.columns if c.strip().lower() == std.lower()), None)
                if m:
                    df.rename(columns={m: std}, inplace=True)
                else:
                    df[std] = 0.0

        df = df[df['OBSERVAÇÃO'].isin(eff_names)]

        # 6.2) DATARDO_STR
        if 'DATARDO_STR' not in df.columns and 'DATARDO' in df.columns:
            df['DATARDO_STR'] = pd.to_datetime(df['DATARDO'], dayfirst=True, errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
        elif 'DATARDO_STR' not in df.columns:
            df['DATARDO_STR'] = ''

        # 6.3) Determina o mês e todos os dias até cutoff_date
        if df['DATARDO_STR'].notna().any():
            dates = pd.to_datetime(df['DATARDO_STR'], format='%d/%m/%Y', errors='coerce')
            month = dates.dt.to_period('M').iloc[0] if dates.notna().any() else pd.Timestamp('2025-07-01').to_period('M')
        else:
            month = pd.Timestamp('2025-07-01').to_period('M')
        month_start = month.start_time.date()
        month_end = min(month.end_time.date(), cutoff_date)
        all_dates = pd.date_range(month_start, month_end, freq='D')
        dates_list = [dt.strftime('%d/%m/%Y') for dt in all_dates]
        columns = ['OBSERVAÇÃO', 'DISCIPLINA'] + dates_list

        if sel_disc != 'All':
            df = df[df['DISCIPLINA'] == sel_disc]
            eff_df = eff_df[eff_df['DISCIPLINA'] == sel_disc]

        disciplines = sorted(df['DISCIPLINA'].unique())
        if sel_disc == 'All':
            disciplines = sorted(eff_df['DISCIPLINA'].unique())

        # 6.4) Agrupa e pivota
        grp = df.groupby(['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], as_index=False).agg({'HORA NORMAL': 'sum', 'HORA EXTRA': 'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
        table = grp.pivot(index=['OBSERVAÇÃO', 'DISCIPLINA'], columns='DATARDO_STR', values='TOTAL_HH').reset_index().fillna(0)

        # 6.5) Adiciona colaboradores sem registros
        names_src = pd.concat([
            vac_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            inss_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            eff_df[['OBSERVAÇÃO', 'DISCIPLINA']]
        ]).drop_duplicates()
        extra = []
        for _, src in names_src.iterrows():
            nome, disc = src['OBSERVAÇÃO'], src['DISCIPLINA']
            if sel_disc != 'All' and disc != sel_disc:
                continue
            if nome in eff_names and not ((table['OBSERVAÇÃO'] == nome) & (table['DISCIPLINA'] == disc)).any():
                row = {'OBSERVAÇÃO': nome, 'DISCIPLINA': disc}
                for dt in dates_list:
                    row[dt] = 0.0
                extra.append(row)
        if extra:
            table = pd.concat([table, pd.DataFrame(extra)], ignore_index=True)

        # 6.6) Preenche células
        for _, row in table.iterrows():
            rec = {'OBSERVAÇÃO': row['OBSERVAÇÃO'], 'DISCIPLINA': row['DISCIPLINA']}
            for dt in dates_list:
                if has_calendar and dt not in cobrar_days:
                    raw = row.get(dt, 0.0)
                    if raw == 0 or pd.isna(raw):
                        rec[dt] = ''
                        rec[f'{dt}_class'] = 'code-nocharge'
                        logger.debug(f"Assigned code-nocharge for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    else:
                        rec[dt] = f"{raw:.2f}".replace('.', ',')
                        rec[f'{dt}_class'] = 'hours-cell'
                        logger.debug(f"Assigned hours {rec[dt]} for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                sub_j = just_df[(just_df['OBSERVAÇÃO'] == row['OBSERVAÇÃO']) & (just_df['DISCIPLINA'] == row['DISCIPLINA']) & (just_df['DATARDO_STR'] == dt)]
                if not sub_j.empty:
                    code = sub_j['CODIGO'].iloc[0]
                    text = sub_j['FRENTE DE TRABALHO'].iloc[0]
                    rec[dt] = code
                    rec[f'{dt}_class'] = f'code-{code}'
                    rec[f'{dt}_title'] = text
                    logger.debug(f"Assigned code-{code} for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                dt_date = datetime.strptime(dt, '%d/%m/%Y').date()

                sub_t = term_df[(term_df['OBSERVAÇÃO'] == row['OBSERVAÇÃO']) & (term_df['DISCIPLINA'] == row['DISCIPLINA'])]
                if not sub_t.empty and dt_date > sub_t['DATA'].iloc[0]:
                    rec[dt] = 'DL'
                    rec[f'{dt}_class'] = 'code-DL'
                    logger.debug(f"Assigned code-DL for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                sub_v = vac_df[(vac_df['NOME'] == row['OBSERVAÇÃO']) & (vac_df['DISCIPLINA'] == row['DISCIPLINA'])]
                if any(v['Férias - Início'] <= dt_date <= v['Férias - Término'] for _, v in sub_v.iterrows()):
                    rec[dt] = 'F'
                    rec[f'{dt}_class'] = 'code-F'
                    logger.debug(f"Assigned code-F for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                sub_i = inss_df[(inss_df['NOME'] == row['OBSERVAÇÃO']) & (inss_df['DISCIPLINA'] == row['DISCIPLINA'])]
                if any(i['Início'] <= dt_date <= i['Término'] for _, i in sub_i.iterrows()):
                    rec[dt] = 'I'
                    rec[f'{dt}_class'] = 'code-I'
                    logger.debug(f"Assigned code-I for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                sub_a = adm_df[(adm_df['OBSERVAÇÃO'] == row['OBSERVAÇÃO']) & (adm_df['DISCIPLINA'] == row['DISCIPLINA'])]
                if not sub_a.empty and dt_date < sub_a['DATA'].iloc[0]:
                    rec[dt] = 'AG'
                    rec[f'{dt}_class'] = 'code-AG'
                    logger.debug(f"Assigned code-AG for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                    continue

                raw = row.get(dt, 0.0)
                if raw == 0 or pd.isna(raw):
                    rec[dt] = 'X'
                    rec[f'{dt}_class'] = 'empty-cell'
                    logger.debug(f"Assigned empty-cell for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")
                else:
                    rec[dt] = f"{raw:.2f}".replace('.', ',')
                    rec[f'{dt}_class'] = 'hours-cell'
                    logger.debug(f"Assigned hours {rec[dt]} for {row['OBSERVAÇÃO']} | {row['DISCIPLINA']} | {dt}")

            pivot.append(rec)

        pivot = sorted(pivot, key=lambda x: (x['DISCIPLINA'], x['OBSERVAÇÃO']))

    logger.info(f"Rendering validation.html with {len(pivot)} pivot records")
    return render_template(
        'validation.html',
        files=files,
        selected_file=sel_file,
        disciplines=disciplines,
        selected_discipline=sel_disc,
        dates=dates_list,
        columns=columns,
        pivot=pivot
    )

@bp.route('/pending')
@login_required
@roles_required('admin', 'editor')
def pending():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')
    sel_date = request.args.get('date', 'All')
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.xls', '.xlsx')))

    pending_lines = []
    disciplines = []
    dates = []

    if sel_file:
        # 1) Data de corte (dia anterior ao atual)
        cutoff_date = datetime.now().date() - timedelta(days=1)
        logger.info(f"Data de corte para cobrança: {cutoff_date.strftime('%d/%m/%Y')}")

        df = _load_df(sel_file)
        for std in ['HORA NORMAL', 'HORA EXTRA']:
            if std not in df.columns:
                m = next((c for c in df.columns if c.strip().lower() == std.lower()), None)
                if m:
                    df.rename(columns={m: std}, inplace=True)
                else:
                    df[std] = 0.0

        ef_path = os.path.join(folder, 'Efetivo.xlsx')
        eff_names = []
        if os.path.exists(ef_path):
            all_eff = pd.read_excel(ef_path, sheet_name=0, dtype=str)
            status_col = all_eff.columns[2]
            eff_names = all_eff.loc[all_eff[status_col].str.strip() == 'MOD', all_eff.columns[0]].str.strip().tolist()
            eff_disciplines = all_eff.loc[all_eff[status_col].str.strip() == 'MOD', all_eff.columns[1]].str.strip().tolist()
            eff_df = pd.DataFrame({'OBSERVAÇÃO': eff_names, 'DISCIPLINA': eff_disciplines})
            df = df[df['OBSERVAÇÃO'].isin(eff_names)]
        else:
            eff_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA'])

        if 'DATARDO_STR' not in df.columns and 'DATARDO' in df.columns:
            df['DATARDO_STR'] = pd.to_datetime(df['DATARDO'], dayfirst=True, errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
        elif 'DATARDO_STR' not in df.columns:
            df['DATARDO_STR'] = ''

        # 2) Determina o mês e todos os dias até cutoff_date
        if df['DATARDO_STR'].notna().any():
            dates_series = pd.to_datetime(df['DATARDO_STR'], format='%d/%m/%Y', errors='coerce')
            month = dates_series.dt.to_period('M').iloc[0] if dates_series.notna().any() else pd.Timestamp('2025-07-01').to_period('M')
        else:
            month = pd.Timestamp('2025-07-01').to_period('M')
        month_start = month.start_time.date()
        month_end = min(month.end_time.date(), cutoff_date)
        all_dates = pd.date_range(month_start, month_end, freq='D')

        # 3) Filtra dias cobráveis
        cal_path = os.path.join(folder, 'calendar.xlsx')
        has_calendar = os.path.exists(cal_path)
        cobrar_days = set()
        if has_calendar:
            cal_df = pd.read_excel(cal_path, sheet_name=0, dtype={'DATA': object, 'COBRAR?': str})
            cal_df['DATA'] = pd.to_datetime(cal_df['DATA'], dayfirst=True, errors='coerce')
            cobrar_days = set(
                cal_df.loc[
                    (cal_df['COBRAR?'].str.strip().str.lower() == 'sim') &
                    (cal_df['DATA'].dt.date <= cutoff_date),
                    'DATA'
                ].dt.strftime('%d/%m/%Y').dropna()
            )
        dates = [dt.strftime('%d/%m/%Y') for dt in all_dates if has_calendar and dt.strftime('%d/%m/%Y') in cobrar_days or not has_calendar]

        if sel_disc != 'All':
            df = df[df['DISCIPLINA'] == sel_disc]
            eff_df = eff_df[eff_df['DISCIPLINA'] == sel_disc]

        disciplines = sorted(df['DISCIPLINA'].unique())
        if sel_disc == 'All':
            disciplines = sorted(eff_df['DISCIPLINA'].unique())

        # 4) Agrupa e pivota
        grp = df.groupby(['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], as_index=False).agg({'HORA NORMAL': 'sum', 'HORA EXTRA': 'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
        table = grp.pivot(index=['OBSERVAÇÃO', 'DISCIPLINA'], columns='DATARDO_STR', values='TOTAL_HH').reset_index().fillna(0)

        # 5) Adiciona colaboradores sem registros
        fer_inss = os.path.join(folder, 'ferias_inss.xlsx')
        if os.path.exists(fer_inss):
            vac_df = pd.read_excel(fer_inss, sheet_name='Férias')
            vac_df.columns = vac_df.columns.str.strip()
            col_map = {}
            for col in vac_df.columns:
                low = col.lower().replace('_', ' ').replace('-', ' ').strip()
                if 'início' in low or 'inicio' in low:
                    col_map[col] = 'Férias - Início'
                if 'término' in low or 'termino' in low:
                    col_map[col] = 'Férias - Término'
            vac_df = vac_df.rename(columns=col_map)
            vac_df['Férias - Início'] = pd.to_datetime(vac_df['Férias - Início'], dayfirst=True, errors='coerce').dt.date
            vac_df['Férias - Término'] = pd.to_datetime(vac_df['Férias - Término'], dayfirst=True, errors='coerce').dt.date
            vac_df['NOME'] = vac_df['NOME'].str.strip()
            vac_df['DISCIPLINA'] = vac_df['DISCIPLINA'].fillna('').astype(str)

            inss_df = pd.read_excel(fer_inss, sheet_name='INSS', dtype=str)
            inss_df['Início'] = pd.to_datetime(inss_df['Início'], dayfirst=False, errors='coerce').dt.date
            inss_df['Término'] = pd.to_datetime(inss_df['Término'], dayfirst=False, errors='coerce').dt.date
            inss_df['NOME'] = inss_df['NOME'].str.strip()
            inss_df['DISCIPLINA'] = inss_df['DISCIPLINA'].fillna('').astype(str)
        else:
            vac_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Férias - Início', 'Férias - Término'])
            inss_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Início', 'Término'])

        if os.path.exists(ef_path):
            adm_raw = pd.read_excel(ef_path, sheet_name=1, dtype=str)
            adm_df = pd.DataFrame({
                'OBSERVAÇÃO': adm_raw.iloc[:, 0].str.strip(),
                'DISCIPLINA': adm_raw.iloc[:, 1].fillna('').astype(str),
                'DATA': pd.to_datetime(adm_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
            })
            term_raw = pd.read_excel(ef_path, sheet_name=2, dtype=str)
            term_df = pd.DataFrame({
                'OBSERVAÇÃO': term_raw.iloc[:, 0].str.strip(),
                'DISCIPLINA': term_raw.iloc[:, 1].fillna('').astype(str),
                'DATA': pd.to_datetime(term_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
            })
        else:
            adm_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])
            term_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])

        just_path = os.path.join(folder, 'Justificativas.xlsx')
        if os.path.exists(just_path):
            just_raw = pd.read_excel(just_path, sheet_name='Justificativas')
            just_raw['OBSERVAÇÃO'] = just_raw['OBSERVAÇÃO'].str.strip()
            just_raw['DISCIPLINA'] = just_raw['DISCIPLINA'].fillna('').str.strip()
            just_raw['DATA'] = pd.to_datetime(just_raw['DATA'], dayfirst=True, errors='coerce')
            just_raw['DATARDO_STR'] = just_raw['DATA'].dt.strftime('%d/%m/%Y')
            just_raw['FRENTE DE TRABALHO'] = just_raw['FRENTE DE TRABALHO'].fillna('').astype(str)
            just_raw['CODIGO'] = just_raw['CODIGO'].fillna('').astype(str).str.strip()
            just_df = just_raw[['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO']]
        else:
            just_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO'])

        names_src = pd.concat([
            vac_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            inss_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            eff_df[['OBSERVAÇÃO', 'DISCIPLINA']]
        ]).drop_duplicates()
        extra = []
        for _, src in names_src.iterrows():
            nome, disc = src['OBSERVAÇÃO'], src['DISCIPLINA']
            if sel_disc != 'All' and disc != sel_disc:
                continue
            if nome in eff_names and not ((table['OBSERVAÇÃO'] == nome) & (table['DISCIPLINA'] == disc)).any():
                row = {'OBSERVAÇÃO': nome, 'DISCIPLINA': disc}
                for dt in dates:
                    row[dt] = 0.0
                extra.append(row)
        if extra:
            table = pd.concat([table, pd.DataFrame(extra)], ignore_index=True)

        for _, row in table.iterrows():
            nome = row['OBSERVAÇÃO']
            disc = row['DISCIPLINA']
            if sel_disc != 'All' and disc != sel_disc:
                continue
            for dt in dates:
                if sel_date != 'All' and dt != sel_date:
                    continue
                if has_calendar and dt not in cobrar_days:
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (not chargeable)")
                    continue
                sub_j = just_df[
                    (just_df['OBSERVAÇÃO'] == nome) &
                    (just_df['DISCIPLINA'] == disc) &
                    (just_df['DATARDO_STR'] == dt)
                ]
                if not sub_j.empty:
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (has justification)")
                    continue
                dt_date = datetime.strptime(dt, '%d/%m/%Y').date()
                sub_t = term_df[
                    (term_df['OBSERVAÇÃO'] == nome) &
                    (term_df['DISCIPLINA'] == disc)
                ]
                if not sub_t.empty and dt_date > sub_t['DATA'].iloc[0]:
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (terminated)")
                    continue
                sub_v = vac_df[
                    (vac_df['NOME'] == nome) &
                    (vac_df['DISCIPLINA'] == disc)
                ]
                if any(v['Férias - Início'] <= dt_date <= v['Férias - Término'] for _, v in sub_v.iterrows()):
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (on vacation)")
                    continue
                sub_i = inss_df[
                    (inss_df['NOME'] == nome) &
                    (inss_df['DISCIPLINA'] == disc)
                ]
                if any(i['Início'] <= dt_date <= i['Término'] for _, i in sub_i.iterrows()):
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (on INSS)")
                    continue
                sub_a = adm_df[
                    (adm_df['OBSERVAÇÃO'] == nome) &
                    (adm_df['DISCIPLINA'] == disc)
                ]
                if not sub_a.empty and dt_date < sub_a['DATA'].iloc[0]:
                    logger.debug(f"Skipping {dt} for {nome} | {disc} (pre-admission)")
                    continue
                raw = row.get(dt, 0.0)
                if raw == 0 or pd.isna(raw):
                    logger.debug(f"Pending record added: {nome} | {disc} | {dt}")
                    pending_lines.append({
                        'NOME': nome,
                        'DISCIPLINA': disc,
                        'DATA': dt
                    })

    logger.info(f"[Pending] {len(pending_lines)} registros pendentes encontrados")

    return render_template('pending.html',
        files=files,
        selected_file=sel_file,
        disciplines=disciplines,
        dates=dates,
        selected_discipline=sel_disc,
        selected_date=sel_date,
        pending_lines=pending_lines
    )

@bp.route('/export_pendentes')
@login_required
@roles_required('admin', 'editor')
def export_pendentes():
    folder = current_app.config['UPLOAD_FOLDER']
    sel_file = request.args.get('file')
    sel_disc = request.args.get('discipline', 'All')
    sel_date = request.args.get('date', 'All')

    pending_lines = []

    if sel_file:
        cutoff_date = datetime.now().date() - timedelta(days=1)
        logger.info(f"Data de corte para exportação de pendentes: {cutoff_date.strftime('%d/%m/%Y')}")

        df = _load_df(sel_file)
        for std in ('HORA NORMAL', 'HORA EXTRA'):
            df[std] = pd.to_numeric(df.get(std, 0.0), errors='coerce').fillna(0.0)

        ef_path = os.path.join(folder, 'Efetivo.xlsx')
        eff_names = []
        if os.path.exists(ef_path):
            eff = pd.read_excel(ef_path, sheet_name=0, dtype=str)
            status_col = eff.columns[2]
            eff_names = eff.loc[eff[status_col].str.strip() == 'MOD', eff.columns[0]].str.strip().tolist()
            eff_disciplines = eff.loc[eff[status_col].str.strip() == 'MOD', eff.columns[1]].str.strip().tolist()
            eff_df = pd.DataFrame({'OBSERVAÇÃO': eff_names, 'DISCIPLINA': eff_disciplines})
            df = df[df['OBSERVAÇÃO'].isin(eff_names)]
        else:
            eff_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA'])

        if 'DATARDO_STR' not in df.columns and 'DATARDO' in df.columns:
            df['DATARDO_STR'] = pd.to_datetime(df['DATARDO'], dayfirst=True, errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
        elif 'DATARDO_STR' not in df.columns:
            df['DATARDO_STR'] = ''

        if df['DATARDO_STR'].notna().any():
            dates_series = pd.to_datetime(df['DATARDO_STR'], format='%d/%m/%Y', errors='coerce')
            month = dates_series.dt.to_period('M').iloc[0] if dates_series.notna().any() else pd.Timestamp('2025-07-01').to_period('M')
        else:
            month = pd.Timestamp('2025-07-01').to_period('M')
        month_start = month.start_time.date()
        month_end = min(month.end_time.date(), cutoff_date)
        all_dates = pd.date_range(month_start, month_end, freq='D')

        cal_path = os.path.join(folder, 'calendar.xlsx')
        has_calendar = os.path.exists(cal_path)
        cobrar_days = set()
        if has_calendar:
            cal_df = pd.read_excel(cal_path, sheet_name=0, dtype={'DATA': object, 'COBRAR?': str})
            cal_df['DATA'] = pd.to_datetime(cal_df['DATA'], dayfirst=True, errors='coerce')
            cobrar_days = set(
                cal_df.loc[
                    (cal_df['COBRAR?'].str.strip().str.lower() == 'sim') &
                    (cal_df['DATA'].dt.date <= cutoff_date),
                    'DATA'
                ].dt.strftime('%d/%m/%Y').dropna()
            )
        dates = [dt.strftime('%d/%m/%Y') for dt in all_dates if has_calendar and dt.strftime('%d/%m/%Y') in cobrar_days or not has_calendar]

        if sel_disc != 'All':
            df = df[df['DISCIPLINA'] == sel_disc]
            eff_df = eff_df[eff_df['DISCIPLINA'] == sel_disc]

        grp = df.groupby(['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR'], as_index=False).agg({'HORA NORMAL': 'sum', 'HORA EXTRA': 'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
        table = grp.pivot(index=['OBSERVAÇÃO', 'DISCIPLINA'], columns='DATARDO_STR', values='TOTAL_HH').reset_index().fillna(0)

        fer_inss = os.path.join(folder, 'ferias_inss.xlsx')
        if os.path.exists(fer_inss):
            vac_df = pd.read_excel(fer_inss, sheet_name='Férias')
            vac_df.columns = vac_df.columns.str.strip()
            col_map = {}
            for col in vac_df.columns:
                low = col.lower().replace('_', ' ').replace('-', ' ').strip()
                if 'início' in low or 'inicio' in low:
                    col_map[col] = 'Férias - Início'
                if 'término' in low or 'termino' in low:
                    col_map[col] = 'Férias - Término'
            vac_df = vac_df.rename(columns=col_map)
            vac_df['Férias - Início'] = pd.to_datetime(vac_df['Férias - Início'], dayfirst=True, errors='coerce').dt.date
            vac_df['Férias - Término'] = pd.to_datetime(vac_df['Férias - Término'], dayfirst=True, errors='coerce').dt.date
            vac_df['NOME'] = vac_df['NOME'].str.strip()
            vac_df['DISCIPLINA'] = vac_df['DISCIPLINA'].fillna('').astype(str)

            inss_df = pd.read_excel(fer_inss, sheet_name='INSS', dtype=str)
            inss_df['Início'] = pd.to_datetime(inss_df['Início'], dayfirst=False, errors='coerce').dt.date
            inss_df['Término'] = pd.to_datetime(inss_df['Término'], dayfirst=False, errors='coerce').dt.date
            inss_df['NOME'] = inss_df['NOME'].str.strip()
            inss_df['DISCIPLINA'] = inss_df['DISCIPLINA'].fillna('').astype(str)
        else:
            vac_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Férias - Início', 'Férias - Término'])
            inss_df = pd.DataFrame(columns=['NOME', 'DISCIPLINA', 'Início', 'Término'])

        if os.path.exists(ef_path):
            adm_raw = pd.read_excel(ef_path, sheet_name=1, dtype=str)
            adm_df = pd.DataFrame({
                'OBSERVAÇÃO': adm_raw.iloc[:, 0].str.strip(),
                'DISCIPLINA': adm_raw.iloc[:, 1].fillna('').astype(str),
                'DATA': pd.to_datetime(adm_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
            })
            term_raw = pd.read_excel(ef_path, sheet_name=2, dtype=str)
            term_df = pd.DataFrame({
                'OBSERVAÇÃO': term_raw.iloc[:, 0].str.strip(),
                'DISCIPLINA': term_raw.iloc[:, 1].fillna('').astype(str),
                'DATA': pd.to_datetime(term_raw.iloc[:, 2], dayfirst=False, errors='coerce').dt.date
            })
        else:
            adm_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])
            term_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATA'])

        just_path = os.path.join(folder, 'Justificativas.xlsx')
        if os.path.exists(just_path):
            just_raw = pd.read_excel(just_path, sheet_name='Justificativas')
            just_raw['OBSERVAÇÃO'] = just_raw['OBSERVAÇÃO'].str.strip()
            just_raw['DISCIPLINA'] = just_raw['DISCIPLINA'].fillna('').str.strip()
            just_raw['DATA'] = pd.to_datetime(just_raw['DATA'], dayfirst=True, errors='coerce')
            just_raw['DATARDO_STR'] = just_raw['DATA'].dt.strftime('%d/%m/%Y')
            just_raw['FRENTE DE TRABALHO'] = just_raw['FRENTE DE TRABALHO'].fillna('').astype(str)
            just_raw['CODIGO'] = just_raw['CODIGO'].fillna('').astype(str).str.strip()
            just_df = just_raw[['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO']]
        else:
            just_df = pd.DataFrame(columns=['OBSERVAÇÃO', 'DISCIPLINA', 'DATARDO_STR', 'FRENTE DE TRABALHO', 'CODIGO'])

        names_src = pd.concat([
            vac_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            inss_df[['NOME', 'DISCIPLINA']].rename(columns={'NOME': 'OBSERVAÇÃO'}),
            eff_df[['OBSERVAÇÃO', 'DISCIPLINA']]
        ]).drop_duplicates()
        extra = []
        for _, src in names_src.iterrows():
            nome, disc = src['OBSERVAÇÃO'], src['DISCIPLINA']
            if sel_disc != 'All' and disc != sel_disc:
                continue
            if nome in eff_names and not ((table['OBSERVAÇÃO'] == nome) & (table['DISCIPLINA'] == disc)).any():
                row = {'OBSERVAÇÃO': nome, 'DISCIPLINA': disc}
                for dt in dates:
                    row[dt] = 0.0
                extra.append(row)
        if extra:
            table = pd.concat([table, pd.DataFrame(extra)], ignore_index=True)

        for _, row in table.iterrows():
            nome = row['OBSERVAÇÃO']
            disc = row['DISCIPLINA']
            if sel_disc != 'All' and disc != sel_disc:
                continue
            for dt in dates:
                if sel_date != 'All' and dt != sel_date:
                    continue
                if has_calendar and dt not in cobrar_days:
                    continue
                sub_j = just_df[
                    (just_df['OBSERVAÇÃO'] == nome) &
                    (just_df['DISCIPLINA'] == disc) &
                    (just_df['DATARDO_STR'] == dt)
                ]
                if not sub_j.empty:
                    continue
                dt_date = datetime.strptime(dt, '%d/%m/%Y').date()
                sub_t = term_df[
                    (term_df['OBSERVAÇÃO'] == nome) &
                    (term_df['DISCIPLINA'] == disc)
                ]
                if not sub_t.empty and dt_date > sub_t['DATA'].iloc[0]:
                    continue
                sub_v = vac_df[
                    (vac_df['NOME'] == nome) &
                    (vac_df['DISCIPLINA'] == disc)
                ]
                if any(v['Férias - Início'] <= dt_date <= v['Férias - Término'] for _, v in sub_v.iterrows()):
                    continue
                sub_i = inss_df[
                    (inss_df['NOME'] == nome) &
                    (inss_df['DISCIPLINA'] == disc)
                ]
                if any(i['Início'] <= dt_date <= i['Término'] for _, i in sub_i.iterrows()):
                    continue
                sub_a = adm_df[
                    (adm_df['OBSERVAÇÃO'] == nome) &
                    (adm_df['DISCIPLINA'] == disc)
                ]
                if not sub_a.empty and dt_date < sub_a['DATA'].iloc[0]:
                    continue
                raw = row.get(dt, 0.0)
                if raw == 0 or pd.isna(raw):
                    pending_lines.append({
                        'NOME': nome,
                        'DISCIPLINA': disc,
                        'DATA': dt
                    })

    df_export = pd.DataFrame(pending_lines, columns=['NOME', 'DISCIPLINA', 'DATA'])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Pendentes')
    buf.seek(0)

    return send_file(
        buf,
        download_name="pendentes_completos.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
