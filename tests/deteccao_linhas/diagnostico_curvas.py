"""Diagnóstico de fileiras em curva (NÃO é teste do pytest: o nome não começa com test_).

Gera ortomosaicos SINTÉTICOS com fileiras curvas (arcos concêntricos e uma curva em S), com verdade
exata conhecida, roda o pacote `deteccao_linhas` SEM alterar o código e mede o erro lateral.
Prova só o comportamento do algoritmo sobre imagem sintética; NÃO é acurácia de campo.

Uso:  python tests/deteccao_linhas/diagnostico_curvas.py base|varredura|figuras [pasta_trabalho]
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import cKDTree
from shapely.geometry import Polygon

from deteccao_linhas.cli import executar_deteccao
from deteccao_linhas.config import carregar_config

CRS_M = "EPSG:31983"
RES = 0.06
CENTRO = (394000.0, 7775000.0)
RAIOS = [None, 400, 200, 100, 50, 30]  # None = reta
CONFIG_BASE = Path(__file__).resolve().parents[2] / "config_deteccao.yaml"


# ----------------------------------------------------------------------------- geometria da verdade
class Curva:
    """Linha de referência (eixo do talhão) por integração da curvatura; esquerda = lado positivo."""

    def __init__(self, raio: float | None, comprimento: float, s_forma: bool = False, azimute: float = 20.0):
        passo = 0.25
        n = int(comprimento / passo) + 1
        s = np.arange(n) * passo
        if raio is None:
            kappa = np.zeros(n)
        elif s_forma:
            kappa = np.where(s < comprimento / 2, 1.0 / raio, -1.0 / raio)
        else:
            kappa = np.full(n, 1.0 / raio)
        # rumo matemático (anti-horário a partir do leste); começa de modo que o azimute médio ~ `azimute`
        phi = np.cumsum(kappa) * passo
        phi = phi - phi[n // 2] + np.deg2rad(90.0 - azimute)
        x = np.concatenate([[0.0], np.cumsum(np.cos(phi[:-1]) * passo)])
        y = np.concatenate([[0.0], np.cumsum(np.sin(phi[:-1]) * passo)])
        self.s, self.phi = s, phi
        self.pts = np.column_stack([x, y]) + np.array(CENTRO)
        self.tan = np.column_stack([np.cos(phi), np.sin(phi)])
        self.nor = np.column_stack([-np.sin(phi), np.cos(phi)])  # esquerda
        self.kappa = kappa
        self.arv = cKDTree(self.pts)

    def deslocada(self, d: float) -> np.ndarray:
        return self.pts + d * self.nor

    def distancia_assinada(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Distância assinada exata (projeção nos segmentos vizinhos) e abscissa curvilínea s."""
        _, i = self.arv.query(xy)
        melhor = np.full(len(xy), np.inf)
        s_out = np.zeros(len(xy))
        sinal = np.zeros(len(xy))
        n = len(self.pts)
        for dj in (-1, 0):
            a = np.clip(i + dj, 0, n - 2)
            p0, p1 = self.pts[a], self.pts[a + 1]
            v = p1 - p0
            t = np.clip(np.einsum("ij,ij->i", xy - p0, v) / np.einsum("ij,ij->i", v, v), 0, 1)
            q = p0 + v * t[:, None]
            dist = np.hypot(*(xy - q).T)
            mel = dist < melhor
            cross = v[:, 0] * (xy[:, 1] - q[:, 1]) - v[:, 1] * (xy[:, 0] - q[:, 0])
            sinal = np.where(mel, np.sign(cross + 1e-12), sinal)
            s_out = np.where(mel, self.s[a] + t * 0.25, s_out)
            melhor = np.minimum(melhor, dist)
        return melhor * sinal, s_out

    def poligono(self, largura: float) -> Polygon:
        esq, dire = self.deslocada(largura / 2), self.deslocada(-largura / 2)
        return Polygon(np.vstack([esq, dire[::-1]]))


def fileiras_verdade(rng, largura: float, jitter: float) -> np.ndarray:
    """Deslocamentos d_k das fileiras: passadas de 3 m (+ desvio de GPS entre passadas), gêmeas a 1,5 m."""
    n_passadas = int(np.ceil(largura / 3.0)) + 4
    centros = (np.arange(n_passadas) - n_passadas // 2) * 3.0 + 0.3
    if jitter > 0:
        centros = centros + np.clip(rng.normal(0, jitter, n_passadas), -2.5 * jitter, 2.5 * jitter)
    return np.sort(np.concatenate([centros - 0.75, centros + 0.75]))


# ----------------------------------------------------------------------------- cenário sintético
def montar_cenario(pasta: Path, nome: str, raio: float | None, *, s_forma=False, realista=True, semente=1):
    """Cria <pasta>/<nome>.tif, <nome>_talhao.gpkg e <nome>_verdade.npz. Devolve o dicionário do cenário."""
    pasta.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(semente)
    largura = 40.0 if (raio is None or raio >= 50) else 30.0
    comprimento = 150.0 if raio is None else min(150.0, raio * 3.5)
    if s_forma:
        comprimento = 300.0
    curva = Curva(raio, comprimento, s_forma)
    dk = fileiras_verdade(rng, largura + 20, 0.08 if realista else 0.0)
    poli = curva.poligono(largura)
    x0, y0, x1, y1 = poli.bounds
    x0, y0, x1, y1 = x0 - 12, y0 - 12, x1 + 12, y1 + 12  # margem (fileiras continuam além do talhão)
    w, h = int(np.ceil((x1 - x0) / RES)), int(np.ceil((y1 - y0) / RES))
    cx = x0 + (np.arange(w) + 0.5) * RES
    cy = y1 - (np.arange(h) + 0.5) * RES
    XX, YY = np.meshgrid(cx, cy)
    xy = np.column_stack([XX.ravel(), YY.ravel()])
    d, s = curva.distancia_assinada(xy)
    pos = np.searchsorted(dk, d)
    esq = dk[np.clip(pos, 0, len(dk) - 1)]
    dir_ = dk[np.clip(pos - 1, 0, len(dk) - 1)]
    k = np.where(np.abs(d - esq) < np.abs(d - dir_), np.clip(pos, 0, len(dk) - 1), np.clip(pos - 1, 0, len(dk) - 1))
    dist_fileira = np.abs(d - dk[k])
    veg = dist_fileira <= 0.24
    if realista:
        # falhas: ~1,2 por 100 m de fileira, de 2 a 6 m (as bordas ficam em s por fileira)
        ngap = int(np.ceil((comprimento / 100.0) * 1.2)) + 1
        mask_falha = np.zeros_like(veg)
        for ik in range(len(dk)):
            for _ in range(rng.poisson(ngap)):
                a = rng.uniform(0, comprimento)
                b = a + rng.uniform(2.0, 6.0)
                mask_falha |= (k == ik) & (s >= a) & (s <= b)
        veg &= ~mask_falha
        # manchas de "daninha" (verde fora das linhas) e ruído
        verdes = veg.copy()
        for _ in range(int(0.4 * (largura * comprimento) / 100.0)):
            cxp = rng.uniform(poli.bounds[0], poli.bounds[2])
            cyp = rng.uniform(poli.bounds[1], poli.bounds[3])
            raio_m = rng.uniform(0.5, 1.5)
            verdes |= ((XX.ravel() - cxp) ** 2 + (YY.ravel() - cyp) ** 2 <= raio_m**2)
        veg = verdes
    veg = veg.reshape(h, w)
    img = np.empty((3, h, w), dtype=np.uint8)
    solo, verde = np.array([150, 110, 80]), np.array([60, 160, 50])
    for b in range(3):
        base = np.where(veg, verde[b], solo[b]).astype(np.float32)
        if realista:
            base = base + rng.normal(0, 10, base.shape).astype(np.float32)
        img[b] = np.clip(base, 0, 255).astype(np.uint8)
    tif, gp = pasta / f"{nome}.tif", pasta / f"{nome}_talhao.gpkg"
    with rasterio.open(tif, "w", driver="GTiff", height=h, width=w, count=3, dtype="uint8", crs=CRS_M,
                       transform=from_origin(x0, y1, RES, RES), compress="deflate") as ds:
        ds.write(img)
    gpd.GeoDataFrame({"id": ["T1"]}, geometry=[poli], crs=CRS_M).to_file(gp, driver="GPKG")
    np.savez(pasta / f"{nome}_verdade.npz", dk=dk, pts=curva.pts)
    return {"nome": nome, "raio": raio, "s_forma": s_forma, "realista": realista, "largura": largura,
            "comprimento": comprimento, "tif": tif, "talhao": gp, "curva": curva, "dk": dk, "poli": poli}


# ----------------------------------------------------------------------------- métricas
def metricas(cen: dict, saida: Path, buffer_m: float) -> dict:
    curva, dk, poli = cen["curva"], cen["dk"], cen["poli"]
    util = poli.buffer(-buffer_m)
    fil = gpd.read_file(saida, layer="fileiras")
    tre = gpd.read_file(saida, layer="trechos")
    xy = np.column_stack([tre.geometry.x, tre.geometry.y])
    d, s = curva.distancia_assinada(xy)
    k = np.abs(d[:, None] - dk[None, :]).argmin(axis=1)
    erro = d - dk[k]
    status = tre["status"].to_numpy()
    raio_local = np.full(len(d), np.inf) if cen["raio"] is None else np.abs(
        (cen["raio"] if not cen["s_forma"] else cen["raio"]) - np.sign(1.0) * d)  # centro à esquerda
    out: dict = {"n_pontos": int(len(tre)), "n_fileiras_detectadas": int(len(fil))}
    for st in ("detectado", "interpolado", "duvidoso"):
        out[f"frac_{st}"] = float((status == st).mean()) if len(tre) else float("nan")

    def estat(m, rotulo):
        e = np.abs(erro[m])
        if e.size == 0:
            return {f"{rotulo}_n": 0}
        return {f"{rotulo}_n": int(e.size), f"{rotulo}_mediana_cm": float(np.median(e) * 100),
                f"{rotulo}_p95_cm": float(np.percentile(e, 95) * 100), f"{rotulo}_vies_cm": float(np.median(erro[m]) * 100),
                f"{rotulo}_gt10": float((e > 0.10).mean()), f"{rotulo}_gt25": float((e > 0.25).mean())}
    out.update(estat(np.ones(len(tre), bool), "todos"))
    out.update(estat(status == "detectado", "conf"))
    # verdade dentro da área útil: cobertura por linha detectada a <=10/30 cm
    tr_n = []
    amostras = []
    for ik, dd in enumerate(dk):
        linha = curva.deslocada(dd)
        sel = np.array([util.contains(__import__("shapely").geometry.Point(*p)) for p in linha[::4]])
        pts = linha[::4][sel]
        amostras.append(pts)
        tr_n.append(len(pts))
    amostras = np.vstack([a for a in amostras if len(a)])
    arv_det = fil.geometry.union_all()
    dist = np.array([arv_det.distance(__import__("shapely").geometry.Point(*p)) for p in amostras])
    out["cobertura_10cm"] = float((dist <= 0.10).mean())
    out["cobertura_30cm"] = float((dist <= 0.30).mean())
    out["comprimento_verdade_m"] = float(len(amostras))  # amostras a cada 1 m
    n_verd = sum(1 for t in tr_n if t * 1.0 >= 30)
    out["n_fileiras_verdade_ge30m"] = int(n_verd)
    # fragmentação / troca de fileira
    ids = tre["id_fileira"].to_numpy()
    trocas, frag = 0, {}
    for i in np.unique(ids):
        m = ids == i
        ks, cont = np.unique(k[m], return_counts=True)
        validos = ks[cont >= 3]
        if len(validos) > 1:
            trocas += 1
        if len(ks):
            frag.setdefault(int(ks[cont.argmax()]), 0)
            frag[int(ks[cont.argmax()])] += 1
    out["fileiras_com_troca"] = int(trocas)
    out["frag_media"] = float(np.mean(list(frag.values()))) if frag else float("nan")
    # por raio local (faixas)
    if cen["raio"] is not None and not cen["s_forma"]:
        rl = cen["raio"] - d  # centro à esquerda: raio local = R - d
        for lo, hi in ((0, 30), (30, 50), (50, 100), (100, 200), (200, 1e9)):
            m = (rl >= lo) & (rl < hi)
            if m.sum() >= 20:
                out[f"faixa_raio_{lo}_{int(min(hi, 9999))}"] = {
                    "n": int(m.sum()), "mediana_cm": float(np.median(np.abs(erro[m])) * 100),
                    "gt25": float((np.abs(erro[m]) > 0.25).mean()),
                    "frac_det": float((status[m] == "detectado").mean())}
    out["_erro_pontos"] = None
    return out


def _azimute_verdade(curva: Curva, x: float, y: float) -> float:
    _, i = curva.arv.query([x, y])
    return float((90.0 - np.rad2deg(curva.phi[i])) % 180.0)


def _dif180(a: float, b: float) -> float:
    return (a - b + 90.0) % 180.0 - 90.0


def _instalar_orientacao(cen: dict, oraculo: bool, registro: list) -> object:
    """Envolve `estimar_direcoes` (só no diagnóstico): registra o erro de orientação por região e, no modo
    oráculo, troca a direção estimada pela tangente verdadeira no centroide da região."""
    from deteccao_linhas import cli
    from deteccao_linhas.tipos import DirecaoFileiras
    original = cli.estimar_direcoes

    def envolto(fb, regioes, cfg):
        saida, u_ref = original(fb, regioes, cfg)
        novas = []
        for r in saida:
            c = r.poligono.centroid
            az_v = _azimute_verdade(cen["curva"], c.x, c.y)
            registro.append({"erro_graus": abs(_dif180(r.direcao.azimute_graus, az_v)),
                             "herdada": bool(r.direcao.herdada), "area_m2": float(r.poligono.area)})
            if oraculo:
                a = np.deg2rad(az_v)
                v = (float(np.sin(a)), float(np.cos(a)))
                if v[0] * u_ref[0] + v[1] * u_ref[1] < 0:
                    v = (-v[0], -v[1])
                r = replace(r, direcao=DirecaoFileiras(azimute_graus=az_v, vetor=v, confianca=1.0, herdada=False))
            novas.append(r)
        return novas, u_ref
    cli.estimar_direcoes = envolto
    return original


def rodar(cen: dict, cfg, pasta: Path, rotulo: str, oraculo: bool = False) -> dict:
    from deteccao_linhas import cli
    saida = pasta / f"saida_{cen['nome']}_{rotulo}.gpkg"
    t0 = time.time()
    registro: list = []
    original = _instalar_orientacao(cen, oraculo, registro)
    try:
        resumos = executar_deteccao(cen["tif"], cen["talhao"], saida, cfg)
    except Exception as exc:  # falha do algoritmo é resultado, não erro do diagnóstico
        cli.estimar_direcoes = original
        return {"erro": f"{type(exc).__name__}: {exc}", "tempo_s": time.time() - t0, "cenario": cen["nome"],
                "rotulo": rotulo}
    cli.estimar_direcoes = original
    t = time.time() - t0
    m = metricas(cen, saida, cfg.buffer_interno_m)
    m.pop("_erro_pontos", None)
    r = resumos[0]
    eo = [e["erro_graus"] for e in registro]
    m.update({"orient_erro_med_graus": float(np.median(eo)), "orient_erro_max_graus": float(np.max(eo)),
              "orient_oraculo": oraculo})
    m.update({"tempo_s": t, "cenario": cen["nome"], "rotulo": rotulo, "n_regioes": r.n_regioes,
              "regioes_herdadas": r.n_regioes_direcao_herdada, "n_blocos": r.n_blocos,
              "trilhas_descartadas": r.n_trilhas_descartadas})
    return m


def principal(modo: str, pasta: Path) -> None:
    import contextlib
    import io
    cfg0 = carregar_config(CONFIG_BASE)
    res_json = pasta / f"resultados_{modo}.json"
    resultados = json.loads(res_json.read_text()) if res_json.exists() else []
    feitos = {(r["cenario"], r["rotulo"]) for r in resultados}

    def executar(cen, cfg, rot, oraculo=False):
        if (cen["nome"], rot) in feitos:
            return
        with contextlib.redirect_stdout(io.StringIO()):
            r = rodar(cen, cfg, pasta, rot, oraculo)
        r["params"] = {"regiao_m": cfg.regiao_m, "bloco_m": cfg.comprimento_bloco_m, "passo_m": cfg.passo_bloco_m,
                       "desvio_max": cfg.desvio_angular_max_graus}
        resultados.append(r)
        res_json.write_text(json.dumps(resultados, indent=1, default=str))
        print(f"{cen['nome']:>14} {rot:<22} {'ERRO ' + r['erro'] if 'erro' in r else '%.0fs cobert30=%.2f conf_gt25=%.3f' % (r['tempo_s'], r['cobertura_30cm'], r.get('conf_gt25', float('nan')))}", flush=True)

    if modo == "base":
        for realista in (False, True):
            for raio in RAIOS:
                nome = ("reta" if raio is None else f"R{raio}") + ("_real" if realista else "_limpo")
                executar(montar_cenario(pasta, nome, raio, realista=realista), cfg0, "padrao")
        executar(montar_cenario(pasta, "S100_real", 100, s_forma=True, realista=True), cfg0, "padrao")
        executar(montar_cenario(pasta, "S100_limpo", 100, s_forma=True, realista=False), cfg0, "padrao")
    elif modo == "s":
        cen = montar_cenario(pasta, "S100_real", 100, s_forma=True, realista=True)
        for reg, cb, pb in ((15.0, 5.0, 5.0), (10.0, 5.0, 2.5), (10.0, 10.0, 10.0)):
            cfg = replace(cfg0, regiao_m=reg, area_minima_regiao_m2=min(2000.0, 0.3 * reg * reg),
                          desvio_angular_max_graus=90.0, comprimento_bloco_m=cb, passo_bloco_m=pb)
            executar(cen, cfg, f"reg{int(reg)}_bloco{cb:g}_{pb:g}")
    elif modo == "oraculo":
        cens = [montar_cenario(pasta, "reta_real", None)] + [montar_cenario(pasta, f"R{r}_real", r) for r in (400, 200, 100, 50, 30)]
        for cen in cens:
            for reg, cb, pb in ((150.0, 10.0, 10.0), (50.0, 10.0, 10.0), (25.0, 10.0, 10.0), (25.0, 5.0, 5.0), (10.0, 10.0, 10.0), (10.0, 5.0, 5.0)):
                cfg = replace(cfg0, regiao_m=reg, area_minima_regiao_m2=min(2000.0, 0.3 * reg * reg),
                              desvio_angular_max_graus=90.0, comprimento_bloco_m=cb, passo_bloco_m=pb)
                executar(cen, cfg, f"orac_reg{int(reg)}_bloco{cb:g}", oraculo=True)
    elif modo == "varredura":
        cens = [montar_cenario(pasta, "reta_real", None)] + [montar_cenario(pasta, f"R{r}_real", r) for r in (100, 50, 30)]
        for cen in cens:
            for reg in (150.0, 75.0, 50.0, 25.0, 15.0, 10.0):
                for desv in (15.0, 90.0):
                    cfg = replace(cfg0, regiao_m=reg, area_minima_regiao_m2=min(2000.0, 0.3 * reg * reg),
                                  desvio_angular_max_graus=desv)
                    executar(cen, cfg, f"reg{int(reg)}_desv{int(desv)}")
            for cb, pb in ((10.0, 10.0), (5.0, 5.0), (10.0, 5.0), (5.0, 2.5)):
                cfg = replace(cfg0, regiao_m=50.0, area_minima_regiao_m2=750.0, desvio_angular_max_graus=90.0,
                              comprimento_bloco_m=cb, passo_bloco_m=pb)
                executar(cen, cfg, f"reg50_bloco{cb:g}_{pb:g}")
            for reg in (15.0, 10.0):
                for cb, pb in ((5.0, 5.0), (10.0, 5.0), (5.0, 2.5)):
                    cfg = replace(cfg0, regiao_m=reg, area_minima_regiao_m2=min(2000.0, 0.3 * reg * reg),
                                  desvio_angular_max_graus=90.0, comprimento_bloco_m=cb, passo_bloco_m=pb)
                    executar(cen, cfg, f"reg{int(reg)}_bloco{cb:g}_{pb:g}")


if __name__ == "__main__":
    modo = sys.argv[1]
    pasta = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/curvas")
    principal(modo, pasta)
