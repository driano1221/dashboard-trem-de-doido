import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide", page_icon="💰")

# --- ESTILOS CSS ---
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 26px; }
    [data-testid="stMetricDelta"] { font-size: 16px; }
    .stDataFrame { border: 1px solid #f0f2f6; border-radius: 5px; }
    div[data-testid="stExpander"] details summary p { font-weight: bold; font-size: 1.1em; }
</style>
""", unsafe_allow_html=True)

# --- CONFIGURAÇÃO GOOGLE (MÉTODO SEGURO PARA NUVEM) ---
try:
    # AQUI ESTÁ A MUDANÇA: O código busca os dados no cofre do Streamlit
    PASTA_ID = st.secrets["drive_folder_id"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
except Exception as e:
    st.error(f"Erro de Segurança: Não encontrei as chaves no Secrets. {e}")
    st.stop()

# --- MAPA DE MESES ---
MAPA_MESES = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
    'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
}

# --- CÉREBRO DE CATEGORIZAÇÃO ---
def definir_categoria(descricao, tipo):
    if not isinstance(descricao, str): return "Outros"
    desc = descricao.lower().strip()
    
    if tipo == 'Saída':
        if any(x in desc for x in ['luz', 'cemig', 'energia']): return 'Energia Elétrica'
        if any(x in desc for x in ['água', 'agua', 'saneamento']): return 'Água & Esgoto'
        if any(x in desc for x in ['internet', 'wifi', 'vivo', 'claro']): return 'Internet'
        if any(x in desc for x in ['manutenção', 'reparo', 'pedreiro', 'obra']): return 'Manutenção'
        if any(x in desc for x in ['mercado', 'compras', 'fatura']): return 'Mercado/Compras'
        if any(x in desc for x in ['aluguel', 'condominio']): return 'Aluguel (Pago)'
        if any(x in desc for x in ['gás', 'gas']): return 'Gás'
        if any(x in desc for x in ['divida', 'dívida', 'pagamento']): return 'Dívidas/Empréstimos'
    elif tipo == 'Entrada':
        if any(x in desc for x in ['morador', 'hospedagem', 'aluguel']): return 'Receita Aluguéis'
        if any(x in desc for x in ['xusha', 'sequela', 'confuso', 'cobolas', 'gugu', 'bixo', 'damião', 'edvaldo', 'tanimado', 'khdinho', 'judas', 'terraplana']): return 'Receita Aluguéis'
        if any(x in desc for x in ['aporte', 'transferencia']): return 'Aportes/Outros'
    return "Outros"

@st.cache_resource
def get_drive_service():
    # Removemos a criação da credencial daqui de dentro, pois já foi criada lá no topo
    return build('drive', 'v3', credentials=creds)

def limpar_valor(valor):
    if isinstance(valor, str):
        valor = valor.replace('R$', '').replace(' ', '').strip()
        valor = valor.replace('.', '').replace(',', '.')
    return pd.to_numeric(valor, errors='coerce')

@st.cache_data(ttl=600)
def carregar_dados():
    service = get_drive_service()
    results = service.files().list(
        q=f"'{PASTA_ID}' in parents and trashed=false",
        fields="files(id, name, mimeType)"
    ).execute()
    files = results.get('files', [])
    lista_dfs = []
    saldos_iniciais = {}
    
    for arquivo in files:
        if "Fluxo de Caixa" in arquivo['name']:
            try:
                # Extração Nome: "Fluxo de Caixa Novembro - 2025.xlsx"
                nome_limpo = arquivo['name'].replace('.xlsx', '').replace('Fluxo de Caixa', '').strip()
                partes = nome_limpo.split('-')
                if len(partes) >= 2:
                    mes_texto = partes[0].strip().lower()
                    ano_texto = partes[1].strip()
                else:
                    mes_texto = nome_limpo.lower()
                    ano_texto = "2025" 
                
                num_mes = MAPA_MESES.get(mes_texto, 0)
                if num_mes > 0:
                    data_ref = datetime(int(ano_texto), num_mes, 1)
                    nome_exibicao = f"{mes_texto.capitalize()} {ano_texto}"
                else:
                    data_ref = datetime(1900, 1, 1)
                    nome_exibicao = arquivo['name']

                # Leitura
                if 'application/vnd.google-apps.spreadsheet' in arquivo['mimeType']:
                    request = service.files().export_media(fileId=arquivo['id'], mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                else:
                    request = service.files().get_media(fileId=arquivo['id'])
                
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False: status, done = downloader.next_chunk()
                fh.seek(0)
                
                df = pd.read_excel(fh, nrows=35)
                df.iloc[:, 1] = df.iloc[:, 1].apply(limpar_valor)
                df.iloc[:, 5] = df.iloc[:, 5].apply(limpar_valor)
                
                linha_saldo = df[df.iloc[:, 0].astype(str).str.contains('Saldo', case=False, na=False)]
                saldo_ini = linha_saldo.iloc[0, 1] if not linha_saldo.empty else 0.0
                saldos_iniciais[data_ref] = saldo_ini

                entradas = df.iloc[:, [0, 1, 2]].copy()
                entradas.columns = ['Descricao', 'Valor', 'Data']
                entradas['Tipo'] = 'Entrada'
                saidas = df.iloc[:, [4, 5, 6]].copy()
                saidas.columns = ['Descricao', 'Valor', 'Data']
                saidas['Tipo'] = 'Saída'
                df_temp = pd.concat([entradas, saidas], ignore_index=True)
                
                df_temp = df_temp.dropna(subset=['Valor'])
                df_temp = df_temp[~df_temp['Descricao'].astype(str).str.contains('TOTAL|SALDO', case=False, regex=True, na=False)]
                df_temp['Categoria'] = df_temp.apply(lambda x: definir_categoria(x['Descricao'], x['Tipo']), axis=1)
                df_temp['Data'] = pd.to_datetime(df_temp['Data'], dayfirst=True, errors='coerce')
                df_temp = df_temp.dropna(subset=['Data'])
                df_temp['Mes_Ref_Date'] = data_ref
                df_temp['Mes_Exibicao'] = nome_exibicao
                
                lista_dfs.append(df_temp)
            except Exception as e:
                print(f"Erro {arquivo['name']}: {e}")

    if lista_dfs:
        return pd.concat(lista_dfs, ignore_index=True).sort_values(by='Mes_Ref_Date'), saldos_iniciais
    else:
        return pd.DataFrame(), {}

# --- INTERFACE ---
st.title("Dashboard Financeiro Trem de Doido 🚂")
with st.spinner('Sincronizando...'):
    df_final, saldos_iniciais = carregar_dados()

if not df_final.empty:
    datas_disponiveis = sorted(df_final['Mes_Ref_Date'].unique())
    opcoes_map = {d: df_final[df_final['Mes_Ref_Date'] == d]['Mes_Exibicao'].iloc[0] for d in datas_disponiveis}
    
    st.sidebar.header("🗓️ Navegação")
    data_selecionada = st.sidebar.selectbox("Mês de Referência:", options=datas_disponiveis, format_func=lambda x: opcoes_map[x], index=len(datas_disponiveis)-1)
    
    # Filtros e Cálculos
    df_atual = df_final[df_final['Mes_Ref_Date'] == data_selecionada]
    saldo_ini_atual = saldos_iniciais.get(data_selecionada, 0.0)
    
    entradas_atual = df_atual[df_atual['Tipo'] == 'Entrada']['Valor'].sum()
    saidas_atual = df_atual[df_atual['Tipo'] == 'Saída']['Valor'].sum()
    resultado_atual = entradas_atual - saidas_atual
    
    # Delta
    index_atual = datas_disponiveis.index(data_selecionada)
    delta_entradas = delta_saidas = 0
    if index_atual > 0:
        df_ant = df_final[df_final['Mes_Ref_Date'] == datas_disponiveis[index_atual - 1]]
        ent_ant = df_ant[df_ant['Tipo'] == 'Entrada']['Valor'].sum()
        sai_ant = df_ant[df_ant['Tipo'] == 'Saída']['Valor'].sum()
        if ent_ant > 0: delta_entradas = ((entradas_atual - ent_ant) / ent_ant) * 100
        if sai_ant > 0: delta_saidas = ((saidas_atual - sai_ant) / sai_ant) * 100

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldo Mês Anterior", f"R$ {saldo_ini_atual:,.2f}")
    c2.metric("Entradas", f"R$ {entradas_atual:,.2f}", f"{delta_entradas:+.1f}%" if index_atual > 0 else None)
    c3.metric("Saídas", f"R$ {saidas_atual:,.2f}", f"{delta_saidas:+.1f}%" if index_atual > 0 else None, delta_color="inverse")
    c4.metric("Resultado (L/P)", f"R$ {resultado_atual:,.2f}", delta_color="normal" if resultado_atual > 0 else "inverse")
    
    st.divider()

    # --- GRÁFICOS ---
    col_g1, col_g2 = st.columns([3, 2])
    
    with col_g1:
        st.subheader("📈 Evolução Diária (Série Temporal)")
        # Agrupa por Data e Tipo para criar barras
        daily_data = df_atual.groupby(['Data', 'Tipo'])['Valor'].sum().reset_index()
        fig_bar = px.bar(daily_data, x='Data', y='Valor', color='Tipo', barmode='group',
                         color_discrete_map={'Entrada': '#00C896', 'Saída': '#FF5252'},
                         template="plotly_white")
        fig_bar.update_xaxes(dtick="D1", tickformat="%d/%m") # Mostra todos os dias
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_g2:
        st.subheader("Despesas por Categoria")
        df_saidas = df_atual[df_atual['Tipo'] == 'Saída']
        if not df_saidas.empty:
            gastos_cat = df_saidas.groupby('Categoria')['Valor'].sum().reset_index().sort_values(by='Valor', ascending=False)
            fig_pizza = px.pie(gastos_cat, values='Valor', names='Categoria', hole=0.5, 
                               color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pizza.update_layout(showlegend=False) # Legenda fica dentro do gráfico pra ficar limpo
            fig_pizza.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pizza, use_container_width=True)
        else:
            st.info("Sem saídas.")

    # --- TABELAS ---
    st.subheader("📝 Detalhamento")
    
    tab_lado, tab_full = st.tabs(["Lado a Lado (Entradas vs Saídas)", "Extrato Unificado"])
    
    config_cols = {
        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
    }

    with tab_lado:
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("### 🟢 Entradas")
            df_ent = df_atual[df_atual['Tipo'] == 'Entrada'][['Data', 'Descricao', 'Categoria', 'Valor']].sort_values('Data')
            st.dataframe(df_ent, use_container_width=True, hide_index=True, column_config=config_cols)
        with col_t2:
            st.markdown("### 🔴 Saídas")
            df_sai = df_atual[df_atual['Tipo'] == 'Saída'][['Data', 'Descricao', 'Categoria', 'Valor']].sort_values('Data')
            st.dataframe(df_sai, use_container_width=True, hide_index=True, column_config=config_cols)

    with tab_full:
        st.dataframe(df_atual[['Data', 'Descricao', 'Categoria', 'Valor', 'Tipo']].sort_values('Data'), 
                     use_container_width=True, hide_index=True, column_config=config_cols)

else:
    st.warning("Renomeie seus arquivos para 'Fluxo de Caixa Mês - Ano.xlsx' (ex: Fluxo de Caixa Novembro - 2025.xlsx)")