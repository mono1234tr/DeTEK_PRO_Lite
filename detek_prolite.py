import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import json
from google.oauth2.service_account import Credentials
import gspread
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- FUNCIÓN CON REINTENTOS PARA ACCESO A GOOGLE SHEETS ---
def get_sheet_with_retry(client, sheet_id, worksheet_name, retries=3, delay=2):
    for i in range(retries):
        try:
            return client.open_by_key(sheet_id).worksheet(worksheet_name)
        except Exception as e:
            if i < retries - 1:
                time.sleep(delay)
            else:
                st.error(f"No se pudo acceder a la hoja '{worksheet_name}': {e}")
                st.stop()

# --- CONFIGURACIÓN GOOGLE SHEETS ---
# --- FUNCIÓN PARA EDITAR LA DESCRIPCIÓN DE UN CONSUMIBLE EN LA HOJA DE EQUIPOS ---
def actualizar_descripcion_consumible(empresa, codigo, consumible, nueva_descripcion):
    # Buscar la fila correspondiente en equipos_df
    idx = None
    for i, row in equipos_df.iterrows():
        if row["empresa"].strip() == empresa and row["codigo"].strip() == codigo:
            idx = i
            break
    if idx is None:
        st.error("No se encontró el equipo en la hoja de Equipos.")
        return False
    # Obtener la lista de consumibles y descripciones actuales
    consumibles = [c.strip() for c in equipos_df.iloc[idx]["consumibles"].split(",")]
    descripciones_raw = str(equipos_df.iloc[idx].get("descripcion_consumibles", "")).strip()
    descripciones = [d.strip() for d in descripciones_raw.split("|")] if descripciones_raw else ["" for _ in consumibles]
    # Actualizar la descripción del consumible
    for i, c in enumerate(consumibles):
        if c == consumible:
            descripciones[i] = nueva_descripcion
    # Unir las descripciones y actualizar la celda en Google Sheets
    nueva_celda = "|".join(descripciones)
    ws = sheet_equipos
    # Buscar el índice de la columna descripcion_consumibles
    cols = ws.row_values(1)
    col_idx = None
    for i, col in enumerate(cols):
        if col.lower().strip() == "descripcion_consumibles":
            col_idx = i + 1
            break
    if col_idx is None:
        st.error("No se encontró la columna 'descripcion_consumibles' en la hoja de Equipos.")
        return False
    ws.update_cell(idx + 2, col_idx, nueva_celda)
    st.success(f"Descripción actualizada para '{consumible}' en el equipo '{codigo}'.")
    return True
service_account_info = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPE)
client = gspread.authorize(creds)

# --- HOJAS ---
SHEET_ID = "1288rxOwtZDI3A7kuLnR4AXaI-GKt6YizeZS_4ZvdTnQ"
sheet_registro = get_sheet_with_retry(client, SHEET_ID, "Hoja 1")
sheet_equipos = get_sheet_with_retry(client, SHEET_ID, "Equipos")
# --- HOJA DE CHAT ---
try:
    sheet_chat = get_sheet_with_retry(client, SHEET_ID, "Chat")
except:
    # Si no existe, crearla con encabezados
    sheet_chat = client.open_by_key(SHEET_ID).add_worksheet(title="Chat", rows="1000", cols="4")
    sheet_chat.append_row(["fecha", "usuario", "mensaje", "empresa"])

# --- VIDA ÚTIL POR DEFECTO ---
VIDA_UTIL_DEFECTO = 700

# --- CARGAR DATOS DE EQUIPOS DESDE GOOGLE SHEETS ---
equipos_df = pd.DataFrame(sheet_equipos.get_all_records())
equipos_df.columns = [col.lower().strip() for col in equipos_df.columns]

# Diccionario para guardar descripciones fijas de consumibles
DESCRIPCIONES_CONSUMIBLES = {}

EQUIPOS_EMPRESA = {}
VIDA_UTIL = {}

for _, row in equipos_df.iterrows():
    empresa = row["empresa"].strip()
    codigo = row["codigo"].strip()
    descripcion = row["descripcion"].strip()
    consumibles = [c.strip() for c in row["consumibles"].split(",")]
    # Descripciones fijas por consumible (columna: descripcion_consumibles)
    descripciones_raw = str(row.get("descripcion_consumibles", "")).strip()
    descripciones = [d.strip() for d in descripciones_raw.split("|")] if descripciones_raw else ["" for _ in consumibles]

    # Nueva lógica: vida útil específica por consumible
    vida_util_raw = str(row.get("vida_util", "")).strip()
    vidas = [v.strip() for v in vida_util_raw.split(",")] if vida_util_raw else []

    if empresa not in EQUIPOS_EMPRESA:
        EQUIPOS_EMPRESA[empresa] = {}

    EQUIPOS_EMPRESA[empresa][codigo] = {
        "descripcion": descripcion,
        "consumibles": consumibles
    }

    for i, consumible in enumerate(consumibles):
        try:
            VIDA_UTIL[consumible] = int(vidas[i]) if i < len(vidas) else VIDA_UTIL_DEFECTO
        except:
            VIDA_UTIL[consumible] = VIDA_UTIL_DEFECTO
        # Guardar descripción fija
        DESCRIPCIONES_CONSUMIBLES[f"{empresa}|{codigo}|{consumible}"] = descripciones[i] if i < len(descripciones) else ""

# --- INTERFAZ ---
st.set_page_config(page_title="DeTEK PRO Lite", layout="centered")
# --- --------------LOGO ---
st.markdown(
    """
    <div style="display: flex; flex-direction: column; align-items: center; margin-top: 18px; margin-bottom: 10px;">
        <img src='https://i0.wp.com/tekpro.com.co/wp-content/uploads/2023/12/cropped-logo-tekpro-main-retina.png?fit=522%2C145&ssl=1' style='max-width: 90vw; width: 180px; height: auto; margin-bottom: 0;'>
        <div style='font-family: Georgia, serif; font-size: 8vw; color: #009999; font-weight: bold; margin-top: 0; margin-bottom: 0; text-align:center;'>Tekpro</div>
    </div>
    <div style='text-align:center; margin-top: 0;'>
        <span style='font-family: Georgia, serif; font-size: 6vw; color: #00BDAD; font-weight: bold;'>DeTEK PRO Lite</span>
    </div>
    """,
    unsafe_allow_html=True
)
st.sidebar.title("Menú de empresa")

empresas_disponibles = list(EQUIPOS_EMPRESA.keys())
empresa_seleccionada = st.sidebar.selectbox("Selecciona la empresa:", empresas_disponibles)

# --- REGISTRO DE NUEVO EQUIPO ---
st.sidebar.markdown("### Registrar nuevo equipo")
with st.sidebar.form("form_registro_equipo"):
    nueva_empresa = st.text_input("Empresa (debe coincidir)", value=empresa_seleccionada)
    nuevo_codigo = st.text_input("Código del equipo (Ej: RF999)")
    nueva_descripcion = st.text_input("Descripción del equipo")
    nuevos_consumibles = st.text_input("Consumibles (separados por coma)")

    if st.form_submit_button("Guardar equipo"):
        fila = [
            nueva_empresa.strip(),
            nuevo_codigo.strip(),
            nueva_descripcion.strip(),
            nuevos_consumibles.strip()
        ]
        sheet_equipos.append_row(fila)
        st.success(f"✅ Equipo {nuevo_codigo} registrado correctamente. Recarga la página para verlo.")
        st.stop()

# --- CARGAR REGISTROS EXISTENTES ---
data = pd.DataFrame(sheet_registro.get_all_records())
data.columns = [col.lower().strip() for col in data.columns]

# --- PROCESOS Y SELECTOR ---
equipos_empresa = EQUIPOS_EMPRESA.get(empresa_seleccionada, {})

selector_visible = []
estado_equipos = {}

for codigo, detalles in equipos_empresa.items():
    descripcion = detalles["descripcion"]
    consumibles = detalles["consumibles"]
    estado_icono = "🟢"
    data_equipo = data[(data["empresa"] == empresa_seleccionada) & (data["codigo"] == codigo)]
    estado_partes = {parte: 0 for parte in consumibles}

    for _, fila in data_equipo.iterrows():
        horas = fila.get("hora de uso", 0)
        try:
            horas = float(horas)
        except:
            horas = 0
        partes_cambiadas = str(fila.get("parte cambiada", "")).split(";")
        for parte in estado_partes:
            if parte in partes_cambiadas:
                estado_partes[parte] = 0
            else:
                estado_partes[parte] += horas

    # Determinar el estado más crítico entre los consumibles
    icono_equipo = "🟢"
    for parte, usadas in estado_partes.items():
        limite = VIDA_UTIL.get(parte, VIDA_UTIL_DEFECTO)
        restantes = limite - usadas
        if restantes <= 0.5:
            icono_equipo = "⚠️"
            break
        elif restantes <= 24 and icono_equipo != "⚠️":
            icono_equipo = "🔴"

    visible = f"{icono_equipo} {codigo} - {descripcion}"
    selector_visible.append(visible)
    estado_equipos[visible] = codigo



# --- CHAT EN LÍNEA EN BARRA LATERAL IZQUIERDA (EXPANDER) ---
with st.sidebar.expander("💬 Chat en línea entre usuarios de la empresa", expanded=False):
    chat_df = pd.DataFrame(sheet_chat.get_all_records())
    if not chat_df.empty:
        chat_df = chat_df[chat_df["empresa"] == empresa_seleccionada]
        chat_df = chat_df.tail(30)
        for _, row in chat_df.iterrows():
            st.markdown(f"<span style='color:#00BDAD'><b>{row['usuario']}</b></span> <span style='color:gray;font-size:12px'>({row['fecha']})</span>: {row['mensaje']}", unsafe_allow_html=True)
    else:
        st.info("No hay mensajes en el chat todavía.")
    st.markdown("---")
    usuario_chat = st.text_input("Tu nombre para el chat:", value="Usuario", key="chat_nombre")
    mensaje_chat = st.text_input("Mensaje:", value="", key="chat_mensaje")
    if st.button("Enviar mensaje", key="chat_enviar"):
        if mensaje_chat.strip():
            sheet_chat.append_row([
                str(datetime.now()),
                usuario_chat.strip(),
                mensaje_chat.strip(),
                empresa_seleccionada
            ])
            st.success("Mensaje enviado!")
            # No recargar toda la app, solo limpiar el campo de mensaje si se desea
            # st.experimental_rerun() eliminado para evitar recarga global

# --- SELECCIÓN DE EQUIPO ---
st.markdown(f"**Empresa :** `{empresa_seleccionada}`")
st.markdown("<hr style='margin-top:10px;margin-bottom:10px;border:1px solid #e0e0e0;'>", unsafe_allow_html=True)

if not selector_visible:
    st.warning("⚠️ Esta empresa aún no tiene equipos registrados. Agrega uno desde la barra lateral.")
    st.stop()

seleccion = st.selectbox("Seleccione el proceso/equipo:", selector_visible)

if not seleccion or seleccion not in estado_equipos:
    st.warning("⚠️ Selecciona un equipo válido para continuar.")
    st.stop()

codigo = estado_equipos[seleccion]
descripcion = equipos_empresa[codigo]["descripcion"]
consumibles_equipo = equipos_empresa[codigo]["consumibles"]

# --- HORARIO DE OPERACIÓN ---
st.subheader(" Horario del turno")
col1, col2 = st.columns(2)
with col1:
    hora_inicio = st.time_input("Hora de inicio", value=datetime.strptime("07:00", "%H:%M").time())
with col2:
    hora_fin = st.time_input("Hora de finalización", value=datetime.strptime("16:00", "%H:%M").time())

inicio_dt = datetime.combine(date.today(), hora_inicio)
fin_dt = datetime.combine(date.today(), hora_fin)
if fin_dt < inicio_dt:
    fin_dt += timedelta(days=1)
horas_trabajadas = round((fin_dt - inicio_dt).total_seconds() / 3600, 2)

# --- OBSERVACIONES ---
st.subheader(" Observaciones")
observaciones = st.text_area("Ingrese observaciones del día:")

# --- GUARDAR DATOS ---
if st.button("Guardar información para todos los procesos"):
    for codigo, detalles in equipos_empresa.items():
        fila = [
            empresa_seleccionada,
            str(date.today()),
            "",  # OP
            codigo,
            detalles["descripcion"],
            horas_trabajadas,
            "",  # Parte cambiada
            observaciones,
            ""  # Observaciones técnicas
        ]
        sheet_registro.append_row(fila)
    st.success("✅ Registro guardado para todos los procesos.")

# --- ESTADO DE CONSUMIBLES ---

st.subheader("🔧 Estado de consumibles del proceso seleccionado")
data_equipo = data[(data["empresa"] == empresa_seleccionada) & (data["codigo"] == codigo)]
estado_partes = {parte: 0 for parte in consumibles_equipo}

# Diccionario para guardar descripciones de consumibles
if 'descripcion_consumibles' not in st.session_state:
    st.session_state['descripcion_consumibles'] = {}

for _, fila in data_equipo.iterrows():
    horas = fila.get("hora de uso", 0)
    try:
        horas = float(horas)
    except:
        horas = 0
    partes_cambiadas = str(fila.get("parte cambiada", "")).split(";")
    for parte in estado_partes:
        if parte in partes_cambiadas:
            estado_partes[parte] = 0
        else:
            estado_partes[parte] += horas

if 'alertas_enviadas' not in st.session_state:
    st.session_state['alertas_enviadas'] = {}
#-------------------------------------------------CAMBIAR CORREO AQUIIII-----------------------------
def enviar_alerta_email(parte, equipo, empresa, restantes, descripcion):
    remitente = st.secrets.get("EMAIL_USER")
    password = st.secrets.get("EMAIL_PASS")
    destinatario = "produccion@tekpro.com.co"
    if not remitente or not password or not destinatario:
        st.warning("No se pudo enviar alerta: faltan datos de configuración de correo.")
        return False
    asunto = f"ALERTA: Consumible crítico en {equipo} ({empresa})"
    cuerpo = f"El consumible '{parte}' del equipo '{equipo}' en la empresa '{empresa}' está en estado de falla inminente. Restan {restantes:.1f} horas de vida útil.\n\nDescripción: {descripcion}\n\nComunicate con TEKPRO al siguiente correo ventas@tekpro.com.co, o escribenos al chat que esta en la app DeTEK PRO."
    msg = MIMEMultipart()
    msg['From'] = remitente
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain'))
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(remitente, password)
            server.sendmail(remitente, destinatario, msg.as_string())
        return True
    except Exception as e:
        st.warning(f"No se pudo enviar alerta por email: {e}")
        return False

for parte, usadas in estado_partes.items():
    limite = VIDA_UTIL.get(parte, VIDA_UTIL_DEFECTO)
    restantes = limite - usadas
    clave_alerta = f"{empresa_seleccionada}|{codigo}|{parte}"
    # Mostrar descripción fija desde hoja de Equipos
    descripcion_fija = DESCRIPCIONES_CONSUMIBLES.get(clave_alerta, "")
    with st.expander(f"ℹ️ Información adicional de '{parte}'", expanded=False):
        st.markdown(f"<div style='background:#f7f7f7;padding:8px;border-radius:6px;color:#222'>{descripcion_fija if descripcion_fija else 'Sin descripción disponible.'}</div>", unsafe_allow_html=True)
    if restantes <= 0.5:
        color, estado = "⚠️", "Falla esperada"
        # Enviar alerta solo si no se ha enviado para este consumible/equipo/empresa
        if not st.session_state['alertas_enviadas'].get(clave_alerta, False):
            enviado = enviar_alerta_email(parte, codigo, empresa_seleccionada, restantes, descripcion_fija)
            if enviado:
                st.success(f"Alerta enviada por email para {parte} ({codigo})")
            else:
                st.error(f"No se pudo enviar la alerta por email para {parte} ({codigo})")
            st.session_state['alertas_enviadas'][clave_alerta] = True
    elif restantes <= 24:
        color, estado = "🔴", "Crítico"
    elif restantes <= 360:
        color, estado = "🟡", "Advertencia"
    else:
        color, estado = "🟢", "Bueno"
        # Si el consumible vuelve a estar en "Bueno", se puede resetear la alerta para futuros eventos
        if st.session_state['alertas_enviadas'].get(clave_alerta, False):
            st.session_state['alertas_enviadas'][clave_alerta] = False
    st.markdown(f"{color} **{parte}**: {usadas:.1f} h | Estado: `{estado}`")
