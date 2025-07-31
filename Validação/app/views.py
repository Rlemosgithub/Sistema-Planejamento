import os
import csv
import pandas as pd
from flask import (
    Blueprint, current_app, render_template,
    request, redirect, url_for, flash
)

bp = Blueprint('main', __name__)

def _load_df(filename):
    """Lê o Excel de A até M (sempre fresco) e formata colunas básicas."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    df = pd.read_excel(
        path,
        sheet_name='Sheet1',
        usecols='A:M',
        dtype=str,
        na_filter=False,
        engine='openpyxl'
    )

    # Datas
    df['DATARDO']     = pd.to_datetime(df['DATARDO'], dayfirst=True, errors='coerce')
    df['DATARDO_STR'] = df['DATARDO'].dt.strftime('%d/%m/%Y').fillna('')

    # Horas numéricas
    df['HORA NORMAL'] = pd.to_numeric(df['HORA NORMAL'], errors='coerce').fillna(0.0)
    df['HORA EXTRA']  = pd.to_numeric(df['HORA EXTRA'], errors='coerce').fillna(0.0)

    # Texto
    for c in ['ORDEM','OPERAÇÃO','T_ATIV','OBSERVAÇÃO']:
        if c in df.columns:
            df[c] = df[c].fillna('').astype(str)

    # Mapeamento de disciplina
    map_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'mapping.xlsx')
    if os.path.exists(map_path):
        dm = pd.read_excel(map_path, dtype=str, na_filter=False).iloc[:, :2]
        dm.columns = ['OBSERVAÇÃO','DISCIPLINA']
        dm = dm.drop_duplicates('OBSERVAÇÃO', keep='first')
        df = df.merge(dm, on='OBSERVAÇÃO', how='left')
    if 'DISCIPLINA' not in df.columns:
        df['DISCIPLINA'] = ''
    df['DISCIPLINA'] = df['DISCIPLINA'].fillna('').astype(str)

    return df

@bp.route('/')
def dashboard():
    folder   = current_app.config['UPLOAD_FOLDER']
    files    = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.xls','.xlsx')))
    sel_file = request.args.get('file') or (files[0] if files else None)
    sel_disc = request.args.get('discipline', 'All')
    sel_date = request.args.get('date', 'All')
    sel_err  = request.args.get('error', 'All')

    cards       = []
    entries     = []
    disciplines = []
    dates       = []
    total = coll = 0

    if sel_file:
        # 1) sempre lê A:M via _load_df
        df = _load_df(sel_file)

        # 2) calcula TOTAl_HH e ERROR por colaborador+disciplina+data
        grp = df.groupby(
            ['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR'],
            as_index=False
        ).agg({'HORA NORMAL':'sum','HORA EXTRA':'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']
        tol = 0.01
        def is_error(v):
            if 7.95 <= v <= 8.80: return False
            if abs(v - 9.00) <= tol or abs(v - 10.00) <= tol: return False
            return True
        grp['ERROR'] = grp['TOTAL_HH'].apply(is_error)

        # 3) mapeia de volta em df para cada linha original
        df = df.merge(
            grp[['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','TOTAL_HH','ERROR']],
            on=['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR'],
            how='left'
        )

        # 4) prepara listas para filtros
        disciplines = sorted(df['DISCIPLINA'].unique())
        dates       = sorted(df['DATARDO_STR'].unique())

        # 5) aplica filtros
        if sel_disc != 'All':
            df = df[df['DISCIPLINA'] == sel_disc]
        if sel_date != 'All':
            df = df[df['DATARDO_STR'] == sel_date]
        if sel_err != 'All':
            flag = (sel_err == 'Erro')
            df = df[df['ERROR'] == flag]

        # 6) prepara métricas e registros
        total = len(df)
        coll  = df['OBSERVAÇÃO'].nunique()
        cards = [
            {'title':'Registros','value':total,'icon':'fa-file-alt'},
            {'title':'Colaboradores','value':coll,'icon':'fa-users'}
        ]
        entries = df.to_dict(orient='records')

    return render_template('dashboard.html',
        files=files,
        selected_file=sel_file,
        disciplines=disciplines,
        selected_discipline=sel_disc,
        dates=dates,
        selected_date=sel_date,
        error_options=['All','Ok','Erro'],
        selected_error=sel_err,
        cards=cards,
        entries=entries
    )


@bp.route('/upload', methods=['GET','POST'])
def upload():
    if request.method=='POST':
        h = request.files.get('file')
        d = request.files.get('discipline_file')
        if h and h.filename.lower().endswith(('.xls','.xlsx')):
            h.save(os.path.join(current_app.config['UPLOAD_FOLDER'], h.filename))
            flash('Horas carregadas!','success')
        if d and d.filename.lower().endswith(('.xls','.xlsx')):
            d.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'mapping.xlsx'))
            flash('Disciplinas carregadas!','success')
        return redirect(url_for('main.dashboard'))
    return render_template('upload.html')


@bp.route('/atestado', methods=['GET','POST'])
def atestado():
    folder        = current_app.config['UPLOAD_FOLDER']
    sel_file      = request.args.get('file')
    df            = _load_df(sel_file) if sel_file else pd.DataFrame()
    disciplines   = sorted(df['DISCIPLINA'].unique())
    collaborators = sorted(df['OBSERVAÇÃO'].unique())
    dates         = sorted(df['DATARDO_STR'].unique())
    deviations    = ['Atestado','Ausente','SP','DEP']

    csv_path = os.path.join(folder,'justificativas.csv')
    just_df  = (pd.read_csv(csv_path, dtype=str) if os.path.exists(csv_path)
                else pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','DESVIO']))

    if request.method=='POST':
        disc = request.form['discipline']
        coll = request.form['collaborator']
        date = request.form['date']
        dev  = request.form['deviation']
        exists = os.path.exists(csv_path)
        with open(csv_path,'a',newline='',encoding='utf-8') as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','DESVIO'])
            w.writerow([coll,disc,date,dev])
        flash('Justificativa salva!','success')
        return redirect(url_for('main.atestado',file=sel_file))

    return render_template('atestado.html',
        file=sel_file,
        disciplines=disciplines,
        collaborators=collaborators,
        dates=dates,
        deviations=deviations,
        justificativas=just_df.to_dict('records')
    )


@bp.route('/atestado/delete/<int:idx>', methods=['POST'])
def atestado_delete(idx):
    folder   = current_app.config['UPLOAD_FOLDER']
    csv_path = os.path.join(folder,'justificativas.csv')
    df = pd.read_csv(csv_path, dtype=str)
    df = df.drop(df.index[idx]).reset_index(drop=True)
    df.to_csv(csv_path, index=False)
    flash('Justificativa excluída','warning')
    return redirect(request.referrer or url_for('main.atestado',file=request.args.get('file')))


@bp.route('/atestado/edit/<int:idx>', methods=['GET','POST'])
def atestado_edit(idx):
    folder   = current_app.config['UPLOAD_FOLDER']
    csv_path = os.path.join(folder,'justificativas.csv')
    df = pd.read_csv(csv_path, dtype=str)
    if request.method=='POST':
        df.at[idx,'DISCIPLINA']   = request.form['discipline']
        df.at[idx,'OBSERVAÇÃO']   = request.form['collaborator']
        df.at[idx,'DATARDO_STR']  = request.form['date']
        df.at[idx,'DESVIO']       = request.form['deviation']
        df.to_csv(csv_path, index=False)
        flash('Justificativa atualizada','success')
        return redirect(url_for('main.atestado',file=request.args.get('file')))

    row = df.iloc[idx]
    return render_template('atestado_edit.html',
        idx=idx,
        file=request.args.get('file'),
        disciplines=sorted(df['DISCIPLINA'].unique()),
        collaborators=sorted(df['OBSERVAÇÃO'].unique()),
        dates=sorted(df['DATARDO_STR'].unique()),
        deviations=['Atestado','Ausente','SP','DEP'],
        entry=row.to_dict()
    )


@bp.route('/validation')
def validation():
    folder     = current_app.config['UPLOAD_FOLDER']
    files      = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.xls','.xlsx')))
    sel_file   = request.args.get('file')
    sel_disc   = request.args.get('discipline','All')

    pivot = []
    dates_list = []
    disciplines = []
    just_path = os.path.join(folder,'justificativas.csv')
    just_df   = (pd.read_csv(just_path, dtype=str) if os.path.exists(just_path)
                 else pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','DESVIO']))

    if sel_file:
        df = _load_df(sel_file)
        disciplines = sorted(df['DISCIPLINA'].unique())
        if sel_disc!='All':
            df = df[df['DISCIPLINA']==sel_disc]
        dates_list = sorted(df['DATARDO_STR'].unique())

        # Soma diária completa
        grp = df.groupby(
            ['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR'], as_index=False
        ).agg({'HORA NORMAL':'sum','HORA EXTRA':'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']

        table = grp.pivot(
            index=['OBSERVAÇÃO','DISCIPLINA'],
            columns='DATARDO_STR',
            values='TOTAL_HH'
        ).reset_index()

        columns = ['OBSERVAÇÃO','DISCIPLINA'] + dates_list
        for _, row in table.iterrows():
            rec = {'OBSERVAÇÃO':row['OBSERVAÇÃO'],'DISCIPLINA':row['DISCIPLINA']}
            for dt in dates_list:
                raw = row.get(dt)
                # 0 ou NaN → X
                if pd.isna(raw) or raw == 0:
                    disp = 'X'
                else:
                    disp = f"{raw:.2f}".replace('.', ',')
                cls = ''
                mask = (
                    (just_df['OBSERVAÇÃO']==row['OBSERVAÇÃO']) &
                    (just_df['DISCIPLINA']==row['DISCIPLINA']) &
                    (just_df['DATARDO_STR']==dt)
                )
                if mask.any():
                    dev = just_df.loc[mask,'DESVIO'].iloc[0]
                    cmap = {'Atestado':'AT','Ausente':'AU','SP':'SP','DEP':'DEP'}
                    smap = {'AT':'code-AT','AU':'code-AU','SP':'code-SP','DEP':'code-DEP'}
                    code = cmap[dev]
                    disp = code
                    cls  = smap[code]
                rec[dt] = disp
                rec[f"{dt}_class"] = cls or ('empty-cell' if disp=='X' else '')
            pivot.append(rec)

    return render_template('validation.html',
        files=files,
        selected_file=sel_file,
        disciplines=disciplines,
        selected_discipline=sel_disc,
        dates=dates_list,
        columns=columns,
        pivot=pivot
    )

@bp.route('/pending')
def pending():
    folder       = current_app.config['UPLOAD_FOLDER']
    files        = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.xls','.xlsx')))
    sel_file     = request.args.get('file')
    sel_disc     = request.args.get('discipline', 'All')
    sel_date     = request.args.get('date', 'All')

    pending      = []
    disciplines  = []
    business_str = []

    if sel_file:
        # 1) carrega dados e mapa de disciplina
        df = _load_df(sel_file)
        map_path = os.path.join(folder, 'mapping.xlsx')
        if os.path.exists(map_path):
            dm = pd.read_excel(map_path, dtype=str, na_filter=False).iloc[:, :2]
            dm.columns = ['OBSERVAÇÃO','DISCIPLINA']
            dm = dm.drop_duplicates('OBSERVAÇÃO', keep='first')
            collaborator_map = dm.set_index('OBSERVAÇÃO')['DISCIPLINA'].to_dict()
        else:
            collaborator_map = df.set_index('OBSERVAÇÃO')['DISCIPLINA'].to_dict()

        # 2) gera lista de dias úteis entre min e max
        df['DATARDO_DT'] = pd.to_datetime(df['DATARDO_STR'], dayfirst=True, errors='coerce')
        start, end = df['DATARDO_DT'].min(), df['DATARDO_DT'].max()
        business = pd.date_range(start, end, freq='B')
        business_str = [d.strftime('%d/%m/%Y') for d in business]

        # 3) totaliza HH por colaborador/data
        grp = df.groupby(
            ['OBSERVAÇÃO','DATARDO_STR'],
            as_index=False
        ).agg({'HORA NORMAL':'sum','HORA EXTRA':'sum'})
        grp['TOTAL_HH'] = grp['HORA NORMAL'] + grp['HORA EXTRA']

        # 4) carrega justificativas
        just_path = os.path.join(folder,'justificativas.csv')
        just_df   = (pd.read_csv(just_path, dtype=str) if os.path.exists(just_path)
                     else pd.DataFrame(columns=['OBSERVAÇÃO','DISCIPLINA','DATARDO_STR','DESVIO']))

        # 5) itera colaborador × data útil
        collaborators = sorted(collaborator_map.keys())
        disciplines   = sorted(set(collaborator_map.values()))

        for obs in collaborators:
            disc = collaborator_map.get(obs,'')
            for dt in business_str:
                has_hh = not grp[
                    (grp['OBSERVAÇÃO']==obs)&(grp['DATARDO_STR']==dt)&(grp['TOTAL_HH']>0)
                ].empty
                has_just = not just_df[
                    (just_df['OBSERVAÇÃO']==obs)&
                    (just_df['DATARDO_STR']==dt)   # <-- corrigido abaixo
                ].empty
                # (veja nota abaixo sobre typo)
                if not has_hh and not has_just:
                    pending.append({'OBSERVAÇÃO':obs,'DISCIPLINA':disc,'DATARDO_STR':dt})

        # 6) aplica filtros
        if sel_disc!='All':
            pending = [p for p in pending if p['DISCIPLINA']==sel_disc]
        if sel_date!='All':
            pending = [p for p in pending if p['DATARDO_STR']==sel_date]

    return render_template('pending.html',
        files=files,
        selected_file=sel_file,
        disciplines=disciplines,
        dates=business_str,
        selected_discipline=sel_disc,
        selected_date=sel_date,
        pending=pending
    )
