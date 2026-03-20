import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Integración de Energía", layout="wide")


# ==========================================================
# CONVERSIONES DE UNIDADES
# Base interna:
#   Q  -> kW
#   CP -> kW/°C
# ==========================================================
FACTORES_Q = {
    "W": 0.001,
    "kW": 1.0,
    "MW": 1000.0,
    "kcal/h": 0.001163,
    "BTU/h": 0.000293071,
}

FACTORES_CP = {
    "W/°C": 0.001,
    "kW/°C": 1.0,
    "MW/°C": 1000.0,
    "kcal/h·°C": 0.001163,
    "BTU/h·°F": 0.000527527,
}


# ==========================================================
# FUNCIONES AUXILIARES
# ==========================================================
def convertir_q_a_kw(valor, unidad_q):
    if valor in [None, ""] or pd.isna(valor):
        return None
    return float(valor) * FACTORES_Q[unidad_q]

def convertir_kw_a_unidad_q(valor_kw, unidad_q):
    return valor_kw / FACTORES_Q[unidad_q]

def convertir_cp_a_kwc(valor, unidad_cp):
    if valor in [None, ""] or pd.isna(valor):
        return None
    return float(valor) * FACTORES_CP[unidad_cp]



def calcular_cp(row):
    cp = row.get("CP", None)
    q = row.get("Q", None)
    ti = row["Ti"]
    to = row["To"]

    if cp not in [None, ""] and not pd.isna(cp):
        return float(cp)

    if q not in [None, ""] and not pd.isna(q):
        dT = abs(to - ti)
        if dT == 0:
            raise ValueError(f"La corriente {row['Nombre']} tiene ΔT = 0.")
        return float(q) / dT

    raise ValueError(f"La corriente {row['Nombre']} necesita Q o CP.")


def calcular_q(row):
    q = row.get("Q", None)
    if q not in [None, ""] and not pd.isna(q):
        return float(q)
    return float(row["CP"]) * abs(row["To"] - row["Ti"])


def aplicar_shift(row, delta_shift):
    if row["Tipo"] == "F":
        return pd.Series({
            "Ti_s": row["Ti"] + delta_shift,
            "To_s": row["To"] + delta_shift
        })
    else:
        return pd.Series({
            "Ti_s": row["Ti"] - delta_shift,
            "To_s": row["To"] - delta_shift
        })


def preparar_corrientes(df_entrada, unidad_q, unidad_cp):
    df = df_entrada.copy()

    # Convertir a base interna
    df["Q"] = df["Q"].apply(lambda x: convertir_q_a_kw(x, unidad_q))
    df["CP"] = df["CP"].apply(lambda x: convertir_cp_a_kwc(x, unidad_cp))

    # Calcular faltantes
    df["CP"] = df.apply(calcular_cp, axis=1)
    df["Q"] = df.apply(calcular_q, axis=1)

    return df


def construir_cascada(df_entrada, delta_shift):
    df = df_entrada.copy()

    df[["Ti_s", "To_s"]] = df.apply(lambda r: aplicar_shift(r, delta_shift), axis=1)

    temps = sorted(set(df["Ti_s"].tolist() + df["To_s"].tolist()))
    tabla = pd.DataFrame({"T": temps})

    for nombre in df["Nombre"]:
        tabla[nombre] = 0.0

    # Cada fila i representa el intervalo [temps[i-1], temps[i]]
    for i in range(1, len(temps)):
        t_low = temps[i - 1]
        t_high = temps[i]
        dT = t_high - t_low

        for _, row in df.iterrows():
            tmin = min(row["Ti_s"], row["To_s"])
            tmax = max(row["Ti_s"], row["To_s"])

            if (t_low >= tmin - 1e-9) and (t_high <= tmax + 1e-9):
                tabla.loc[i, row["Nombre"]] = row["CP"] * dT

    frias = df[df["Tipo"] == "F"]["Nombre"].tolist()
    calientes = df[df["Tipo"] == "C"]["Nombre"].tolist()

    tabla["CCF"] = tabla[frias].sum(axis=1).cumsum()
    tabla["CCC"] = tabla[calientes].sum(axis=1).cumsum()
    tabla["CCF-CCC"] = tabla["CCF"] - tabla["CCC"]

    # Definiciones corregidas
    calentamiento_original = tabla["CCF"].iloc[-1]
    enfriamiento_original = tabla["CCC"].iloc[-1]

    enfriamiento_min = abs(tabla["CCF-CCC"].min())

    tabla["CCF'"] = tabla["CCF"] + enfriamiento_min
    tabla["CCF'-CCC"] = tabla["CCF'"] - tabla["CCC"]

    calentamiento_min = tabla["CCF'"].iloc[-1] - tabla["CCC"].iloc[-1]

    calor_integrado = tabla["CCC"].iloc[-1] - enfriamiento_min

    ahorro_calor = (
        100 * calor_integrado / enfriamiento_original
        if enfriamiento_original != 0 else 0
    )
    ahorro_frio = (
        100 * calor_integrado / calentamiento_original
        if calentamiento_original != 0 else 0
    )

    tabla_final = tabla.copy()
    fila_suma = {"T": "Suma="}

    for col in frias + calientes:
        fila_suma[col] = tabla_final[col].sum()

    for col in ["CCF", "CCC", "CCF-CCC", "CCF'", "CCF'-CCC"]:
        fila_suma[col] = ""

    tabla_final = pd.concat([tabla_final, pd.DataFrame([fila_suma])], ignore_index=True)

    resultados = {
        "Calentamiento original [kW]": calentamiento_original,
        "Enfriamiento original [kW]": enfriamiento_original,
        "Calor Integrado [kW]": calor_integrado,
        "Enfriamiento mínimo [kW]": enfriamiento_min,
        "Calentamiento mínimo [kW]": calentamiento_min,
        "Ahorro Calor [%]": ahorro_calor,
        "Ahorro Frío [%]": ahorro_frio,
    }

    return df, tabla, tabla_final, resultados, frias, calientes


def graficar_cascada(tabla):
    fig, ax = plt.subplots(figsize=(9, 6))

    ax.plot(tabla["CCF"], tabla["T"], marker="o", label="CCF")
    ax.plot(tabla["CCC"], tabla["T"], marker="o", label="CCC")
    ax.plot(tabla["CCF'"], tabla["T"], marker="o", label="CCF'")

    ax.set_xlabel("Corriente")
    ax.set_ylabel("Temperatura")
    ax.set_title("CCF vs CCC vs CCF'")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()

    return fig


def formatear_df_para_mostrar(df):
    df_show = df.copy()

    for col in df_show.columns:
        if col == "T":
            continue
        if pd.api.types.is_numeric_dtype(df_show[col]):
            df_show[col] = df_show[col].apply(
                lambda x: "" if pd.isna(x) else (f"{x:.3f}" if isinstance(x, (int, float)) else x)
            )

    if "T" in df_show.columns:
        df_show["T"] = df_show["T"].apply(
            lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x
        )

    return df_show


def convertir_kw_a_unidad_q(valor_kw, unidad_q):
    return valor_kw / FACTORES_Q[unidad_q]


# ==========================================================
# DATOS DE EJEMPLO
# ==========================================================
datos_ejemplo = pd.DataFrame([
    {"Nombre": "F1", "Tipo": "F", "Ti": 164.0, "To": 240.0, "Q": 1258.20, "CP": None},
    {"Nombre": "F2", "Tipo": "F", "Ti": 25.0,  "To": 400.0, "Q": 1395.14, "CP": None},
    {"Nombre": "F3", "Tipo": "F", "Ti": 284.4, "To": 284.6, "Q": 588.30,  "CP": None},
    {"Nombre": "C1", "Tipo": "C", "Ti": 360.0, "To": 160.0, "Q": 4362.20, "CP": None},
    {"Nombre": "C2", "Tipo": "C", "Ti": 160.0, "To": 120.0, "Q": 757.00,  "CP": None},
    {"Nombre": "C3", "Tipo": "C", "Ti": 204.0, "To": 203.8, "Q": 217.10,  "CP": None},
])

if "corrientes" not in st.session_state:
    st.session_state.corrientes = datos_ejemplo.copy()


# ==========================================================
# INTERFAZ
# ==========================================================
st.title("Integración de Energía")
st.write("Calculadora de cascada de calor para corrientes frías y calientes.")

col1, col2 = st.columns([2.4, 1])

with col1:
    st.subheader("Corrientes")
    st.caption("Puedes introducir Q o CP. Si uno falta, el sistema lo calcula automáticamente.")

with col2:
    st.subheader("Parámetros")
    delta_shift = st.number_input(
        "Corrimiento individual de temperatura (°C)",
        min_value=0.0,
        value=5.0,
        step=1.0
    )

    unidad_q = st.selectbox(
        "Unidad de Q",
        options=list(FACTORES_Q.keys()),
        index=list(FACTORES_Q.keys()).index("kW")
    )

    unidad_cp = st.selectbox(
        "Unidad de CP",
        options=list(FACTORES_CP.keys()),
        index=list(FACTORES_CP.keys()).index("kW/°C")
    )

    st.caption("Internamente, la app convierte todo a kW y kW/°C.")

df_editado = st.data_editor(
    st.session_state.corrientes,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Nombre": st.column_config.TextColumn("Nombre"),
        "Tipo": st.column_config.SelectboxColumn("Tipo", options=["F", "C"]),
        "Ti": st.column_config.NumberColumn("Ti [°C]"),
        "To": st.column_config.NumberColumn("To [°C]"),
        "Q": st.column_config.NumberColumn(f"Q [{unidad_q}]"),
        "CP": st.column_config.NumberColumn(f"CP [{unidad_cp}]"),
    }
)

b1, b2 = st.columns(2)

with b1:
    calcular = st.button("Calcular integración", use_container_width=True)

with b2:
    restaurar = st.button("Restaurar ejemplo", use_container_width=True)

if restaurar:
    st.session_state.corrientes = datos_ejemplo.copy()
    st.rerun()

if calcular:
    try:
        st.session_state.corrientes = df_editado.copy()

        df_proc = preparar_corrientes(df_editado, unidad_q, unidad_cp)
        df_proc, tabla, tabla_final, resultados, frias, calientes = construir_cascada(df_proc, delta_shift)

        st.success("Cálculo realizado correctamente.")

        # ==========================================================
        # RESULTADOS PRINCIPALES
        # ==========================================================
        st.subheader("Resultados principales")

        unidad_resultado = unidad_q 

        calentamiento_original_disp = convertir_kw_a_unidad_q(
            resultados["Calentamiento original [kW]"], unidad_resultado
        ) 
        enfriamiento_original_disp = convertir_kw_a_unidad_q(
            resultados["Enfriamiento original [kW]"], unidad_resultado
        )
        calor_integrado_disp = convertir_kw_a_unidad_q(
            resultados["Calor Integrado [kW]"], unidad_resultado
        )
        enfriamiento_min_disp = convertir_kw_a_unidad_q(
            resultados["Enfriamiento mínimo [kW]"], unidad_resultado
        )
        calentamiento_min_disp = convertir_kw_a_unidad_q(
            resultados["Calentamiento mínimo [kW]"], unidad_resultado
        )

        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

        c1.metric(
            "Calentamiento original",
            f"{calentamiento_original_disp:.3f} {unidad_resultado}"
        )
        c2.metric(
            "Enfriamiento original",
            f"{enfriamiento_original_disp:.3f} {unidad_resultado}"
        )
        c3.metric(
            "Calor Integrado",
            f"{calor_integrado_disp:.3f} {unidad_resultado}"
        )
        c4.metric(
            "Enfriamiento mínimo",
            f"{enfriamiento_min_disp:.3f} {unidad_resultado}"
        )
        c5.metric(
            "Calentamiento mínimo",
            f"{calentamiento_min_disp:.3f} {unidad_resultado}"
        )
        c6.metric(
            "Ahorro Calor",
            f"{resultados['Ahorro Calor [%]']:.2f} %"
        )
        c7.metric(
            "Ahorro Frío",
            f"{resultados['Ahorro Frío [%]']:.2f} %"
        )

        # ==========================================================
        # CORRIENTES PROCESADAS
        # ==========================================================
        st.subheader("Corrientes procesadas")
        df_proc_show = df_proc.copy()
        df_proc_show["Q"] = df_proc_show["Q"].map(lambda x: f"{x:.3f}")
        df_proc_show["CP"] = df_proc_show["CP"].map(lambda x: f"{x:.3f}")
        df_proc_show["Ti_s"] = df_proc_show["Ti_s"].map(lambda x: f"{x:.2f}")
        df_proc_show["To_s"] = df_proc_show["To_s"].map(lambda x: f"{x:.2f}")

        st.dataframe(
            df_proc_show[["Nombre", "Tipo", "Ti", "To", "Q", "CP", "Ti_s", "To_s"]],
            use_container_width=True
        )

        # ==========================================================
        # TABLA DE CASCADA
        # ==========================================================
        st.subheader("Tabla de cascada de calor")
        st.dataframe(formatear_df_para_mostrar(tabla_final), use_container_width=True)

        # ==========================================================
        # GRÁFICA
        # ==========================================================
        st.subheader("Gráfica")
        fig = graficar_cascada(tabla)
        st.pyplot(fig)

        # ==========================================================
        # DESCARGA CSV
        # ==========================================================
        xlsx = tabla_final.to_xlsx(index=False).encode("utf-8")
        st.download_button(
            label="Descargar tabla de cascada en Excel",
            data=xlsx,
            file_name="cascada_calor.xlsx",
            mime="text/xlsx",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"Ocurrió un error: {e}")