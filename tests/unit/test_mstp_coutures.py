"""Coutures du MSTP entre dalles (constat Bretagne, 2026-11-18).

Une dalle est calculée sur « dalle + marge » puis découpée : tant que la marge couvre le plus grand rayon des
indices demandés, la dalle découpée est identique au calcul d'un seul tenant ; en deçà, rvt reconstruit le
voisinage par symétrie et la jointure saute. En mode « MNT existants » la marge était fixe (50 m) : le MSTP par
défaut (échelle large jusqu'à 200 m, méso 101 m) cousait déjà (banc D:/brouillons/mstp_coutures_2026-11-18 :
rapport jointure / intérieur 61 sur le rouge, 12 sur le vert ; 1 en mode LiDAR, marge 200 m).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.services import rvt_kernel_context as rkc
from app.services.indices_metres import en_px

RACINE = Path(__file__).resolve().parents[2]


def test_marge_requise_suit_le_plus_grand_rayon_des_indices_demandes():
    defauts = en_px({}, 0.5)
    assert rkc.marge_requise_m({"MSTP": True}, defauts) == 200.5             # échelle large 200 m + 1 px
    assert rkc.marge_requise_m({"LD": True}, defauts) == 10.5                # rayon max du LD : 10 m
    assert rkc.marge_requise_m({"LD": True, "MSTP": True}, defauts) == 200.5
    assert rkc.marge_requise_m({"MNT": True, "VAT": True}, defauts) == 0.0   # pas de rayon réglable
    large = en_px({"mstp": {"broad_scale_max_m": 1000.0, "broad_scale_step_m": 90.0}}, 0.5)
    assert rkc.marge_requise_m({"MSTP": True}, large) == 1000.5
    assert rkc.marge_requise_m({"MSTP": True}, en_px({}, 1.0)) == 201.0      # à 1 m/px : 200 px + 1 px


def _mstp(dem):
    from pipeline.ign.products.rvt_embarque import vis

    return vis.mstp(dem=dem.copy(), local_scale=(1, 3, 1), meso_scale=(4, 10, 3), broad_scale=(12, 30, 9),
                    lightness=1.2, ve_factor=1, no_data=None)


def _deux_dalles(dem, marge):
    """Comme le pipeline : chaque dalle calculée sur « dalle + marge » côté voisine, puis découpée."""
    n = dem.shape[1] // 2
    gauche = _mstp(dem[:, :n + marge])[:, :, :n]
    droite = _mstp(dem[:, n - marge:])[:, :, marge:]
    return np.concatenate([gauche, droite], axis=2)


def test_une_marge_qui_couvre_le_rayon_large_ne_coud_pas():
    rng = np.random.default_rng(0)
    dem = np.cumsum(np.cumsum(rng.normal(size=(80, 160)), axis=0), axis=1).astype(np.float32)
    entier = _mstp(dem)
    assert np.allclose(_deux_dalles(dem, 30), entier, atol=1e-5)                      # marge = rayon large max
    assert not np.allclose(_deux_dalles(dem, 10)[0], entier[0], atol=1e-3)            # marge courte : l'échelle
    assert np.allclose(_deux_dalles(dem, 10)[2], entier[2], atol=1e-5)                # large coud, la locale non


def test_le_mode_mnt_existants_calcule_sur_la_marge_requise_et_garde_le_halo_de_la_detection():
    code = (RACINE / "src" / "pipeline" / "modes" / "existing_mnt.py").read_text(encoding="utf-8")
    assert "marge_requise_m(products, rvt_params)" in code
    assert "_materialiser_mnt_avec_marge(\n            mnt_path, tiles, temp_mnt_path, marge_calcul, log)" in code
    assert "_ramener_au_halo(" in code     # intermédiaires (halo de la détection) ramenés à 50 m
