"""Une boîte tranchée par le bord d'une fenêtre SAHI ne doit pas évincer la boîte entière du même objet.

Cas réel (2026-11-12, dalle 0995_6747, modèle des structures ponctuelles, image de 2 400 px de large) : la
charbonnière est vue entière par la fenêtre qui commence à x = 1 614 (confiance 0,527) et coupée par celle qui
commence à x = 1 728 (confiance 0,533 à 0,639). La fusion gardait la plus confiante — le morceau.
"""
from src.pipeline.cv.sahi_lite import Detection, merge_sliced_detections

FENETRE = (672, 672)


def _fusion(par_fenetre, departs):
    return merge_sliced_detections(par_fenetre, departs, 2800, 2400, slice_size=FENETRE)


def test_la_boite_entiere_l_emporte_sur_le_morceau_plus_confiant():
    entiere = Detection(bbox=[95.1, 96.9, 134.0, 135.0], score=0.527, class_id=0)     # fenêtre (1614, 538)
    morceau = Detection(bbox=[0.0, 98.8, 21.0, 136.2], score=0.639, class_id=0)       # fenêtre (1728, 538)
    sortie = _fusion([[entiere], [morceau]], [[1614, 538], [1728, 538]])
    assert len(sortie) == 1
    assert [round(v) for v in sortie[0].bbox] == [1709, 635, 1748, 673]
    assert sortie[0].score == 0.527


def test_un_morceau_seul_est_garde():
    morceau = Detection(bbox=[0.0, 98.8, 21.0, 136.2], score=0.639, class_id=0)
    assert len(_fusion([[morceau]], [[1728, 538]])) == 1


def test_le_bord_de_l_image_n_est_pas_une_coupe():
    """Une boîte posée sur le bord de l'image (fenêtre en x = 0) garde son rang : rien ne la complète ailleurs."""
    au_bord = Detection(bbox=[0.0, 100.0, 30.0, 130.0], score=0.8, class_id=0)
    doublon = Detection(bbox=[2.0, 100.0, 30.0, 130.0], score=0.5, class_id=0)
    sortie = _fusion([[au_bord, doublon]], [[0, 0]])
    assert len(sortie) == 1 and sortie[0].score == 0.8


def test_sans_taille_de_fenetre_rien_ne_change():
    entiere = Detection(bbox=[95.1, 96.9, 134.0, 135.0], score=0.527, class_id=0)
    morceau = Detection(bbox=[0.0, 98.8, 21.0, 136.2], score=0.639, class_id=0)
    sortie = merge_sliced_detections([[entiere], [morceau]], [[1614, 538], [1728, 538]], 2800, 2400)
    assert len(sortie) == 1 and sortie[0].score == 0.639
