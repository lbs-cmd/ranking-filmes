"""Filmes do catálogo que saem dos 8 serviços nos próximos 60 dias.

Fontes, por ordem de prioridade (com conflito vale a data mais próxima e as duas
ficam anotadas na coluna fonte):
  a) JustWatch: availableToTime das ofertas FLATRATE no BR (scripts/jw_catalogo.py)
  b) página do título na plataforma (não funcionou daqui; ver README do commit)
  c) listas mensais brasileiras de saídas (RendaGeek)
  d) MUBI: dataset kubi2021/plugin.video.mubi, branch database

Uso: python3 scripts/saindo.py <jw_datas.json> <mubi films.json.gz> <lista.json>...
  jw_datas.json: {jw_id: {"imdb_id", "saidas": {serviço: data}}}, gerado com
                 jw_catalogo.buscar/datas_saida para os 8 pacotes
  lista.json:    [{"titulo", "ano", "data"}], com "servico" e "fonte" no nome
                 do arquivo ou nos itens
"""
import csv, gzip, json, re, sys, time, unicodedata, urllib.request
from datetime import date, datetime, timedelta

sys.path.insert(0, "scripts")
from jw_catalogo import ORDEM

HOJE = date.today()
LIMITE = HOJE + timedelta(days=60)
CATALOGO, SAIDA = "data/catalogo.csv", "data/saindo.csv"
with open("data/fontes/correcoes_titulos.json", encoding="utf-8") as _fh:
    CORRECOES = json.load(_fh)


def norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


BUSCA = """query($q:String!){popularTitles(country:BR,first:10,filter:{searchQuery:$q,objectTypes:[MOVIE]}){
 edges{node{objectId content(country:BR,language:"pt"){title originalTitle originalReleaseYear externalIds{imdbId}}
  en:content(country:US,language:"en"){title}}}}}"""


def buscar_jw(titulo):
    """Busca do JustWatch BR: [(jw_id, imdb_id, ano)] na ordem de relevância."""
    corpo = json.dumps({"query": BUSCA, "variables": {"q": titulo}}).encode()
    req = urllib.request.Request("https://apis.justwatch.com/graphql", corpo,
                                 {"content-type": "application/json", "user-agent": "Mozilla/5.0"})
    time.sleep(0.5)
    nos = json.load(urllib.request.urlopen(req, timeout=60))["data"]["popularTitles"]["edges"]
    return [(str(n["objectId"]), (n["content"]["externalIds"] or {}).get("imdbId") or "",
             n["content"]["originalReleaseYear"],
             {n["content"]["title"], n["content"]["originalTitle"], (n.get("en") or {}).get("title")})
            for n in (e["node"] for e in nos)]


def parecido(a, b):
    """Um título contém o outro, ou metade das palavras em comum."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    pa, pb = set(a.split()), set(b.split())
    return len(pa & pb) / len(pa | pb) >= 0.5


def brt(iso):
    """Instante UTC -> último dia no horário de Brasília."""
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(hours=3)).date().isoformat()


def main(jw_json, mubi_gz, listas):
    with open(CATALOGO, encoding="utf-8") as fh:
        campos = list(csv.DictReader(fh).fieldnames)
        fh.seek(0)
        cat = list(csv.DictReader(fh))
    por_jw = {f["jw_id"]: f for f in cat}
    por_imdb = {f["imdb_id"]: f for f in cat if f["imdb_id"]}

    # (chave do filme, serviço) -> {fonte: data}
    achados = {}

    def anotar(f, serv, fonte, dia):
        if f and serv in f["servicos"].split("|"):
            achados.setdefault((f["jw_id"], serv), {})[fonte] = dia

    # a) JustWatch
    for jw_id, e in json.load(open(jw_json)).items():
        f = por_jw.get(jw_id) or por_imdb.get(e["imdb_id"])
        for serv, dia in e["saidas"].items():
            anotar(f, serv, "JustWatch", dia)

    # d) MUBI (Brasil)
    for m in json.load(gzip.open(mubi_gz))["items"]:
        br = (m.get("available_countries") or {}).get("BR")
        if br and br.get("availability_ends_at"):
            anotar(por_imdb.get(m.get("imdb_id") or ""), "MUBI", "MUBI dataset (kubi2021)",
                   brt(br["availability_ends_at"]))

    # c) listas brasileiras: casa por título (pt ou original) + ano (±1)
    nao_casados = []
    for caminho in listas:
        for it in json.load(open(caminho, encoding="utf-8")):
            it["titulo"] = CORRECOES.get(it["titulo"], it["titulo"])
            serv, alvo = it["servico"], norm(it["titulo"])
            cands = [f for f in cat if serv in f["servicos"].split("|")
                     and alvo in (norm(f["titulo_pt"]), norm(f["titulo_original"]))
                     and (not it.get("ano") or not f["ano"] or abs(int(f["ano"]) - it["ano"]) <= 1)]
            if len(cands) != 1:
                # nomes diferem entre a lista e o JustWatch: usa a busca do JustWatch.
                # Vale se o filme está no catálogo com esse serviço e (título parecido
                # em pt/original/inglês com ano ±1, ou 1º resultado com o mesmo ano)
                cands = []
                for i, (jw_id, imdb, ano, titulos) in enumerate(buscar_jw(it["titulo"])):
                    f = por_jw.get(jw_id) or por_imdb.get(imdb)
                    if not (f and serv in f["servicos"].split("|") and ano):
                        continue
                    sem_ano = not it.get("ano")
                    perto = sem_ano or abs(ano - it["ano"]) <= 1
                    if (perto and any(parecido(it["titulo"], t) for t in titulos)) or \
                            (i == 0 and (sem_ano or ano == it["ano"])):
                        cands = [f]
                        break
            if len(cands) == 1:
                anotar(cands[0], serv, it["fonte"], it["data"])
            else:
                nao_casados.append((it, len(cands)))

    # resultado por (filme, serviço): data mais próxima
    saidas = {}
    for (jw_id, serv), fontes in achados.items():
        dia = min(fontes.values())
        if len(set(fontes.values())) > 1:
            fonte = "; ".join(f"{k}={v}" for k, v in sorted(fontes.items(), key=lambda kv: kv[1]))
        else:
            fonte = "|".join(sorted(fontes))
        saidas.setdefault(jw_id, {})[serv] = (dia, fonte)

    # saindo.csv: só quem sai entre hoje e hoje+60
    linhas = []
    for jw_id, por_serv in saidas.items():
        f = por_jw[jw_id]
        saem = {s for s, (d, _) in por_serv.items() if HOJE.isoformat() <= d <= LIMITE.isoformat()}
        for serv in saem:
            dia, fonte = por_serv[serv]
            fica = [s for s in ORDEM if s in f["servicos"].split("|") and s not in saem]
            linhas.append({"imdb_id": f["imdb_id"], "titulo_original": f["titulo_original"].strip(),
                           "ano": f["ano"], "servico": serv, "ultimo_dia": dia, "fonte": fonte,
                           "continua_em": "|".join(fica)})
    linhas.sort(key=lambda r: (r["ultimo_dia"], r["servico"], r["titulo_original"].lower()))
    with open(SAIDA, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["imdb_id", "titulo_original", "ano", "servico", "ultimo_dia",
                                "fonte", "continua_em"])
        w.writeheader()
        w.writerows(linhas)

    # sai_em do catálogo: todas as datas conhecidas (não só a janela de 60 dias)
    for f in cat:
        ps = saidas.get(f["jw_id"], {})
        f["sai_em"] = "|".join(f"{s}:{ps[s][0]}" for s in ORDEM if s in ps)
    with open(CATALOGO, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos)
        w.writeheader()
        w.writerows(cat)

    print(f"Janela: {HOJE} a {LIMITE}")
    print(f"Linhas em {SAIDA}: {len(linhas)} | filmes: {len({r['imdb_id'] or r['titulo_original'] for r in linhas})}")
    for s in ORDEM:
        print(f"  {s:12} {sum(r['servico'] == s for r in linhas)}")
    print("Saem de todos os serviços:", len({(r["imdb_id"], r["titulo_original"]) for r in linhas if not r["continua_em"]}))
    print("Itens de lista sem correspondência única no catálogo:", len(nao_casados))
    for it, n in nao_casados:
        print(f"  [{n}] {it['servico']}: {it['titulo']} ({it.get('ano')}) {it['data']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
