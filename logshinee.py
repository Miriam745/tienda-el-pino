import streamlit as st
import MySQLdb
import pandas as pd
from datetime import datetime, timedelta
import uuid
import os
import io
import sqlite3
import tempfile

# Importación de ReportLab para generar tickets en PDF
from reportlab.lib.pagesizes import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- CONFIGURACIÓN DE PÁGINA (ESTILO ILUSION) ---
st.set_page_config(page_title="Abarrotes EL PINO - LogShinee MySQL", layout="wide", page_icon="🌲")

# --- ESTILOS CSS CON PALETA VERDE/BEIGE ---
st.markdown("""
    <style>
    .main {
        background-color: #f7fbf8;
    }
    [data-testid="stSidebar"] {
        background-color: #ebf4ee;
        border-right: 1px solid #d2e4d6;
    }
    h1, h2, h3, h4 {
        color: #1e4620 !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    div.stButton > button {
        border-radius: 8px !important;
        border: 1px solid #2d6a4f !important;
        color: #ffffff !important;
        background-color: #2d6a4f !important;
        font-weight: 600 !important;
    }
    div.stButton > button:hover {
        background-color: #1b4332 !important;
        color: #ffffff !important;
    }
    .stAlert {
        border-radius: 8px !important;
    }
    .stRadio > label {
        color: #1e4620 !important;
        font-weight: bold !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- CONEXIÓN A BASE DE DATOS MYSQL ---
MYSQL_HOST = 'localhost'
MYSQL_USER = 'root'
MYSQL_PASSWORD = ''
MYSQL_DB = 'tiendita'


def get_mysql_connection():
    return MySQLdb.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        passwd=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset='utf8'
    )


def init_db():
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()

        # 0. Tabla de Usuarios para Autenticación
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                          (id INT AUTO_INCREMENT PRIMARY KEY,
                           username VARCHAR(255) UNIQUE NOT NULL, 
                           password VARCHAR(255) NOT NULL)''')

        # Insertar usuario por defecto 'admin' / 'password' si la tabla está vacía
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO usuarios (username, password) VALUES (%s, %s)", ('admin', 'password'))

        # 1. Tabla de Proveedores
        cursor.execute('''CREATE TABLE IF NOT EXISTS proveedores 
                          (id INT AUTO_INCREMENT PRIMARY KEY,
                           nombre VARCHAR(255) UNIQUE, contacto VARCHAR(255), telefono VARCHAR(255))''')

        # 2. Tabla de Inventario / Compras
        cursor.execute('''CREATE TABLE IF NOT EXISTS inventario 
                          (codigo VARCHAR(255) PRIMARY KEY, producto VARCHAR(255), marca VARCHAR(255), 
                           modelo VARCHAR(255), presentacion VARCHAR(255), categoria VARCHAR(255), 
                           unidad VARCHAR(50), stock DOUBLE, stock_minimo DOUBLE, p_compra DOUBLE, 
                           p_venta DOUBLE, proveedor_id INT,
                           FOREIGN KEY(proveedor_id) REFERENCES proveedores(id))''')

        cols_inventario = {
            'marca': "ALTER TABLE inventario ADD COLUMN marca VARCHAR(255) DEFAULT ''",
            'modelo': "ALTER TABLE inventario ADD COLUMN modelo VARCHAR(255) DEFAULT ''",
            'presentacion': "ALTER TABLE inventario ADD COLUMN presentacion VARCHAR(255) DEFAULT ''"
        }
        for col, query_alter in cols_inventario.items():
            cursor.execute(f"SHOW COLUMNS FROM inventario LIKE '{col}'")
            if not cursor.fetchone():
                cursor.execute(query_alter)

        # 3. Tabla de Ventas
        cursor.execute('''CREATE TABLE IF NOT EXISTS ventas 
                          (transaccion_id VARCHAR(255), cliente_dni VARCHAR(255), fecha VARCHAR(50), 
                           hora VARCHAR(50), codigo VARCHAR(255), producto VARCHAR(255), 
                           cantidad DOUBLE, p_venta DOUBLE, total DOUBLE, estado VARCHAR(50))''')

        cols_ventas = {
            'transaccion_id': "ALTER TABLE ventas ADD COLUMN transaccion_id VARCHAR(255) DEFAULT ''",
            'hora': "ALTER TABLE ventas ADD COLUMN hora VARCHAR(50) DEFAULT '00:00'",
            'codigo': "ALTER TABLE ventas ADD COLUMN codigo VARCHAR(255) DEFAULT ''",
            'producto': "ALTER TABLE ventas ADD COLUMN producto VARCHAR(255) DEFAULT ''",
            'p_venta': "ALTER TABLE ventas ADD COLUMN p_venta DOUBLE DEFAULT 0.0",
            'total': "ALTER TABLE ventas ADD COLUMN total DOUBLE DEFAULT 0.0",
            'estado': "ALTER TABLE ventas ADD COLUMN estado VARCHAR(50) DEFAULT 'COMPLETADA'"
        }
        for col, query_alter in cols_ventas.items():
            cursor.execute(f"SHOW COLUMNS FROM ventas LIKE '{col}'")
            if not cursor.fetchone():
                cursor.execute(query_alter)

        # 4. Tabla para Almacenar Datos Generales de Tickets
        cursor.execute('''CREATE TABLE IF NOT EXISTS tickets 
                          (transaccion_id VARCHAR(255) PRIMARY KEY, cliente_dni VARCHAR(255), 
                           fecha VARCHAR(50), hora VARCHAR(50), total DOUBLE, pago_con DOUBLE, 
                           cambio DOUBLE)''')

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error al conectar/actualizar MySQL: {e}")


def run_query(query, params=()):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    cursor.close()
    conn.close()


def get_df(query, params=()):
    conn = get_mysql_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def reload_app():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


# --- GENERADOR DE TICKET PDF ---
def generar_pdf_ticket(id_transaccion, cliente_dni, items, total, pago_con, cambio):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(80 * mm, 190 * mm), rightMargin=4 * mm, leftMargin=4 * mm,
                            topMargin=4 * mm, bottomMargin=4 * mm)
    styles = getSampleStyleSheet()

    style_center = ParagraphStyle('Center', parent=styles['Normal'], alignment=1, fontSize=8, leading=10)
    style_title = ParagraphStyle('Title', parent=styles['Heading1'], alignment=1, fontSize=11, leading=12)
    style_left = ParagraphStyle('Left', parent=styles['Normal'], alignment=0, fontSize=8, leading=10)
    style_right = ParagraphStyle('Right', parent=styles['Normal'], alignment=2, fontSize=8, leading=10)
    style_bold_right = ParagraphStyle('BoldRight', parent=styles['Normal'], alignment=2, fontSize=9, leading=11)

    story = [
        Paragraph("<b>ABARROTES EL PINO</b>", style_title),
        Paragraph("¡Calidad y Buen Precio!", style_center),
        Spacer(1, 2 * mm),
        Paragraph(f"<b>Ticket #:</b> {id_transaccion}", style_left)
    ]
    if cliente_dni:
        story.append(Paragraph(f"<b>Cliente/DNI:</b> {cliente_dni}", style_left))
    story.append(Paragraph(f"<b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", style_left))
    story.append(Spacer(1, 2 * mm))

    data = [[Paragraph("<b>Prod</b>", style_left), Paragraph("<b>Cant</b>", style_center),
             Paragraph("<b>Total</b>", style_right)]]
    for it in items:
        data.append([
            Paragraph(it['producto'][:15], style_left),
            Paragraph(f"{it['cantidad']} {it['unidad'][:2]}", style_center),
            Paragraph(f"${it['subtotal']:,.2f}", style_right)
        ])

    tabla = Table(data, colWidths=[36 * mm, 18 * mm, 18 * mm])
    tabla.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    story.append(tabla)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>TOTAL: ${total:,.2f}</b>", style_bold_right))
    if pago_con > 0:
        story.append(Paragraph(f"Efectivo: ${pago_con:,.2f}", style_right))
        story.append(Paragraph(f"Cambio: ${cambio:,.2f}", style_right))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("¡Gracias por su compra!", style_center))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# --- INICIALIZACIÓN ---
init_db()

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'usuario_actual' not in st.session_state:
    st.session_state.usuario_actual = ""
if 'carrito' not in st.session_state:
    st.session_state.carrito = []
if 'ultimo_ticket' not in st.session_state:
    st.session_state.ultimo_ticket = None

# --- LOGIN CON VALIDACIÓN DESDE MYSQL ---
if not st.session_state.logged_in:
    st.title("🔐 Iniciar Sesión - Abarrotes EL PINO (MySQL)")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar"):
            df_usr = get_df("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
            if not df_usr.empty:
                st.session_state.logged_in = True
                st.session_state.usuario_actual = username
                st.success("¡Sesión iniciada correctamente!")
                reload_app()
            else:
                st.error("Credenciales inválidas. Inténtalo de nuevo.")
    st.stop()

# --- NAVEGACIÓN Y MENÚ ---
st.sidebar.markdown(f"# 🌲 EL PINO POS")
st.sidebar.caption(f"👤 Usuario: **{st.session_state.usuario_actual}**")

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.logged_in = False
    st.session_state.usuario_actual = ""
    st.session_state.carrito = []
    st.session_state.ultimo_ticket = None
    reload_app()

df_stock_critico = get_df("SELECT producto, stock, unidad FROM inventario WHERE stock < 5")
if not df_stock_critico.empty:
    st.sidebar.warning(f"⚠️ **Atención:** Hay {len(df_stock_critico)} producto(s) con stock bajo.")
    with st.sidebar.expander("Ver lista con stock bajo"):
        for _, row in df_stock_critico.iterrows():
            st.write(f"• **{row['producto']}**: {row['stock']} {row['unidad']}")

st.sidebar.markdown("---")
choice = st.sidebar.radio("Menú Principal", [
    "🛒 Punto de Venta",
    "📦 Inventario / Compras",
    "🚚 Proveedores",
    "📊 Corte de Caja",
    "📉 Historial",
    "🛠️ Registrar Producto",
    "💾 Respaldos",
    "👤 Mi Cuenta"
])

# --- 1. PUNTO DE VENTA ---
if choice == "🛒 Punto de Venta":
    st.title("🛒 Punto de Venta")
    df_inv = get_df("SELECT * FROM inventario WHERE stock > 0")

    if not df_inv.empty:
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.subheader("Búsqueda y Selección")
            cliente_dni = st.text_input("DNI / Identificación del Cliente (Opcional):", value="CF")
            df_inv['label'] = df_inv['codigo'] + " - " + df_inv['producto'] + " (" + df_inv['unidad'] + ")"
            prod_sel = st.selectbox("Seleccionar producto:", df_inv['label'])
            item = df_inv[df_inv['label'] == prod_sel].iloc[0]

            cant_en_carrito = sum(i['cantidad'] for i in st.session_state.carrito if i['codigo'] == item['codigo'])
            stock_disp = item['stock'] - cant_en_carrito

            st.info(f"🏷️ **Precio:** ${item['p_venta']:,.2f} | 📦 **Disponible:** {stock_disp} {item['unidad']}")

            if stock_disp > 0:
                step_val = 0.100 if str(item['unidad']).lower() in ['kg', 'litro', 'm'] else 1.0
                cant = st.number_input("Cantidad:", min_value=0.05 if step_val < 1 else 1.0,
                                       max_value=float(stock_disp), step=step_val)
                if st.button("➕ Agregar al Carrito"):
                    st.session_state.carrito.append({
                        'codigo': item['codigo'],
                        'producto': item['producto'],
                        'unidad': item['unidad'],
                        'cantidad': cant,
                        'precio': item['p_venta'],
                        'subtotal': round(item['p_venta'] * cant, 2)
                    })
                    reload_app()
                if st.session_state.carrito and st.button("🗑️ Vaciar Carrito"):
                    st.session_state.carrito = []
                    st.session_state.ultimo_ticket = None
                    reload_app()
            else:
                st.warning("Stock insuficiente.")

        with c2:
            st.subheader("Detalle de la Venta")
            if st.session_state.carrito:
                df_cart = pd.DataFrame(st.session_state.carrito)
                st.dataframe(df_cart[['producto', 'cantidad', 'subtotal']])

                total_v = sum(i['subtotal'] for i in st.session_state.carrito)
                st.markdown(f"<h2 style='text-align: right; color: #1e4620;'>TOTAL: ${total_v:,.2f}</h2>",
                            unsafe_allow_html=True)
                pago_con = st.number_input("Efectivo recibido ($):", min_value=float(total_v), step=10.0)
                cambio = pago_con - total_v
                if pago_con >= total_v:
                    st.success(f"Cambio: **${cambio:,.2f}**")

                if st.button("✅ Confirmar Venta"):
                    t_id = str(uuid.uuid4())[:8].upper()
                    now = datetime.now()

                    for i in st.session_state.carrito:
                        run_query(
                            "INSERT INTO ventas (transaccion_id, cliente_dni, fecha, hora, codigo, producto, cantidad, p_venta, total, estado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (t_id, cliente_dni, now.strftime("%Y-%m-%d"), now.strftime("%H:%M"),
                             i['codigo'], i['producto'], i['cantidad'], i['precio'], i['subtotal'], "COMPLETADA"))
                        run_query("UPDATE inventario SET stock = stock - %s WHERE codigo=%s",
                                  (i['cantidad'], i['codigo']))

                    run_query(
                        "INSERT INTO tickets (transaccion_id, cliente_dni, fecha, hora, total, pago_con, cambio) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (t_id, cliente_dni, now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), total_v, pago_con, cambio))

                    pdf_bytes = generar_pdf_ticket(t_id, cliente_dni, st.session_state.carrito, total_v, pago_con,
                                                   cambio)
                    st.session_state.ultimo_ticket = {"id": t_id, "bytes": pdf_bytes}
                    st.session_state.carrito = []
                    reload_app()
            else:
                st.info("El carrito está vacío.")

            if st.session_state.ultimo_ticket:
                st.success(f"¡Venta #{st.session_state.ultimo_ticket['id']} registrada!")
                st.download_button("📄 Descargar Ticket PDF", data=st.session_state.ultimo_ticket["bytes"],
                                   file_name=f"Ticket_{st.session_state.ultimo_ticket['id']}.pdf",
                                   mime="application/pdf")

# --- 2. INVENTARIO / COMPRAS ---
elif choice == "📦 Inventario / Compras":
    st.title("📦 Control de Inventario (MySQL)")
    search_q = st.text_input("🔍 Buscar por Código de Producto:")

    query_inv = """SELECT i.codigo, i.producto, i.marca, i.modelo, i.presentacion, i.categoria, 
                          i.unidad, i.stock, i.stock_minimo, i.p_compra, i.p_venta, p.nombre as proveedor 
                   FROM inventario i LEFT JOIN proveedores p ON i.proveedor_id = p.id"""

    if search_q:
        df_inv_res = get_df(query_inv + " WHERE i.codigo LIKE %s", (f"%{search_q}%",))
    else:
        df_inv_res = get_df(query_inv)

    st.dataframe(df_inv_res)

# --- 3. PROVEEDORES ---
elif choice == "🚚 Proveedores":
    st.title("🚚 Gestión de Proveedores")
    opcion_prov = st.radio("Acción:", ["Ver Registro", "Nuevo Proveedor"], horizontal=True)

    if opcion_prov == "Ver Registro":
        st.dataframe(get_df("SELECT * FROM proveedores"))
    else:
        with st.form("prov_form"):
            nom = st.text_input("Nombre de la Empresa")
            contacto = st.text_input("Contacto")
            tel = st.text_input("Teléfono")
            if st.form_submit_button("Guardar Proveedor"):
                if nom.strip():
                    try:
                        run_query("INSERT INTO proveedores (nombre, contacto, telefono) VALUES (%s,%s,%s)",
                                  (nom, contacto, tel))
                        st.success("Proveedor guardado.")
                        reload_app()
                    except Exception as e:
                        st.error(f"Error: {e}")

# --- 4. CORTE DE CAJA ---
elif choice == "📊 Corte de Caja":
    st.title("📊 Corte de Caja")
    periodo = st.radio("Filtrar por:", ["Hoy", "Esta Semana", "Este Mes"], horizontal=True)
    hoy = datetime.now()
    if periodo == "Hoy":
        fecha_inicio = hoy.strftime("%Y-%m-%d")
    elif periodo == "Esta Semana":
        fecha_inicio = (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
    else:
        fecha_inicio = hoy.strftime("%Y-%m-01")

    df_corte = get_df(
        "SELECT v.*, i.p_compra FROM ventas v LEFT JOIN inventario i ON v.codigo = i.codigo WHERE v.fecha >= %s AND v.estado = 'COMPLETADA'",
        (fecha_inicio,))

    if not df_corte.empty:
        total_ventas = df_corte['total'].sum()
        total_costos = (df_corte['cantidad'] * df_corte['p_compra'].fillna(0)).sum()
        utilidad = total_ventas - total_costos

        m1, m2, m3 = st.columns(3)
        m1.metric("Ventas Totales", f"${total_ventas:,.2f}")
        m2.metric("Costo Invertido", f"${total_costos:,.2f}")
        m3.metric("Ganancia Neta", f"${utilidad:,.2f}")
        st.dataframe(
            df_corte[['transaccion_id', 'cliente_dni', 'fecha', 'hora', 'producto', 'cantidad', 'p_venta', 'total']])
    else:
        st.info("No hay ventas registradas.")

# --- 5. HISTORIAL ---
elif choice == "📉 Historial":
    st.title("📉 Historial de Ventas")
    df_ventas = get_df("SELECT * FROM ventas ORDER BY fecha DESC, hora DESC")
    st.dataframe(df_ventas)

# --- 6. REGISTRAR PRODUCTO ---
elif choice == "🛠️ Registrar Producto":
    st.title("🛠 Registrar Producto en MySQL")
    df_prov = get_df("SELECT id, nombre FROM proveedores")
    dict_prov = dict(zip(df_prov['nombre'], df_prov['id'])) if not df_prov.empty else {}

    with st.form("prod_form"):
        c1, c2 = st.columns(2)
        cod = c1.text_input("Código de Barras")
        prod = c2.text_input("Nombre del Producto")

        c_m1, c_m2, c_m3 = st.columns(3)
        marca = c_m1.text_input("Marca")
        modelo = c_m2.text_input("Modelo")
        presentacion = c_m3.text_input("Presentación")

        c3, c4, c5 = st.columns(3)
        cat = c3.selectbox("Categoría", ["Abarrotes", "Lácteos", "Bebidas", "Botanas", "Limpieza", "Otros"])
        uni = c4.selectbox("Unidad de Medida", ["Pieza", "Kg", "Litro", "Paquete", "Caja"])
        prov_nom = c5.selectbox("Proveedor", list(dict_prov.keys()) if dict_prov else ["Sin Proveedor"])

        c6, c7, c8, c9 = st.columns(4)
        stk = c6.number_input("Stock Inicial", min_value=0.0, step=1.0)
        stk_min = c7.number_input("Stock Mínimo", min_value=0.0, value=5.0, step=1.0)
        pc = c8.number_input("Precio Compra", min_value=0.0, step=1.0)
        pv = c9.number_input("Precio Venta", min_value=0.0, step=1.0)

        if st.form_submit_button("Guardar Producto"):
            if cod and prod:
                p_id = dict_prov.get(prov_nom, None)
                query = """INSERT INTO inventario (codigo, producto, marca, modelo, presentacion, categoria, unidad, stock, stock_minimo, p_compra, p_venta, proveedor_id) 
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE 
                           producto=VALUES(producto), marca=VALUES(marca), modelo=VALUES(modelo), presentacion=VALUES(presentacion),
                           categoria=VALUES(categoria), unidad=VALUES(unidad), stock=VALUES(stock), stock_minimo=VALUES(stock_minimo),
                           p_compra=VALUES(p_compra), p_venta=VALUES(p_venta), proveedor_id=VALUES(proveedor_id)"""
                run_query(query, (cod, prod, marca, modelo, presentacion, cat, uni, stk, stk_min, pc, pv, p_id))
                st.success(f"Producto '{prod}' guardado en MySQL.")

# --- 7. RESPALDOS Y RESTAURACIÓN ---
elif choice == "💾 Respaldos":
    st.title("💾 Respaldos y Restauración de Base de Datos (MySQL)")

    st.markdown("---")
    st.subheader("🧾 Guardado y Respaldo de Tickets Registrados")

    df_tickets = get_df("SELECT * FROM tickets ORDER BY fecha DESC, hora DESC")

    if not df_tickets.empty:
        st.dataframe(df_tickets)

        csv_data = df_tickets.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Respaldo de Tickets (CSV)",
            data=csv_data,
            file_name=f"Respaldo_Tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("Aún no hay tickets registrados.")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📥 Exportar Copia de Seguridad Completa")
        st.write("Genera un archivo `.sql` con la estructura y todos los datos actuales de MySQL.")

        if st.button("📦 Generar Respaldo SQL"):
            try:
                conn = get_mysql_connection()
                cursor = conn.cursor()

                sql_dump = f"-- Respaldo de Base de Datos: {MYSQL_DB}\n"
                sql_dump += f"-- Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

                cursor.execute("SHOW TABLES")
                tablas = [row[0] for row in cursor.fetchall()]

                for tabla in tablas:
                    cursor.execute(f"SHOW CREATE TABLE `{tabla}`")
                    create_table_sql = cursor.fetchall()[0][1]
                    sql_dump += f"DROP TABLE IF EXISTS `{tabla}`;\n"
                    sql_dump += f"{create_table_sql};\n\n"

                    cursor.execute(f"SELECT * FROM `{tabla}`")
                    filas = cursor.fetchall()
                    if filas:
                        cursor.execute(f"SHOW COLUMNS FROM `{tabla}`")
                        cols = [f"`{c[0]}`" for c in cursor.fetchall()]
                        cols_str = ", ".join(cols)

                        for fila in filas:
                            valores = []
                            for val in fila:
                                if val is None:
                                    valores.append("NULL")
                                elif isinstance(val, (int, float)):
                                    valores.append(str(val))
                                else:
                                    val_esc = str(val).replace("'", "''").replace("\\", "\\\\")
                                    valores.append(f"'{val_esc}'")

                            val_str = ", ".join(valores)
                            sql_dump += f"INSERT INTO `{tabla}` ({cols_str}) VALUES ({val_str});\n"
                        sql_dump += "\n"

                cursor.close()
                conn.close()

                st.download_button(
                    label="💾 Descargar Respaldo (.sql)",
                    data=sql_dump,
                    file_name=f"Respaldo_Tiendita_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql",
                    mime="application/sql"
                )
                st.success("¡Respaldo generado con éxito!")

            except Exception as e:
                st.error(f"Error al exportar la base de datos: {e}")

    with col2:
        st.subheader("📤 Restaurar desde Archivo Respaldo (.sql o .db)")
        st.write("Sube tu archivo `.sql` o `.db` (SQLite) para volcar la información a MySQL.")

        archivo_respaldo = st.file_uploader("Selecciona un archivo .sql o .db", type=["sql", "db"])

        if archivo_respaldo is not None:
            if st.button("🚀 Confirmar y Restaurar Datos"):
                nombre_archivo = archivo_respaldo.name.lower()

                if nombre_archivo.endswith(".sql"):
                    try:
                        contenido_sql = archivo_respaldo.getvalue().decode("utf-8")
                        conn = get_mysql_connection()
                        cursor = conn.cursor()

                        sentencias = contenido_sql.split(";")
                        for sentencia in sentencias:
                            sentencia_limpia = sentencia.strip()
                            if sentencia_limpia and not sentencia_limpia.startswith("--"):
                                cursor.execute(sentencia_limpia)

                        conn.commit()
                        cursor.close()
                        conn.close()
                        st.success("¡Base de datos restaurada correctamente desde el archivo SQL!")
                        reload_app()
                    except Exception as e:
                        st.error(f"Error al restaurar archivo SQL: {e}")

                elif nombre_archivo.endswith(".db"):
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp_file:
                            tmp_file.write(archivo_respaldo.getvalue())
                            tmp_path = tmp_file.name

                        sqlite_conn = sqlite3.connect(tmp_path)
                        mysql_conn = get_mysql_connection()
                        mysql_cursor = mysql_conn.cursor()


                        def clean_val(v, default=None):
                            return default if pd.isna(v) else v


                        try:
                            df_prov = pd.read_sql_query("SELECT * FROM proveedores", sqlite_conn)
                            df_prov = df_prov.where(pd.notnull(df_prov), None)
                            for _, r in df_prov.iterrows():
                                mysql_cursor.execute(
                                    "INSERT INTO proveedores (id, nombre, contacto, telefono) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)",
                                    (clean_val(r.get('id')), clean_val(r.get('nombre'), ''),
                                     clean_val(r.get('contacto'), ''), clean_val(r.get('telefono'), ''))
                                )
                        except Exception:
                            pass

                        try:
                            df_inv = pd.read_sql_query("SELECT * FROM inventario", sqlite_conn)
                            df_inv = df_inv.where(pd.notnull(df_inv), None)
                            for _, r in df_inv.iterrows():
                                mysql_cursor.execute(
                                    """INSERT INTO inventario (codigo, producto, marca, modelo, presentacion, categoria, unidad, stock, stock_minimo, p_compra, p_venta, proveedor_id)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                       ON DUPLICATE KEY UPDATE producto=VALUES(producto), stock=VALUES(stock), p_venta=VALUES(p_venta)""",
                                    (clean_val(r.get('codigo'), ''), clean_val(r.get('producto'), ''),
                                     clean_val(r.get('marca'), ''), clean_val(r.get('modelo'), ''),
                                     clean_val(r.get('presentacion'), ''),
                                     clean_val(r.get('categoria'), 'Abarrotes'), clean_val(r.get('unidad'), 'Pieza'),
                                     clean_val(r.get('stock'), 0.0), clean_val(r.get('stock_minimo'), 5.0),
                                     clean_val(r.get('p_compra'), 0.0), clean_val(r.get('p_venta'), 0.0),
                                     clean_val(r.get('proveedor_id')))
                                )
                        except Exception:
                            pass

                        try:
                            df_ventas = pd.read_sql_query("SELECT * FROM ventas", sqlite_conn)
                            df_ventas = df_ventas.where(pd.notnull(df_ventas), None)
                            for _, r in df_ventas.iterrows():
                                mysql_cursor.execute(
                                    """INSERT INTO ventas (transaccion_id, cliente_dni, fecha, hora, codigo, producto, cantidad, p_venta, total, estado)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                    (clean_val(r.get('transaccion_id'), ''), clean_val(r.get('cliente_dni'), 'CF'),
                                     clean_val(r.get('fecha'), ''), clean_val(r.get('hora'), ''),
                                     clean_val(r.get('codigo'), ''), clean_val(r.get('producto'), ''),
                                     clean_val(r.get('cantidad'), 1.0), clean_val(r.get('p_venta'), 0.0),
                                     clean_val(r.get('total'), 0.0), clean_val(r.get('estado'), 'COMPLETADA'))
                                )
                        except Exception:
                            pass

                        mysql_conn.commit()
                        mysql_cursor.close()
                        mysql_conn.close()
                        sqlite_conn.close()
                        os.remove(tmp_path)

                        st.success("¡Respaldo .db (SQLite) migrado y cargado exitosamente a MySQL!")
                        reload_app()
                    except Exception as e:
                        st.error(f"Error al migrar archivo .db a MySQL: {e}")

# --- 8. CONFIGURACIÓN DE CUENTA DE USUARIO ---
elif choice == "👤 Mi Cuenta":
    st.title("👤 Configuración de la Cuenta de Acceso")
    st.write("Cambia tu nombre de usuario o contraseña para acceder al sistema.")

    # Cargar datos actuales del usuario en sesión
    usr_actual = st.session_state.usuario_actual

    with st.form("form_mi_cuenta"):
        nuevo_usuario = st.text_input("Nuevo Nombre de Usuario", value=usr_actual)
        pass_actual = st.text_input("Contraseña Actual", type="password")
        pass_nueva = st.text_input("Nueva Contraseña", type="password")
        pass_confirmar = st.text_input("Confirmar Nueva Contraseña", type="password")

        if st.form_submit_button("💾 Guardar Cambios"):
            if not nuevo_usuario.strip():
                st.error("El nombre de usuario no puede estar vacío.")
            elif not pass_actual:
                st.error("Ingresa tu contraseña actual para confirmar los cambios.")
            else:
                # Verificar credenciales actuales
                df_check = get_df("SELECT * FROM usuarios WHERE username = %s AND password = %s",
                                  (usr_actual, pass_actual))

                if df_check.empty:
                    st.error("La contraseña actual es incorrecta.")
                else:
                    if pass_nueva:
                        if pass_nueva != pass_confirmar:
                            st.error("La nueva contraseña y la confirmación no coinciden.")
                        else:
                            run_query("UPDATE usuarios SET username = %s, password = %s WHERE username = %s",
                                      (nuevo_usuario.strip(), pass_nueva, usr_actual))
                            st.session_state.usuario_actual = nuevo_usuario.strip()
                            st.success("¡Usuario y contraseña actualizados con éxito!")
                            reload_app()
                    else:
                        run_query("UPDATE usuarios SET username = %s WHERE username = %s",
                                  (nuevo_usuario.strip(), usr_actual))
                        st.session_state.usuario_actual = nuevo_usuario.strip()
                        st.success("¡Nombre de usuario actualizado con éxito!")
                        reload_app()