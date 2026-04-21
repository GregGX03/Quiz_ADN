from flask import Flask, render_template, request, session, redirect, url_for
import random, json, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "quiz_adn_secret_2024"

# ─── TABLE DES CODONS ────────────────────────────────────────────────────────
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

CLASSEMENT_FILE = "classement.json"

# ─── NIVEAUX ─────────────────────────────────────────────────────────────────
NIVEAUX = {
    'facile': {
        'label': 'Facile', 'emoji': '🟢', 'nb_codons': 2, 'timer': 60,
        'points_arn': 1, 'points_prot': 2, 'description': '2 acides aminés · 60 secondes'
    },
    'moyen': {
        'label': 'Moyen', 'emoji': '🟡', 'nb_codons': 4, 'timer': 45,
        'points_arn': 1, 'points_prot': 3, 'description': '4 acides aminés · 45 secondes'
    },
    'difficile': {
        'label': 'Difficile', 'emoji': '🔴', 'nb_codons': 6, 'timer': 30,
        'points_arn': 1, 'points_prot': 4, 'description': '6 acides aminés · 30 secondes'
    }
}

# ─── LOGIQUE BIO ──────────────────────────────────────────────────────────────
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

def normaliser_prot(s):
    s = s.strip().upper()
    s = s.replace(' ', '-').replace(',', '-').replace(';', '-').replace('/', '-')
    while '--' in s:
        s = s.replace('--', '-')
    return s

def normaliser_arn(s):
    return s.strip().upper().replace(' ', '')

def explication_erreur_arn(adn, arn_saisi, arn_correct):
    erreurs = []
    if not arn_saisi:
        erreurs.append("Aucune réponse saisie pour l'ARNm.")
    elif len(arn_saisi) != len(arn_correct):
        erreurs.append(f"Longueur incorrecte : {len(arn_saisi)} bases saisies au lieu de {len(arn_correct)}.")
    else:
        positions = [i+1 for i in range(len(arn_saisi)) if arn_saisi[i] != arn_correct[i]]
        if positions:
            erreurs.append(f"Erreur(s) à la position : {', '.join(map(str, positions[:3]))}.")
    erreurs.append("Rappel : lors de la transcription, T→U, A→A, C→C, G→G.")
    return erreurs

def explication_erreur_prot(arn_correct, prot_saisie, prot_correct):
    erreurs = []
    saisi_list = [x for x in prot_saisie.split('-') if x]
    if not saisi_list:
        erreurs.append("Aucune réponse saisie pour la protéine.")
    elif len(saisi_list) != len(prot_correct):
        erreurs.append(f"{len(saisi_list)} acide(s) aminé(s) saisi(s) au lieu de {len(prot_correct)}.")
    for i, (s, c) in enumerate(zip(saisi_list, prot_correct)):
        if s.capitalize() != c and s.upper() != c.upper():
            codon_pos = i * 3
            codon = arn_correct[codon_pos:codon_pos+3] if codon_pos+3 <= len(arn_correct) else '?'
            nom_complet = AA_NOMS.get(c, c)
            erreurs.append(f"Position {i+1} : codon {codon} → {c} ({nom_complet}), pas {s}.")
    erreurs.append("Rappel : la traduction commence à AUG (Met) et s'arrête au codon STOP.")
    return erreurs

# ─── CLASSEMENT ───────────────────────────────────────────────────────────────
def charger_classement():
    if os.path.exists(CLASSEMENT_FILE):
        with open(CLASSEMENT_FILE) as f:
            return json.load(f)
    return []

def sauver_classement(pseudo, score, total, niveau):
    classement = charger_classement()
    classement.append({
        'pseudo': pseudo, 'score': score, 'total': total,
        'pct': round(score / total * 100) if total > 0 else 0,
        'niveau': niveau, 'date': datetime.now().strftime('%d/%m/%Y')
    })
    classement.sort(key=lambda x: x['pct'], reverse=True)
    classement = classement[:20]
    with open(CLASSEMENT_FILE, 'w') as f:
        json.dump(classement, f)

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def accueil():
    return render_template('accueil.html', niveaux=NIVEAUX)


@app.route('/demarrer', methods=['POST'])
def demarrer():
    session.clear()
    session['niveau'] = request.form.get('niveau', 'facile')
    session['pseudo'] = request.form.get('pseudo', 'Anonyme').strip() or 'Anonyme'
    session['score'] = 0
    session['total'] = 0
    session['question_num'] = 0
    return redirect(url_for('nouvelle_question'))


@app.route('/quiz')
def nouvelle_question():
    """Génère une nouvelle question et affiche le formulaire."""
    if 'niveau' not in session:
        return redirect(url_for('accueil'))

    niveau = session['niveau']
    cfg = NIVEAUX[niveau]

    adn = generer_adn(cfg['nb_codons'])
    session['adn'] = adn

    return render_template('quiz.html',
        adn=adn, niveau=niveau, cfg=cfg,
        score=session.get('score', 0),
        total=session.get('total', 0),
        question_num=session.get('question_num', 0),
        correction=None,
        codons=CODONS, aa_noms=AA_NOMS
    )


@app.route('/quiz/valider', methods=['POST'])
def valider_reponse():
    """Reçoit les réponses, calcule le score, affiche la correction."""
    if 'niveau' not in session:
        return redirect(url_for('accueil'))

    niveau = session['niveau']
    cfg = NIVEAUX[niveau]

    adn = session.get('adn', '')
    arn_correct = transcription(adn)
    prot_correct = traduction(arn_correct)
    prot_str = '-'.join(prot_correct)

    arn_saisi = normaliser_arn(request.form.get('arn', ''))
    prot_saisie = normaliser_prot(request.form.get('prot', ''))

    arn_ok = (arn_saisi == arn_correct)
    prot_ok = (prot_saisie == prot_str.upper())

    pts = 0
    if arn_ok:
        pts += cfg['points_arn']
    if prot_ok:
        pts += cfg['points_prot']

    session['score'] = session.get('score', 0) + pts
    session['total'] = session.get('total', 0) + cfg['points_arn'] + cfg['points_prot']
    session['question_num'] = session.get('question_num', 0) + 1

    expl_arn = [] if arn_ok else explication_erreur_arn(adn, arn_saisi, arn_correct)
    expl_prot = [] if prot_ok else explication_erreur_prot(arn_correct, prot_saisie, prot_correct)

    detail_codons = []
    for i in range(0, len(arn_correct) - 2, 3):
        codon = arn_correct[i:i+3]
        aa = CODONS.get(codon, '?')
        nom = AA_NOMS.get(aa, aa) if aa not in ('STOP', '?') else aa
        detail_codons.append({'codon': codon, 'aa': aa, 'nom': nom})

    correction = {
        'arn': arn_correct,
        'prot': prot_str,
        'prot_list': prot_correct,
        'arn_ok': arn_ok,
        'prot_ok': prot_ok,
        'pts': pts,
        'pts_max': cfg['points_arn'] + cfg['points_prot'],
        'expl_arn': expl_arn,
        'expl_prot': expl_prot,
        'detail_codons': detail_codons,
        'arn_saisi': arn_saisi,
        'prot_saisie': prot_saisie,
    }

    return render_template('quiz.html',
        adn=adn, niveau=niveau, cfg=cfg,
        score=session.get('score', 0),
        total=session.get('total', 0),
        question_num=session.get('question_num', 0),
        correction=correction,
        codons=CODONS, aa_noms=AA_NOMS
    )


@app.route('/terminer', methods=['POST'])
def terminer():
    pseudo = session.get('pseudo', 'Anonyme')
    score = session.get('score', 0)
    total = session.get('total', 0)
    niveau = session.get('niveau', 'facile')
    if total > 0:
        sauver_classement(pseudo, score, total, niveau)
    return redirect(url_for('resultats'))


@app.route('/resultats')
def resultats():
    classement = charger_classement()
    return render_template('resultats.html',
        pseudo=session.get('pseudo', 'Anonyme'),
        score=session.get('score', 0),
        total=session.get('total', 0),
        niveau=session.get('niveau', 'facile'),
        question_num=session.get('question_num', 0),
        classement=classement,
        niveaux=NIVEAUX
    )


@app.route('/reset')
def reset():
    session.clear()
    return redirect(url_for('accueil'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
