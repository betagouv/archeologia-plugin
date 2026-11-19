"""Un fichier de dalles « nom,url » dont le nom n'a pas d'extension (2026-11-19).

Le nom des dalles dans la grille IGN (``nom_pkk``) n'a pas d'extension. Repris tel quel dans un fichier de
dalles fait à la main, il donnait des fichiers sans ``.copc.laz`` que PDAL refusait (« Cannot determine
reader »), puis « Aucune dalle téléchargée… vérifiez votre connexion réseau ». Le nom vient alors de l'URL.
"""
import pipeline.ign.downloader as dl

URL = ("https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_RE_2025-02-17/"
       "LHD_FXX_0986_6860_PTS_LAMB93_IGN69.copc.laz")


def test_nom_sans_extension_pris_dans_l_url(tmp_path):
    f = tmp_path / "dalles.txt"
    f.write_bytes(f"LHD_FXX_0986_6860_PTS_LAMB93_IGN69,{URL}\r\n".encode("utf-8"))
    assert dl.parse_ign_input_file(f, tmp_path / "tri.txt", log=lambda *_: None) == [
        ("LHD_FXX_0986_6860_PTS_LAMB93_IGN69.copc.laz", URL)]


def test_nom_avec_extension_garde(tmp_path):
    f = tmp_path / "dalles.txt"
    f.write_text(f"ma_dalle.laz,{URL}\n", encoding="utf-8")
    assert dl.parse_ign_input_file(f, tmp_path / "tri.txt", log=lambda *_: None) == [("ma_dalle.laz", URL)]
