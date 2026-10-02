"""Entradas e saídas por serviço entre duas versões do catálogo.

Uso: python3 scripts/comparar.py <catalogo_anterior.csv> <catalogo_novo.csv>
Gera data/entraram.csv e data/sairam.csv (imdb_id, titulo_original, ano, servico).
A chave é filme+serviço (mesmo filme = mesmo jw_id ou mesmo IMDb ID): um filme
que só trocou de serviço aparece nos dois.
"""
import csv, sys

sys.path.insert(0, "scripts")
from jw_catalogo import ORDEM

QUEDA_MAX = 0.20


def pares(caminho):
    """{("jw<jw_id>", serviço): linha do catálogo}."""
    with open(caminho, encoding="utf-8") as fh:
        out = {}
        for f in csv.DictReader(fh):
            for s in filter(None, f["servicos"].split("|")):
                out[("jw" + f["jw_id"], s)] = f
        return out


def presente(f, serv, outro):
    """O filme f continua com o serviço na outra versão (mesmo jw_id ou mesmo IMDb)?"""
    return ("jw" + f["jw_id"], serv) in outro or (f["imdb_id"], serv) in outro


def gravar(caminho, itens):
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["imdb_id", "titulo_original", "ano", "servico"])
        w.writeheader()
        for (_, s), f in sorted(itens, key=lambda kv: (ORDEM.index(kv[0][1]), kv[1]["titulo_original"].lower())):
            w.writerow({"imdb_id": f["imdb_id"], "titulo_original": f["titulo_original"].strip(),
                        "ano": f["ano"], "servico": s})


def main(antigo, novo):
    a, n = pares(antigo), pares(novo)
    # índice extra por IMDb, para filmes cujo jw_id mudou (duplicatas juntadas)
    a_idx = {**a, **{(f["imdb_id"], s): f for (_, s), f in a.items() if f["imdb_id"]}}
    n_idx = {**n, **{(f["imdb_id"], s): f for (_, s), f in n.items() if f["imdb_id"]}}
    entraram = [(k, f) for k, f in n.items() if not presente(f, k[1], a_idx)]
    sairam = [(k, f) for k, f in a.items() if not presente(f, k[1], n_idx)]
    gravar("data/entraram.csv", entraram)
    gravar("data/sairam.csv", sairam)

    alertas = []
    print(f"{'serviço':12} {'antes':>6} {'agora':>6} {'entr.':>6} {'saíram':>6}")
    for s in ORDEM:
        antes = sum(1 for (_, x) in a if x == s)
        agora = sum(1 for (_, x) in n if x == s)
        print(f"{s:12} {antes:>6} {agora:>6} {sum(k[1] == s for k, _ in entraram):>6} "
              f"{sum(k[1] == s for k, _ in sairam):>6}")
        if agora == 0 or (antes and (antes - agora) / antes > QUEDA_MAX):
            alertas.append(s)
    print(f"Entraram: {len(entraram)} | saíram: {len(sairam)}")
    print("ALERTA (0 filmes ou queda > 20%):", ", ".join(alertas) if alertas else "nenhum")
    return alertas


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], sys.argv[2]) else 0)
