from flask import Flask, render_template, request, session, redirect, url_for
import random, os, sqlite3, unicodedata, re
from datetime import datetime

# ─── DÉTECTION POSTGRESQL (Supabase) VS SQLITE ────────────────────────────────
_raw_url = os.environ.get('DATABASE_URL', '')
# Supabase / Render renvoient parfois "postgres://", psycopg2 veut "postgresql://"
DATABASE_URL = _raw_url.replace('postgres://', 'postgresql://', 1) if _raw_url.startswith('postgres://') else _raw_url
USE_PG = bool(DATABASE_URL)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'quiz_adn_secret_2024')

# ─── TABLE DES CODONS ─────────────────────────────────────────────────────────
CODONS = {
    'UUU':'Phe','UUC':'Phe','UUA':'Leu','UUG':'Leu',
    'UCU':'Ser','UCC':'Ser','UCA':'Ser','UCG':'Ser',
    'UAU':'Tyr','UAC':'Tyr','UAA':'STOP','UAG':'STOP',
    'UGU':'Cys','UGC':'Cys','UGA':'STOP','UGG':'Trp',
    'CUU':'Leu','CUC':'Leu','CUA':'Leu','CUG':'Leu',
    'CCU':'Pro','CCC':'Pro','CCA':'Pro','CCG':'Pro',
    'CAU':'His','CAC':'His','CAA':'Gln','CAG':'Gln',
    'CGU':'Arg','CGC':'Arg','CGA':'Arg','CGG':'Arg',
    'AUU':'Ile','AUC':'Ile','AUA':'Ile','AUG':'Met',
    'ACU':'Thr','ACC':'Thr','ACA':'Thr','ACG':'Thr',
    'AAU':'Asn','AAC':'Asn','AAA':'Lys','AAG':'Lys',
    'AGU':'Ser','AGC':'Ser','AGA':'Arg','AGG':'Arg',
    'GUU':'Val','GUC':'Val','GUA':'Val','GUG':'Val',
    'GCU':'Ala','GCC':'Ala','GCA':'Ala','GCG':'Ala',
    'GAU':'Asp','GAC':'Asp','GAA':'Glu','GAG':'Glu',
    'GGU':'Gly','GGC':'Gly','GGA':'Gly','GGG':'Gly'
}

AA_NOMS = {
    'Phe':'Phénylalanine','Leu':'Leucine','Ser':'Sérine','Tyr':'Tyrosine',
    'Cys':'Cystéine','Trp':'Tryptophane','Pro':'Proline','His':'Histidine',
    'Gln':'Glutamine','Arg':'Arginine','Ile':'Isoleucine','Met':'Méthionine',
    'Thr':'Thréonine','Asn':'Asparagine','Lys':'Lysine','Val':'Valine',
    'Ala':'Alanine','Asp':'Acide aspartique','Glu':'Acide glutamique','Gly':'Glycine'
}

# Table triée par nom d'acide aminé (STOP en dernier)
CODONS_SORTED = dict(sorted(
    CODONS.items(),
    key=lambda x: ('ZZZ' if x[1] == 'STOP' else AA_NOMS.get(x[1], x[1]), x[0])
))

# ─── NORMALISATION ACCENTUÉE ──────────────────────────────────────────────────
def strip_accents(s):
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).upper()

# ─── MAP NOMS COMPLETS / ABRÉVIATIONS → CODE 3 LETTRES ───────────────────────
AA_FULL_MAP = {}
for _ab, _nom in AA_NOMS.items():
    AA_FULL_MAP[strip_accents(_nom)] = _ab   # ex : PHENYLALANINE → Phe
    AA_FULL_MAP[_ab.upper()] = _ab           # ex : PHE → Phe
# Alias spéciaux
AA_FULL_MAP.update({
    'ACIDE ASPARTIQUE': 'Asp', 'ASPARTIQUE': 'Asp',
    'ACIDE GLUTAMIQUE': 'Glu', 'GLUTAMIQUE': 'Glu',
    'METHIONINE': 'Met', 'SERINE': 'Ser',
    'CYSTEINE': 'Cys', 'THREONINE': 'Thr',
    'ISOLEUCINE': 'Ile', 'PHENYLALANINE': 'Phe',
})
# Codes 1 lettre IUPAC (M = Met, L = Leu, etc.)
AA_FULL_MAP.update({
    'A':'Ala','C':'Cys','D':'Asp','E':'Glu',
    'F':'Phe','G':'Gly','H':'His','I':'Ile',
    'K':'Lys','L':'Leu','M':'Met','N':'Asn',
    'P':'Pro','Q':'Gln','R':'Arg','S':'Ser',
    'T':'Thr','V':'Val','W':'Trp','Y':'Tyr',
})

# ─── NIVEAUX (timer supprimé — chronomètre indicatif à la place) ──────────────
NIVEAUX = {
    'facile': {
        'label': 'Facile', 'emoji': '🟢', 'nb_codons': 2,
        'points_arn': 1, 'points_prot': 2,
        'description': '2 acides aminés · Pas de limite de temps'
    },
    'moyen': {
        'label': 'Moyen', 'emoji': '🟡', 'nb_codons': 4,
        'points_arn': 1, 'points_prot': 3,
        'description': '4 acides aminés · Pas de limite de temps'
    },
    'difficile': {
        'label': 'Difficile', 'emoji': '🔴', 'nb_codons': 6,
        'points_arn': 1, 'points_prot': 4,
        'description': '6 acides aminés · Pas de limite de temps'
    }
}

QUESTION_MODES = [
    {'value': 5,  'label': '5', 'sublabel': 'questions'},
    {'value': 10, 'label': '10', 'sublabel': 'questions'},
    {'value': 20, 'label': '20', 'sublabel': 'questions'},
    {'value': 0,  'label': '∞', 'sublabel': 'illimité'},
]

# ─── BASE DE DONNÉES ──────────────────────────────────────────────────────────
# Si DATABASE_URL est défini (Supabase / Render Postgres) → PostgreSQL
# Sinon → SQLite local (fallback, éphémère sur Render free)
DB_PATH = os.environ.get('DB_PATH', 'classement.db')

CREATE_TABLE_PG = """
    CREATE TABLE IF NOT EXISTS classement (
        id           SERIAL PRIMARY KEY,
        pseudo       TEXT    NOT NULL,
        score        INTEGER NOT NULL,
        total        INTEGER NOT NULL,
        pct          INTEGER NOT NULL,
        niveau       TEXT    NOT NULL,
        nb_questions INTEGER NOT NULL DEFAULT 0,
        date         TEXT    NOT NULL
    )
"""
CREATE_TABLE_SQLITE = CREATE_TABLE_PG.replace('SERIAL', 'INTEGER').replace(
    'PRIMARY KEY', 'PRIMARY KEY AUTOINCREMENT'
)

def _pg():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def _sqlite():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        if USE_PG:
            conn = _pg()
            cur = conn.cursor()
            cur.execute(CREATE_TABLE_PG)
            conn.commit(); cur.close(); conn.close()
        else:
            conn = _sqlite()
            conn.execute(CREATE_TABLE_SQLITE)
            conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB init] {e}")

init_db()

def charger_classement():
    try:
        if USE_PG:
            conn = _pg()
            cur = conn.cursor()
            cur.execute(
                "SELECT pseudo,score,total,pct,niveau,nb_questions,date "
                "FROM classement ORDER BY pct DESC, score DESC LIMIT 20"
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            return rows
        else:
            conn = _sqlite()
            rows = conn.execute(
                "SELECT * FROM classement ORDER BY pct DESC, score DESC LIMIT 20"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB load] {e}")
        return []

def sauver_classement(pseudo, score, total, niveau, nb_questions):
    if total <= 0:
        return
    pct = round(score / total * 100)
    date_str = datetime.now().strftime('%d/%m/%Y')
    vals = (pseudo, score, total, pct, niveau, nb_questions, date_str)
    try:
        if USE_PG:
            conn = _pg()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO classement "
                "(pseudo,score,total,pct,niveau,nb_questions,date) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)", vals
            )
            # Garder top 20
            cur.execute("""
                DELETE FROM classement WHERE id NOT IN (
                    SELECT id FROM classement ORDER BY pct DESC, score DESC LIMIT 20
                )
            """)
            conn.commit(); cur.close(); conn.close()
        else:
            conn = _sqlite()
            conn.execute(
                "INSERT INTO classement "
                "(pseudo,score,total,pct,niveau,nb_questions,date) "
                "VALUES (?,?,?,?,?,?,?)", vals
            )
            conn.commit()
            conn.execute("""
                DELETE FROM classement WHERE id NOT IN (
                    SELECT id FROM classement ORDER BY pct DESC, score DESC LIMIT 20
                )
            """)
            conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB save] {e}")

# ─── LOGIQUE BIOLOGIQUE ───────────────────────────────────────────────────────
def transcription(adn):
    return adn.replace('T', 'U')

def traduction(arn):
    start = arn.find('AUG')
    if start == -1:
        return []
    acides = []
    for i in range(start, len(arn) - 2, 3):
        codon = arn[i:i+3]
        if len(codon) < 3:
            break
        aa = CODONS.get(codon, '?')
        if aa == 'STOP':
            break
        acides.append(aa)
    return acides

def generer_adn(nb_codons_internes):
    stops_adn = {'TAA', 'TAG', 'TGA'}
    bases = ['A', 'T', 'C', 'G']
    seq = 'ATG'
    for _ in range(nb_codons_internes):
        while True:
            triplet = ''.join(random.choice(bases) for _ in range(3))
            if triplet not in stops_adn:
                seq += triplet
                break
    seq += random.choice(['TAA', 'TAG', 'TGA'])
    return seq

# ─── NORMALISATION DES RÉPONSES ───────────────────────────────────────────────
def normaliser_arn(s):
    return s.strip().upper().replace(' ', '')

def segment_vers_code(seg):
    """Convertit n'importe quelle forme d'acide aminé en code 3 lettres."""
    seg = seg.strip()
    if not seg:
        return ''
    key = strip_accents(seg)
    if key in AA_FULL_MAP:
        return AA_FULL_MAP[key]
    # Essai avec préfixe "Acide"
    if ('ACIDE ' + key) in AA_FULL_MAP:
        return AA_FULL_MAP['ACIDE ' + key]
    return seg  # inconnu → retourné tel quel

def normaliser_prot(s):
    """
    Parse la saisie protéique de façon souple.
    Accepte : Met-Leu-Gly / Méthionine-Leucine-Glycine / MET,LEU;GLY
    Séparateurs reconnus : - , ; /  (PAS les espaces → "Acide aspartique" reste intact)
    Retourne : 'MET-LEU-GLY'
    """
    s = s.strip()
    if not s:
        return ''
    parts = re.split(r'[-,;/]+', s)
    codes = [segment_vers_code(p).upper() for p in parts if p.strip()]
    return '-'.join(codes)

# ─── EXPLICATIONS D'ERREUR ────────────────────────────────────────────────────
def explication_erreur_arn(adn, arn_saisi, arn_correct):
    erreurs = []
    if not arn_saisi:
        erreurs.append("Aucune réponse saisie pour l'ARNm.")
    elif len(arn_saisi) != len(arn_correct):
        erreurs.append(
            f"Longueur incorrecte : {len(arn_saisi)} bases saisies "
            f"au lieu de {len(arn_correct)}."
        )
    else:
        positions = [i+1 for i in range(len(arn_saisi)) if arn_saisi[i] != arn_correct[i]]
        if positions:
            erreurs.append(f"Base(s) incorrecte(s) en position : {', '.join(map(str, positions[:5]))}.")
    erreurs.append("Rappel : T→U, A→A, C→C, G→G. Seul T est remplacé par U.")
    return erreurs

def explication_erreur_prot(arn_correct, prot_saisie, prot_correct):
    erreurs = []
    saisi_list = [x for x in prot_saisie.split('-') if x]
    if not saisi_list:
        erreurs.append("Aucune réponse saisie pour la protéine.")
    elif len(saisi_list) != len(prot_correct):
        erreurs.append(
            f"{len(saisi_list)} acide(s) aminé(s) saisi(s) "
            f"au lieu de {len(prot_correct)}."
        )
    for i, (s, c) in enumerate(zip(saisi_list, prot_correct)):
        if s.upper() != c.upper():
            codon_pos = i * 3
            codon = arn_correct[codon_pos:codon_pos+3] if codon_pos+3 <= len(arn_correct) else '?'
            nom_complet = AA_NOMS.get(c, c)
            erreurs.append(
                f"Position {i+1} : codon {codon} → {c} ({nom_complet}), "
                f"vous avez écrit « {s} »."
            )
    erreurs.append("Rappel : traduction de AUG (Met) jusqu'au codon STOP.")
    return erreurs

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def accueil():
    return render_template('accueil.html', niveaux=NIVEAUX, question_modes=QUESTION_MODES)


@app.route('/demarrer', methods=['POST'])
def demarrer():
    session.clear()
    session['niveau']       = request.form.get('niveau', 'facile')
    session['pseudo']       = (request.form.get('pseudo', 'Anonyme').strip() or 'Anonyme')[:20]
    session['question_max'] = int(request.form.get('question_max', 10))
    session['mode_examen']  = request.form.get('mode_examen') == 'on'
    session['score']        = 0
    session['total']        = 0
    session['question_num'] = 0
    session['correct_arn']  = 0
    session['correct_prot'] = 0
    return redirect(url_for('nouvelle_question'))


@app.route('/quiz')
def nouvelle_question():
    if 'niveau' not in session:
        return redirect(url_for('accueil'))

    question_max = session.get('question_max', 0)
    question_num = session.get('question_num', 0)

    # Limite atteinte → résultats automatiques
    if question_max > 0 and question_num >= question_max:
        return redirect(url_for('terminer'))

    niveau = session['niveau']
    cfg    = NIVEAUX[niveau]
    adn    = generer_adn(cfg['nb_codons'])
    session['adn'] = adn

    return render_template('quiz.html',
        adn=adn, niveau=niveau, cfg=cfg,
        score=session.get('score', 0),
        total=session.get('total', 0),
        question_num=question_num,
        question_max=question_max,
        mode_examen=session.get('mode_examen', False),
        correction=None,
        codons=CODONS_SORTED, aa_noms=AA_NOMS
    )


@app.route('/quiz/valider', methods=['POST'])
def valider_reponse():
    if 'niveau' not in session:
        return redirect(url_for('accueil'))

    niveau = session['niveau']
    cfg    = NIVEAUX[niveau]

    adn          = session.get('adn', '')
    arn_correct  = transcription(adn)
    prot_correct = traduction(arn_correct)
    prot_str     = '-'.join(prot_correct)

    arn_saisi    = normaliser_arn(request.form.get('arn', ''))
    prot_saisie  = normaliser_prot(request.form.get('prot', ''))

    arn_ok  = (arn_saisi == arn_correct)
    prot_ok = (prot_saisie.upper() == prot_str.upper())

    pts = 0
    if arn_ok:
        pts += cfg['points_arn']
        session['correct_arn'] = session.get('correct_arn', 0) + 1
    if prot_ok:
        pts += cfg['points_prot']
        session['correct_prot'] = session.get('correct_prot', 0) + 1

    session['score']        = session.get('score', 0) + pts
    session['total']        = session.get('total', 0) + cfg['points_arn'] + cfg['points_prot']
    session['question_num'] = session.get('question_num', 0) + 1

    question_max = session.get('question_max', 0)
    question_num = session.get('question_num', 0)
    is_last      = (question_max > 0 and question_num >= question_max)

    expl_arn  = [] if arn_ok  else explication_erreur_arn(adn, arn_saisi, arn_correct)
    expl_prot = [] if prot_ok else explication_erreur_prot(arn_correct, prot_saisie, prot_correct)

    detail_codons = []
    for i in range(0, len(arn_correct) - 2, 3):
        codon = arn_correct[i:i+3]
        aa    = CODONS.get(codon, '?')
        nom   = AA_NOMS.get(aa, aa) if aa not in ('STOP', '?') else aa
        detail_codons.append({'codon': codon, 'aa': aa, 'nom': nom})

    correction = {
        'arn': arn_correct, 'prot': prot_str, 'prot_list': prot_correct,
        'arn_ok': arn_ok, 'prot_ok': prot_ok,
        'pts': pts, 'pts_max': cfg['points_arn'] + cfg['points_prot'],
        'expl_arn': expl_arn, 'expl_prot': expl_prot,
        'detail_codons': detail_codons,
        'arn_saisi': arn_saisi, 'prot_saisie': prot_saisie,
        'is_last': is_last,
    }

    return render_template('quiz.html',
        adn=adn, niveau=niveau, cfg=cfg,
        score=session.get('score', 0),
        total=session.get('total', 0),
        question_num=question_num,
        question_max=question_max,
        mode_examen=session.get('mode_examen', False),
        correction=correction,
        codons=CODONS_SORTED, aa_noms=AA_NOMS
    )


@app.route('/terminer', methods=['GET', 'POST'])
def terminer():
    pseudo       = session.get('pseudo', 'Anonyme')
    score        = session.get('score', 0)
    total        = session.get('total', 0)
    niveau       = session.get('niveau', 'facile')
    nb_questions = session.get('question_num', 0)
    if total > 0:
        sauver_classement(pseudo, score, total, niveau, nb_questions)
    return redirect(url_for('resultats'))


@app.route('/resultats')
def resultats():
    has_played = session.get('question_num', 0) > 0
    classement = charger_classement()
    return render_template('resultats.html',
        pseudo=session.get('pseudo', 'Anonyme'),
        score=session.get('score', 0),
        total=session.get('total', 0),
        niveau=session.get('niveau', 'facile'),
        question_num=session.get('question_num', 0),
        question_max=session.get('question_max', 0),
        correct_arn=session.get('correct_arn', 0),
        correct_prot=session.get('correct_prot', 0),
        classement=classement,
        niveaux=NIVEAUX,
        show_personal=has_played
    )


@app.route('/reset')
def reset():
    session.clear()
    return redirect(url_for('accueil'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
