"""Etapa 1: catálogo de filmes por assinatura (flatrate) no JustWatch BR."""
import csv, json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta
from collections import Counter

API = "https://apis.justwatch.com/graphql"
# código JustWatch -> nome do serviço (variantes contam como o serviço principal)
SERVICOS = {
    "nfx": "Netflix", "nfa": "Netflix",
    "prv": "Prime Video",
    "mxx": "HBO Max",
    "dnp": "Disney+",
    "pmp": "Paramount+", "ppp": "Paramount+",
    "mbi": "MUBI",
    # Telecine e Universal+ só existem no JustWatch BR como canais Amazon;
    # o catálogo é usado como aproximação do que a Claro oferece
    "atl": "Telecine",
    "auc": "Universal+",
}
CONSULTAR = ["nfx", "prv", "mxx", "dnp", "pmp", "mbi", "atl", "auc"]
ORDEM = ["Netflix", "Prime Video", "HBO Max", "Disney+", "Paramount+", "MUBI", "Telecine", "Universal+"]
DURACAO_MIN = 40
SAIDAS_JW = "data/fontes/justwatch_saidas.json"
CATALOGO = "data/catalogo.csv"

Q = """query($after:String,$pkg:[String!],$y0:Int,$y1:Int){
 popularTitles(country:BR,first:100,after:$after,
  filter:{packages:$pkg,objectTypes:[MOVIE],monetizationTypes:[FLATRATE],
          releaseYear:{min:$y0,max:$y1}}){
  totalCount pageInfo{hasNextPage endCursor}
  edges{node{objectId
   content(country:BR,language:"pt"){title originalTitle originalReleaseYear runtime
     externalIds{imdbId tmdbId} scoring{imdbScore imdbVotes}}
   offers(country:BR,platform:WEB){monetizationType availableToTime package{shortName}}}}}}"""


def gql(variables):
    body = json.dumps({"query": Q, "variables": variables}).encode()
    for tentativa in range(5):
        try:
            req = urllib.request.Request(API, body, {"content-type": "application/json",
                                                    "user-agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if "errors" in d:
                raise RuntimeError(d["errors"])
            return d["data"]["popularTitles"]
        except Exception as e:
            print("  erro:", e, "- tentando de novo")
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("JustWatch falhou 5 vezes")


def datas_saida(ofertas):
    """Serviço -> data de saída (AAAA-MM-DD, horário de Brasília).

    Um serviço pode ter várias ofertas (SD/HD/4K); só há data de saída se todas
    tiverem uma, e vale a mais tardia.
    """
    por_serv = {}
    for o in ofertas:
        por_serv.setdefault(SERVICOS[o["package"]["shortName"]], []).append(o["availableToTime"])
    saidas = {}
    for serv, datas in por_serv.items():
        if datas and all(datas):
            fim = max(datetime.fromisoformat(d.replace("Z", "+00:00")) for d in datas)
            saidas[serv] = (fim - timedelta(hours=3)).date().isoformat()
    return saidas


def buscar(pkg, y0=None, y1=None):
    """Pagina uma consulta; se a paginação parar antes do total, divide por anos."""
    nos, after, total = [], None, None
    while True:
        r = gql({"after": after, "pkg": [pkg], "y0": y0, "y1": y1})
        if total is None:  # após ~1900 itens o JW devolve totalCount=0
            total = r["totalCount"]
        nos += [e["node"] for e in r["edges"]]
        if not r["pageInfo"]["hasNextPage"] or not r["edges"]:
            break
        after = r["pageInfo"]["endCursor"]
        time.sleep(0.3)
    if len(nos) < total:
        a, b = (y0 or 1890), (y1 or 2030)
        if a == b:
            print(f"  aviso: {pkg} {a}: só {len(nos)}/{total}")
            return nos
        m = (a + b) // 2
        return buscar(pkg, a, m) + buscar(pkg, m + 1, b)
    return nos


def conferir_imdb(filmes, anterior):
    """O JustWatch às vezes troca o IMDb ID de um título por um errado.

    Quando o ID muda em relação ao catálogo anterior (mesmo jw_id), o Letterboxd
    decide: a página /tmdb/<id>/ traz o link do IMDb. Sem resposta, fica o anterior.
    """
    if not os.path.exists(anterior):
        return
    with open(anterior, encoding="utf-8") as fh:
        antes = {int(f["jw_id"]): f["imdb_id"] for f in csv.DictReader(fh)}
    mudou = [f for k, f in filmes.items() if antes.get(k) and f["imdb_id"] != antes[k]]
    print(f"IMDb ID diferente do catálogo anterior: {len(mudou)} títulos (conferindo no Letterboxd)")
    confirmados = 0
    for f in mudou:
        lb = None
        if f["tmdb_id"]:
            try:
                req = urllib.request.Request(f"https://letterboxd.com/tmdb/{f['tmdb_id']}/",
                                             headers={"User-Agent": "Mozilla/5.0"})
                pagina = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
                m = re.search(r"imdb\.com/title/(tt\d+)", pagina)
                lb = m and m.group(1)
            except Exception:
                pass
            time.sleep(1.5)
        novo = lb or antes[f["jw_id"]]
        confirmados += novo == f["imdb_id"]
        f["imdb_id"] = novo
    print(f"  mantido o ID novo do JustWatch: {confirmados} | corrigido para o anterior/Letterboxd: {len(mudou) - confirmados}")


def main():
    anterior = sys.argv[1] if len(sys.argv) > 1 else CATALOGO
    filmes = {}
    for pkg in CONSULTAR:
        nos = buscar(pkg)
        print(f"{SERVICOS[pkg]}: {len(nos)} títulos retornados")
        for n in nos:
            c = n["content"]
            ofertas = [o for o in n["offers"] or []
                       if o["monetizationType"] == "FLATRATE" and o["package"]["shortName"] in SERVICOS]
            servs = {SERVICOS[o["package"]["shortName"]] for o in ofertas} | {SERVICOS[pkg]}
            f = filmes.setdefault(n["objectId"], {
                "jw_id": n["objectId"], "titulo_pt": c["title"],
                "titulo_original": c["originalTitle"] or c["title"],
                "ano": c["originalReleaseYear"] or "", "duracao_min": c["runtime"] or "",
                "imdb_id": (c["externalIds"] or {}).get("imdbId") or "",
                "imdb_nota": (c["scoring"] or {}).get("imdbScore") or "",
                "imdb_votos": (c["scoring"] or {}).get("imdbVotes") or "",
                "tmdb_id": (c["externalIds"] or {}).get("tmdbId") or "",
                "servicos": set(), "saidas": {}})
            f["servicos"] |= servs
            for serv, data in datas_saida(ofertas).items():
                f["saidas"][serv] = data

    conferir_imdb(filmes, anterior)

    # datas de saída do JustWatch por título, lidas depois pelo saindo.py
    with open(SAIDAS_JW, "w", encoding="utf-8") as fh:
        json.dump({str(k): {"imdb_id": f["imdb_id"], "saidas": f["saidas"]} for k, f in filmes.items()}, fh)

    # junta duplicatas com o mesmo IMDb ID (títulos distintos no JustWatch)
    por_imdb = {}
    for f in list(filmes.values()):
        if f["imdb_id"]:
            if f["imdb_id"] in por_imdb:
                por_imdb[f["imdb_id"]]["servicos"] |= f["servicos"]
                por_imdb[f["imdb_id"]]["saidas"].update(f["saidas"])
                del filmes[f["jw_id"]]
            else:
                por_imdb[f["imdb_id"]] = f

    curtas = [k for k, f in filmes.items() if f["duracao_min"] != "" and f["duracao_min"] < DURACAO_MIN]
    for k in curtas:
        del filmes[k]
    sem_duracao = sum(1 for f in filmes.values() if f["duracao_min"] == "")

    ordem = ORDEM
    campos = ["jw_id", "titulo_pt", "titulo_original", "ano", "duracao_min",
              "imdb_id", "imdb_nota", "imdb_votos", "servicos", "sai_em"]
    with open(CATALOGO, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos, extrasaction="ignore")
        w.writeheader()
        for f in sorted(filmes.values(), key=lambda f: (str(f["titulo_original"]).lower())):
            w.writerow({**f, "servicos": "|".join(s for s in ordem if s in f["servicos"]),
                        "sai_em": "|".join(f"{s}:{f['saidas'][s]}" for s in ordem if s in f["saidas"])})

    cont = Counter(s for f in filmes.values() for s in f["servicos"])
    print(f"\nCurtas descartados (< {DURACAO_MIN} min): {len(curtas)}")
    print(f"Sem duração informada (mantidos): {sem_duracao}")
    print(f"Com data de saída: {sum(1 for f in filmes.values() if f['saidas'])}")
    print(f"Filmes únicos: {len(filmes)}  (com IMDb ID: {sum(1 for f in filmes.values() if f['imdb_id'])})")
    for s in ordem:
        print(f"  {s:12} {cont[s]}")


if __name__ == "__main__":
    main()
