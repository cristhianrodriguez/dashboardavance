import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import numpy as np

def calcular_dias_habiles(start_series, end_series):
    holidays = ['2026-03-24', '2026-04-02', '2026-04-03']
    s = start_series.dt.date.values.astype('datetime64[D]')
    e = end_series.dt.date.values.astype('datetime64[D]')
    return np.busday_count(s, e, holidays=holidays)

st.set_page_config(page_title="Dashboard Gantt de Avance de Producción", layout="wide")

# Función get_base_station original eliminada para usar mapeo dinámico en el procesamiento

st.title("📊 Seguimiento de Producción por Operario (Diagrama de Gantt)")
st.markdown("Visualización del tiempo que cada pieza transcurre en las distintas estaciones de trabajo.")

# Archivo por defecto
default_path = r"c:/Users/Cristhian.Rodriguez/Desktop/Antigravity Projects/ControlporOperario/grupopanamericano-resumen.xlsx"

uploaded_file = st.file_uploader("Sube el archivo Excel de Producción por Operario", type=["xlsx", "xlsm"])
file_path = uploaded_file if uploaded_file else (default_path if os.path.exists(default_path) else None)

if file_path is None:
    st.warning(f"No se subió ningún archivo y no se encontró el archivo por defecto en {default_path}.")
else:
    try:
        # Leer archivo
        df = pd.read_excel(file_path)
        
        # Limpiar columnas para evitar problemas de encoding (ej: Estación de trabajo)
        df.columns = [c.encode('latin1').decode('utf-8', 'ignore') if isinstance(c, str) else c for c in df.columns]
        
        # Detectar columnas clave con flexibilidad
        cols = {c.lower(): c for c in df.columns}
        
        col_codigo = cols.get('codigo qr', cols.get('codigo unico', cols.get('codigo', next((c for c in df.columns if 'codigo' in c.lower()), None))))
        col_nombre = cols.get('codigo', next((c for c in df.columns if 'codigo' in c.lower() and c != col_codigo), None))
        col_fecha = cols.get('fecha de trabajo', next((c for c in df.columns if 'fecha' in c.lower()), None))
        col_estacion = cols.get('estación de trabajo', cols.get('estacin de trabajo', next((c for c in df.columns if 'estaci' in c.lower()), None)))
        col_obra = cols.get('obra', next((c for c in df.columns if 'obra' in c.lower()), None))
        col_peso = cols.get('producción', cols.get('produccin', cols.get('peso', next((c for c in df.columns if 'producc' in c.lower() or 'peso' in c.lower()), None))))
        
        if not all([col_codigo, col_fecha, col_estacion]):
            st.error("No se encontraron las columnas necesarias (Codigo, Fecha de trabajo, Estación de trabajo).")
            st.write("Columnas detectadas:", list(df.columns))
        else:
            # Procesar datos
            df['Fecha Real'] = pd.to_datetime(df[col_fecha], format='%d/%m/%Y', errors='coerce')
            
            # Limpiar codificación de la columna estación
            df['Estacion cruda'] = df[col_estacion].apply(
                lambda x: str(x).encode('latin1').decode('utf-8', 'ignore') if isinstance(x, str) else str(x)
            )
            
            # Crear mapeo dinámico para recuperar el número (ej: 'Soldado' -> '03 - Soldado')
            mapping = {}
            for st_val in df['Estacion cruda'].unique():
                if " - " in str(st_val):
                    base = str(st_val).split(" - ")[-1].strip()
                    mapping[base] = str(st_val).strip()
            
            def map_to_full_station(name):
                name = str(name).strip()
                if " - " in name:
                    return name
                if " Finalizado" in name:
                    base_name = name.replace(" Finalizado", "").strip()
                    return mapping.get(base_name, base_name + " (Finalizado)")
                return mapping.get(name, name)
                
            df['Estacion Base'] = df['Estacion cruda'].apply(map_to_full_station)

            # Filtro por Obra
            if col_obra:
                obras_disp = df[col_obra].dropna().unique()
                obra_sel = st.selectbox("Seleccione la Obra:", options=["Todas"] + list(obras_disp))
                if obra_sel != "Todas":
                    df = df[df[col_obra] == obra_sel]
            
            # Remover nulos en fechas y mantener orden original
            df_valido = df.dropna(subset=['Fecha Real', col_codigo]).copy()
            # Omitir eventos "Pintado Finalizado" debido a retrasos sistémicos en el escaneo
            df_valido = df_valido[~df_valido['Estacion cruda'].astype(str).str.contains('Pintado Finalizado', case=False, na=False)]
            # Añadir índice original para desempatar orden si fuera necesario
            df_valido['_order'] = range(len(df_valido))
            
            # Crear nombres para visualización
            def create_display_names(row):
                qr_val = str(row[col_codigo])
                nombre_val = str(row[col_nombre]) if col_nombre and col_nombre in row else ""
                if nombre_val.lower() == 'nan': nombre_val = ""
                if qr_val.lower() == 'nan': qr_val = ""
                extra = qr_val.replace(nombre_val, "").strip() if nombre_val else qr_val.strip()
                if extra and nombre_val and extra != nombre_val:
                    return f"<b>{nombre_val}</b> ({extra})", f"{nombre_val} ({extra})"
                elif nombre_val:
                    return f"<b>{nombre_val}</b>", nombre_val
                else:
                    return f"<b>{qr_val}</b>", qr_val

            if col_nombre:
                display_tuples = df_valido.apply(create_display_names, axis=1)
                df_valido['Display_Chart'] = [t[0] for t in display_tuples]
                df_valido['Display_Table'] = [t[1] for t in display_tuples]
            else:
                df_valido['Display_Chart'] = "<b>" + df_valido[col_codigo].astype(str) + "</b>"
                df_valido['Display_Table'] = df_valido[col_codigo].astype(str)
                
            map_chart = dict(zip(df_valido[col_codigo], df_valido['Display_Chart']))
            map_table = dict(zip(df_valido[col_codigo], df_valido['Display_Table']))
            
            # Gantt Data
            gantt_data = df_valido.groupby([col_codigo, 'Estacion Base']).agg(
                Start=('Fecha Real', 'min'),
                Finish=('Fecha Real', 'max'),
                Order_Hint=('_order', 'min')  # Para preservar orden cronológico original en el mismo día
            ).reset_index()
            
            # Calcular duración real en días hábiles antes de modificar para visualización
            gantt_data['Duración (Días)'] = calcular_dias_habiles(gantt_data['Start'], gantt_data['Finish'])
            gantt_data['Duración (Días)'] = gantt_data['Duración (Días)'].apply(lambda x: x if x > 0 else 1)
            
            # Forzar la estación de Pintado a contabilizar exactamente 1 día de producción
            mask_pintado = gantt_data['Estacion Base'].str.contains('Pintado', case=False, na=False)
            gantt_data.loc[mask_pintado, 'Duración (Días)'] = 1
            gantt_data.loc[mask_pintado, 'Finish'] = gantt_data.loc[mask_pintado, 'Start']
            
            # Ajuste visual para el Gantt para que EVENTOS DEL MISMO DÍA no se encimen y se oculten
            # Ordenamos por fecha de inicio y luego por su orden original de aparición
            gantt_data = gantt_data.sort_values([col_codigo, 'Start', 'Order_Hint'])
            
            # Si hay varios eventos para el mismo código en el MISMO día de Start, fraccionamos las 24hs
            gantt_data['day_rank'] = gantt_data.groupby([col_codigo, 'Start']).cumcount()
            gantt_data['day_total'] = gantt_data.groupby([col_codigo, 'Start'])['Estacion Base'].transform('count')
            
            gantt_data['Start_Visual'] = gantt_data['Start'] + pd.to_timedelta(gantt_data['day_rank'] * 24 / gantt_data['day_total'], unit='h')
            
            # Para el Finish Visual, si Start == Finish (mismo día), fraccionamos. Si es multi-día, usamos Finish
            gantt_data['Finish_Visual'] = gantt_data['Start'] + pd.to_timedelta((gantt_data['day_rank'] + 1) * 24 / gantt_data['day_total'], unit='h')
            
            multi_day = gantt_data['Finish'] > gantt_data['Start']
            gantt_data.loc[multi_day, 'Finish_Visual'] = gantt_data.loc[multi_day, 'Finish'] + pd.Timedelta(days=1)
            # Para eventos multi-dia, si empezaron junto a otros el mismo dia, su Start_Visual ya está acomodado, 
            # pero típicamente el multi-día es el único. Si no, su Finish_Visual prevalece.
            
            gantt_data = gantt_data.sort_values(['Start', col_codigo])
            gantt_data['Display_Chart'] = gantt_data[col_codigo].map(map_chart)
            
            # --- DETECCIÓN DE ANOMALÍAS ---
            st.sidebar.markdown("---")
            st.sidebar.subheader("⚙️ Filtro de Anomalías")
            umbral_dias = st.sidebar.number_input("Ocultar piezas con tiempo de ciclo mayor a (Días):", min_value=1, value=40, step=5)
            
            # 1. Por duración excesiva en días hábiles
            code_durations = df_valido.groupby(col_codigo)['Fecha Real'].agg(['min', 'max'])
            code_durations['Total_Days'] = calcular_dias_habiles(code_durations['min'], code_durations['max'])
            codes_too_long = code_durations[code_durations['Total_Days'] > umbral_dias].index.tolist()
            
            # 2. Por regresión (saltean y vuelven atrás en los estados)
            def extract_state_number(state_str):
                match = re.search(r'^(\d+)', str(state_str))
                return int(match.group(1)) if match else 99
                
            df_valido['State_Num'] = df_valido['Estacion Base'].apply(extract_state_number)
            def has_regression(group):
                nums = group['State_Num'].dropna().tolist()
                for i in range(1, len(nums)):
                    if nums[i] < nums[i-1]:
                        return True
                return False
                
            regressions = df_valido.sort_values(['Fecha Real', '_order']).groupby(col_codigo).apply(has_regression)
            codes_with_regression = regressions[regressions].index.tolist()
            
            anomalous_codes = set(codes_too_long + codes_with_regression)
            gantt_data['Is_Anomaly'] = gantt_data[col_codigo].isin(anomalous_codes)
            
            # --- CONSTRUCCIÓN DE TABLAS --- 
            resumen_codigo = df_valido.groupby(col_codigo).agg(
                Fecha_Ingreso=('Fecha Real', 'min'),
                Fecha_Ultimo_Cambio=('Fecha Real', 'max'),
            ).reset_index()
            
            ultimo_estado = df_valido.sort_values('Fecha Real').groupby(col_codigo).tail(1)[[col_codigo, 'Estacion Base']]
            ultimo_estado.rename(columns={'Estacion Base': 'Último Estado Registrado'}, inplace=True)
            
            resumen_codigo = resumen_codigo.merge(ultimo_estado, on=col_codigo, how='left')
            resumen_codigo['Tiempo Total (Días)'] = calcular_dias_habiles(resumen_codigo['Fecha_Ingreso'], resumen_codigo['Fecha_Ultimo_Cambio'])
            resumen_codigo['Tiempo Total (Días)'] = resumen_codigo['Tiempo Total (Días)'].apply(lambda x: x if x > 0 else 1)
            resumen_codigo['Fecha de Ingreso a Planta'] = resumen_codigo['Fecha_Ingreso'].dt.strftime('%d/%m/%Y')
            resumen_codigo['Fecha de Último Movimiento'] = resumen_codigo['Fecha_Ultimo_Cambio'].dt.strftime('%d/%m/%Y')
            resumen_codigo.rename(columns={col_codigo: 'Código'}, inplace=True)
            resumen_codigo['Código'] = resumen_codigo['Código'].map(map_table)
            resumen_cols = ['Código', 'Fecha de Ingreso a Planta', 'Fecha de Último Movimiento', 'Último Estado Registrado', 'Tiempo Total (Días)']
            resumen_codigo = resumen_codigo[resumen_cols]
            
            detalle_estados = gantt_data[[col_codigo, 'Estacion Base', 'Start', 'Finish', 'Duración (Días)', 'Is_Anomaly']].copy()
            detalle_estados['Fecha Inicio'] = detalle_estados['Start'].dt.strftime('%d/%m/%Y')
            detalle_estados['Fecha Fin'] = detalle_estados['Finish'].dt.strftime('%d/%m/%Y')
            detalle_estados.rename(columns={col_codigo: 'Código', 'Estacion Base': 'Estado / Estación'}, inplace=True)
            detalle_estados['Código'] = detalle_estados['Código'].map(map_table)
            detalle_cols = ['Código', 'Estado / Estación', 'Fecha Inicio', 'Fecha Fin', 'Duración (Días)']
            
            # --- RENDERIZADO DE TABS ---
            tab_normal, tab_anomalo = st.tabs(["✅ Producción Regular", "⚠️ Anomalías y Reprocesos"])
            
            with tab_normal:
                st.subheader("📊 Resumen Global en Planta")
                resumen_normal = resumen_codigo[~resumen_codigo['Código'].isin(anomalous_codes)]
                if not resumen_normal.empty:
                    col1, col2 = st.columns(2)
                    torta_data = resumen_normal['Último Estado Registrado'].value_counts().reset_index()
                    torta_data.columns = ['Estado', 'Cantidad de Piezas']
                    fig_pie = px.pie(torta_data, names='Estado', values='Cantidad de Piezas', hole=0.4, title="📦 Distribución de Piezas (Uds)")
                    fig_pie.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                    col1.plotly_chart(fig_pie, use_container_width=True)
                    
                    if col_peso:
                        ultimos_eventos = df_valido[~df_valido[col_codigo].isin(anomalous_codes)].copy()
                        ultimos_eventos = ultimos_eventos.sort_values(['Fecha Real', '_order']).groupby(col_codigo).tail(1)
                        ultimos_eventos['_peso'] = pd.to_numeric(ultimos_eventos[col_peso], errors='coerce').fillna(0)
                        bar_data = ultimos_eventos.groupby('Estacion Base')['_peso'].sum().reset_index()
                        bar_data.rename(columns={'Estacion Base': 'Estado', '_peso': 'Peso Total (Kg)'}, inplace=True)
                        bar_data = bar_data.sort_values(by='Peso Total (Kg)', ascending=False)
                        fig_bar = px.bar(bar_data, x='Estado', y='Peso Total (Kg)', color='Estado', title="⚖️ Avance por Peso (Kilos)")
                        fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', showlegend=False)
                        col2.plotly_chart(fig_bar, use_container_width=True)
                
                st.markdown("---")
                st.subheader("🗓️ Diagrama de Avance Principal")
                gantt_normal = gantt_data[~gantt_data['Is_Anomaly']]
                
                
                if gantt_normal.empty:
                    st.info("No hay flujos regulares para mostrar.")
                else:
                    fig_normal = px.timeline(
                        gantt_normal, x_start="Start_Visual", x_end="Finish_Visual", y="Display_Chart", color="Estacion Base",
                        hover_data={"Start_Visual": False, "Start": "|%d/%m/%Y", "Finish": "|%d/%m/%Y", "Finish_Visual": False, "Duración (Días)": True},
                    )
                    fig_normal.update_yaxes(autorange="reversed", showgrid=True, gridcolor='rgba(255,255,255,0.05)')
                    fig_normal.update_xaxes(showgrid=True, gridcolor='rgba(255,255,255,0.2)')
                    fig_normal.update_layout(
                        height=max(400, len(gantt_normal[col_codigo].unique()) * 20),
                        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
                    )
                    fig_normal.layout.xaxis.type = 'date'
                    st.plotly_chart(fig_normal, use_container_width=True)
                
                st.subheader("⏱️ Tiempos Totales")
                st.dataframe(resumen_codigo[~resumen_codigo['Código'].isin(anomalous_codes)], use_container_width=True, hide_index=True)
                st.subheader("📋 Detalle de Estados")
                st.dataframe(detalle_estados[~detalle_estados['Is_Anomaly']][detalle_cols], use_container_width=True, hide_index=True)

            with tab_anomalo:
                st.subheader("⚠️ Sector de Anomalías")
                st.markdown("Se han separado porque superaron el umbral de duración, o retrocedieron de fase (ej: de Plantillado volvieron a Soldado).")
                
                gantt_anomalo = gantt_data[gantt_data['Is_Anomaly']]
                
                if gantt_anomalo.empty:
                    st.success("¡No se detectaron piezas con comportamiento anómalo!")
                else:
                    if codes_too_long:
                        mapped_too_long = [map_table.get(c, c) for c in codes_too_long]
                        st.error(f"**Tiempos Extremos (> {umbral_dias} días):** {', '.join(str(c) for c in mapped_too_long)}")
                    if codes_with_regression:
                        mapped_regression = [map_table.get(c, c) for c in codes_with_regression]
                        st.warning(f"**Regresiones o Reprocesos (saltos erróneos):** {', '.join(str(c) for c in mapped_regression)}")
                    
                    fig_anomalo = px.timeline(
                        gantt_anomalo, x_start="Start_Visual", x_end="Finish_Visual", y="Display_Chart", color="Estacion Base",
                        hover_data={"Start_Visual": False, "Start": "|%d/%m/%Y", "Finish": "|%d/%m/%Y", "Finish_Visual": False, "Duración (Días)": True},
                    )
                    fig_anomalo.update_yaxes(autorange="reversed", showgrid=True, gridcolor='rgba(255,255,255,0.05)')
                    fig_anomalo.update_xaxes(showgrid=True, gridcolor='rgba(255,255,255,0.2)')
                    fig_anomalo.update_layout(
                        height=max(400, len(gantt_anomalo[col_codigo].unique()) * 20),
                        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
                    )
                    fig_anomalo.layout.xaxis.type = 'date'
                    st.plotly_chart(fig_anomalo, use_container_width=True)
                    
                    st.subheader("⏱️ Tiempos Totales (Irregulares)")
                    st.dataframe(resumen_codigo[resumen_codigo['Código'].isin(anomalous_codes)], use_container_width=True, hide_index=True)
                    st.subheader("📋 Detalle de Estados (Irregulares)")
                    st.dataframe(detalle_estados[detalle_estados['Is_Anomaly']][detalle_cols], use_container_width=True, hide_index=True)
            
    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
