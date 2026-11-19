"""Contexte moderne d'une détection — règles et phrases, module PUR (ni Qt, ni QGIS, ni géométrie).

Après un traitement, chaque détection est croisée avec des objets de la BD TOPO de l'IGN proches
d'elle (bâtiments, surfaces en eau). Ce module dit, pour chaque objet, **l'effet** qu'il a sur la
détection et **la phrase** qu'on en écrit. Décisions de l'utilisateur (2026-11-10 et 11) :

- **marquer, jamais supprimer** : la détection reste dans son fichier, score et fiabilité intacts ;
- deux effets : **exclure** (champ ``contexte_moderne`` rempli → catégorie grise « Contexte moderne » de
  la légende, décochée à l'ouverture) ou **informer** (champ ``contexte_info``, aucun effet d'affichage) ;
- des **phrases**, pas des codes : « bâtiment agricole à 3 m », « mare à 6 m (origine naturelle) » ;
- cinq champs : :data:`CHAMPS` ;
- **plusieurs motifs** par champ (2026-11-12) : un par donnée, le plus proche d'abord, séparés par « ; ».

Six données (2026-11-12) : bâtiments et surfaces en eau pour toutes les structures ; cours d'eau, zones
d'habitation, ronds-points et lieux-dits pour les seules structures **ponctuelles** (charbonnières, fours,
cratères, dépressions, enclos : tout ce que :func:`est_lineaire` ne reconnaît pas comme linéaire — les
linéaires viendront plus tard). Les zones de regroupement (cratères regroupés) ne sont pas croisées.

La règle dépend de la **nature de l'objet** et de la **structure détectée** : une ruine ou une église
ne sont pas du contexte moderne, une mare sous une dépression peut être une mardelle, une digue
d'étang sous un talus est un vrai talus. Rayons mesurés sur le run entier des Vosges saônoises
(1 575 dalles, 2026-11-11) : les bâtiments marquent 14, 48 puis 88 grandes dépressions visibles à 0,
5 et 10 m (courbe raide → 5 m) ; l'eau en marque 299, 308 puis 324 (elle se joue au recouvrement → 0 m).

La géométrie (distance, part recouverte) est calculée par ``pipeline/contexte/croisement.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

EXCLURE, INFORMER = "exclure", "informer"
BATIMENT, EAU = "batiment", "eau"
COURS_EAU, HABITATION, ROND_POINT = "cours_eau", "habitation", "rond_point"
#: Données croisées avec les seules structures ponctuelles. Les lieux-dits en sont sortis le 2026-11-18
#: (décision de l'utilisateur) : une étiquette de carte, qui informait sans rien apprendre.
SOURCES_PONCTUELLES = (COURS_EAU, HABITATION, ROND_POINT)
#: Données croisées avec les seules structures **linéaires** (2026-11-19, décision de l'utilisateur) : elles
#: n'excluent jamais, elles disent qu'un talus ou un chemin creux longe un objet moderne déjà recensé.
ROUTE, VOIE_FERREE, TALUS_IGN, CANALISATION = "route", "voie_ferree", "talus_ign", "canalisation"
SOURCES_LINEAIRES = (ROUTE, VOIE_FERREE, TALUS_IGN, CANALISATION)
#: Les lignes dont on mesure, sous une structure linéaire, la part de la détection qui les longe (le cours
#: d'eau sert les deux familles : il informe les ponctuelles à 15 m, il « longe » les linéaires).
LIGNES_LONGEES = SOURCES_LINEAIRES + (COURS_EAU,)
#: Patrimoine connu (2026-11-19, décision de l'utilisateur) : il **informe** « site connu à proximité », pour
#: toutes les structures, et n'exclut jamais (c'est un indice favorable). Monuments historiques et archéologie
#: des plans d'urbanisme (Géoplateforme, toute la France où ils sont publiés) ; zones de présomption de
#: prescription archéologique des régions qui les publient (Bretagne, Auvergne-Rhône-Alpes, Centre-Val de Loire).
MONUMENT, PLU_ZONE, PLU_POINT = "monument", "plu_zone", "plu_point"
ZPPA_BRETAGNE, ZPPA_AURA, ZPPA_CVL = "zppa_bretagne", "zppa_aura", "zppa_cvl"
SOURCES_PATRIMOINE = (MONUMENT, PLU_ZONE, PLU_POINT, ZPPA_BRETAGNE, ZPPA_AURA, ZPPA_CVL)
#: Exclusions **à calibrer** (2026-11-19, décision de l'utilisateur) : un réservoir ou un bassin, une station
#: d'épuration ou une déchèterie, un terrain de sport, un parking dessinent des cercles, des cuvettes et des
#: enclos parfaits. Elles écarteraient, comme le bâti, à partir de :data:`PART_EXCLUSION` de la détection
#: recouverte (structures ponctuelles, enclos, dépressions ; jamais les linéaires).
RESERVOIR, EPURATION, TERRAIN_SPORT, PARKING = "reservoir", "epuration", "terrain_sport", "parking"
SOURCES_A_CALIBRER = (RESERVOIR, EPURATION, TERRAIN_SPORT, PARKING)
#: Celles dont l'exclusion est **activée**, après jugement de leur galerie par l'utilisateur (2026-11-19,
#: D:/brouillons/galerie_regles_2026-11-19 : « tous les cas écartés dans les exemples me semblent bons »).
#: Une source absente d'ici informe seulement (« parking recouvrant 40 % de la détection »).
EXCLUSIONS_ACTIVES: frozenset = frozenset({EPURATION, RESERVOIR, TERRAIN_SPORT, PARKING})
#: Attribut posé par le croisement sur un objet à calibrer qui n'est qu'un carré symbolique de l'IGN (5 × 5 m,
#: emprise non dessinée) : il informe dans :data:`RAYON_INFO` et n'écarte jamais (parkings, 2026-11-19).
SYMBOLE = "_symbole"
#: Celles qui sont des zones : la détection est « dans » la zone, plutôt qu'« à N m ».
ZONES_PATRIMOINE = (PLU_ZONE, ZPPA_BRETAGNE, ZPPA_AURA, ZPPA_CVL)

#: Les cinq champs écrits sur chaque détection, dans cet ordre.
CHAMPS = ("contexte_moderne", "contexte_info", "contexte_dist_m", "contexte_part", "contexte_source")

#: Rayons en mètres. Un objet plus loin que le rayon de sa règle n'a aucun effet.
RAYON_BATIMENT = 5.0       # rayon d'information seulement : un bâtiment n'exclut plus à distance (2026-11-13)
#: Part de la détection qu'un bâtiment (les bâtiments cumulés) ou un plan d'eau aménagé doit recouvrir pour
#: l'exclure (décisions de l'utilisateur : bâti le 2026-11-13, qui remplace les rayons de 5 et 15 m des
#: enclos ; même règle pour l'eau le 2026-11-18, qui écartait au moindre contact). 10 % retenu le
#: 2026-11-18 après lecture de la galerie des cas (D:/brouillons/galerie_exclusions_2026-11-18) : la seule
#: exclusion « probable » (un enclos à 6 % de bâti) retombe en information.
PART_EXCLUSION = 0.10
PART_BATIMENT = PART_EXCLUSION
RAYON_EAU = 0.0            # au recouvrement
RAYON_INFO = 15.0          # mares (décalées de 12 m en médiane sous forêt) et digues d'étangs
RAYON_COURS_EAU = 15.0     # un cours d'eau qui traverse ou longe la détection
#: Part de la détection à partir de laquelle elle est « sur » un rond-point (exclue) ou dite « dans » une
#: zone d'habitation (phrase seulement).
PART_DEDANS = 0.5
#: Linéaires (2026-11-19) : part de la détection à moins de :data:`RAYON_LINEAIRE` m de la ligne (son axe,
#: dans la BD TOPO), à partir de laquelle on dit qu'elle la « longe ». Mesure en surface, qui vaut la part
#: de longueur pour une détection allongée. Calibrage (2026-11-19, 6 704 détections linéaires de 8 traitements,
#: ``D:/brouillons/galerie_regles_2026-11-19/calibre_lineaires.json``) : largeur médiane 5,8 m (90 % sous 7 m) ;
#: la part qui longe une route croît sans palier (255, 488, 621, 846, 1 059 détections à 30 % pour 3, 5, 6, 8,
#: 10 m) : 6 m = une demi-largeur et environ 3 m d'écart de position de l'IGN, sans gagner les talus
#: d'accotement. À 30 %, 621 détections longent une route ; 392 à 50 %.
RAYON_LINEAIRE = 6.0
PART_LONGE = 0.3
#: Patrimoine : un monument ou un site connu à moins de 50 m. Assez pour l'enceinte, les fossés ou la motte
#: d'un château, une chapelle et son cimetière, un site ponctuel des plans d'urbanisme (pointé à quelques
#: dizaines de mètres près) ; pas les 500 m des abords d'un monument historique, qui couvriraient un village.
RAYON_PATRIMOINE = 50.0
#: Rayon de recherche des objets autour d'une détection : le plus grand des rayons ci-dessus.
RAYON_PROCHE = max(RAYON_BATIMENT, RAYON_EAU, RAYON_INFO, RAYON_COURS_EAU, RAYON_LINEAIRE)
RAYON_RECHERCHE = max(RAYON_PROCHE, RAYON_PATRIMOINE)


def marge(source: str) -> float:
    """La marge de téléchargement autour des détections : le patrimoine se cherche plus loin que le reste."""
    return RAYON_PATRIMOINE if source in SOURCES_PATRIMOINE else RAYON_PROCHE
#: En deçà, l'objet touche la détection : on écrit « recouvrant N % de la détection » ou « touchant la
#: détection », jamais « à 0 m ».
CONTACT_M = 0.5

#: Natures de bâtiment qui relèvent du patrimoine, pas du contexte moderne (BD TOPO 3.5, § 8.2).
BATI_PATRIMOINE = frozenset({
    "Eglise", "Chapelle", "Château", "Tour, donjon", "Moulin à vent", "Fort, blockhaus, casemate",
    "Monument", "Arc de triomphe", "Arène ou théâtre antique",
})
#: Surfaces en eau aménagées : une forme qu'elles dessinent est un leurre net.
EAU_AMENAGEE = frozenset({
    "Retenue", "Retenue-barrage", "Retenue-digue", "Retenue-bassin portuaire", "Réservoir-bassin",
    "Réservoir-bassin d'orage", "Réservoir-bassin piscicole", "Plan d'eau de gravière", "Plan d'eau de mine",
    "Canal", "Ecoulement canalisé",
})
_RETENUES = frozenset(n for n in EAU_AMENAGEE if n.startswith("Retenue"))
#: Zones d'habitation qui relèvent du patrimoine : elles informent, elles n'excluent pas.
HABITAT_PATRIMOINE = {"Ruines": "ruines", "Château": "château", "Moulin": "moulin"}
#: Tronçons hydrographiques qui ne sont que l'axe d'une surface en eau, déjà croisée par ailleurs.
_TRONCONS_DE_SURFACE = ("Retenue", "Réservoir", "Plan d'eau", "Lac", "Mare", "Marais", "Lagune", "Glacier")
#: Nom courant des natures de tronçon hydrographique.
NOMS_COURS_EAU = {"Ecoulement canalisé": "cours d'eau canalisé", "Conduit buse": "cours d'eau busé",
                  "Conduit forcé": "conduite forcée", "Canal": "canal", "Aqueduc": "aqueduc"}


@dataclass(frozen=True)
class Objet:
    """Un objet de la BD TOPO près d'une détection."""
    source: str                    # BATIMENT ou EAU
    attributs: Mapping[str, Any]   # tels que les donne l'IGN (nature, usage_1, etat_de_l_objet, origine…)
    distance_m: float              # 0 si l'objet touche ou recouvre la détection
    part: float = 0.0              # part de la surface de la détection que l'objet recouvre, 0 à 1


def _txt(attributs: Mapping[str, Any], cle: str) -> str:
    return str(attributs.get(cle) or "").strip()


def est_talus(structure: str) -> bool:
    """La structure détectée est-elle un talus ou un fossé (slug de l'entité ou nom de classe) ?"""
    s = (structure or "").lower()
    return "talus" in s or "fosse" in s or "fossé" in s


def est_lineaire(structure: str) -> bool:
    """La structure détectée est-elle linéaire (talus, fossé, chemin creux, parcellaire, tranchée) ?"""
    s = (structure or "").lower()
    return est_talus(s) or any(m in s for m in ("chemin", "parcellaire", "tranch", "boyau", "lineaire", "linéaire"))


def est_depression(structure: str) -> bool:
    s = (structure or "").lower()
    return "depression" in s or "dépression" in s


def consulte(source: str, structure: str) -> bool:
    """La donnée ``source`` est-elle croisée avec cette structure ? Les linéaires reçoivent les leurs et le
    cours d'eau ; les ponctuelles, les leurs ; le bâti et l'eau servent tout le monde."""
    lineaire = est_lineaire(structure)
    if source in SOURCES_LINEAIRES:
        return lineaire
    if source in SOURCES_PONCTUELLES:
        return not lineaire or source == COURS_EAU
    if source in SOURCES_A_CALIBRER:
        return not lineaire
    return True


def regle(objet: Objet, structure: str = "") -> Optional[Tuple[str, float]]:
    """``(effet, rayon en m)`` de l'objet pour cette structure, ou ``None`` s'il n'en a pas.

    Un bâtiment exclut la détection dont il recouvre au moins :data:`PART_BATIMENT` ; en deçà, ou à côté
    jusqu'à 5 m, il informe (2026-11-13). Une zone d'habitation informe toujours. Par structure (revue du
    2026-11-12) : un plan d'eau aménagé informe une **dépression** sans l'exclure ; une structure
    **linéaire** n'est jamais exclue (:func:`effet`)."""
    a = objet.attributs
    if objet.source in SOURCES_PATRIMOINE:
        return INFORMER, RAYON_PATRIMOINE
    if objet.source in SOURCES_A_CALIBRER:
        if est_lineaire(structure):
            return None
        if a.get(SYMBOLE):
            # carré symbolique de l'IGN = un point : dans la détection, il écarte ; à côté, il informe
            dedans = objet.distance_m < CONTACT_M and objet.source in EXCLUSIONS_ACTIVES
            return (EXCLURE, 0.0) if dedans else (INFORMER, RAYON_INFO)
        exclut = objet.source in EXCLUSIONS_ACTIVES and objet.part >= PART_EXCLUSION
        return (EXCLURE if exclut else INFORMER), 0.0       # au contact : à côté, il ne dit rien
    if objet.source in LIGNES_LONGEES and est_lineaire(structure):
        if objet.source == COURS_EAU and _txt(a, "nature").startswith(_TRONCONS_DE_SURFACE):
            return None
        return (INFORMER, RAYON_LINEAIRE) if objet.part >= PART_LONGE else None
    if objet.source in SOURCES_LINEAIRES:
        return None
    if objet.source in SOURCES_PONCTUELLES:
        if est_lineaire(structure):
            return None
        if objet.source == COURS_EAU:
            return None if _txt(a, "nature").startswith(_TRONCONS_DE_SURFACE) else (INFORMER, RAYON_COURS_EAU)
        if objet.source == HABITATION:
            return INFORMER, 0.0        # n'exclut plus (2026-11-13) : c'est le bâtiment qui écarte, pas la zone
        # rond-point : même part que le bâti et l'eau (2026-11-19, 50 % avant) ; en deçà, il informe
        return (EXCLURE if objet.part >= PART_EXCLUSION else INFORMER), 0.0
    if objet.source == BATIMENT:
        if _txt(a, "etat_de_l_objet") == "En ruine" or _txt(a, "nature") in BATI_PATRIMOINE:
            return INFORMER, RAYON_BATIMENT
        if objet.part >= PART_BATIMENT:
            return EXCLURE, 0.0
        return INFORMER, RAYON_BATIMENT                 # à côté ou à peine touché : dit, pas écarté
    if objet.source == EAU:
        nature = _txt(a, "nature")
        if nature == "Mare":
            return INFORMER, RAYON_INFO
        if nature in _RETENUES and est_talus(structure):
            return INFORMER, RAYON_INFO                 # une digue d'étang est un vrai talus
        if _txt(a, "origine").startswith("Naturelle"):
            return INFORMER, RAYON_EAU
        if nature in EAU_AMENAGEE:
            # sous une dépression, un étang se dit mais n'écarte pas : la cuvette peut l'avoir précédé ;
            # ailleurs, il écarte à partir de la même part que le bâti (2026-11-18), il informe en deçà
            exclut = not est_depression(structure) and objet.part >= PART_EXCLUSION
            return (EXCLURE if exclut else INFORMER), RAYON_EAU
        return INFORMER, RAYON_EAU                      # lac, écoulement naturel, marais, nature inconnue
    return None


def effet(objet: Objet, structure: str = "") -> Optional[str]:
    """L'effet de l'objet **à sa distance** : ``None`` s'il est hors du rayon de sa règle."""
    r = regle(objet, structure)
    if r is None or objet.distance_m > r[1] + 1e-9:
        return None
    # Une structure linéaire n'est jamais écartée : un talus, un chemin ou un parcellaire longent et
    # traversent le bâti et l'eau sans en être des leurres. Tout ce qui exclurait informe.
    return INFORMER if est_lineaire(structure) else r[0]


def _cumuler_bati(objets: Iterable[Objet]) -> list:
    """Plusieurs bâtiments modernes qui touchent la détection, chacun sous :data:`PART_EXCLUSION` mais
    ensemble au-dessus, sont remplacés par un seul objet de leur part cumulée (2026-11-18 : la part était
    mesurée bâtiment par bâtiment). Le patrimoine (ruine, église…) ne s'additionne pas."""
    objets = list(objets)
    modernes = [o for o in objets if o.source == BATIMENT and o.distance_m < CONTACT_M and o.part > 0
                and _txt(o.attributs, "etat_de_l_objet") != "En ruine"
                and _txt(o.attributs, "nature") not in BATI_PATRIMOINE]
    total = sum(o.part for o in modernes)
    if len(modernes) < 2 or total < PART_EXCLUSION or max(o.part for o in modernes) >= PART_EXCLUSION:
        return objets
    return [o for o in objets if o not in modernes] + [Objet(BATIMENT, {"_cumul": len(modernes)}, 0.0, total)]


def _nom_batiment(a: Mapping[str, Any]) -> str:
    if a.get("_cumul"):
        return f"{a['_cumul']} bâtiments"
    nature, usage = _txt(a, "nature"), _txt(a, "usage_1")
    if nature and nature not in ("Indifférenciée", "Industriel, agricole ou commercial"):
        # L'IGN écrit « Eglise » sans accent.
        nom = {"Tour, donjon": "tour ou donjon", "Fort, blockhaus, casemate": "fort, blockhaus ou casemate",
               "Eglise": "église"}.get(nature, nature[:1].lower() + nature[1:])
    else:
        nom = {"Agricole": "bâtiment agricole", "Industriel": "bâtiment industriel", "Résidentiel": "bâtiment résidentiel",
               "Commercial et services": "bâtiment commercial", "Religieux": "bâtiment religieux",
               "Sportif": "bâtiment sportif", "Annexe": "annexe"}.get(usage, "bâtiment")
    etat = _txt(a, "etat_de_l_objet")
    if etat == "En ruine":
        nom += " en ruine"
    elif etat == "En construction":
        nom += " en construction"
    return nom


#: Nom courant des natures de surface en eau (BD TOPO 3.5, § hydrographie), suivi du mot de l'IGN entre
#: parenthèses : « Retenue » y comprend les étangs, « Retenue-digue » est un plan d'eau endigué.
NOMS_EAU = {
    "Retenue": "étang (retenue)",
    "Retenue-barrage": "lac de barrage (retenue-barrage)",
    "Retenue-digue": "plan d'eau endigué (retenue-digue)",
    "Retenue-bassin portuaire": "bassin portuaire",
    "Réservoir-bassin": "bassin (réservoir-bassin)",
    "Réservoir-bassin d'orage": "bassin d'orage",
    "Réservoir-bassin piscicole": "bassin piscicole",
    "Plan d'eau de gravière": "plan d'eau de gravière",
    "Plan d'eau de mine": "plan d'eau de mine",
    "Ecoulement naturel": "cours d'eau",
    "Ecoulement canalisé": "cours d'eau canalisé",
}


def _nom_eau(a: Mapping[str, Any]) -> str:
    nature = _txt(a, "nature")
    if not nature or nature == "Inconnue":
        nom = "surface en eau"
    else:
        nom = NOMS_EAU.get(nature, nature[:1].lower() + nature[1:])
    toponyme = _txt(a, "cpx_toponyme_de_plan_d_eau") or _txt(a, "toponyme")
    if toponyme:
        nom += f" « {toponyme} »"
    return nom


def _precisions_batiment(a: Mapping[str, Any]) -> str:
    return " (construction légère)" if a.get("construction_legere") in (True, "true", "True", 1, "1") else ""


def _precisions_eau(a: Mapping[str, Any]) -> str:
    """Origine et persistance, sans accord grammatical à faire : « (origine naturelle, eau intermittente) »."""
    mots = []
    if _txt(a, "origine").startswith("Naturelle"):
        mots.append("origine naturelle")
    if _txt(a, "persistance") == "Intermittent":
        mots.append("eau intermittente")
    return f" ({', '.join(mots)})" if mots else ""


def _ou(objet: Objet) -> str:
    """« recouvrant 80 % de la détection », « touchant la détection » ou « à 6 m »."""
    if objet.distance_m >= CONTACT_M:
        return f"à {round(objet.distance_m)} m"
    pourcent = round(max(0.0, min(1.0, objet.part)) * 100)
    if pourcent >= 1:
        return f"recouvrant {pourcent} % de la détection"
    return "touchant la détection"


def _nomme(nom: str, toponyme: str) -> str:
    return f"{nom} « {toponyme} »" if toponyme else nom


def _phrase_ponctuelle(objet: Objet) -> str:
    """Les phrases des données croisées avec les structures ponctuelles."""
    a, contact = objet.attributs, objet.distance_m < CONTACT_M
    if objet.source == COURS_EAU:
        nom = _nomme(NOMS_COURS_EAU.get(_txt(a, "nature"), "cours d'eau"), _txt(a, "cpx_toponyme_de_cours_d_eau"))
        ou = "traversant la détection" if contact else f"à {round(objet.distance_m)} m"
        return f"{nom} {ou}" + (" (intermittent)" if _txt(a, "persistance") == "Intermittent" else "")
    if objet.source == ROND_POINT:
        return f"rond-point {_ou(objet)}"
    patrimoine = HABITAT_PATRIMOINE.get(_txt(a, "nature"))
    if patrimoine:
        return f"{_nomme(patrimoine, _txt(a, 'toponyme'))} {_ou(objet)}"
    nom = _nomme("zone d'habitation", _txt(a, "toponyme"))
    return f"dans la {nom}" if objet.part >= PART_DEDANS else f"{nom} {_ou(objet)}"


#: Ce que longe une structure linéaire, avec son article (BD TOPO 3.5 : natures des tronçons de route, des
#: lignes orographiques et des tronçons hydrographiques).
_LONGES = {
    ROUTE: {"Chemin": "un chemin", "Sentier": "un sentier", "Route empierrée": "une route empierrée",
            "Escalier": "un escalier", "Piste cyclable": "une piste cyclable", "": "une route"},
    TALUS_IGN: {"Talus": "un talus recensé par l'IGN", "Levée": "une levée recensée par l'IGN",
                "Carrière": "un front de carrière recensé par l'IGN", "": "une ligne de relief recensée par l'IGN"},
    COURS_EAU: {"Ecoulement canalisé": "un cours d'eau canalisé", "Conduit buse": "un cours d'eau busé",
                "Conduit forcé": "une conduite forcée", "Canal": "un canal", "Aqueduc": "un aqueduc",
                "": "un cours d'eau"},
}


def _phrase_longe(objet: Objet) -> str:
    """« longe un chemin sur 80 % de sa longueur »."""
    a = objet.attributs
    if objet.source == VOIE_FERREE:
        nom = "une voie ferrée"
    elif objet.source == CANALISATION:
        nom = "une canalisation"
    else:
        noms = _LONGES[objet.source]
        nom = noms.get(_txt(a, "nature"), noms[""])
    if objet.source == COURS_EAU:
        nom = _nomme(nom, _txt(a, "cpx_toponyme_de_cours_d_eau"))
    return f"longe {nom} sur {round(max(0.0, min(1.0, objet.part)) * 100)} % de sa longueur"


#: Nom courant d'un objet à calibrer, par nature (BD TOPO 3.5).
_NOMS_A_CALIBRER = {
    RESERVOIR: {"Château d'eau": "château d'eau", "Réservoir d'eau ou château d'eau au sol": "réservoir d'eau au sol",
                "Réservoir industriel": "réservoir industriel", "": "réservoir"},
    EPURATION: {"Station d'épuration": "station d'épuration", "Déchèterie": "déchèterie", "": "station d'épuration"},
    TERRAIN_SPORT: {"Grand terrain de sport": "grand terrain de sport", "Petit terrain multi-sports": "terrain multisport",
                    "Terrain de tennis": "court de tennis", "Piste de sport": "piste de sport",
                    "Carrière équestre": "carrière équestre", "": "terrain de sport"},
    PARKING: {"": "parking"},
}
_FEMININS = frozenset({"station d'épuration", "déchèterie", "carrière équestre", "piste de sport"})
_ZPPA = "zone de présomption de prescription archéologique"


def _phrase_patrimoine(objet: Objet) -> str:
    """« site connu à proximité : monument historique « Château de … » à 30 m », « site connu : dans la zone
    de présomption de prescription archéologique (Rennes, zone 12) »."""
    a, s = objet.attributs, objet.source
    if s == MONUMENT:
        nom = _nomme("monument historique", _txt(a, "nomsuplitt") or _txt(a, "nomgen"))
    elif s == PLU_ZONE:
        nom = _nomme("zone archéologique du plan d'urbanisme", _txt(a, "libelle"))
    elif s == PLU_POINT:
        nom = _nomme("site archéologique du plan d'urbanisme", _txt(a, "libelle"))
    else:
        commune = _txt(a, "COMMUNE") or _txt(a, "comm_nom") or _txt(a, "communes")
        zone = _txt(a, "N_ZONE") or _txt(a, "zone")
        lieu = ", ".join(x for x in (commune, f"zone {zone}" if zone else "") if x)
        nom = f"{_ZPPA} ({lieu})" if lieu else _ZPPA
    if s in ZONES_PATRIMOINE and objet.distance_m < CONTACT_M:
        return f"site connu : dans la {nom}"
    ou = "touchant la détection" if objet.distance_m < CONTACT_M else f"à {round(objet.distance_m)} m"
    return f"site connu à proximité : {nom} {ou}"


def phrase(objet: Objet, structure: str = "") -> str:
    """« étang (retenue) recouvrant 80 % de la détection », « bâtiment agricole à 3 m »,
    « mare à 6 m (origine naturelle) », « cours d'eau traversant la détection », et pour une structure
    linéaire « longe un chemin sur 80 % de sa longueur »."""
    if objet.source in SOURCES_PATRIMOINE:
        return _phrase_patrimoine(objet)
    if objet.source in SOURCES_A_CALIBRER:
        noms = _NOMS_A_CALIBRER[objet.source]
        nom = noms.get(_txt(objet.attributs, "nature"), noms[""])
        if objet.attributs.get(SYMBOLE):
            e = "e" if nom in _FEMININS else ""
            ou = "dans la détection" if objet.distance_m < CONTACT_M else f"à {round(objet.distance_m)} m"
            return f"{nom} signalé{e} {ou} (emprise non dessinée par l'IGN)"
        return f"{nom} {_ou(objet)}"
    if objet.source in LIGNES_LONGEES and est_lineaire(structure):
        return _phrase_longe(objet)
    if objet.source in SOURCES_PONCTUELLES:
        return _phrase_ponctuelle(objet)
    a = objet.attributs
    nom = _nom_batiment(a) if objet.source == BATIMENT else _nom_eau(a)
    ou = _ou(objet)
    return f"{nom} {ou}" + (_precisions_eau(a) if objet.source == EAU else _precisions_batiment(a))


def champs(objets: Iterable[Objet], structure: str = "", source: str = "",
           titres: Optional[Mapping[str, str]] = None, date_iso: str = "") -> Dict[str, Any]:
    """Les cinq champs d'une détection, d'après les objets trouvés près d'elle.

    Chaque champ de texte liste **un motif par donnée** (le plus proche ; à distance égale, celui qui
    recouvre le plus), le plus proche d'abord, séparés par « ; ». ``contexte_dist_m`` et ``contexte_part``
    décrivent le motif qui **décide** : le premier qui exclut, sinon le premier qui informe.
    ``contexte_source`` nomme les données citées (``titres`` : leur nom dans le Catalogue des flux, par
    source) ; ``source`` est écrit quand rien n'est trouvé : il distingue « rien à proximité » de
    « croisement non fait ».
    """
    meilleurs: Dict[str, Dict[str, Objet]] = {EXCLURE: {}, INFORMER: {}}
    for o in _cumuler_bati(objets):
        e = effet(o, structure)
        if e is None:
            continue
        actuel = meilleurs[e].get(o.source)
        if actuel is None or (o.distance_m, -o.part) < (actuel.distance_m, -actuel.part):
            meilleurs[e][o.source] = o
    exclus, infos = (sorted(meilleurs[e].values(), key=lambda o: (o.distance_m, -o.part)) for e in (EXCLURE, INFORMER))
    cites = exclus + infos
    decide = cites[0] if cites else None
    if cites and titres:
        libelle = libelle_source(date_iso, list(dict.fromkeys(titres[o.source] for o in cites if o.source in titres)),
                                 base_de(o.source for o in cites))
    else:
        libelle = source
    return {
        "contexte_moderne": " ; ".join(phrase(o, structure) for o in exclus) or None,
        "contexte_info": " ; ".join(phrase(o, structure) for o in infos) or None,
        "contexte_dist_m": None if decide is None else int(round(decide.distance_m)),
        "contexte_part": None if decide is None else int(round(max(0.0, min(1.0, decide.part)) * 100)),
        "contexte_source": libelle or None,
    }


def base_de(sources: Iterable[str]) -> str:
    """« BD TOPO, IGN », ou « données publiques » dès qu'une donnée de patrimoine est citée (servitudes et
    plans d'urbanisme de la Géoplateforme, services régionaux) : la BD TOPO ne la porte pas."""
    return "données publiques" if any(s in SOURCES_PATRIMOINE for s in sources) else "BD TOPO, IGN"


def libelle_source(date_iso: str, titres: Sequence[str] = (), base: str = "BD TOPO, IGN") -> str:
    """« Bâtiments (BD TOPO, IGN), lue le 2026-11-12 » : le nom de la donnée dans le Catalogue des flux,
    pour la retrouver et l'ajouter au projet, puis la base et la date de lecture (la base n'annonce pas son
    édition dans le flux). Plusieurs titres quand aucun objet n'a décidé : toutes les données consultées."""
    tete = " · ".join(titres)
    texte = f"{tete} ({base})" if tete else "BD TOPO (IGN)"
    return f"{texte}, lue le {date_iso}" if date_iso else texte


def resume(marquees: int, informees: int, total: int) -> str:
    """Phrase du journal de fin de traitement ; vide si rien n'a été croisé."""
    if total <= 0:
        return ""
    if not marquees and not informees:
        return f"Contexte moderne : rien à signaler autour de {total} détection{'s' if total > 1 else ''}."
    morceaux = []
    if marquees:
        morceaux.append(f"{marquees} écartée{'s' if marquees > 1 else ''} (catégorie « Écartées », décochée)")
    if informees:
        morceaux.append(f"{informees} avec une information de contexte")
    return f"Contexte moderne : sur {total} détection{'s' if total > 1 else ''}, " + ", ".join(morceaux) + "."


def ligne_etat(trace: Optional[Mapping[str, Any]]) -> str:
    """La ligne sous le bilan de fin de traitement, d'après ``traitement.json["contexte_moderne"]`` :
    « Contexte moderne : 67 détections grisées, 148 avec une information · données de l'IGN lues le
    12/11/2026 », ou la raison pour laquelle le croisement n'a pas été fait. Vide si le traitement ne l'a
    pas demandé (option décochée, pas de détection)."""
    if not isinstance(trace, Mapping):
        return ""
    motif = str(trace.get("motif") or "").strip()
    if motif:
        return motif
    total = int(trace.get("total") or 0)
    if total <= 0:
        return ""
    grisees, informees = int(trace.get("marquees") or 0), int(trace.get("informees") or 0)
    if not grisees and not informees:
        texte = "Contexte moderne : rien à signaler"
    else:
        morceaux = []
        if grisees:
            morceaux.append(f"{grisees} détection{'s' if grisees > 1 else ''} grisée{'s' if grisees > 1 else ''}")
        if informees:
            morceaux.append(f"{informees} avec une information")
        texte = "Contexte moderne : " + ", ".join(morceaux)
    import re

    m = re.search(r"lue le (\d{4})-(\d{2})-(\d{2})", str(trace.get("source") or ""))
    return texte + (f" · données de l'IGN lues le {m.group(3)}/{m.group(2)}/{m.group(1)}" if m else "")


# ----------------------------------------------------------------------
# Légende (lue par ui/layer_loader : rendu catégorisé sur une expression)
# ----------------------------------------------------------------------
#: Valeur et libellé de la catégorie grise de la légende ; décochée à l'ouverture. « Écartées » depuis le
#: 2026-11-19 (« Contexte moderne » avant) : elle reçoit aussi les détections sous l'aire minimale.
CATEGORIE_LEGENDE = "Écartées"
COULEUR_LEGENDE = "#8a8f94"
#: Raison d'un écart par la taille, écrite par le filtre d'aire (pipeline/cv/conversion_shp).
CHAMP_ECART_TAILLE = "ecart_taille"
#: Les champs qui écartent une détection, dans l'ordre où l'infobulle les dit.
CHAMPS_ECART = ("contexte_moderne", CHAMP_ECART_TAILLE)


def expression_legende(classement: str, champs=("contexte_moderne",)) -> str:
    """L'expression du rendu catégorisé : « Écartées » si l'un des ``champs`` est rempli, sinon la valeur
    d'origine (``fiabilite`` ou ``conf_bin``, un nom de champ ou déjà une expression). ``champs`` : ceux que
    la couche porte vraiment — un champ absent rendrait l'expression invalide et masquerait tout."""
    origine = classement if classement.startswith(("(", "if(", "CASE")) else f'"{classement}"'
    test = " or ".join(f"coalesce(\"{c}\", '') <> ''" for c in champs)
    return f"if({test}, '{CATEGORIE_LEGENDE}', {origine})"
