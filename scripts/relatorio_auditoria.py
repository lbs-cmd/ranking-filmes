"""Gera data/auditoria_<data>.md a partir dos arquivos da auditoria.

Uso: python3 scripts/relatorio_auditoria.py <catalogo_anterior.csv> <letterboxd_antes.csv> <sem_nota_antes.csv>
Os dois últimos são as versões de letterboxd.csv/sem_nota.csv de antes da auditoria
(para contar quantos filmes novos ganharam nota).
"""
import csv, json, sys
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, "scripts")
from jw_catalogo import ORDEM

HOJE = date.today().isoformat()


def ler(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(anterior, lb_antes, sn_antes):
    cat, entr, sai = ler("data/catalogo.csv"), ler("data/entraram.csv"), ler("data/sairam.csv")
    cor = [c for c in ler("data/correcoes_manuais.csv") if c["data"] == HOJE]
    saindo, amostra = ler("data/saindo.csv"), ler(f"data/fontes/auditoria_amostra_{HOJE}.csv")
    cheg, mubi = ler(f"data/fontes/auditoria_chegadas_{HOJE}.csv"), ler(f"data/fontes/auditoria_mubi_{HOJE}.csv")
    saidas_aud = ler(f"data/fontes/auditoria_saidas_{HOJE}.csv")

    total = Counter(s for f in cat for s in filter(None, f["servicos"].split("|")))
    n_entr, n_sai = Counter(e["servico"] for e in entr), Counter(s["servico"] for s in sai)
    add = Counter(c["servico"] for c in cor if c["acao"].startswith("adicionado"))
    rest = Counter(c["servico"] for c in cor if c["acao"] == "restaurado_saida_falsa")
    rem = Counter(c["servico"] for c in cor if c["acao"].startswith("removido"))
    am = defaultdict(lambda: [0, 0])
    for a in amostra:
        am[a["servico"]][0] += a["bate"] == "sim"
        am[a["servico"]][1] += 1
    ate, n_saindo = {}, Counter()
    for s in saindo:
        n_saindo[s["servico"]] += 1
        ate[s["servico"]] = max(ate.get(s["servico"], ""), s["ultimo_dia"])

    k = lambda r: r["imdb_id"] or "jw" + r["jw_id"]
    lb_ok = {r["imdb_id"] for r in ler("data/letterboxd.csv")}
    sn = {(r["imdb_id"] or "jw" + r["jw_id"]): r["motivo"] for r in ler("data/sem_nota.csv")}
    ja = {r["imdb_id"] for r in ler(lb_antes)} | {(r["imdb_id"] or "jw" + r["jw_id"]) for r in ler(sn_antes)}
    novos = [f for f in cat if k(f) not in ja]
    com_nota = sum(k(f) in lb_ok for f in novos)
    motivos = Counter(sn[k(f)] for f in novos if k(f) in sn)

    L = [f"# Auditoria do catálogo — {HOJE}", "",
         f"Catálogo anterior: `{anterior}`. Serviços: {', '.join(ORDEM)} (Brasil, só FLATRATE).", "",
         "## Resumo por serviço", "",
         "| Serviço | Total | Chegadas | Saídas | Chegadas adicionadas na auditoria | Saídas falsas desfeitas | Removidos (MUBI) | Amostra | Saem em 60 dias | Datas até |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for s in ORDEM:
        a = am[s]
        L.append(f"| {s} | {total[s]} | {n_entr[s]} | {n_sai[s]} | {add[s]} | {rest[s]} | {rem[s]} | "
                 f"{a[0]} de {a[1]} | {n_saindo[s]} | {ate.get(s, '—')} |")
    L += ["", f"Chegadas e saídas já consideram as correções da auditoria. Letterboxd: {len(novos)} filmes novos "
          f"consultados, {com_nota} ganharam nota; sem nota: {dict(motivos)}.", ""]

    L += ["## Correções feitas (data/correcoes_manuais.csv)", ""]
    nomes = {"restaurado_saida_falsa": "Saídas falsas desfeitas (o JustWatch ainda tem a oferta FLATRATE)",
             "adicionado_justwatch": "Adicionados com confirmação do JustWatch",
             "adicionado_kubi": "Adicionados só pelo dataset kubi2021/plugin.video.mubi (BR, live) — o JustWatch não confirma",
             "adicionado_fonte_oficial": "Adicionados por fonte oficial (o JustWatch não confirma)",
             "removido_kubi": "Removidos (kubi diz que saiu e o JustWatch não tem mais a oferta)"}
    for acao, titulo in nomes.items():
        itens = [c for c in cor if c["acao"] == acao]
        if itens:
            L += [f"### {titulo} — {len(itens)}", ""]
            L += [f"- {c['servico']}: {c['titulo_original']} ({c['imdb_id'] or 'sem IMDb'})" for c in itens]
            L.append("")

    L += ["## Parte 2 — chegadas de novembro nas listas brasileiras", "",
          "Listas usadas (nenhuma é página oficial do serviço):", ""]
    for url in sorted({c["url"] for c in cheg}):
        L.append(f"- {url}")
    L += ["", "| Serviço | " + " | ".join(sorted({c['resultado'] for c in cheg})) + " |",
          "|---|" + "---|" * len({c['resultado'] for c in cheg})]
    res = sorted({c["resultado"] for c in cheg})
    for s in ORDEM:
        cont = Counter(c["resultado"] for c in cheg if c["servico"] == s)
        if cont:
            L.append(f"| {s} | " + " | ".join(str(cont[r]) for r in res) + " |")
    pend = [c for c in cheg if c["resultado"] in ("justwatch_sem_oferta", "nao_encontrado_justwatch")]
    L += ["", "Não confirmados (não adicionados, pois a fonte não é oficial):", ""]
    L += [f"- {c['servico']}: {c['titulo']} ({c['data']}) — {c['resultado']}"
          + (f", JustWatch achou “{c['titulo_jw']}” sem essa oferta" if c.get("titulo_jw") else "") for c in pend]

    L += ["", "## Parte 3 — saídas", "",
          f"{len(saidas_aud)} saídas reconferidas no JustWatch (pelo ID e pelo título): "
          f"{dict(Counter(x['resultado'] for x in saidas_aud))}.", "",
          "Cruzamento com o dataset kubi (MUBI, BR):", ""]
    for sentido in ("kubi_sem_catalogo", "catalogo_sem_kubi"):
        L.append(f"- {sentido}: {dict(Counter(m['resultado'] for m in mubi if m['sentido'] == sentido))}")
    div = [m for m in mubi if m["resultado"].startswith("divergencia")]
    if div:
        L += ["", "Divergências (no catálogo e com oferta no JustWatch, mas fora do kubi BR):", ""]
        L += [f"- {m['titulo']} ({m['ano']})" for m in div]

    L += ["", "## Parte 4 — amostra de controle", "",
          "25 filmes sorteados por serviço (semente = data) e reconsultados no JustWatch.", ""]
    L += [f"- {a['servico']}: {a['titulo_original']} — catálogo diz {a['servico']}, JustWatch hoje: "
          f"{a['servicos_justwatch'] or 'nenhum dos 8'}" for a in amostra if a["bate"] != "sim"] or ["- Todos batem."]
    L += ["", "## Observações", ""]
    with open(f"data/auditoria_{HOJE}.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"data/auditoria_{HOJE}.md")


if __name__ == "__main__":
    main(*sys.argv[1:])
