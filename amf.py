import json
import random
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st
from openpyxl import load_workbook

# ==================== Configuration ====================
APP_TITLE = "Entraînement Certification AMF"
# Mets ici le nom exact de ton fichier Excel présent à côté du script
DEFAULT_XLSX = "AMF.xlsx"   # ex: "AMF (1).xlsx"
SHEET_NAME = "V4"
QUIZ_SIZE = 84

# Historiques
SEEN_FILE = Path(".amf_seen_ids.json")    # questions déjà vues
WRONG_FILE = Path(".amf_wrong_ids.json")  # questions ratées

# ==================== Compat rerun ====================
try:
    RERUN = st.rerun
except AttributeError:
    RERUN = st.experimental_rerun  # type: ignore[attr-defined]

# ==================== Helpers génériques ====================
def s(val) -> str:
    """Cast vers str + strip, gère None, float, int, etc."""
    return "" if val is None else str(val).strip()

def cell_is_yellow(cell) -> bool:
    """Détecte si la cellule est surlignée en jaune (plusieurs formats Excel)."""
    f = cell.fill
    if not f or not f.fgColor:
        return False

    rgb_val = getattr(f.fgColor, "rgb", None)
    if rgb_val:
        rgb_str = str(rgb_val).upper()  # peut être objet -> cast en str
        for pat in ["FFEB9C", "FFFF00", "FFFDEB", "FFF2CC", "FFFFFF00"]:
            if pat in rgb_str:
                return True

    # Palette indexée (legacy)
    if getattr(f.fgColor, "indexed", None) is not None:
        return f.fgColor.indexed in (5, 6, 13, 27, 44)

    return False

def load_json_ids(file_path: Path) -> set:
    if file_path.exists():
        try:
            return set(json.loads(file_path.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_json_ids(file_path: Path, ids: set) -> None:
    try:
        file_path.write_text(json.dumps(sorted(list(ids)), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_seen_ids() -> set:
    return load_json_ids(SEEN_FILE)

def save_seen_ids(seen: set) -> None:
    save_json_ids(SEEN_FILE, seen)

def load_wrong_ids() -> set:
    return load_json_ids(WRONG_FILE)

def save_wrong_ids(wrong: set) -> None:
    save_json_ids(WRONG_FILE, wrong)

def pick_quiz_ids(all_ids: List[int], seen: set, k: int) -> List[int]:
    """Privilégie les ids jamais vus, complète aléatoirement si pas assez."""
    unseen = [i for i in all_ids if i not in seen]
    random.shuffle(unseen)
    chosen = unseen[:k]
    if len(chosen) < k:
        remaining = [i for i in all_ids if i not in chosen]
        random.shuffle(remaining)
        chosen += remaining[:(k - len(chosen))]
    return chosen

# ==================== Chargement base ====================
@st.cache_data(show_spinner=False)
def load_questions_from_excel(xlsx_path: str, sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """
    Retourne un DataFrame:
      id, question, A, B, C, correct_idx, correct_text
    La bonne réponse est repérée via le surlignage jaune.
    """
    wb = load_workbook(xlsx_path, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Onglet introuvable: {sheet_name}")
    ws = wb[sheet_name]

    # Trouver la ligne après l'en-tête "n°identifiant"
    start_row = 1
    for i in range(1, ws.max_row + 1):
        v = ws.cell(row=i, column=1).value
        if v and s(v).lower().startswith("n°identifiant"):
            start_row = i + 1
            break

    records = []
    for r in ws.iter_rows(min_row=start_row, max_row=ws.max_row):
        rid = r[0].value
        if rid is None or (isinstance(rid, str) and rid.strip() == ""):
            continue
        try:
            rid_int = int(s(rid))
        except Exception:
            continue

        q_text = s(r[1].value)
        A = s(r[2].value)
        B = s(r[3].value)
        C = s(r[4].value)

        # Détection de la bonne réponse via la couleur
        correct_idx = None
        for idx, c in enumerate([r[2], r[3], r[4]]):
            try:
                if cell_is_yellow(c):
                    correct_idx = idx
                    break
            except Exception:
                pass

        correct_text = [A, B, C][correct_idx] if correct_idx is not None else ""

        if q_text:
            records.append({
                "id": rid_int,
                "question": q_text,
                "A": A, "B": B, "C": C,
                "correct_idx": correct_idx,
                "correct_text": correct_text
            })

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df = df[df["question"] != ""]
    return df

# ==================== UI ====================
def style_app():
    st.markdown(
        """
        <style>
        .main .block-container {max-width: 980px;}
        .question-card {
            border: 1px solid rgba(120,120,120,.25);
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 14px;
            background: var(--background-color, #fff);
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        .question-title { font-weight: 700; margin-bottom: 10px; }
        .correct {
            background: rgba(16,185,129,0.12);
            border-left: 6px solid #10b981;
            padding: 12px 14px; border-radius: 10px; color: inherit;
        }
        .wrong {
            background: rgba(239,68,68,0.12);
            border-left: 6px solid #ef4444;
            padding: 12px 14px; border-radius: 10px; color: inherit;
        }
        .muted { opacity: .9; }
        .pill {
            display: inline-block; padding: 2px 8px; border-radius: 999px;
            font-size: 11px; font-weight: 700; border: 1px solid rgba(120,120,120,.35);
            margin-right: 6px;
        }
        .ans-line { margin: 2px 0 2px 0; }
        .ans-label { font-weight: 700; width: 28px; display: inline-block; }
        </style>
        """,
        unsafe_allow_html=True
    )

def render_header():
    st.title(APP_TITLE)
    st.caption("Test aléatoire de 84 questions, nouvelle sélection à chaque relance, priorité aux questions jamais vues.")

def sidebar_controls(df: pd.DataFrame):
    st.sidebar.header("Paramètres")

    uploaded = st.sidebar.file_uploader("Importer un fichier Excel AMF", type=["xlsx"])
    if uploaded is not None:
        tmp_path = Path("uploaded_amf.xlsx")
        with open(tmp_path, "wb") as f:
            f.write(uploaded.getbuffer())
        st.session_state["xlsx_path"] = str(tmp_path)
        st.sidebar.success("Fichier importé. Recharge en cours…")
        RERUN()

    st.sidebar.write("")
    if st.sidebar.button("🔁 Nouveau test aléatoire", use_container_width=True):
        st.session_state["quiz_started"] = False
        st.session_state["submitted"] = False
        st.session_state["mode_erreurs"] = False
        RERUN()

    wrong_ids = load_wrong_ids()
    if st.sidebar.button(f"📌 Réviser mes erreurs ({len(wrong_ids)})", use_container_width=True):
        st.session_state["quiz_started"] = False
        st.session_state["submitted"] = False
        st.session_state["mode_erreurs"] = True
        RERUN()

    st.sidebar.write("---")
    if st.sidebar.button("🧹 Réinitialiser l'historique (vu)", use_container_width=True):
        if SEEN_FILE.exists():
            SEEN_FILE.unlink(missing_ok=True)
        st.sidebar.success("Historique 'vu' effacé.")
        RERUN()

    if st.sidebar.button("🧹 Réinitialiser mes erreurs", use_container_width=True):
        if WRONG_FILE.exists():
            WRONG_FILE.unlink(missing_ok=True)
        st.sidebar.success("Liste d'erreurs effacée.")
        RERUN()

    st.sidebar.write("---")
    st.sidebar.caption(f"{len(df)} questions disponibles dans la base.")

def start_quiz(df: pd.DataFrame):
    all_ids = df["id"].tolist()

    if st.session_state.get("mode_erreurs", False):
        wrong_ids = list(load_wrong_ids())
        if len(wrong_ids) == 0:
            st.warning("Ta liste d’erreurs est vide. Je te lance un test aléatoire classique.")
            seen = load_seen_ids()
            chosen_ids = pick_quiz_ids(all_ids, seen, QUIZ_SIZE)
        else:
            chosen_ids = wrong_ids if len(wrong_ids) <= QUIZ_SIZE else random.sample(wrong_ids, QUIZ_SIZE)
    else:
        seen = load_seen_ids()
        chosen_ids = pick_quiz_ids(all_ids, seen, QUIZ_SIZE)

    st.session_state["quiz_ids"] = chosen_ids
    st.session_state["answers"] = {}      # id -> "A"/"B"/"C"
    st.session_state["submitted"] = False
    st.session_state["quiz_started"] = True

def render_quiz(df: pd.DataFrame):
    ids = st.session_state["quiz_ids"]
    answers = st.session_state["answers"]
    rows = df.set_index("id").loc[ids].reset_index()

    for _, row in rows.iterrows():
        qid = int(row["id"])
        options = [f"A) {row['A']}", f"B) {row['B']}", f"C) {row['C']}"]

        st.markdown("<div class='question-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='question-title'>Q{qid}. {row['question']}</div>", unsafe_allow_html=True)

        radio_kwargs = dict(label="", options=options, key=f"q_{qid}")
        if qid in answers:
            default_idx = {"A": 0, "B": 1, "C": 2}.get(answers[qid])
            if default_idx is not None:
                radio_kwargs["index"] = default_idx

        choice = st.radio(**radio_kwargs)
        chosen_letter = choice.split(")")[0]  # "A", "B" ou "C"
        st.session_state["answers"][qid] = chosen_letter

        st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    if st.button("🟡 Voir les réponses", type="primary", use_container_width=True):
        st.session_state["submitted"] = True

def grade_and_show_results(df: pd.DataFrame):
    ids = st.session_state.get("quiz_ids", [])
    answers = st.session_state.get("answers", {})
    if not ids:
        st.warning("Aucune question chargée.")
        return

    rows = df.set_index("id").loc[ids].reset_index()

    score = 0
    details = []
    wrong_ids_set = load_wrong_ids()

    for _, row in rows.iterrows():
        qid = int(row["id"])
        correct_idx = row["correct_idx"]
        correct_letter = ["A", "B", "C"][correct_idx] if pd.notna(correct_idx) and correct_idx in [0, 1, 2] else None
        user_letter = answers.get(qid)

        if user_letter == correct_letter:
            score += 1
            # si la question était précédemment en erreurs → on la retire
            if qid in wrong_ids_set:
                wrong_ids_set.remove(qid)
        else:
            # mauvaise réponse (ou pas de réponse) → on ajoute en erreurs
            wrong_ids_set.add(qid)

        details.append((qid, row["question"], user_letter, correct_letter, row["A"], row["B"], row["C"]))

    # Sauvegarde erreurs & “vues”
    save_wrong_ids(wrong_ids_set)

    seen = load_seen_ids()
    for (qid, _, _, correct_letter, *_rest) in details:
        if correct_letter is not None:
            seen.add(qid)
    save_seen_ids(seen)

    st.subheader("Résultats")
    st.markdown(f"### Score : **{score} / {len(ids)}**")

    # corrections détaillées et lisibles
    for (qid, qtext, user_letter, correct_letter, A, B, C) in details:
        if correct_letter is None:
            st.markdown(
                f"<div class='wrong'><b>Q{qid}.</b> {qtext}<br>"
                f"<span class='muted'>Impossible de détecter la bonne réponse (vérifie le surlignage jaune dans l’Excel).</span></div>",
                unsafe_allow_html=True
            )
            continue

        ok = (user_letter == correct_letter)
        box_class = "correct" if ok else "wrong"
        st.markdown(f"<div class='{box_class}'><b>Q{qid}.</b> {qtext}</div>", unsafe_allow_html=True)

        # Lignes de réponses avec marquage ✅ / 🔘
        mapping = {"A": A, "B": B, "C": C}
        lines = []
        for letter in ["A", "B", "C"]:
            icon = ""
            if letter == correct_letter:
                icon = "✅"
            elif user_letter == letter and user_letter != correct_letter:
                icon = "🔘"
            text = mapping[letter] if mapping[letter] else "—"
            lines.append(f"<div class='ans-line'><span class='ans-label'>{letter})</span> {icon} {text}</div>")

        st.markdown("<div style='margin:6px 0 16px 12px;'>" + "".join(lines) + "</div>", unsafe_allow_html=True)

    st.write("")
    if st.button("🔁 Recommencer un nouveau test", use_container_width=True):
        st.session_state["quiz_started"] = False
        st.session_state["submitted"] = False
        RERUN()

# ==================== Main ====================
def main():
    style_app()
    render_header()

    if "xlsx_path" not in st.session_state:
        st.session_state["xlsx_path"] = DEFAULT_XLSX

    xlsx_path = st.session_state["xlsx_path"]

    if not Path(xlsx_path).exists():
        st.info(f"Place le fichier **{DEFAULT_XLSX}** à côté du script ou importe-le via la barre latérale.")
        sidebar_controls(pd.DataFrame({"question": []}))
        return

    try:
        df = load_questions_from_excel(xlsx_path, sheet_name=SHEET_NAME)
    except Exception as e:
        st.error(f"Impossible de lire le fichier Excel : {e}")
        return

    sidebar_controls(df)

    if not st.session_state.get("quiz_started", False):
        if len(df) < QUIZ_SIZE and not st.session_state.get("mode_erreurs", False):
            st.warning(f"La base ne contient que {len(df)} questions. Le test aura {len(df)} questions.")
        start_quiz(df)

    if not st.session_state.get("submitted", False):
        render_quiz(df)
    else:
        grade_and_show_results(df)

if __name__ == "__main__":
    main()
